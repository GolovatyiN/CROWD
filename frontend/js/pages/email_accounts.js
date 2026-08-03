import { api, auth } from "../api.js";
import { el, fmtRelative, fmtDate, emptyState, tableSkeleton, menuButton, searchInput, sortHeader, copy, avatar } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export async function renderEmailAccounts(host) {
  const isAdmin = auth.isAdmin();
  const view = { mode: "pool" };  // pool | employees (employees is admin-only)

  // Admins need the employee list for the "issue to" dropdown + filter.
  let employees = [];
  if (isAdmin) {
    try { employees = await api.users({ sort: "full_name", order: "asc" }); } catch { /* ignore */ }
  }

  const header = el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Аккаунты"),
      el("div", { class: "page-subtitle" }, isAdmin
        ? "Общий пул email-аккаунтов — выдавайте их сотрудникам для размещений"
        : "Аккаунты, выданные вам для размещений"),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { onClick: () => openForm(null, () => mount(), employees) }, icon("plus", { size: 14 }), el("span", {}, "Новый аккаунт")),
    ),
  );
  host.appendChild(header);

  // Segmented switch between the pool table and the per-employee breakdown.
  if (isAdmin) {
    const seg = el("div", { class: "segmented", style: { marginBottom: "14px" } });
    const SEGS = [["pool", "Пул аккаунтов"], ["employees", "По сотрудникам"]];
    const rebuild = () => {
      seg.innerHTML = "";
      SEGS.forEach(([m, label]) => seg.appendChild(el("button", {
        class: `seg ${view.mode === m ? "active" : ""}`,
        onClick: () => { if (view.mode !== m) { view.mode = m; rebuild(); mount(); } },
      }, label)));
    };
    rebuild();
    host.appendChild(seg);
  }

  const container = el("div", {});
  host.appendChild(container);

  function mount() {
    container.innerHTML = "";
    if (view.mode === "employees" && isAdmin) mountEmployees(container);
    else mountPool(container, isAdmin, employees);
  }
  mount();
}

// ---------------- Pool view (the shared mailbox table) ----------------

function mountPool(root, isAdmin, employees) {
  const state = { q: "", is_active: "", assigned_to: "", sort: "id", order: "asc" };

  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({
    placeholder: "Поиск по email или метке…",
    onInput: (v) => { state.q = v; debounce(load)(); },
  }));
  sb.appendChild(el("button", { class: "ghost", onClick: () => { filters.style.display = filters.style.display === "none" ? "" : "none"; } },
    icon("filter", { size: 14 }), el("span", {}, "Фильтры")));
  root.appendChild(sb);

  const filters = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } });
  filters.appendChild(field("Статус", selectInput(state.is_active, ["", "true", "false"], v => state.is_active = v, "(все)", { true: "активные", false: "неактивные" })));
  if (isAdmin) {
    const opts = ["", "0", ...employees.map(u => String(u.id))];
    const labels = { "0": "Общие (без сотрудника)" };
    employees.forEach(u => labels[String(u.id)] = u.full_name || u.email);
    filters.appendChild(field("Сотрудник", selectInput(state.assigned_to, opts, v => state.assigned_to = v, "(все)", labels)));
  }
  filters.appendChild(el("button", { onClick: () => load() }, "Применить"));
  filters.appendChild(el("button", { class: "ghost", onClick: () => {
    state.q = ""; state.is_active = ""; state.assigned_to = "";
    sb.querySelector("input").value = "";
    filters.querySelectorAll("select").forEach(s => s.value = "");
    load();
  } }, "Сбросить"));
  root.appendChild(filters);

  const wrap = el("div", { class: "table-wrap" });
  root.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(5, 7));
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
    headCells.push(el("th", { class: "right" }, "Доноры"));
    headCells.push(el("th", { class: "right" }, "Размещений"));
    headCells.push(sortHeader("Статус", "is_active", state, load));
    headCells.push(el("th", { class: "right" }, ""));
    table.appendChild(el("thead", {}, el("tr", {}, ...headCells)));

    const tbody = el("tbody");
    accounts.forEach(a => tbody.appendChild(accountRow(a, load, isAdmin, employees)));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  load();
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
  // Доноры — how many distinct donors this mailbox has served; click to see them.
  const donorsUsed = a.donors_used || 0;
  cells.push(el("td", { class: "right" }, donorsUsed
    ? el("button", { class: "subtle small", style: { fontFamily: "var(--mono)", fontSize: "12px" }, title: "На каких донорах использован",
        onClick: () => openDonorsModal(a.id, a.email) }, String(donorsUsed))
    : el("span", { class: "dimmed" }, "0")));
  cells.push(el("td", { class: "right tabular mono", style: { fontSize: "12px" } }, a.usage_count ? String(a.usage_count) : el("span", { class: "dimmed" }, "0")));
  cells.push(el("td", {}, a.is_active ? el("span", { class: "pill success" }, "активен") : el("span", { class: "pill error" }, "неактивен")));

  const menuItems = [
    { label: "На каких донорах", icon: "donors", onClick: () => openDonorsModal(a.id, a.email) },
    { label: "Скопировать email", icon: "copy", onClick: async () => { (await copy(a.email)) && toast("Email скопирован", "success"); } },
    a.password && { label: "Скопировать пароль", icon: "copy", onClick: async () => { (await copy(a.password)) && toast("Пароль скопирован", "success"); } },
  ];
  if (isAdmin) {
    menuItems.push({ separator: true });
    menuItems.push({ label: "Редактировать / выдать", icon: "pencil", onClick: () => openForm(a, reload, employees) });
    menuItems.push(a.is_active
      ? { label: "Деактивировать", icon: "trash", onClick: async () => {
          try { await api.updateEmailAccount(a.id, { is_active: false }); toast("Деактивирован", "success"); reload(); }
          catch (e) { toast(e.message, "error"); }
        } }
      : { label: "Активировать", icon: "check", onClick: async () => {
          try { await api.updateEmailAccount(a.id, { is_active: true }); toast("Активирован", "success"); reload(); }
          catch (e) { toast(e.message, "error"); }
        } });
    menuItems.push({ label: "Удалить", icon: "trash", danger: true, onClick: async () => {
      if (!confirm(`Удалить аккаунт ${a.email}?`)) return;
      try { await api.deleteEmailAccount(a.id); toast("Удалено", "success"); reload(); }
      catch (e) { toast(e.message, "error"); }
    } });
  }
  cells.push(el("td", { class: "right actions" }, menuButton(menuItems.filter(Boolean))));

  return el("tr", { style: a.is_active ? null : { opacity: 0.55 } }, ...cells);
}

// ---------------- By-employee view ----------------

async function mountEmployees(root) {
  root.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "12px" } },
    "Сколько ящиков закреплено за каждым сотрудником и на скольких донорах они уже использованы."));
  const wrap = el("div", { class: "table-wrap" });
  root.appendChild(wrap);
  wrap.appendChild(tableSkeleton(5, 5));

  let rows;
  try { rows = await api.emailAccountEmployeeStats(); }
  catch (e) { wrap.innerHTML = ""; wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }

  wrap.innerHTML = "";
  if (!rows.length) {
    wrap.appendChild(emptyState({ iconName: "users", title: "Пока нет данных",
      desc: "Выдайте сотрудникам email-аккаунты из пула — здесь появится их статистика." }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "Сотрудник"),
    el("th", { class: "right" }, "Ящиков закреплено"),
    el("th", { class: "right" }, "Активных"),
    el("th", { class: "right" }, "Доноров покрыто"),
    el("th", { class: "right" }, "Размещений"),
  )));
  const tbody = el("tbody");
  rows.forEach(r => tbody.appendChild(el("tr", {},
    el("td", { class: "left" },
      el("div", { style: { display: "flex", alignItems: "center", gap: "8px" } },
        avatar(r.name, 26),
        el("div", {},
          el("div", { style: { fontSize: "13.5px", fontWeight: 500 } }, r.name),
          el("div", { class: "muted", style: { fontSize: "11.5px" } }, r.email),
        ),
      ),
    ),
    el("td", { class: "right tabular mono", style: { fontSize: "13px" } }, String(r.assigned_mailboxes)),
    el("td", { class: "right tabular mono muted", style: { fontSize: "12.5px" } }, String(r.active_mailboxes)),
    el("td", { class: "right tabular mono", style: { fontSize: "13px" } }, r.donors_covered ? String(r.donors_covered) : el("span", { class: "dimmed" }, "0")),
    el("td", { class: "right tabular mono", style: { fontSize: "13px" } }, r.placements ? String(r.placements) : el("span", { class: "dimmed" }, "0")),
  )));
  table.appendChild(tbody);
  wrap.appendChild(table);
}

// ---------------- Donors-of-a-mailbox modal ----------------

async function openDonorsModal(accountId, email) {
  const body = el("div", {}, tableSkeleton(4, 2));
  openModal({
    title: `Доноры аккаунта ${email}`,
    content: body,
    size: "lg",
    footer: el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { class: "ghost", onClick: () => closeModal() }, "Закрыть")),
  });
  let data;
  try { data = await api.emailAccountDonors(accountId); }
  catch (e) { body.innerHTML = ""; body.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }
  body.innerHTML = "";
  const donors = data.donors || [];
  if (!donors.length) {
    body.appendChild(emptyState({ iconName: "donors", title: "Ещё не использован",
      desc: "Этот ящик пока не привязан ни к одному донору." }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "Донор"),
    el("th", { class: "left" }, "Аккаунт (username)"),
    el("th", {}, "Статус"),
  )));
  const tbody = el("tbody");
  donors.forEach(d => tbody.appendChild(el("tr", {},
    el("td", { class: "left mono", style: { fontSize: "12.5px" } }, d.domain || `#${d.donor_id}`),
    el("td", { class: "left mono muted", style: { fontSize: "12px" } }, d.account_username || el("span", { class: "dimmed" }, "—")),
    el("td", {}, d.is_active ? el("span", { class: "pill success" }, "активен") : el("span", { class: "pill muted" }, "неактивен")),
  )));
  table.appendChild(tbody);
  body.appendChild(el("div", { class: "table-wrap", style: { maxHeight: "420px", overflow: "auto" } }, table));
}

// ---------------- shared helpers ----------------

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
      } }, "Сохранить"));
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
