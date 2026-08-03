"""Ready-link verification.

Level 1 (HTTP + HTML) here; headless L3 comes later. I/O (fetch) is separated
from pure analysis so the logic is unit-testable without network. SSRF-hardened:
only public http/https hosts, private/loopback/reserved IPs blocked (incl. after
redirects), timeouts, redirect cap, response-size cap.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy.orm import Session

from ..models import AnchorPlanItem, LinkCheck, LinkCheckResult, Placement, utcnow
from .url_match import anchor_match, domain_of, is_dofollow, same_domain, urls_equivalent

# ---------------- statuses (do NOT collapse into one) ----------------
PENDING = "pending"; CHECKING = "checking"; FOUND = "found"; NOT_FOUND = "not_found"
WRONG_URL = "wrong_url"; WRONG_ANCHOR = "wrong_anchor"; ANCHOR_CHANGED = "anchor_changed"
PAGE_UNAVAILABLE = "page_unavailable"; REDIRECT = "redirect"; AUTH_REQUIRED = "auth_required"
BLOCKED_CAPTCHA = "blocked_captcha"; TEMPORARY_ERROR = "temporary_error"; CHECK_ERROR = "check_error"
MANUAL_REQUIRED = "manual_required"

ALL_STATUSES = [PENDING, CHECKING, FOUND, NOT_FOUND, WRONG_URL, WRONG_ANCHOR, ANCHOR_CHANGED,
                PAGE_UNAVAILABLE, REDIRECT, AUTH_REQUIRED, BLOCKED_CAPTCHA, TEMPORARY_ERROR,
                CHECK_ERROR, MANUAL_REQUIRED]
HEALTHY = {FOUND}
PROBLEM = {NOT_FOUND, WRONG_URL, WRONG_ANCHOR, ANCHOR_CHANGED, PAGE_UNAVAILABLE}
TRANSIENT = {TEMPORARY_ERROR, CHECK_ERROR}  # worth retrying

MAX_BYTES = 3_000_000
TIMEOUT = 15.0
MAX_REDIRECTS = 8
DEFAULT_RECHECK_HOURS = 24


# ---------------- SSRF guard ----------------
class SSRFError(Exception):
    pass


def _host_is_public(host: str) -> bool:
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified):
            return False
    return True


def validate_public_url(url: str) -> str:
    """Return the normalised URL if it targets a PUBLIC http/https host, else raise."""
    u = (url or "").strip()
    if not u:
        raise SSRFError("пустой URL")
    if "://" not in u:
        u = "http://" + u
    p = urlsplit(u)
    if p.scheme not in ("http", "https"):
        raise SSRFError(f"схема не http/https: {p.scheme}")
    host = p.hostname or ""
    if not host or not _host_is_public(host):
        raise SSRFError("непубличный или неразрешимый хост")
    return u


# ---------------- HTML link extraction (stdlib, dependency-free) ----------------
class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._stack: list[dict] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self._stack.append({"href": d.get("href", ""), "rel": d.get("rel", "") or "", "text": []})
        elif tag == "title":
            self._in_title = True
        elif tag == "img" and self._stack:
            self._stack[-1]["text"].append(d.get("alt", "") or "")

    def handle_startendtag(self, tag, attrs):
        # self-closing <img/> inside an <a>
        if tag == "img" and self._stack:
            self._stack[-1]["text"].append(dict(attrs).get("alt", "") or "")

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            a = self._stack.pop()
            self.links.append({"href": a["href"], "rel": a["rel"],
                               "text": " ".join(t for t in a["text"] if t).strip()})
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._stack:
            self._stack[-1]["text"].append(data)
        if self._in_title:
            self.title += data


def extract_links(html: str) -> tuple[list[dict], str]:
    p = _LinkParser()
    try:
        p.feed(html or "")
    except Exception:
        pass
    return p.links, p.title.strip()


# ---------------- pure analysis ----------------
def analyze(html: str, final_url: str, expected_url: str, expected_anchor: str,
            expected_link_type: str = "") -> dict:
    """Decide the verification status from fetched HTML. Pure — no I/O."""
    links, _title = extract_links(html)
    resolved = [(l, urljoin(final_url or "", l["href"] or "")) for l in links]

    matches = [(l, absu) for (l, absu) in resolved
               if urls_equivalent(expected_url, l["href"]) or urls_equivalent(expected_url, absu)]

    base = {"final_url": final_url, "found_anchor": "", "is_dofollow": None, "anchor_kind": ""}
    if not matches:
        dom_hits = [(l, absu) for (l, absu) in resolved if same_domain(expected_url, absu)]
        if dom_hits:
            l, _absu = dom_hits[0]
            return {**base, "status": WRONG_URL, "found_anchor": l["text"], "is_dofollow": is_dofollow(l["rel"])}
        return {**base, "status": NOT_FOUND}

    # Prefer a match whose anchor is also correct.
    best = None
    for l, _absu in matches:
        ok, kind = anchor_match(expected_anchor, l["text"], target_url=expected_url)
        if ok:
            best = (l, kind, True)
            break
        if best is None:
            best = (l, kind, False)
    l, kind, ok = best
    df = is_dofollow(l["rel"])
    result = {**base, "found_anchor": l["text"], "is_dofollow": df, "anchor_kind": kind}
    if not ok:
        result["status"] = WRONG_ANCHOR
        return result
    # Optional link-type check (dofollow/nofollow requirement).
    req = (expected_link_type or "").lower()
    result["status"] = FOUND
    return result


# ---------------- fetch (sync httpx + SSRF, incl. redirect target) ----------------
def fetch(url: str) -> dict:
    try:
        safe = validate_public_url(url)
    except SSRFError as e:
        return {"error_status": CHECK_ERROR, "error": f"SSRF/невалидный URL: {e}"}
    try:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT, max_redirects=MAX_REDIRECTS,
                          headers={"User-Agent": "CrowdLinkChecker/1.0 (+link verification)"}) as client:
            r = client.get(safe)
    except httpx.TooManyRedirects:
        return {"error_status": REDIRECT, "error": "слишком много редиректов"}
    except httpx.TimeoutException:
        return {"error_status": TEMPORARY_ERROR, "error": "таймаут"}
    except Exception as e:  # noqa: BLE001
        return {"error_status": PAGE_UNAVAILABLE, "error": str(e)[:200]}

    final_url = str(r.url)
    try:
        validate_public_url(final_url)  # block redirect-to-internal
    except SSRFError as e:
        return {"error_status": CHECK_ERROR, "error": f"редирект на непубличный хост: {e}"}

    code = r.status_code
    chain = " → ".join(str(h.url) for h in r.history) + (" → " if r.history else "") + final_url
    if code == 401:
        return {"error_status": AUTH_REQUIRED, "http_status": code, "final_url": final_url, "chain": chain}
    if code == 403:
        return {"error_status": BLOCKED_CAPTCHA, "http_status": code, "final_url": final_url, "chain": chain}
    if code >= 500:
        return {"error_status": TEMPORARY_ERROR, "http_status": code, "final_url": final_url, "chain": chain}
    if code >= 400:
        return {"error_status": PAGE_UNAVAILABLE, "http_status": code, "final_url": final_url, "chain": chain}

    html = (r.text or "")[:MAX_BYTES]
    low = html.lower()
    if "cf-browser-verification" in low or ("captcha" in low and ("verify" in low or "robot" in low)):
        return {"error_status": BLOCKED_CAPTCHA, "http_status": code, "final_url": final_url, "chain": chain}
    return {"html": html, "http_status": code, "final_url": final_url, "chain": chain}


# ---------------- orchestrate + persist ----------------
def get_or_create_check(db: Session, placement: Placement) -> LinkCheck:
    lc = db.query(LinkCheck).filter(LinkCheck.placement_id == placement.id).first()
    if lc:
        return lc
    req_lt = ""
    if placement.anchor_plan_item_id:
        item = db.get(AnchorPlanItem, placement.anchor_plan_item_id)
        if item:
            req_lt = item.required_link_type or ""
    lc = LinkCheck(
        placement_id=placement.id,
        status=PENDING,
        kind=getattr(placement, "kind", "internal") or "internal",
        expected_url=placement.target_url,
        expected_anchor=placement.anchor_text or "",
        expected_link_type=req_lt,
        next_check_at=utcnow(),
    )
    db.add(lc)
    db.flush()
    return lc


def enqueue_placement(db: Session, placement: Placement) -> LinkCheck:
    """Called on mark_placed — (re)queue the placement for its first check."""
    lc = get_or_create_check(db, placement)
    lc.status = PENDING
    lc.expected_url = placement.target_url
    lc.expected_anchor = placement.anchor_text or ""
    lc.next_check_at = utcnow()
    lc.locked_at = None
    return lc


def check_placement(db: Session, placement: Placement, *, level: int = 1,
                    recheck_hours: int = DEFAULT_RECHECK_HOURS) -> dict:
    """Verify one placement now: fetch → analyze → write a history row + update state."""
    start = time.perf_counter()
    lc = get_or_create_check(db, placement)
    expected_url = placement.target_url
    expected_anchor = placement.anchor_text or ""

    res = fetch(placement.result_url)
    if "error_status" in res:
        analysis = {"status": res["error_status"], "found_anchor": "", "is_dofollow": None,
                    "final_url": res.get("final_url", "")}
        error = res.get("error", "")
        http_status = res.get("http_status")
        chain = res.get("chain", "")
    else:
        analysis = analyze(res["html"], res["final_url"], expected_url, expected_anchor, lc.expected_link_type)
        error = ""
        http_status = res.get("http_status")
        chain = res.get("chain", "")

    duration = int((time.perf_counter() - start) * 1000)
    status = analysis["status"]

    db.add(LinkCheckResult(
        placement_id=placement.id, link_check_id=lc.id, status=status, level=level,
        http_status=http_status, found_url=analysis.get("final_url", ""),
        found_anchor=analysis.get("found_anchor", ""), expected_url=expected_url,
        expected_anchor=expected_anchor, final_url=analysis.get("final_url", ""),
        is_dofollow=analysis.get("is_dofollow"), redirect_chain=chain,
        error_reason=error, duration_ms=duration,
    ))

    lc.status = status
    lc.level = level
    lc.final_url = analysis.get("final_url", "") or ""
    lc.found_anchor = analysis.get("found_anchor", "") or ""
    lc.http_status = http_status
    lc.is_dofollow = analysis.get("is_dofollow")
    lc.error_reason = error
    lc.attempts = (lc.attempts or 0) + 1
    lc.last_checked_at = utcnow()
    lc.locked_at = None
    lc.next_check_at = utcnow() + timedelta(hours=recheck_hours)
    db.flush()
    return {"status": status, "duration_ms": duration, "http_status": http_status,
            "final_url": lc.final_url, "found_anchor": lc.found_anchor, "is_dofollow": lc.is_dofollow}
