import { api, auth } from "../api.js";
import { el, statusPill, STATUS_LABELS, emptyState, tableSkeleton, menuButton, searchInput, fmtRelative, sortHeader, submitButton } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

const ITEM_STATUSES = ["new", "donor_selected", "assigned", "in_progress", "placed", "rejected", "problem", "done"];

export async function renderPlanDetails(host, planId) {
  const isAdmin = auth.isAdmin();
  // Fetch the plan and the user list in parallel — they're independent, so
  // one round-trip instead of two serial ones.
  let plan, users = [];
  try {
    const [planRes, usersRes] = await Promise.all([
      api.plan(planId),
      api.users().catch(() => []),  // employees may lack access — that's fine
    ]);
    plan = planRes;
    users = usersRes || [];
  } catch (e) {
    host.appendChild(emptyState({ iconName: "alert", title: "План не найден", desc: e.message }));
    return;
  }

  const state = { q: "", status: "", geo: "", language: "", assigned_to: "", sort: "id", order: "asc", hide_done: false };
  const selected = new Set();
  // Maps for targeted in-place row updates (avoid full table reload after
  // an action — keeps scroll, other selections and filters intact).
  const rowById = {};   // item id -> <tr>
  const itemById = {};  // item id -> item object

  const headerActions = el("div", { class: "page-actions" },
    el("button", { class: "ghost", onClick: () => api.exportPlan(planId) }, icon("download", { size: 14 }), el("span", {}, "Экспорт CSV")),
  );
  if (isAdmin) {
    headerActions.appendChild(el("button", { class: "ghost", onClick: () => openAssign() }, icon("user", { size: 14 }), el("span", {}, "Назначить выбранные")));

    headerActions.appendChild(busyButton("ghost", icon("target", { size: 14 }), "Заполнить гео по TLD",
      "Заполняем гео…",
      async () => {
        const r = await api.reinferGeo(planId);
        toast(`Восстановлено: гео для ${r.geo_filled}, язык для ${r.language_filled} из ${r.items_total} строк`, "success");
        load();
      }));

    headerActions.appendChild(busyButton("ghost", icon("refresh", { size: 14 }), "Перепривязать всех",
      "Подбираем доноров…",
      async () => {
        if (!confirm("Сбросить всех доноров и подобрать заново? Размещённые строки останутся как есть.")) return;
        const r = await api.rematchAll(planId);
        toast(`Подобрано заново: ${r.matched} из ${r.considered}${r.not_matched ? `, проблем: ${r.not_matched}` : ""}`, "success");
        load();
      }));

    headerActions.appendChild(busyButton("", icon("zap", { size: 14 }), "Подобрать доноров",
      "Подбираем…",
      async () => {
        const r = await api.autoMatch(planId);
        if (!r.considered) {
          toast("Нет строк, требующих подбора — у всех уже есть донор", "warning");
        } else if (!r.matched) {
          toast(`Рассмотрено ${r.considered}, подходящих доноров не нашлось`, "error");
        } else if (r.not_matched) {
          toast(`Подобрано: ${r.matched} из ${r.considered}, проблем: ${r.not_matched} — нажмите статус "Проблема" чтобы узнать причину`, "success");
        } else {
          toast(`Подобрано: ${r.matched} из ${r.considered}`, "success");
        }
        load();
      }));

    headerActions.appendChild(el("button", { class: "subtle", title: "Сводка по донорам", onClick: showDonorStats },
      icon("info", { size: 14 })));
  }

  // Wraps an async click handler with disabled-state + spinner + replaces label
  // while in flight. We use it on the long-running matcher buttons.
  function busyButton(klass, iconEl, idleLabel, busyLabel, run) {
    const labelSpan = el("span", {}, idleLabel);
    const btn = el("button", { class: klass, onClick: async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      const prevChildren = [...btn.childNodes];
      btn.innerHTML = "";
      btn.appendChild(el("span", { class: "spinner", style: { width: "12px", height: "12px", borderWidth: "2px" } }));
      btn.appendChild(el("span", {}, busyLabel));
      try { await run(); }
      catch (e) { toast(e.message || "Ошибка", "error"); }
      finally {
        btn.disabled = false;
        btn.innerHTML = "";
        prevChildren.forEach(c => btn.appendChild(c));
      }
    }}, iconEl, labelSpan);
    return btn;
  }

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "row", style: { gap: "8px", alignItems: "center" } },
        el("a", { href: "#/plans", class: "subtle", style: { display: "inline-flex", padding: "2px" } }, icon("chevronLeft", { size: 16 })),
        el("div", { class: "page-title" }, plan.plan_name),
      ),
      el("div", { class: "page-subtitle" }, `${plan.total_rows} строк · готово ${plan.completed_rows} · в работе ${plan.pending_rows} · проблем ${plan.problem_rows}`),
    ),
    headerActions,
  ));

  // mini stats
  const stats = el("div", { class: "cards", style: { gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "16px" } });
  stats.appendChild(miniStat("Всего", plan.total_rows));
  stats.appendChild(miniStat("Готово", plan.completed_rows, "success"));
  stats.appendChild(miniStat("В работе", plan.pending_rows, "warning"));
  stats.appendChild(miniStat("Проблем", plan.problem_rows, "error"));
  host.appendChild(stats);

  // search + filters
  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({ placeholder: "Поиск по домену, URL, анкору…",
    onInput: (v) => { state.q = v; debounce(load)(); } }));
  const hideDoneBtn = el("button", { class: "ghost", onClick: () => {
    state.hide_done = !state.hide_done;
    hideDoneBtn.classList.toggle("ghost", !state.hide_done);
    load();
  }}, icon("eyeOff", { size: 14 }), el("span", {}, "Скрыть готовые"));
  sb.appendChild(hideDoneBtn);
  sb.appendChild(el("button", { class: "ghost", onClick: () => filters.style.display = filters.style.display === "none" ? "" : "none" },
    icon("filter", { size: 14 }), el("span", {}, "Фильтры")));
  host.appendChild(sb);

  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } },
    field("Статус", selectInput(state.status, ["", ...ITEM_STATUSES], v => state.status = v, "(все)", STATUS_LABELS)),
    field("Гео", el("input", { type: "text", onInput: (e) => state.geo = e.target.value })),
    field("Язык", el("input", { type: "text", onInput: (e) => state.language = e.target.value })),
    field("Сотрудник", selectUserInput(state.assigned_to, users, v => state.assigned_to = v)),
    el("button", { onClick: load }, "Применить"),
  );
  host.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  // Guards against out-of-order responses: if the user types/sorts quickly,
  // an earlier slow response must not overwrite a later one.
  let loadSeq = 0;

  async function load() {
    const my = ++loadSeq;
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(8, 8));
    const params = { sort: state.sort, order: state.order };
    ["q", "status", "geo", "language", "assigned_to"].forEach(k => { if (state[k] !== "") params[k] = state[k]; });
    try {
      let items = await api.planItems(planId, params);
      if (my !== loadSeq) return;  // a newer load already started
      if (state.hide_done) {
        items = items.filter(i => !["placed", "done"].includes(i.status));
      }
      renderTable(items);
    } catch (e) {
      if (my !== loadSeq) return;
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  // A row is eligible for bulk "Назначить выбранные" only while it has no
  // owner yet and isn't finished. Assigned / in-progress / placed rows are
  // locked — reassignment goes through the per-row Edit dialog.
  function isSelectable(i) {
    if (i.assigned_to) return false;
    if (["placed", "done", "rejected"].includes(i.status)) return false;
    return true;
  }

  // Rebuild a single row in place from its (mutated) item object.
  function refreshRow(id) {
    const item = itemById[id];
    const oldRow = rowById[id];
    if (!item || !oldRow) return;
    const fresh = itemRow(item);
    oldRow.replaceWith(fresh);
    rowById[id] = fresh;
  }

  function renderTable(items) {
    wrap.innerHTML = "";
    if (!items.length) {
      wrap.appendChild(emptyState({ iconName: "plans", title: "Нет строк", desc: "По выбранным фильтрам строк не найдено." }));
      return;
    }
    const table = el("table");
    const selectableItems = items.filter(isSelectable);
    const headerCheckbox = isAdmin ? el("input", {
      type: "checkbox",
      // Disable "select all" entirely if nothing on the page can be assigned.
      disabled: selectableItems.length ? null : "",
      title: selectableItems.length ? "Выбрать все неназначенные" : "Нет строк для назначения",
      onChange: (e) => {
        selected.clear();
        // Only ever select rows that are still free to assign.
        if (e.target.checked) selectableItems.forEach(i => selected.add(i.id));
        wrap.querySelectorAll("input.row-check:not(:disabled)").forEach(c => c.checked = e.target.checked);
      },
    }) : "";
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "compact left" }, headerCheckbox),
      sortHeader("Целевая ссылка", "target_url", state, load, "left"),
      el("th", { class: "left" }, "Параметры"),
      el("th", { class: "left" }, "Донор"),
      sortHeader("Сотрудник", "assigned_to", state, load, "left"),
      sortHeader("Статус", "status", state, load),
      el("th", { class: "left" }, "Результат"),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    // Reset the row/item maps for this render, then fill as we build rows.
    for (const k in rowById) delete rowById[k];
    for (const k in itemById) delete itemById[k];
    items.forEach(i => {
      const tr = itemRow(i);
      rowById[i.id] = tr;
      itemById[i.id] = i;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  function itemRow(i) {
    // Use the embedded assignee/donor from the API (single round-trip) and
    // fall back to the users[] lookup only if the backend didn't populate it.
    const assignee = i.assignee || users.find(u => u.id === i.assigned_to);
    let rowStyle = null;
    if (i.status === "placed" || i.status === "done") rowStyle = { opacity: 0.35 };
    else if (i.status === "assigned" || i.status === "in_progress") rowStyle = { opacity: 0.6 };

    const targetText = i.target_url || i.target_domain || "";
    const targetHref = targetText.startsWith("http") ? targetText : (targetText ? "https://" + targetText : "#");

    const selectable = isSelectable(i);
    return el("tr", { style: rowStyle },
      el("td", { class: "compact left" }, isAdmin ? el("input", {
        class: "row-check",
        type: "checkbox",
        // Already-assigned (or finished) rows can't be bulk-assigned — reassign
        // one-by-one via the row's "Редактировать" action instead.
        disabled: selectable ? null : "",
        title: selectable ? null : "Уже назначена — изменить можно через «Редактировать»",
        onChange: (e) => {
          if (e.target.checked) selected.add(i.id); else selected.delete(i.id);
        },
      }) : ""),
      el("td", { class: "left truncate", title: targetText }, targetText
        ? el("a", { href: targetHref, target: "_blank", class: "mono", style: { fontSize: "12.5px" } }, targetText)
        : el("span", { class: "dimmed" }, "—")),
      el("td", { class: "left" }, paramsBlock(i.geo, i.language, i.required_link_type)),
      el("td", { class: "left" }, donorBlock(i.donor)),
      el("td", { class: "left" }, assignee
        ? el("span", { style: { fontSize: "13px" } }, assignee.name || assignee.full_name || assignee.email)
        : el("span", { class: "dimmed" }, "—")),
      el("td", {}, statusCellWithReason(i)),
      el("td", { class: "left truncate", title: i.result_url || "" }, i.result_url
        ? el("a", { href: i.result_url, target: "_blank", class: "mono" }, i.result_url)
        : el("span", { class: "dimmed" }, "—")),
      el("td", { class: "right actions" }, menuButton([
        isAdmin && { label: "Подобрать автоматически", icon: "zap", onClick: async () => {
          try { const r = await api.matchOne(i.id); toast(`Подобран донор #${r.donor_id}`, "success"); load(); }
          catch (e) { toast(e.message, "error"); }
        }},
        isAdmin && { label: "Выбрать вручную…", icon: "target", onClick: () => openDonorPicker(i, (c) => {
          // Targeted update: attach the chosen donor to this row, no reload.
          i.selected_donor_id = c.id;
          i.donor = {
            id: c.id, donor_url: c.donor_url, domain: c.domain,
            geo: c.geo, language: c.language, link_type: c.link_type,
            tr: c.tr, organic_traffic: c.organic_traffic,
          };
          if (["new", "problem"].includes(i.status)) i.status = "donor_selected";
          refreshRow(i.id);
        }) },
        isAdmin && { label: "Редактировать", icon: "pencil", onClick: () => openItemEditor(i, load, users) },
        i.target_url && { label: "Открыть target", icon: "external", onClick: () => window.open(i.target_url, "_blank") },
        i.result_url && { label: "Открыть результат", icon: "external", onClick: () => window.open(i.result_url, "_blank") },
      ])),
    );
  }

  function openAssign() {
    if (!selected.size) { toast("Сначала выберите строки", "error"); return; }
    if (!users.length) { toast("Нет доступных сотрудников", "error"); return; }
    const form = el("form", {});
    form.appendChild(el("div", { class: "field" },
      el("label", {}, "Назначить на"),
      selectUserInput("", users, () => {}, "assigned_to"),
    ));
    openModal({
      title: `Назначить ${selected.size} строк`,
      content: form,
      footer: btnRow(
        el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"),
        submitButton("Назначить", async () => {
          const userId = parseInt(form.querySelector("[name=assigned_to]").value || 0);
          if (!userId) { toast("Выберите сотрудника", "error"); return; }
          const ids = [...selected];
          try {
            await api.assign(planId, ids, userId);
            toast(`Назначено: ${ids.length}`, "success");
            closeModal();
            // Targeted update: refresh only the assigned rows in place — no
            // full reload, scroll & other state preserved.
            const assignee = users.find(u => u.id === userId);
            ids.forEach((id) => {
              const item = itemById[id];
              const oldRow = rowById[id];
              if (!item || !oldRow) return;
              item.assigned_to = userId;
              item.assignee = assignee ? { id: assignee.id, name: assignee.full_name || assignee.email, email: assignee.email } : item.assignee;
              if (["new", "donor_selected"].includes(item.status)) item.status = "assigned";
              const fresh = itemRow(item);
              oldRow.replaceWith(fresh);
              rowById[id] = fresh;
            });
            selected.clear();
          } catch (e) { toast(e.message, "error"); }
        }),
      ),
    });
  }

  await load();
}

// ---- Inline cells ----

function statusCellWithReason(item) {
  const pill = statusPill(item.status);
  if ((item.status === "problem" || item.status === "rejected") && item.comment) {
    pill.title = item.comment;
    pill.style.cursor = "help";
  }
  return pill;
}

function paramsBlock(geo, lang, type) {
  const parts = [];
  if (geo) parts.push(geo);
  if (lang) parts.push(lang);
  const wrap = el("div", { class: "row", style: { gap: "6px", flexWrap: "wrap" } });
  if (parts.length) wrap.appendChild(el("span", { class: "muted", style: { fontSize: "12px" } }, parts.join(" · ")));
  if (type) wrap.appendChild(el("span", { class: "pill", style: { fontSize: "10.5px" } }, type));
  if (!wrap.children.length) wrap.appendChild(el("span", { class: "dimmed" }, "—"));
  return wrap;
}

function donorBlock(donor) {
  if (!donor) return el("span", { class: "dimmed" }, "не подобран");
  const linkClass = donor.link_type === "dofollow" ? "success"
    : donor.link_type === "nofollow" ? "muted"
    : donor.link_type === "mixed" ? "info"
    : donor.link_type === "error" ? "error"
    : "";
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", gap: "2px", alignItems: "flex-start", minWidth: 0 } });
  wrap.appendChild(el("a", {
    href: donor.donor_url && donor.donor_url.startsWith("http") ? donor.donor_url : "https://" + (donor.donor_url || donor.domain || ""),
    target: "_blank",
    class: "mono",
    title: donor.donor_url || donor.domain || "",
    style: { fontSize: "12.5px", fontWeight: 500 },
  }, donor.domain || donor.donor_url));
  const meta = [];
  if (donor.geo) meta.push(donor.geo);
  if (donor.language) meta.push(donor.language);
  if (donor.tr) meta.push("DR " + donor.tr);
  const metaRow = el("div", { class: "row", style: { gap: "6px", flexWrap: "wrap", fontSize: "11px" } });
  if (meta.length) metaRow.appendChild(el("span", { class: "muted" }, meta.join(" · ")));
  if (donor.link_type) metaRow.appendChild(el("span", { class: `pill ${linkClass}`, style: { fontSize: "10px" } }, donor.link_type));
  wrap.appendChild(metaRow);
  return wrap;
}

async function showDonorStats() {
  const body = el("div", {});
  body.innerHTML = `<div style="padding:20px; text-align:center"><span class="spinner"></span></div>`;
  const modal = openModal({ title: "Сводка по базе доноров", content: body, size: "lg" });
  try {
    const s = await api.donorStats();
    body.innerHTML = "";
    body.appendChild(el("div", { class: "muted", style: { marginBottom: "12px" } },
      `Всего активных доноров: ${s.active} из ${s.total}`));
    body.appendChild(distributionBlock("По GEO", s.by_geo, 12));
    body.appendChild(distributionBlock("По языку", s.by_language, 12));
    body.appendChild(distributionBlock("По типу ссылки", s.by_link_type, 8));
  } catch (e) {
    body.innerHTML = "";
    body.appendChild(el("div", { class: "empty" }, "Ошибка: " + e.message));
  }
}

function distributionBlock(title, rows, limit = 10) {
  const wrap = el("div", { style: { marginBottom: "16px" } });
  wrap.appendChild(el("div", { class: "panel-title", style: { marginBottom: "8px" } }, title));
  if (!rows.length) {
    wrap.appendChild(el("div", { class: "dimmed" }, "—"));
    return wrap;
  }
  const max = rows[0].count || 1;
  const list = el("div", {});
  rows.slice(0, limit).forEach(r => {
    const pct = Math.round((r.count / max) * 100);
    list.appendChild(el("div", { class: "row", style: { gap: "10px", padding: "4px 0" } },
      el("div", { class: "mono", style: { width: "120px", fontSize: "12.5px" } }, r.key),
      el("div", { class: "progress", style: { flex: 1 } }, el("div", { class: "bar", style: { width: `${pct}%` } })),
      el("div", { class: "mono tabular muted", style: { width: "70px", textAlign: "right", fontSize: "12px" } }, String(r.count)),
    ));
  });
  if (rows.length > limit) {
    list.appendChild(el("div", { class: "muted", style: { fontSize: "12px", marginTop: "6px" } },
      `и ещё ${rows.length - limit} групп`));
  }
  wrap.appendChild(list);
  return wrap;
}

async function openDonorPicker(item, onChosen) {
  const body = el("div", {});
  body.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "10px" } },
    "Цель: ", el("span", { class: "mono" }, item.target_url || item.target_domain),
  ));
  const listWrap = el("div", {});
  listWrap.innerHTML = `<div style="padding:20px; text-align:center"><span class="spinner"></span></div>`;
  body.appendChild(listWrap);
  openModal({ title: "Подобрать донора вручную", content: body, size: "lg" });

  try {
    const candidates = await api.candidates(item.id, 30);
    listWrap.innerHTML = "";
    if (!candidates.length) {
      listWrap.appendChild(el("div", { class: "empty" },
        el("div", { class: "icon-circle" }, icon("alert", { size: 20 })),
        el("div", { class: "title" }, "Подходящих доноров нет"),
        el("div", { class: "desc" }, "По правилам (гео, язык, тип ссылки, стоп-лист) ничего не нашлось."),
      ));
      return;
    }
    const table = el("table", { style: { minWidth: "auto" } });
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "left" }, "Domain"),
      el("th", { class: "right" }, "DR"),
      el("th", { class: "right" }, "Traffic"),
      el("th", {}, "GEO"),
      el("th", {}, "Lang"),
      el("th", {}, "Type"),
      el("th", { class: "right" }, "Score"),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    candidates.forEach((c, idx) => tbody.appendChild(el("tr", {},
      el("td", { class: "left" },
        el("a", { href: c.donor_url.match(/^https?:/) ? c.donor_url : `https://${c.donor_url}`, target: "_blank", class: "mono", style: { fontWeight: idx < 3 ? 600 : 500 } }, c.domain || c.donor_url),
      ),
      el("td", { class: "right tabular mono" }, String(c.tr || 0)),
      el("td", { class: "right tabular mono" }, fmtTraffic(c.organic_traffic)),
      el("td", {}, c.geo || "—"),
      el("td", {}, c.language || "—"),
      el("td", {}, el("span", { class: "pill" }, c.link_type)),
      el("td", { class: "right tabular mono", style: { color: idx === 0 ? "var(--success)" : "inherit" } }, String(c.score)),
      el("td", { class: "right" },
        submitButton("Выбрать", async () => {
          try {
            await api.setDonor(item.id, c.id);
            toast(`Назначен: ${c.domain || c.donor_url}`, "success");
            closeModal();
            onChosen && onChosen(c);  // targeted row update via callback
          } catch (e) { toast(e.message, "error"); }
        }, { className: "small" }),
      ),
    )));
    table.appendChild(tbody);
    listWrap.appendChild(el("div", { class: "table-wrap" }, table));
  } catch (e) {
    listWrap.innerHTML = "";
    listWrap.appendChild(el("div", { class: "empty" },
      el("div", { class: "icon-circle" }, icon("alert", { size: 20 })),
      el("div", { class: "title" }, "Ошибка"),
      el("div", { class: "desc" }, e.message),
    ));
  }
}

function fmtTraffic(n) {
  if (!n) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k";
  return String(n);
}

function openItemEditor(item, reload, users) {
  const form = el("form", {});
  const labels = {
    target_url: "Целевая ссылка",
    anchor_text: "Анкор",
    geo: "Гео",
    language: "Язык",
    required_link_type: "Тип ссылки",
    comment: "Комментарий",
  };
  Object.entries(labels).forEach(([k, label]) =>
    form.appendChild(el("div", { class: "field" }, el("label", {}, label), el("input", { name: k, type: "text", value: item[k] || "" }))));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "ID выбранного донора"),
    el("input", { name: "selected_donor_id", type: "number", value: item.selected_donor_id || "" })));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Назначен на"),
    selectUserInput(String(item.assigned_to || ""), users, () => {}, "assigned_to")));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Статус"),
    selectInput(item.status, ITEM_STATUSES, () => {}, null, STATUS_LABELS, "status")));

  openModal({
    title: "Редактирование строки",
    content: form,
    footer: btnRow(
      el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"),
      el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
        data.selected_donor_id = data.selected_donor_id ? parseInt(data.selected_donor_id) : null;
        data.assigned_to = data.assigned_to ? parseInt(data.assigned_to) : null;
        try { await api.updateItem(item.id, data); toast("Сохранено", "success"); closeModal(); reload(); }
        catch (e) { toast(e.message, "error"); }
      }}, "Сохранить"),
    ),
  });
}

function miniStat(label, value, tint) {
  return el("div", { class: "stat-card" },
    el("div", { class: "label" }, label),
    el("div", { class: "value tabular", style: tint ? { color: `var(--${tint})` } : null }, String(value)),
  );
}

function field(label, input) {
  return el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, label), input);
}

function selectInput(value, options, onChange, emptyLabel, labels, name) {
  const sel = document.createElement("select");
  if (name) sel.name = name;
  sel.addEventListener("change", (e) => onChange && onChange(e.target.value));
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o;
    if (o === value) opt.selected = true;
    if (!o) opt.textContent = emptyLabel || "(любой)";
    else if (labels && labels[o]) opt.textContent = labels[o];
    else opt.textContent = o;
    sel.appendChild(opt);
  });
  return sel;
}

function selectUserInput(value, users, onChange, name) {
  const sel = document.createElement("select");
  if (name) sel.name = name;
  sel.addEventListener("change", (e) => onChange && onChange(e.target.value));
  const empty = document.createElement("option");
  empty.value = ""; empty.textContent = "(все)";
  if (!value) empty.selected = true;
  sel.appendChild(empty);
  users.filter(u => u.is_active).forEach(u => {
    const opt = document.createElement("option");
    opt.value = String(u.id);
    opt.textContent = u.full_name || u.email;
    if (String(u.id) === String(value)) opt.selected = true;
    sel.appendChild(opt);
  });
  return sel;
}

function btnRow(...buttons) {
  const r = document.createElement("div");
  r.className = "row";
  r.style.justifyContent = "flex-end";
  r.style.gap = "8px";
  buttons.forEach(b => r.appendChild(b));
  return r;
}

const _timers = new WeakMap();
function debounce(fn, ms = 250) {
  return (...args) => {
    clearTimeout(_timers.get(fn));
    _timers.set(fn, setTimeout(() => fn(...args), ms));
  };
}
