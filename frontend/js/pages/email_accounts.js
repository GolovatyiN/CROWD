import { api } from "../api.js";
import { el, fmtRelative, fmtDate, emptyState, tableSkeleton, menuButton, searchInput, sortHeader, copy } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export async function renderEmailAccounts(host) {
  const state = { q: "", is_active: "", sort: "id", order: "asc" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Аккаунты"),
      el("div", { class: "page-subtitle" }, "Общий пул email-аккаунтов для регистрации на донорах"),
    ),
    el("div", { class: "page-actions" },
      el("button", { onClick: () => openForm(null, load) }, icon("plus", { size: 14 }), el("span", {}, "Новый аккаунт")),
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
  filters.appendChild(el("button", { onClick: load }, "Применить"));
  filters.appendChild(el("button", { class: "ghost", onClick: () => {
    state.q = ""; state.is_active = "";
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
    if (state.is_active === "true") params.is_active = true;
    if (state.is_active === "false") params.is_active = false;
    try {
      const accounts = await api.emailAccounts(params);
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
        title: "Аккаунтов пока нет",
        desc: "Добавьте email и пароль — потом сможете быстро выбирать его при отметке размещения.",
        action: el("button", { onClick: () => openForm(null, load) }, icon("plus", { size: 14 }), el("span", {}, "Новый аккаунт")),
      }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      sortHeader("Email", "email", state, load, "left"),
      el("th", { class: "left" }, "Пароль"),
      sortHeader("Метка", "label", state, load, "left"),
      el("th", { class: "right" }, "Использован"),
      sortHeader("Статус", "is_active", state, load),
      sortHeader("Создан", "created_at", state, load),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    accounts.forEach(a => tbody.appendChild(accountRow(a, load)));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  await load();
}

function accountRow(a, reload) {
  return el("tr", { style: a.is_active ? null : { opacity: 0.55 } },
    el("td", { class: "left" },
      el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } },
        el("span", { class: "mono", style: { fontSize: "13px", fontWeight: 500 } }, a.email),
        copyMicroBtn(a.email, "Email скопирован"),
      ),
      a.comment && el("div", { class: "muted", style: { fontSize: "11.5px", marginTop: "2px" } }, a.comment),
    ),
    el("td", { class: "left" }, passwordCell(a.password)),
    el("td", { class: "left muted", style: { fontSize: "12.5px" } }, a.label || el("span", { class: "dimmed" }, "—")),
    el("td", { class: "right tabular mono", style: { fontSize: "12px" } }, a.usage_count ? String(a.usage_count) : el("span", { class: "dimmed" }, "0")),
    el("td", {}, a.is_active ? el("span", { class: "pill success" }, "активен") : el("span", { class: "pill error" }, "неактивен")),
    el("td", { class: "muted", style: { fontSize: "12px" }, title: fmtDate(a.created_at) }, fmtRelative(a.created_at)),
    el("td", { class: "right actions" }, menuButton([
      { label: "Скопировать email", icon: "copy", onClick: async () => { (await copy(a.email)) && toast("Email скопирован", "success"); }},
      a.password && { label: "Скопировать пароль", icon: "copy", onClick: async () => { (await copy(a.password)) && toast("Пароль скопирован", "success"); }},
      { separator: true },
      { label: "Редактировать", icon: "pencil", onClick: () => openForm(a, reload) },
      a.is_active && { label: "Деактивировать", icon: "trash", onClick: async () => {
        try { await api.updateEmailAccount(a.id, { is_active: false }); toast("Деактивирован", "success"); reload(); }
        catch (e) { toast(e.message, "error"); }
      }},
      !a.is_active && { label: "Активировать", icon: "check", onClick: async () => {
        try { await api.updateEmailAccount(a.id, { is_active: true }); toast("Активирован", "success"); reload(); }
        catch (e) { toast(e.message, "error"); }
      }},
      { label: "Удалить", icon: "trash", danger: true, onClick: async () => {
        if (!confirm(`Удалить аккаунт ${a.email}? История размещений не пострадает.`)) return;
        try { await api.deleteEmailAccount(a.id); toast("Удалено", "success"); reload(); }
        catch (e) { toast(e.message, "error"); }
      }},
    ])),
  );
}

function passwordCell(pw) {
  if (!pw) return el("span", { class: "dimmed" }, "—");
  let shown = false;
  const val = el("span", { class: "mono", style: { fontSize: "12.5px" } }, "••••••••");
  const eye = el("button", {
    class: "copy-btn", type: "button", title: "Показать / скрыть",
    onClick: () => { shown = !shown; val.textContent = shown ? pw : "••••••••"; },
  }, icon("eye", { size: 13 }));
  const cp = el("button", {
    class: "copy-btn", type: "button", title: "Скопировать",
    onClick: async () => { (await copy(pw)) && toast("Пароль скопирован", "success"); },
  }, icon("copy", { size: 13 }));
  return el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } }, val, eye, cp);
}

function copyMicroBtn(text, toastText = "Скопировано") {
  return el("button", {
    class: "copy-btn", type: "button", title: "Скопировать",
    style: { width: "22px", height: "22px", padding: 0, opacity: 0.6 },
    onClick: async (e) => {
      e.preventDefault(); e.stopPropagation();
      if (await copy(text)) toast(toastText, "success");
    },
  }, icon("copy", { size: 13 }));
}

function openForm(account, reload) {
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
  openModal({
    title: isEdit ? "Редактирование аккаунта" : "Новый email-аккаунт",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
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
