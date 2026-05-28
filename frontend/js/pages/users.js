import { api } from "../api.js";
import { el, fmtDate, fmtRelative, ROLE_LABELS, avatar, emptyState, tableSkeleton, menuButton, sortHeader } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export async function renderUsers(host) {
  const state = { sort: "id", order: "asc" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Сотрудники"),
      el("div", { class: "page-subtitle" }, "Управление учётными записями"),
    ),
    el("div", { class: "page-actions" },
      el("button", { onClick: () => openUserForm(null, load) }, icon("plus", { size: 14 }), el("span", {}, "Новый сотрудник")),
    ),
  ));

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(5, 5));
    try {
      const users = await api.users({ sort: state.sort, order: state.order });
      renderTable(users);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function renderTable(users) {
    wrap.innerHTML = "";
    if (!users.length) {
      wrap.appendChild(emptyState({ iconName: "users", title: "Нет сотрудников" }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      sortHeader("Сотрудник", "full_name", state, load, "left"),
      sortHeader("Email", "email", state, load, "left"),
      sortHeader("Роль", "role", state, load),
      sortHeader("Статус", "is_active", state, load),
      sortHeader("Создан", "created_at", state, load),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    users.forEach(u => tbody.appendChild(el("tr", {},
      el("td", { class: "left" }, el("div", { class: "row", style: { gap: "10px" } },
        avatar(u.full_name || u.email, 28),
        el("div", { style: { fontWeight: 500 } }, u.full_name || el("span", { class: "muted" }, "Без имени")),
      )),
      el("td", { class: "left mono", style: { fontSize: "12.5px", color: "var(--text-2)" } }, u.email),
      el("td", {}, el("span", { class: `pill ${u.role === "admin" ? "violet" : ""}` }, ROLE_LABELS[u.role] || u.role)),
      el("td", {}, u.is_active ? el("span", { class: "pill success" }, "активен") : el("span", { class: "pill error" }, "неактивен")),
      el("td", { class: "muted", style: { fontSize: "12px" }, title: fmtDate(u.created_at) }, fmtRelative(u.created_at)),
      el("td", { class: "right actions" }, menuButton([
        { label: "Редактировать", icon: "pencil", onClick: () => openUserForm(u, load) },
        u.is_active && { separator: true },
        u.is_active && { label: "Деактивировать", icon: "trash", danger: true, onClick: async () => {
          if (!confirm("Деактивировать сотрудника?")) return;
          try { await api.deactivateUser(u.id); toast("Деактивирован", "success"); load(); }
          catch (e) { toast(e.message, "error"); }
        }},
      ])),
    )));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  await load();
}

function openUserForm(user, reload) {
  const isEdit = !!user;
  const form = el("form", {});
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Email"),
    el("input", { name: "email", type: "email", value: user?.email || "", required: true, readonly: isEdit ? "" : null })));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Полное имя"),
    el("input", { name: "full_name", type: "text", value: user?.full_name || "" })));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Роль"),
    selectInput(user?.role || "employee", ["employee", "admin"], "role", ROLE_LABELS)));
  form.appendChild(el("div", { class: "field" }, el("label", {}, isEdit ? "Новый пароль (не обязательно)" : "Пароль *"),
    el("input", { name: "password", type: "password", required: isEdit ? null : "" })));
  if (isEdit) {
    form.appendChild(el("div", { class: "field" }, el("label", {}, "Активен"),
      selectInput(String(user.is_active), ["true", "false"], "is_active", { true: "да", false: "нет" })));
  }

  openModal({
    title: isEdit ? "Редактирование сотрудника" : "Новый сотрудник",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => { if (v !== "") data[k] = v; });
        if ("is_active" in data) data.is_active = data.is_active === "true";
        try {
          if (isEdit) await api.updateUser(user.id, data);
          else await api.createUser(data);
          toast("Сохранено", "success"); closeModal(); reload();
        } catch (e) { toast(e.message, "error"); }
      }}, "Сохранить"));
      return f;
    })(),
  });
}

function selectInput(value, options, name, labels) {
  const sel = document.createElement("select");
  if (name) sel.name = name;
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o;
    opt.textContent = labels && labels[o] ? labels[o] : o;
    if (String(o) === String(value)) opt.selected = true;
    sel.appendChild(opt);
  });
  return sel;
}
