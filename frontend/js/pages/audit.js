import { api } from "../api.js";
import { el, fmtDate, fmtRelative, emptyState, tableSkeleton, searchInput } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { toast } from "../components/toast.js";

const ACTION_LABELS = {
  "user.create": "Создание сотрудника",
  "user.update": "Изменение профиля",
  "user.role_change": "Смена роли",
  "user.activate": "Активация",
  "user.deactivate": "Деактивация",
};

const ACTION_VARIANT = {
  "user.create": "success",
  "user.update": "info",
  "user.role_change": "violet",
  "user.activate": "success",
  "user.deactivate": "error",
};

export async function renderAudit(host) {
  const state = { action: "", date_from: "", date_to: "" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Журнал действий"),
      el("div", { class: "page-subtitle" }, "Все изменения по сотрудникам — кто, что и когда"),
    ),
  ));

  const sb = el("div", { class: "search-bar" });
  sb.appendChild(el("div", { class: "input-wrap", style: { flex: 1, minWidth: "200px" } },
    icon("file", { size: 14 }),
    selectInput(state.action, ["", ...Object.keys(ACTION_LABELS)], v => { state.action = v; load(); },
      "(все типы действий)", ACTION_LABELS),
  ));
  sb.appendChild(el("button", { class: "ghost", onClick: () => { filters.style.display = filters.style.display === "none" ? "" : "none"; }},
    icon("filter", { size: 14 }), el("span", {}, "Период")));
  host.appendChild(sb);

  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } },
    field("С", el("input", { type: "date", onInput: e => state.date_from = e.target.value })),
    field("По", el("input", { type: "date", onInput: e => state.date_to = e.target.value })),
    el("button", { onClick: load }, "Применить"),
    el("button", { class: "ghost", onClick: () => {
      state.date_from = ""; state.date_to = "";
      filters.querySelectorAll("input").forEach(i => i.value = "");
      load();
    }}, "Сбросить"),
  );
  host.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(6, 5));
    const params = {};
    if (state.action) params.action = state.action;
    if (state.date_from) params.date_from = state.date_from;
    if (state.date_to) params.date_to = state.date_to;
    try {
      const data = await api.auditLogs(params);
      render(data);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function render(data) {
    wrap.innerHTML = "";
    if (!data.items.length) {
      wrap.appendChild(emptyState({ iconName: "file", title: "Записей нет", desc: "По выбранным фильтрам ничего не найдено." }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "left" }, "Когда"),
      el("th", { class: "left" }, "Кто"),
      el("th", {}, "Действие"),
      el("th", { class: "left" }, "Над кем"),
      el("th", { class: "left" }, "Детали"),
    )));
    const tbody = el("tbody");
    data.items.forEach(r => tbody.appendChild(el("tr", {},
      el("td", { class: "left muted", style: { fontSize: "12px" }, title: fmtDate(r.created_at) }, fmtRelative(r.created_at)),
      el("td", { class: "left mono", style: { fontSize: "12.5px" } }, r.actor_email || el("span", { class: "dimmed" }, "система")),
      el("td", {}, el("span", { class: `pill ${ACTION_VARIANT[r.action] || ""}` }, ACTION_LABELS[r.action] || r.action)),
      el("td", { class: "left mono", style: { fontSize: "12.5px" } }, r.target_label || el("span", { class: "dimmed" }, "—")),
      el("td", { class: "left muted", style: { fontSize: "11.5px", maxWidth: "400px" } }, summarise(r.details)),
    )));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  await load();
}

function summarise(details) {
  if (!details || !Object.keys(details).length) return "—";
  if (details.changes) {
    const parts = [];
    for (const [k, v] of Object.entries(details.changes)) {
      if (v === "changed") parts.push(`${k}: изменён`);
      else if (typeof v === "object" && v.from !== undefined && v.to !== undefined) {
        parts.push(`${k}: ${v.from} → ${v.to}`);
      } else parts.push(`${k}: ${JSON.stringify(v)}`);
    }
    return parts.join("; ");
  }
  return Object.entries(details).map(([k, v]) => `${k}: ${v}`).join("; ");
}

function field(label, input) {
  return el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, label), input);
}

function selectInput(value, options, onChange, emptyLabel, labels) {
  const sel = document.createElement("select");
  sel.style.paddingLeft = "32px";
  sel.style.border = "none";
  sel.style.background = "transparent";
  sel.style.boxShadow = "none";
  sel.addEventListener("change", e => onChange(e.target.value));
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o;
    if (String(o) === String(value)) opt.selected = true;
    opt.textContent = !o ? (emptyLabel || "(все)") : (labels && labels[o]) || o;
    sel.appendChild(opt);
  });
  return sel;
}
