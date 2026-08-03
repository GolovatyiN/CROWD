"""URL and anchor matching for link verification.

Pure functions (no I/O) so they're trivially unit-tested. Handle the real-world
variations a published link can have vs. the expected target:
http/https, www/no-www, trailing slash, UTM & tracking params, extra GET params,
URL-encoding, and anchorless / brand / URL-anchor placements.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that never change the resource identity — strip before comparing.
_TRACKING = ("utm_", "fbclid", "gclid", "yclid", "ymclid", "_openstat", "mc_eid", "mc_cid", "igshid", "ref_")


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return any(k.startswith(p) for p in _TRACKING)


def normalize_url(url: str, *, drop_query: bool = False) -> str:
    """Canonical comparison form: lowercase scheme+host, drop 'www.', drop default
    ports, strip a trailing slash, drop tracking params, sort remaining query."""
    if not url:
        return ""
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    try:
        p = urlsplit(u)
    except Exception:
        return u.lower()
    scheme = (p.scheme or "http").lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = p.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if drop_query:
        query = ""
    else:
        kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _is_tracking(k)]
        query = urlencode(sorted(kept))
    return urlunsplit((scheme, host, path, query, ""))


def _parts(url: str, drop_query: bool):
    n = normalize_url(url, drop_query=drop_query)
    s = urlsplit(n)
    return (s.hostname or "", s.path or "/", s.query or "")


def _query_pairs(q: str) -> set[tuple[str, str]]:
    return set(parse_qsl(q, keep_blank_values=True))


def urls_equivalent(target: str, found: str) -> bool:
    """True if `found` (a href on the page) points to the `target` URL, tolerating
    scheme/www/slash/UTM/extra-param differences. Host+path must match; if the
    target carries meaningful query params, `found` must include them (superset ok)."""
    if not target or not found:
        return False
    th, tp, tq = _parts(target, drop_query=False)
    fh, fp, fq = _parts(found, drop_query=False)
    if th != fh or tp != fp:
        return False
    if not tq:
        return True
    # target has real params → found must contain them all (may have extras)
    return _query_pairs(tq).issubset(_query_pairs(fq))


def domain_of(url: str) -> str:
    _h, _p, _q = _parts(url, drop_query=True)
    return _h


def same_domain(a: str, b: str) -> bool:
    da, db = domain_of(a), domain_of(b)
    return bool(da) and da == db


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def anchor_match(expected: str, found: str, *, target_url: str = "") -> tuple[bool, str]:
    """Classify how the found anchor relates to the expected one.

    Returns (ok, kind) where kind ∈ {anchorless, exact, url, brand, mismatch}.
    - anchorless: expected anchor is empty → any anchor is acceptable (link presence is what matters)
    - exact: normalised texts equal
    - url: the anchor text is the target URL / domain (URL-anchor placement)
    - brand: expected brand token contained in the found text
    """
    e, f = _norm_text(expected), _norm_text(found)
    if not e:
        return True, "anchorless"
    if e == f:
        return True, "exact"
    # URL-anchor: anchor text is the target url or its domain
    if target_url:
        tgt_dom = domain_of(target_url)
        if tgt_dom and (tgt_dom in f or (found and urls_equivalent(target_url, found.strip()))):
            return True, "url"
    # brand-ish: single-token expected fully contained in found
    if " " not in e and e in f:
        return True, "brand"
    return False, "mismatch"


_REL_NOFOLLOW = {"nofollow", "ugc", "sponsored"}


def is_dofollow(rel: str) -> bool:
    """A link is dofollow unless its rel marks it nofollow/ugc/sponsored."""
    tokens = {t.strip().lower() for t in re.split(r"\s+", rel or "") if t.strip()}
    return not (tokens & _REL_NOFOLLOW)
