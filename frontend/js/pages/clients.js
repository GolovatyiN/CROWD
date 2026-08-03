import { api, auth } from "../api.js";
import { el, fmtDate, emptyState, tableSkeleton, menuButton, submitButton, pill } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

const CLIENT_STATUS = { active: "Активен", paused: "На паузе", archived: "В архиве" };
const PROJECT_STATUS = { active: "Активен", paused: "На паузе", done: "Завершён", archived: "В архиве" };

function statusChip(map, s) {
  const variant = s === "active" ? "success" : s === "archived" ? "muted" : "warning";
  return pill(map[s] || s || "—", variant);
}

// ---------------- Clients list ----------------

export async function renderClients(host) {
  const isAdmin = auth.isAdmin();
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Клиенты"),
      el("div", { class: "page-subtitle" }, "Внешние клиенты и их проекты"),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { onClick: () => clientModal(null, load) }, icon("plus", { size: 14 }), el("span", {}, "Создать клиента")),
    ),
  ));
  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(5, 6));
    let data;
    try { data = await api.clients(); }
    catch (e) { wrap.innerHTML = ""; wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }
    wrap.innerHTML = "";
    if (!data.length) {
      wrap.appendChild(emptyState({ iconName: "user", title: "Пока нет клиентов",
        desc: "Создайте первого клиента, чтобы вести клиентские проекты.",
        action: isAdmin && el("button", { onClick: () => clientModal(null, load) }, icon("plus", { size: 14 }), el("span", {}, "Создать клиента")) }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "left" }, "Клиент"),
      el("th", {}, "Статус"),
      el("th", { class: "right" }, "Проектов"),
      el("th", { class: "right" }, "Размещений"),
      el("th", {}, "Создан"),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    data.forEach(c => tbody.appendChild(clientRow(c, load, isAdmin)));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }
  await load();
}

function clientRow(c, reload, isAdmin) {
  return el("tr", {},
    el("td", { class: "left" },
      el("a", { href: `#/clients/${c.id}`, style: { fontWeight: 500 } }, c.name),
      c.contact_info && el("div", { class: "mono", style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: "2px" } }, c.contact_info),
    ),
    el("td", {}, statusChip(CLIENT_STATUS, c.status)),
    el("td", { class: "right tabular mono" }, String(c.projects_count || 0)),
    el("td", { class: "right tabular mono" }, `${c.placements_done || 0} / ${c.placements_total || 0}`),
    el("td", { class: "muted", style: { fontSize: "12px" } }, fmtDate(c.created_at)),
    el("td", { class: "right actions" }, menuButton([
      { label: "Открыть", icon: "external", onClick: () => location.hash = `#/clients/${c.id}` },
      isAdmin && { label: "Редактировать", icon: "pencil", onClick: () => clientModal(c, reload) },
      isAdmin && { separator: true },
      isAdmin && { label: c.status === "archived" ? "В архиве" : "В архив", icon: "trash", danger: true, onClick: async () => {
        if (c.status === "archived") return;
        if (!confirm(`Отправить клиента «${c.name}» в архив?`)) return;
        try { await api.archiveClient(c.id); toast("В архиве", "success"); reload(); } catch (e) { toast(e.message, "error"); }
      } },
    ])),
  );
}

function clientModal(client, onDone) {
  const name = el("input", { type: "text", value: client?.name || "", placeholder: "Название клиента" });
  const contact = el("input", { type: "text", value: client?.contact_info || "", placeholder: "Email / телефон / контакт" });
  const comment = el("textarea", { rows: 3, placeholder: "Комментарий" }, client?.comment || "");
  const status = el("select", {},
    ...Object.entries(CLIENT_STATUS).map(([v, l]) => el("option", { value: v, selected: (client?.status || "active") === v }, l)));
  const content = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Название"), name),
    el("div", { class: "field" }, el("label", {}, "Контакты"), contact),
    el("div", { class: "field" }, el("label", {}, "Статус"), status),
    el("div", { class: "field" }, el("label", {}, "Комментарий"), comment),
  );
  const footer = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
    el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"),
    submitButton(client ? "Сохранить" : "Создать", async () => {
      if (!name.value.trim()) { toast("Введите название", "error"); return; }
      const data = { name: name.value.trim(), contact_info: contact.value, comment: comment.value, status: status.value };
      try {
        if (client) await api.updateClient(client.id, data); else await api.createClient(data);
        toast(client ? "Сохранено" : "Клиент создан", "success"); closeModal(); onDone && onDone();
      } catch (e) { toast(e.message, "error"); }
    }),
  );
  openModal({ title: client ? "Клиент" : "Новый клиент", content, footer });
  setTimeout(() => name.focus(), 50);
}

// ---------------- Client detail (projects) ----------------

export async function renderClientDetail(host, clientId) {
  const isAdmin = auth.isAdmin();
  let client, projects, users;
  try {
    [client, projects, users] = await Promise.all([
      api.client(clientId), api.clientProjects({ client_id: clientId }), api.users().catch(() => []),
    ]);
  } catch (e) { host.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "row", style: { gap: "8px", alignItems: "center" } },
        el("a", { href: "#/clients", class: "subtle", style: { display: "inline-flex", padding: "2px" } }, icon("chevronLeft", { size: 16 })),
        el("div", { class: "page-title" }, client.name),
        statusChip(CLIENT_STATUS, client.status),
      ),
      el("div", { class: "page-subtitle" }, `${client.contact_info || "—"} · проектов ${client.projects_count} · размещений ${client.placements_done}/${client.placements_total}`),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { onClick: () => projectModal(clientId, null, users, () => location.reload()) }, icon("plus", { size: 14 }), el("span", {}, "Создать проект")),
    ),
  ));

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);
  if (!projects.length) {
    wrap.appendChild(emptyState({ iconName: "plans", title: "Нет проектов у клиента",
      desc: "Создайте клиентский проект, затем импортируйте в него анкор-план.",
      action: isAdmin && el("button", { onClick: () => projectModal(clientId, null, users, () => location.reload()) }, icon("plus", { size: 14 }), el("span", {}, "Создать проект")) }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "Проект"),
    el("th", {}, "GEO / язык"),
    el("th", { class: "right" }, "План"),
    el("th", { class: "right" }, "Готово / всего"),
    el("th", {}, "Статус"),
    el("th", { class: "right" }, "Сотрудников"),
    el("th", { class: "right" }, ""),
  )));
  const tbody = el("tbody");
  projects.forEach(p => tbody.appendChild(projectRow(p, clientId, users, isAdmin)));
  table.appendChild(tbody);
  wrap.appendChild(table);
}

function projectRow(p, clientId, users, isAdmin) {
  return el("tr", {},
    el("td", { class: "left" },
      el("div", { style: { fontWeight: 500 } }, p.name),
      p.promoted_domain && el("div", { class: "mono", style: { fontSize: "11.5px", color: "var(--text-3)" } }, p.promoted_domain),
    ),
    el("td", { class: "muted", style: { fontSize: "12px" } }, `${p.geo || "—"} / ${p.language || "—"}`),
    el("td", { class: "right tabular mono" }, String(p.planned_count || 0)),
    el("td", { class: "right tabular mono" }, `${p.completed_rows || 0} / ${p.total_rows || 0}`),
    el("td", {}, statusChip(PROJECT_STATUS, p.status)),
    el("td", { class: "right tabular mono" }, String((p.member_ids || []).length)),
    el("td", { class: "right actions" }, menuButton([
      { label: "Импортировать план", icon: "upload", onClick: () => { sessionStorage.setItem("import_client_project", String(p.id)); location.hash = "#/import-export"; } },
      { label: "Скачать отчёт", icon: "download", onClick: () => api.clientProjectReportInternal(p.id).catch(e => toast(e.message, "error")) },
      isAdmin && { label: "Редактировать", icon: "pencil", onClick: () => projectModal(clientId, p, users, () => location.reload()) },
      isAdmin && { separator: true },
      isAdmin && { label: "В архив", icon: "trash", danger: true, onClick: async () => {
        if (!confirm(`Отправить проект «${p.name}» в архив?`)) return;
        try { await api.archiveClientProject(p.id); toast("В архиве", "success"); location.reload(); } catch (e) { toast(e.message, "error"); }
      } },
    ])),
  );
}

function projectModal(clientId, project, users, onDone) {
  const f = {
    name: el("input", { type: "text", value: project?.name || "", placeholder: "Название проекта" }),
    promoted_domain: el("input", { type: "text", value: project?.promoted_domain || "", placeholder: "example.com" }),
    geo: el("input", { type: "text", value: project?.geo || "", placeholder: "US" }),
    language: el("input", { type: "text", value: project?.language || "", placeholder: "en" }),
    planned_count: el("input", { type: "number", value: project?.planned_count || 0, min: "0" }),
    donor_requirements: el("textarea", { rows: 2, placeholder: "Требования к донорам" }, project?.donor_requirements || ""),
    status: el("select", {}, ...Object.entries(PROJECT_STATUS).map(([v, l]) => el("option", { value: v, selected: (project?.status || "active") === v }, l))),
  };
  // Employees as assignable members (checkbox list).
  const employees = (users || []).filter(u => u.is_active);
  const selected = new Set(project?.member_ids || []);
  const memberBox = el("div", { style: { maxHeight: "140px", overflow: "auto", border: "1px solid var(--border)", borderRadius: "8px", padding: "6px" } },
    ...employees.map(u => {
      const cb = el("input", { type: "checkbox", checked: selected.has(u.id) });
      cb.addEventListener("change", () => cb.checked ? selected.add(u.id) : selected.delete(u.id));
      return el("label", { class: "row", style: { gap: "8px", padding: "3px 2px", cursor: "pointer" } }, cb, el("span", {}, u.full_name || u.email));
    }),
    !employees.length && el("div", { class: "dimmed", style: { fontSize: "12px" } }, "Нет сотрудников"),
  );
  const content = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Название"), f.name),
    el("div", { class: "row", style: { gap: "8px" } },
      el("div", { class: "field", style: { flex: 2 } }, el("label", {}, "Продвигаемый домен"), f.promoted_domain),
      el("div", { class: "field", style: { flex: 1 } }, el("label", {}, "GEO"), f.geo),
      el("div", { class: "field", style: { flex: 1 } }, el("label", {}, "Язык"), f.language),
    ),
    el("div", { class: "row", style: { gap: "8px" } },
      el("div", { class: "field", style: { flex: 1 } }, el("label", {}, "План размещений"), f.planned_count),
      el("div", { class: "field", style: { flex: 1 } }, el("label", {}, "Статус"), f.status),
    ),
    el("div", { class: "field" }, el("label", {}, "Требования к донорам"), f.donor_requirements),
    el("div", { class: "field" }, el("label", {}, "Назначенные сотрудники"), memberBox),
  );
  const footer = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
    el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"),
    submitButton(project ? "Сохранить" : "Создать", async () => {
      if (!f.name.value.trim()) { toast("Введите название", "error"); return; }
      const data = {
        name: f.name.value.trim(), promoted_domain: f.promoted_domain.value, geo: f.geo.value,
        language: f.language.value, planned_count: parseInt(f.planned_count.value) || 0,
        donor_requirements: f.donor_requirements.value, status: f.status.value,
        member_ids: [...selected],
      };
      try {
        if (project) await api.updateClientProject(project.id, data);
        else await api.createClientProject({ client_id: clientId, ...data });
        toast(project ? "Сохранено" : "Проект создан", "success"); closeModal(); onDone && onDone();
      } catch (e) { toast(e.message, "error"); }
    }),
  );
  openModal({ title: project ? "Клиентский проект" : "Новый проект", content, footer, size: "lg" });
  setTimeout(() => f.name.focus(), 50);
}
