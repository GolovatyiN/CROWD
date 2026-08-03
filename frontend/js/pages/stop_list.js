import { api, auth } from "../api.js";
import { el, fmtDate, fmtRelative, emptyState, tableSkeleton, menuButton, searchInput, sortHeader, pill } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { toast } from "../components/toast.js";

const KIND_LABELS = { internal: "Наш", client: "Клиентский" };
const KIND_VARIANT = { internal: "muted", client: "info" };
const SOURCE_LABELS = { auto: "Авто", import: "Импорт", manual: "Ручное", historical: "История", client_forbidden: "Запрет клиента" };

export async function renderStopList(host) {
  const isAdmin = auth.isAdmin();

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Стоп-лист"),
      el("div", { class: "page-subtitle" }, "Связки целевая ссылка ↔ донор, которые уже использовались. Матчер исключает их при автоподборе доноров."),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { class: "ghost", onClick: () => api.exportStopList() }, icon("download", { size: 14 }), el("span", {}, "Экспорт")),
      isAdmin && el("button", { class: "cta", onClick: () => location.hash = "#/import-export" }, icon("upload", { size: 14 }), el("span", {}, "Импорт")),
    ),
  ));

  const state = {
    q: "", kind: "", client_id: "", source: "",
    date_from: "", date_to: "", sort: "placed_at", order: "desc",
    offset: 0, limit: 50,
  };

  // Client list for the filter — managers/admins only; ignore if forbidden.
  let clients = [];
  try { clients = await api.clients(); } catch { clients = []; }

  // ---- search + filter toggle ----
  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({
    placeholder: "Поиск по домену, ссылке или донору…",
    onInput: (v) => { state.q = v; state.offset = 0; debounce(load)(); },
  }));
  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } });
  sb.appendChild(el("button", { class: "ghost", onClick: () => filters.style.display = filters.style.display === "none" ? "" : "none" },
    icon("filter", { size: 14 }), el("span", {}, "Фильтры")));
  host.appendChild(sb);

  const applyFilter = () => { state.offset = 0; load(); };
  filters.append(
    selectField("Стоп-лист", state.kind, [
      { value: "", label: "Все" },
      { value: "internal", label: "Наш (внутренний)" },
      { value: "client", label: "Клиентский" },
    ], v => { state.kind = v; }),
    selectField("Клиент", state.client_id, [
      { value: "", label: "Все клиенты" },
      ...clients.map(c => ({ value: String(c.id), label: c.name })),
    ], v => { state.client_id = v; }),
    selectField("Источник", state.source, [
      { value: "", label: "Любой" },
      { value: "auto", label: "Авто (после размещения)" },
      { value: "import", label: "Импорт" },
      { value: "manual", label: "Ручное" },
      { value: "historical", label: "История" },
      { value: "client_forbidden", label: "Запрет клиента" },
    ], v => { state.source = v; }),
    field("С", el("input", { type: "date", onInput: (e) => state.date_from = e.target.value })),
    field("По", el("input", { type: "date", onInput: (e) => state.date_to = e.target.value })),
    el("button", { onClick: applyFilter }, "Применить"),
    el("button", { class: "ghost", onClick: () => {
      Object.assign(state, { kind: "", client_id: "", source: "", date_from: "", date_to: "", offset: 0 });
      filters.querySelectorAll("input").forEach(i => i.value = "");
      filters.querySelectorAll("select").forEach(s => s.value = "");
      load();
    } }, "Сбросить"),
  );
  host.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);
  const pager = el("div", { class: "row", style: { justifyContent: "space-between", alignItems: "center", marginTop: "12px" } });
  host.appendChild(pager);

  let loadSeq = 0;
  async function load() {
    const my = ++loadSeq;
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(7, 7));
    pager.innerHTML = "";
    const params = { sort: state.sort, order: state.order, limit: state.limit, offset: state.offset };
    ["q", "kind", "client_id", "source", "date_from", "date_to"].forEach(k => { if (state[k] !== "") params[k] = state[k]; });
    try {
      const data = await api.stopList(params);
      if (my !== loadSeq) return;
      renderTable(data.items || []);
      renderPager(data.total || 0);
    } catch (e) {
      if (my !== loadSeq) return;
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function renderPager(total) {
    pager.innerHTML = "";
    if (!total) return;
    const from = state.offset + 1;
    const to = Math.min(state.offset + state.limit, total);
    pager.appendChild(el("span", { class: "muted", style: { fontSize: "13px" } },
      `Показано ${from.toLocaleString("ru-RU")}–${to.toLocaleString("ru-RU")} из ${total.toLocaleString("ru-RU")}`));
    pager.appendChild(el("div", { class: "row", style: { gap: "8px" } },
      el("button", { class: "ghost small", disabled: state.offset <= 0 ? "" : null,
        onClick: () => { state.offset = Math.max(0, state.offset - state.limit); load(); } }, icon("chevronLeft", { size: 14 }), el("span", {}, "Назад")),
      el("button", { class: "ghost small", disabled: to >= total ? "" : null,
        onClick: () => { state.offset += state.limit; load(); } }, el("span", {}, "Вперёд"), icon("chevronRight", { size: 14 })),
    ));
  }

  function renderTable(rows) {
    wrap.innerHTML = "";
    if (!rows.length) {
      wrap.appendChild(emptyState({
        iconName: "stop",
        title: state.q || hasFilters() ? "Ничего не найдено" : "Стоп-лист пуст",
        desc: state.q || hasFilters()
          ? "Измените поиск или фильтры."
          : "Записи появятся автоматически, когда сотрудники отметят первые размещения как выполненные, либо после импорта.",
      }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      sortHeader("Целевой домен", "target_domain", state, load, "left"),
      sortHeader("Целевая ссылка", "target_url", state, load, "left"),
      sortHeader("Донор", "donor_url", state, load, "left"),
      el("th", {}, "Стоп-лист"),
      el("th", {}, "Источник"),
      sortHeader("Дата", "placed_at", state, load),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    rows.forEach(r => tbody.appendChild(el("tr", {},
      el("td", { class: "left truncate mono", style: { fontSize: "12px" }, title: r.target_domain }, r.target_domain || el("span", { class: "dimmed" }, "—")),
      el("td", { class: "left truncate mono", style: { fontSize: "12px" }, title: r.target_url }, r.target_url || el("span", { class: "dimmed" }, "—")),
      el("td", { class: "left truncate", title: r.donor_url }, el("a", { href: ensureUrl(r.donor_url), target: "_blank", rel: "noopener", class: "mono", style: { fontSize: "12px" } }, r.donor_url)),
      el("td", {}, pill(KIND_LABELS[r.kind] || "—", KIND_VARIANT[r.kind] || "muted")),
      el("td", { class: "muted", style: { fontSize: "12px" } }, SOURCE_LABELS[r.source] || r.source || "—"),
      el("td", { class: "muted", title: fmtDate(r.placed_at) }, fmtRelative(r.placed_at)),
      el("td", { class: "right actions" }, menuButton([
        r.result_url && { label: "Открыть результат", icon: "external", onClick: () => window.open(r.result_url, "_blank") },
        r.donor_url && { label: "Открыть донор", icon: "external", onClick: () => window.open(ensureUrl(r.donor_url), "_blank") },
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

  function hasFilters() {
    return state.kind || state.client_id || state.source || state.date_from || state.date_to;
  }

  await load();
}

// ---- helpers ----

function selectField(labelText, value, options, onChange) {
  const sel = el("select", { onChange: (e) => onChange(e.target.value) });
  options.forEach(o => {
    const opt = el("option", { value: o.value }, o.label);
    if (o.value === value) opt.selected = true;
    sel.appendChild(opt);
  });
  return field(labelText, sel);
}

function ensureUrl(raw) {
  if (!raw) return "#";
  return /^https?:\/\//i.test(raw) ? raw : "https://" + raw;
}

function field(label, input) {
  return el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, label), input);
}

const _timers = new WeakMap();
function debounce(fn, ms = 300) {
  return (...args) => {
    clearTimeout(_timers.get(fn));
    _timers.set(fn, setTimeout(() => fn(...args), ms));
  };
}
