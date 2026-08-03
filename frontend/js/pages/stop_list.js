import { api, auth } from "../api.js";
import { el, fmtDate, fmtRelative, emptyState, tableSkeleton, menuButton, searchInput, sortHeader } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { toast } from "../components/toast.js";

export async function renderStopList(host) {
  const isAdmin = auth.isAdmin();
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Стоп-лист"),
      el("div", { class: "page-subtitle" }, "Связки целевая ссылка ↔ донор, которые уже использовались"),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { class: "ghost", onClick: () => api.exportStopList() }, icon("download", { size: 14 }), el("span", {}, "Экспорт")),
      isAdmin && el("button", { class: "cta", onClick: () => location.hash = "#/import-export" }, icon("upload", { size: 14 }), el("span", {}, "Импорт")),
    ),
  ));

  const state = { q: "", date_from: "", date_to: "", sort: "placed_at", order: "desc" };
  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({
    placeholder: "Поиск по целевой ссылке или донору…",
    onInput: (v) => { state.q = v; debounce(load)(); },
  }));
  sb.appendChild(el("button", { class: "ghost", onClick: () => filters.style.display = filters.style.display === "none" ? "" : "none" },
    icon("filter", { size: 14 }), el("span", {}, "Период")));
  host.appendChild(sb);

  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } },
    field("С", el("input", { type: "date", onInput: (e) => state.date_from = e.target.value })),
    field("По", el("input", { type: "date", onInput: (e) => state.date_to = e.target.value })),
    el("button", { onClick: load }, "Применить"),
    el("button", { class: "ghost", onClick: () => { state.date_from = ""; state.date_to = ""; filters.querySelectorAll("input").forEach(i => i.value = ""); load(); } }, "Сбросить"),
  );
  host.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  let loadSeq = 0;
  async function load() {
    const my = ++loadSeq;
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(6, 6));
    const params = { sort: state.sort, order: state.order };
    ["q", "date_from", "date_to"].forEach(k => { if (state[k] !== "") params[k] = state[k]; });
    try {
      const data = await api.stopList(params);
      if (my !== loadSeq) return;
      renderTable(data);
    } catch (e) {
      if (my !== loadSeq) return;
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function renderTable(rows) {
    wrap.innerHTML = "";
    if (!rows.length) {
      wrap.appendChild(emptyState({
        iconName: "stop",
        title: "Стоп-лист пуст",
        desc: "Записи появятся автоматически, когда сотрудники отметят первые размещения как выполненные.",
      }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      sortHeader("Целевая ссылка", "target_url", state, load, "left"),
      sortHeader("Донор", "donor_url", state, load, "left"),
      sortHeader("Анкор", "anchor_text", state, load, "left"),
      el("th", { class: "left" }, "Результат"),
      el("th", { class: "left" }, "Аккаунт"),
      sortHeader("План", "source_anchor_plan", state, load),
      sortHeader("Дата", "placed_at", state, load),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    rows.forEach(r => tbody.appendChild(el("tr", {},
      el("td", { class: "left truncate mono", title: r.target_url }, r.target_url),
      el("td", { class: "left truncate", title: r.donor_url }, el("a", { href: ensureUrl(r.donor_url), target: "_blank", class: "mono" }, r.donor_url)),
      el("td", { class: "left truncate", title: r.anchor_text || "" }, r.anchor_text || el("span", { class: "dimmed" }, "—")),
      el("td", { class: "left truncate", title: r.result_url || "" }, r.result_url ? el("a", { href: r.result_url, target: "_blank", class: "mono" }, r.result_url) : el("span", { class: "dimmed" }, "—")),
      el("td", { class: "left mono muted" }, r.account_username || r.login_email || el("span", { class: "dimmed" }, "—")),
      el("td", { class: "muted" }, r.source_anchor_plan || el("span", { class: "dimmed" }, "—")),
      el("td", { class: "muted", title: fmtDate(r.placed_at) }, fmtRelative(r.placed_at)),
      el("td", { class: "right actions" }, menuButton([
        r.result_url && { label: "Открыть результат", icon: "external", onClick: () => window.open(r.result_url, "_blank") },
        r.donor_url && { label: "Открыть донор", icon: "external", onClick: () => window.open(r.donor_url, "_blank") },
        isAdmin && { separator: true },
        isAdmin && { label: "Удалить запись", icon: "trash", danger: true, onClick: async () => {
          if (!confirm("Удалить запись из стоп-листа? Эта связка снова станет доступна для размещения.")) return;
          try { await api.deleteStopEntry(r.id); toast("Удалено", "success"); load(); }
          catch (e) { toast(e.message, "error"); }
        }},
      ])),
    )));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  await load();
}

function ensureUrl(raw) {
  if (!raw) return "#";
  return /^https?:\/\//i.test(raw) ? raw : "https://" + raw;
}

function field(label, input) {
  return el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, label), input);
}

const _timers = new WeakMap();
function debounce(fn, ms = 250) {
  return (...args) => {
    clearTimeout(_timers.get(fn));
    _timers.set(fn, setTimeout(() => fn(...args), ms));
  };
}
