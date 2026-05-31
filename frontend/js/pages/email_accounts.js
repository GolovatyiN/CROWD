import { api, auth } from "../api.js";
import { el, fmtRelative, fmtDate, emptyState, tableSkeleton, menuButton, searchInput, sortHeader, copy } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export async function renderEmailAccounts(host) {
  const isAdmin = auth.isAdmin();
  const state = { q: "", is_active: "", assigned_to: "", sort: "id", order: "asc" };

  // Admins need the employee list for the "issue to" dropdown + filter.
  let employees = [];
  if (isAdmin) {
    try { employees = await api.users({ sort: "full_name", order: "asc" }); } catch { /* ignore */ }
  }

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Аккаунты"),
      el("div", { class: "page-subtitle" }, isAdmin
        ? "Общий пул email-аккаунтов — выдавайте их сотрудникам для размещений"
        : "Аккаунты, выданные вам для размещений"),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { onClick: () => openForm(null, load, employees) }, icon("plus", { size: 14 }), el("span", {}, "Новый аккаунт")),
    ),
  ));

  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({
    placeholder: "Поиск по email или метке…",
    onInput: (v) => { state.q = v; debounce(load)(); },
  }));
  sb.appendChild(el("button", { class: "ghost", onClick: () => { filters.style.display = filters.style.display === "none" ? "" : "none"; }},
    icon("filter", { size: 14 }), el("span", {}, "Фильтры")));
  host.appendChild(sb);

  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } });
  filters.appendChild(field("Статус", selectInput(state.is_active, ["", "true", "false"], v => state.is_active = v, "(все)", { true: "активные", false: "неактивные" })));
  if (isAdmin) {
    const opts = ["", "0", ...employees.map(u => String(u.id))];
    const labels = { "0": "Общие (без сотрудника)" };
    employees.forEach(u => labels[String(u.id)] = u.full_name || u.email);
    filters.appendChild(field("Сотрудник", selectInput(state.assigned_to, opts, v => state.assigned_to = v, "(все)", labels)));
  }
  filters.appendChild(el("button", { onClick: load }, "Применить"));
  filters.appendChild(el("button", { class: "ghost", onClick: () => {
    state.q = ""; state.is_active = ""; state.assigned_to = "";
    sb.querySelector("input").value = "";
    filters.querySelectorAll("select").forEach(s => s.value = "");
    load();
  }}, "Сбросить"));
  host.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(5, 6));
    const params = { sort: state.sort, order: state.order };
    if (state.q) params.q = state.q;
    if (state.is_active === "true") params.is_active = true;
    if (state.is_active === "false") params.is_active = false;
    // assigned_to: "0" means "shared only" → we filter client-side for that,
    // otherwise pass through to the server.
    if (state.assigned_to && state.assigned_to !== "0") params.assigned_to = state.assigned_to;
    try {
      let accounts = await api.emailAccounts(params);
      if (state.assigned_to === "0") accounts = accounts.filter(a => !a.assigned_to);
      render(accounts);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function render(accounts) {
    wrap.innerHTML = "";
    if (!accounts.length) {
      wrap.appendChild(emptyState({
        iconName: "user",
        title: isAdmin ? "Аккаунтов пока нет" : "Вам пока не выдали аккаунты",
        desc: isAdmin
          ? "Добавьте email и пароль, затем выдайте его сотруднику."
          : "Когда менеджер выдаст вам аккаунт, он появится здесь.",
        action: isAdmin ? el("button", { onClick: () => openForm(null, load, employees) }, icon("plus", { size: 14 }), el("span", {}, "Новый аккаунт")) : null,
      }));
      return;
    }
    const table = el("table");
    const headCells = [
      sortHeader("Email", "email", state, load, "left"),
      el("th", { class: "left" }, "Пароль"),
      sortHeader("Метка", "label", state, load, "left"),
    ];
    if (isAdmin) headCells.push(sortHeader("Сотрудник", "assigned_to", state, load, "left"));
    headCells.push(el("th", { class: "right" }, "Использован"));
    headCells.push(sortHeader("Статус", "is_active", state, load));
    headCells.push(el("th", { class: "right" }, ""));
    table.appendChild(el("thead", {}, el("tr", {}, ...headCells)));

    const tbody = el("tbody");
    accounts.forEach(a => tbody.appendChild(accountRow(a, load, isAdmin, employees)));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  await load();
}

function accountRow(a, reload, isAdmin, employees) {
  const cells = [
    el("td", { class: "left" },
      el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } },
        el("span", { class: "mono", style: { fontSize: "13px", fontWeight: 500 } }, a.email),
        copyMicroBtn(a.email, "Email скопирован"),
      ),
      a.comment && el("div", { class: "muted", style: { fontSize: "11.5px", marginTop: "2px" } }, a.comment),
    ),
    el("td", { class: "left" }, passwordCell(a.password)),
    el("td", { class: "left muted", style: { fontSize: "12.5px" } }, a.label || el("span", { class: "dimmed" }, "—")),
  ];
  if (isAdmin) {
    cells.push(el("td", { class: "left" }, a.assigned_to
      ? el("span", { class: "pill info" }, a.assignee_name || `#${a.assigned_to}`)
      : el("span", { class: "pill muted" }, "Общий")));
  }
  cells.push(el("td", { class: "right tabular mono", style: { fontSize: "12px" } }, a.usage_count ? String(a.usage_count) : el("span", { class: "dimmed" }, "0")));
  cells.push(el("td", {}, a.is_active ? el("span", { class: "pill success" }, "активен") : el("span", { class: "pill error" }, "неактивен")));

  const menuItems = [
    { label: "Скопировать email", icon: "copy", onClick: async () => { (await copy(a.email)) && toast("Email скопирован", "success"); }},
    a.password && { label: "Скопировать пароль", icon: "copy", onClick: async () => { (await copy(a.password)) && toast("Пароль скопирован", "success"); }},
  ];
  if (isAdmin) {
    menuItems.push({ separator: true });
    menuItems.push({ label: "Редактировать / выдать", icon: "pencil", onClick: () => openForm(a, reload, employees) });
    menuItems.push(a.is_active
      ? { label: "Деактивировать", icon: "trash", onClick: async () => {
          try { await api.updateEmailAccount(a.id, { is_active: false }); toast("Деактивирован", "success"); reload(); }
          catch (e) { toast(e.message, "error"); }
        }}
      : { label: "Активировать", icon: "check", onClick: async () => {
          try { await api.updateEmailAccount(a.id, { is_active: true }); toast("Активирован", "success"); reload(); }
          catch (e) { toast(e.message, "error"); }
        }});
    menuItems.push({ label: "Удалить", icon: "trash", danger: true, onClick: async () => {
      if (!confirm(`Удалить аккаунт ${a.email}?`)) return;
      try { await api.deleteEmailAccount(a.id); toast("Удалено", "success"); reload(); }
      catch (e) { toast(e.message, "error"); }
    }});
  }
  cells.push(el("td", { class: "right actions" }, menuButton(menuItems.filter(Boolean))));

  return el("tr", { style: a.is_active ? null : { opacity: 0.55 } }, ...cells);
}

function passwordCell(pw) {
  if (!pw) return el("span", { class: "dimmed" }, "—");
  let shown = false;
  const val = el("span", { class: "mono", style: { fontSize: "12.5px" } }, "••••••••");
  const eye = el("button", { class: "copy-btn", type: "button", title: "Показать / скрыть",
    onClick: () => { shown = !shown; val.textContent = shown ? pw : "••••••••"; } }, icon("eye", { size: 13 }));
  const cp = el("button", { class: "copy-btn", type: "button", title: "Скопировать",
    onClick: async () => { (await copy(pw)) && toast("Пароль скопирован", "success"); } }, icon("copy", { size: 13 }));
  return el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } }, val, eye, cp);
}

function copyMicroBtn(text, toastText = "Скопировано") {
  return el("button", {
    class: "copy-btn", type: "button", title: "Скопировать",
    style: { width: "22px", height: "22px", padding: 0, opacity: 0.6 },
    onClick: async (e) => { e.preventDefault(); e.stopPropagation(); if (await copy(text)) toast(toastText, "success"); },
  }, icon("copy", { size: 13 }));
}

function openForm(account, reload, employees) {
  const isEdit = !!account;
  const form = el("form", {});
  const fields = [
    ["email", "Email *", "email", account?.email || "", true],
    ["password", "Пароль", "text", account?.password || "", false],
    ["label", "Метка (например, «основной gmail»)", "text", account?.label || "", false],
    ["comment", "Комментарий", "text", account?.comment || "", false],
  ];
  for (const [name, label, type, value, required] of fields) {
    form.appendChild(el("div", { class: "field" },
      el("label", {}, label),
      el("input", { name, type, value, required: required ? "" : null }),
    ));
  }
  // "Issue to" dropdown — the whole point of this screen for admins.
  const assignSelect = document.createElement("select");
  assignSelect.name = "assigned_to";
  const noneOpt = document.createElement("option");
  noneOpt.value = ""; noneOpt.textContent = "Общий (доступен всем)";
  if (!account?.assigned_to) noneOpt.selected = true;
  assignSelect.appendChild(noneOpt);
  (employees || []).filter(u => u.is_active).forEach(u => {
    const o = document.createElement("option");
    o.value = String(u.id);
    o.textContent = u.full_name || u.email;
    if (String(account?.assigned_to) === String(u.id)) o.selected = true;
    assignSelect.appendChild(o);
  });
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Выдать сотруднику"), assignSelect));

  openModal({
    title: isEdit ? "Редактирование аккаунта" : "Новый email-аккаунт",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
        // empty string → shared pool (null)
        data.assigned_to = data.assigned_to ? parseInt(data.assigned_to) : null;
        try {
          if (isEdit) await api.updateEmailAccount(account.id, data);
          else await api.createEmailAccount(data);
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

function selectInput(value, options, onChange, emptyLabel, labels) {
  const sel = document.createElement("select");
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

const _timers = new WeakMap();
function debounce(fn, ms = 250) {
  return (...args) => {
    clearTimeout(_timers.get(fn));
    _timers.set(fn, setTimeout(() => fn(...args), ms));
  };
}
