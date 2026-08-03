import { api, auth } from "../api.js";
import { el, fmtDate, fmtRelative, ROLE_LABELS, avatar, emptyState, tableSkeleton, menuButton, sortHeader, searchInput } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

const ROLES = ["user", "teamlead", "manager", "admin", "super_admin", "client"];

export async function renderUsers(host) {
  const state = { q: "", role: "", is_active: "", sort: "id", order: "asc" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Сотрудники"),
      el("div", { class: "page-subtitle" }, "Управление учётными записями и ролями"),
    ),
    el("div", { class: "page-actions" },
      el("button", { onClick: () => openUserForm(null, load) }, icon("plus", { size: 14 }), el("span", {}, "Новый сотрудник")),
    ),
  ));

  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({
    placeholder: "Поиск по имени или email…",
    onInput: (v) => { state.q = v; debounce(load)(); },
  }));
  sb.appendChild(el("button", { class: "ghost", onClick: () => { filters.style.display = filters.style.display === "none" ? "" : "none"; } },
    icon("filter", { size: 14 }), el("span", {}, "Фильтры")));
  host.appendChild(sb);

  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } });
  filters.appendChild(field("Роль", selectInput(state.role, ["", ...ROLES], v => state.role = v, "(все)", ROLE_LABELS)));
  filters.appendChild(field("Статус", selectInput(state.is_active, ["", "true", "false"], v => state.is_active = v, "(все)", { true: "активные", false: "неактивные" })));
  filters.appendChild(el("button", { onClick: load }, "Применить"));
  filters.appendChild(el("button", { class: "ghost", onClick: () => {
    state.q = ""; state.role = ""; state.is_active = "";
    sb.querySelector("input").value = "";
    filters.querySelectorAll("select").forEach(s => s.value = "");
    load();
  }}, "Сбросить"));
  host.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(5, 5));
    const params = { sort: state.sort, order: state.order };
    if (state.q) params.q = state.q;
    if (state.role) params.role = state.role;
    if (state.is_active === "true") params.is_active = true;
    if (state.is_active === "false") params.is_active = false;
    try {
      const users = await api.users(params);
      renderTable(users);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function renderTable(users) {
    wrap.innerHTML = "";
    if (!users.length) {
      wrap.appendChild(emptyState({ iconName: "users", title: "Ничего не найдено", desc: "Попробуйте сбросить фильтры." }));
      return;
    }
    const me = auth.getUser();
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
    users.forEach(u => tbody.appendChild(el("tr", { style: u.is_active ? null : { opacity: 0.6 } },
      el("td", { class: "left" }, el("div", { class: "row", style: { gap: "10px" } },
        avatar(u.full_name || u.email, 28),
        el("div", { style: { fontWeight: 500 } },
          u.full_name || el("span", { class: "muted" }, "Без имени"),
          me && u.id === me.id ? el("span", { class: "muted", style: { fontSize: "11.5px", marginLeft: "6px" } }, "— это вы") : null,
        ),
      )),
      el("td", { class: "left mono", style: { fontSize: "12.5px", color: "var(--text-2)" } }, u.email),
      el("td", {}, el("span", { class: `pill ${roleVariant(u.role)}` }, ROLE_LABELS[u.role] || u.role)),
      el("td", {}, u.is_active ? el("span", { class: "pill success" }, "активен") : el("span", { class: "pill error" }, "неактивен")),
      el("td", { class: "muted", style: { fontSize: "12px" }, title: fmtDate(u.created_at) }, fmtRelative(u.created_at)),
      el("td", { class: "right actions" }, menuButton([
        { label: "Редактировать", icon: "pencil", onClick: () => openUserForm(u, load) },
        u.is_active && (me?.id !== u.id) && { separator: true },
        u.is_active && (me?.id !== u.id) && { label: "Деактивировать", icon: "trash", danger: true, onClick: async () => {
          if (!confirm(`Деактивировать ${u.full_name || u.email}? Сессия будет немедленно прервана.`)) return;
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

function roleVariant(role) {
  if (role === "super_admin") return "violet";
  if (role === "admin") return "info";
  return "";
}

async function openUserForm(user, reload) {
  const isEdit = !!user;
  const clients = await api.clients().catch(() => []);
  const form = el("form", {});
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Email"),
    el("input", { name: "email", type: "email", value: user?.email || "", required: true, readonly: isEdit ? "" : null })));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Полное имя"),
    el("input", { name: "full_name", type: "text", value: user?.full_name || "" })));
  // Client selector — shown ONLY when the role is «Клиент» (irrelevant for staff
  // roles). Hidden fields are cleared so client_id isn't submitted for staff.
  const clientLabels = {};
  clients.forEach(c => (clientLabels[c.id] = c.name));
  const clientField = el("div", { class: "field" }, el("label", {}, "Клиент"),
    selectInput(user?.client_id || "", ["", ...clients.map(c => c.id)], () => {}, "— выберите клиента —", clientLabels, "client_id"));
  const clientSelect = clientField.querySelector("select");
  const toggleClientField = (role) => {
    const show = role === "client";
    clientField.style.display = show ? "" : "none";
    if (!show && clientSelect) clientSelect.value = "";
  };
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Роль"),
    selectInput(user?.role || "user", ROLES, toggleClientField, "user", ROLE_LABELS, "role")));
  form.appendChild(clientField);
  toggleClientField(user?.role || "user");
  form.appendChild(el("div", { class: "field" }, el("label", {}, isEdit ? "Новый пароль (не обязательно)" : "Пароль *"),
    el("input", { name: "password", type: "password", required: isEdit ? null : "" })));
  if (isEdit) {
    form.appendChild(el("div", { class: "field" }, el("label", {}, "Активен"),
      selectInput(String(user.is_active), ["true", "false"], () => {}, "true", { true: "да", false: "нет" }, "is_active")));
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

function field(label, input) {
  return el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, label), input);
}

function selectInput(value, options, onChange, emptyLabel, labels, name) {
  const sel = document.createElement("select");
  if (name) sel.name = name;
  sel.addEventListener("change", e => onChange && onChange(e.target.value));
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o;
    if (String(o) === String(value)) opt.selected = true;
    opt.textContent = !o ? (emptyLabel || "(все)") : (labels && labels[o]) || o;
    sel.appendChild(opt);
  });
  return sel;
}

const _timers = new WeakMap();
function debounce(fn, ms = 250) {
  return (...args) => {
    clearTimeout(_timers.get(fn));
    _timers.set(fn, setTimeout(() => fn(...args), ms));
  };
}
