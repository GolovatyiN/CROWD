import { api, auth } from "../api.js";
import { el, fmtDate, fmtRelative, emptyState, tableSkeleton, pill, menuButton } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export const LINK_STATUS = {
  pending: "Ожидает", checking: "Проверяется", found: "Найдена", not_found: "Не найдена",
  wrong_url: "Неправильный URL", wrong_anchor: "Неправильный анкор", anchor_changed: "Анкор изменён",
  page_unavailable: "Страница недоступна", redirect: "Редирект", auth_required: "Нужна авторизация",
  blocked_captcha: "CAPTCHA / блок", temporary_error: "Временная ошибка", check_error: "Ошибка проверки",
  manual_required: "Ручная проверка",
};
const VARIANT = {
  found: "success", not_found: "error", wrong_url: "error", page_unavailable: "error",
  wrong_anchor: "warning", anchor_changed: "warning", redirect: "warning", auth_required: "warning",
  blocked_captcha: "warning", manual_required: "violet", pending: "muted", checking: "info",
  temporary_error: "muted", check_error: "muted",
};

function linkStatusPill(s) { return pill(LINK_STATUS[s] || s || "—", VARIANT[s] || "muted"); }

function box(label, value, color) {
  return el("div", { style: {
    flex: "1 1 120px", minWidth: "110px", padding: "12px 14px", border: "1px solid var(--border)",
    borderRadius: "10px", background: "var(--surface)",
  } },
    el("div", { style: { fontSize: "12px", color: "var(--text-3)" } }, label),
    el("div", { style: { fontSize: "22px", fontWeight: 600, color: color || "var(--text-1)", marginTop: "2px" } }, String(value)),
  );
}

export async function renderLinkMonitor(host) {
  const isAdmin = auth.isAdmin();
  const state = { kind: "", status: "", is_dofollow: "", search: "" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Контроль ссылок"),
      el("div", { class: "page-subtitle" }, "Сохранность опубликованных размещений — автопроверка ready-link"),
    ),
    el("div", { class: "page-actions" },
      el("button", { class: "ghost", onClick: () => load() }, icon("refresh", { size: 14 }), el("span", {}, "Обновить")),
      isAdmin && el("button", { onClick: async () => {
        try { const r = await api.linkCheckRun(100); toast(`Запущена проверка (до ${r.limit})`, "success"); }
        catch (e) { toast(e.message, "error"); }
      } }, icon("refresh", { size: 14 }), el("span", {}, "Проверить сейчас")),
    ),
  ));

  const cards = el("div", { style: { display: "flex", gap: "10px", flexWrap: "wrap", marginBottom: "14px" } });
  host.appendChild(cards);

  // Filters
  const kindSel = sel(["", "internal", "client"], { "": "Все", internal: "Наши", client: "Клиентские" }, state.kind, v => { state.kind = v; load(); });
  const statusSel = sel(["", ...Object.keys(LINK_STATUS)], { "": "Все статусы", ...LINK_STATUS }, state.status, v => { state.status = v; load(); });
  const followSel = sel(["", "true", "false"], { "": "Follow: все", true: "dofollow", false: "nofollow" }, state.is_dofollow, v => { state.is_dofollow = v; load(); });
  const searchInp = el("input", { type: "text", placeholder: "Поиск по URL / донору", style: { minWidth: "200px" } });
  searchInp.addEventListener("input", debounce(() => { state.search = searchInp.value.trim(); load(); }, 300));
  host.appendChild(el("div", { class: "row", style: { gap: "8px", marginBottom: "12px", flexWrap: "wrap" } },
    kindSel, statusSel, followSel, searchInp));

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  function params() {
    const p = {};
    if (state.kind) p.kind = state.kind;
    if (state.status) p.status = state.status;
    if (state.is_dofollow) p.is_dofollow = state.is_dofollow;
    if (state.search) p.search = state.search;
    return p;
  }

  async function load() {
    wrap.innerHTML = ""; wrap.appendChild(tableSkeleton(6, 7));
    let summary, data;
    try { [summary, data] = await Promise.all([api.linkMonitorSummary(params()), api.linkMonitorItems({ ...params(), limit: 200 })]); }
    catch (e) { wrap.innerHTML = ""; wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }

    cards.innerHTML = "";
    cards.appendChild(box("% сохранности", `${summary.survival_pct}%`, summary.survival_pct >= 90 ? "var(--success)" : summary.survival_pct >= 70 ? "var(--warning)" : "var(--error)"));
    cards.appendChild(box("Найдено", summary.found, "var(--success)"));
    cards.appendChild(box("Пропало", summary.removed, "var(--error)"));
    cards.appendChild(box("Анкор изменён", summary.anchor_changed, "var(--warning)"));
    cards.appendChild(box("Недоступно", summary.unavailable, "var(--error)"));
    cards.appendChild(box("Ждут проверки", summary.waiting));
    cards.appendChild(box("Ручная", summary.manual, "var(--violet, #8b5cf6)"));
    cards.appendChild(box("Всего", summary.total));

    wrap.innerHTML = "";
    if (!data.items.length) {
      wrap.appendChild(emptyState({ iconName: "tasks", title: "Нет размещений под контролем",
        desc: "Как только сотрудник добавит ready link, размещение попадёт сюда на автопроверку." }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "left" }, "Целевой URL"),
      el("th", { class: "left" }, "Донор"),
      el("th", { class: "left" }, "Анкор (ожид → факт)"),
      el("th", {}, "Статус"),
      el("th", {}, "Follow"),
      el("th", {}, "Проверено"),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    data.items.forEach(it => tbody.appendChild(row(it, load)));
    table.appendChild(tbody);
    wrap.appendChild(table);
    wrap.appendChild(el("div", { class: "muted", style: { fontSize: "12px", marginTop: "8px" } },
      `Показано ${data.items.length} из ${data.total}. Последняя проверка: ${summary.last_checked_at ? fmtDate(summary.last_checked_at) : "—"}`));
  }

  await load();
}

function row(it, reload) {
  const followBadge = it.is_dofollow === true ? pill("dofollow", "success")
    : it.is_dofollow === false ? pill("nofollow", "muted") : el("span", { class: "dimmed" }, "—");
  return el("tr", {},
    el("td", { class: "left truncate mono", style: { fontSize: "12px", maxWidth: "220px" }, title: it.target_url },
      it.result_url ? el("a", { href: it.result_url, target: "_blank", rel: "noopener" }, it.target_url) : it.target_url),
    el("td", { class: "left mono", style: { fontSize: "12px" } }, it.donor_domain || "—"),
    el("td", { class: "left", style: { fontSize: "12.5px", maxWidth: "220px" } },
      el("span", {}, it.anchor_text || el("span", { class: "dimmed" }, "безанкор")),
      it.found_anchor && it.found_anchor !== it.anchor_text ? el("span", { class: "muted" }, ` → ${it.found_anchor}`) : null),
    el("td", {}, linkStatusPill(it.status)),
    el("td", {}, followBadge),
    el("td", { class: "muted", style: { fontSize: "12px" }, title: it.last_checked_at ? fmtDate(it.last_checked_at) : "" },
      it.last_checked_at ? fmtRelative(it.last_checked_at) : el("span", { class: "dimmed" }, "—")),
    el("td", { class: "right actions" }, menuButton([
      { label: "Перепроверить", icon: "refresh", onClick: async () => {
        try { const r = await api.recheckPlacement(it.placement_id); toast(`Проверено: ${LINK_STATUS[r.status] || r.status}`, "success"); reload(); }
        catch (e) { toast(e.message, "error"); }
      } },
      { label: "История проверок", icon: "file", onClick: () => historyModal(it.placement_id) },
      it.result_url && { label: "Открыть ссылку", icon: "external", onClick: () => window.open(it.result_url, "_blank") },
    ])),
  );
}

async function historyModal(placementId) {
  let data;
  try { data = await api.placementChecks(placementId); } catch (e) { toast(e.message, "error"); return; }
  const rows = (data.history || []).map(h => el("tr", {},
    el("td", { class: "muted", style: { fontSize: "11.5px" } }, fmtDate(h.checked_at)),
    el("td", {}, pill(LINK_STATUS[h.status] || h.status, VARIANT[h.status] || "muted")),
    el("td", { class: "mono", style: { fontSize: "11.5px" } }, h.http_status || "—"),
    el("td", { class: "truncate", style: { fontSize: "11.5px", maxWidth: "180px" }, title: h.error_reason || h.final_url || "" }, h.error_reason || h.found_anchor || "—"),
    el("td", { class: "muted", style: { fontSize: "11.5px" } }, `${h.duration_ms} мс`),
  ));
  const content = el("div", {},
    data.current && el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "10px" } },
      `Текущий статус: ${LINK_STATUS[data.current.status] || data.current.status}. Проверок: ${data.current.attempts}. Следующая: ${data.current.next_check_at ? fmtDate(data.current.next_check_at) : "—"}`),
    rows.length
      ? el("div", { class: "table-wrap", style: { maxHeight: "360px", overflow: "auto" } },
          el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Когда"), el("th", {}, "Статус"), el("th", {}, "HTTP"), el("th", {}, "Детали"), el("th", {}, "Время"))), el("tbody", {}, ...rows)))
      : el("div", { class: "dimmed", style: { fontSize: "13px" } }, "Проверок ещё не было."),
  );
  openModal({ title: "История проверок ссылки", content, size: "lg",
    footer: el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { class: "ghost", onClick: () => closeModal() }, "Закрыть")) });
}

function sel(options, labels, value, onChange) {
  const s = document.createElement("select");
  s.addEventListener("change", e => onChange(e.target.value));
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o; opt.textContent = labels[o] ?? o;
    if (String(o) === String(value)) opt.selected = true;
    s.appendChild(opt);
  });
  return s;
}

const _t = new WeakMap();
function debounce(fn, ms) { return (...a) => { clearTimeout(_t.get(fn)); _t.set(fn, setTimeout(() => fn(...a), ms)); }; }
