import { api, auth } from "../api.js";
import { el, statusPill, fmtDate, emptyState, tableSkeleton, menuButton, searchInput, copy } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

const LINK_TYPES = ["dofollow", "nofollow", "mixed", "error", "unknown"];
const LINK_TYPE_VARIANT = { dofollow: "success", nofollow: "muted", mixed: "info", error: "error", unknown: "" };

const PAGE_SIZE = 100;

export async function renderDonors(host) {
  const isAdmin = auth.isAdmin();
  const state = {
    q: "", geo: "", language: "", link_type: "",
    min_tr: "", min_traffic: "", min_ref_domains: "", min_backlinks: "",
    is_active: "", used: "",
    sort: "tr", order: "desc",
    offset: 0,
  };
  let total = 0;
  let loadedItems = [];
  const selected = new Set();

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Доноры"),
      el("div", { class: "page-subtitle" }, "База площадок для размещения ссылок"),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { class: "ghost", onClick: () => api.exportDonors() }, icon("download", { size: 14 }), el("span", {}, "Экспорт")),
      isAdmin && el("button", { class: "ghost", onClick: () => location.hash = "#/import-export" }, icon("upload", { size: 14 }), el("span", {}, "Импорт")),
      isAdmin && el("button", { onClick: () => openDonorForm(null, refresh) }, icon("plus", { size: 14 }), el("span", {}, "Новый донор")),
      isAdmin && el("button", { class: "danger ghost", onClick: () => deleteAllDonors() }, icon("trash", { size: 14 }), el("span", {}, "Удалить всё")),
    ),
  ));

  // Wipe the entire donor base — double confirm because it's destructive and
  // unbounded (ignores filters: removes everything).
  async function deleteAllDonors() {
    if (!total && !loadedItems.length) { toast("База доноров уже пуста", "warning"); return; }
    if (!confirm(`Удалить ВСЕХ доноров (${total})? История размещений и стоп-лист сохранятся, но связь с донорами потеряется.`)) return;
    if (!confirm("Точно удалить всю базу доноров? Это нельзя отменить.")) return;
    try {
      const r = await api.deleteAllDonors();
      toast(`Удалено доноров: ${r.deleted}`, "success");
      selected.clear();
      refresh();
    } catch (e) { toast(e.message, "error"); }
  }

  const sb = el("div", { class: "search-bar" });
  sb.appendChild(searchInput({
    placeholder: "Поиск по URL или домену…",
    value: state.q,
    onInput: (v) => { state.q = v; debounced(refresh)(); },
  }));
  const filterBtn = el("button", { class: "ghost", onClick: () => { advanced.style.display = advanced.style.display === "none" ? "" : "none"; } },
    icon("filter", { size: 14 }), el("span", {}, "Фильтры"));
  sb.appendChild(filterBtn);
  host.appendChild(sb);

  const advanced = el("div", { class: "filters", style: { display: "none", marginBottom: "12px" } });
  buildAdvancedFilters(advanced, state, refresh);
  host.appendChild(advanced);

  // Bulk action bar — appears when something is selected
  const bulkBar = el("div", { class: "panel", style: { display: "none", padding: "10px 14px", marginBottom: "12px" } });
  host.appendChild(bulkBar);

  const tableWrap = el("div", { class: "table-wrap" });
  host.appendChild(tableWrap);

  const paginationBar = el("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 4px", color: "var(--text-2)", fontSize: "12.5px" } });
  host.appendChild(paginationBar);

  function refreshBulkBar() {
    if (!selected.size) { bulkBar.style.display = "none"; return; }
    bulkBar.style.display = "";
    bulkBar.innerHTML = "";
    bulkBar.appendChild(el("div", { class: "row", style: { gap: "12px", justifyContent: "space-between" } },
      el("div", { class: "row", style: { gap: "10px" } },
        el("strong", {}, `Выбрано: ${selected.size}`),
        el("button", { class: "subtle small", onClick: () => { selected.clear(); refreshBulkBar(); renderRows(); } }, "Снять"),
      ),
      isAdmin ? el("div", { class: "row", style: { gap: "6px" } },
        el("button", { class: "ghost small", onClick: async () => {
          try { const r = await api.bulkActivateDonors([...selected]); toast(`Активировано: ${r.updated}`, "success"); selected.clear(); refresh(); }
          catch (e) { toast(e.message, "error"); }
        }}, icon("check", { size: 13 }), el("span", {}, "Активировать")),
        el("button", { class: "ghost small", onClick: async () => {
          if (!confirm(`Деактивировать ${selected.size} доноров?`)) return;
          try { const r = await api.bulkDeactivateDonors([...selected]); toast(`Деактивировано: ${r.updated}`, "success"); selected.clear(); refresh(); }
          catch (e) { toast(e.message, "error"); }
        }}, icon("eyeOff", { size: 13 }), el("span", {}, "Деактивировать")),
        el("button", { class: "danger ghost small", onClick: async () => {
          if (!confirm(`Удалить ${selected.size} доноров безвозвратно? Стоп-лист и история размещений сохранятся.`)) return;
          try { const r = await api.bulkDeleteDonors([...selected]); toast(`Удалено: ${r.deleted}`, "success"); selected.clear(); refresh(); }
          catch (e) { toast(e.message, "error"); }
        }}, icon("trash", { size: 13 }), el("span", {}, "Удалить")),
      ) : null,
    ));
  }

  async function refresh() {
    state.offset = 0;
    loadedItems = [];
    selected.clear();
    refreshBulkBar();
    await loadPage(true);
  }

  async function loadMore() {
    state.offset = loadedItems.length;
    await loadPage(false);
  }

  // Bumped on every fresh search/filter so a slow first-page response from an
  // old query can't overwrite the results of a newer one.
  let loadSeq = 0;

  async function loadPage(first) {
    const my = first ? ++loadSeq : loadSeq;
    if (first) {
      tableWrap.innerHTML = "";
      tableWrap.appendChild(tableSkeleton(6, 9));
      paginationBar.innerHTML = "";
    }
    const params = paramsForRequest(state);
    try {
      const data = await api.donors(params);
      if (my !== loadSeq) return;  // superseded by a newer search
      total = data.total;
      loadedItems = loadedItems.concat(data.items);
      renderRows();
      renderPagination();
    } catch (e) {
      if (my !== loadSeq) return;
      tableWrap.innerHTML = "";
      tableWrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function renderRows() {
    tableWrap.innerHTML = "";
    if (!loadedItems.length) {
      tableWrap.appendChild(emptyState({
        iconName: "donors",
        title: "Доноров не найдено",
        desc: state.q || hasFilters(state) ? "Попробуйте изменить фильтры." : "Импортируйте CSV/XLSX или добавьте первого донора.",
        action: isAdmin && !state.q && !hasFilters(state)
          ? el("button", { class: "cta", onClick: () => location.hash = "#/import-export" }, icon("upload", { size: 14 }), el("span", {}, "Импортировать"))
          : null,
      }));
      return;
    }
    const table = el("table");
    const allOnPageSelected = loadedItems.every(d => selected.has(d.id));
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "compact left" }, isAdmin ? el("input", { type: "checkbox", checked: allOnPageSelected ? "" : null, onChange: (e) => {
        if (e.target.checked) loadedItems.forEach(d => selected.add(d.id));
        else loadedItems.forEach(d => selected.delete(d.id));
        refreshBulkBar();
        renderRows();
      }}) : ""),
      sortHeader("Domain", "domain", state, refresh, "left"),
      sortHeader("DR", "tr", state, refresh, "right"),
      sortHeader("Organic Traffic", "organic_traffic", state, refresh, "right"),
      sortHeader("Referring Domains", "ref_domains", state, refresh, "right"),
      sortHeader("Backlinks", "backlinks", state, refresh, "right"),
      sortHeader("GEO", "geo", state, refresh),
      sortHeader("Language", "language", state, refresh),
      sortHeader("link_type", "link_type", state, refresh),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    loadedItems.forEach(d => tbody.appendChild(donorRow(d, refresh, selected, refreshBulkBar)));
    table.appendChild(tbody);
    tableWrap.appendChild(table);
  }

  function renderPagination() {
    paginationBar.innerHTML = "";
    paginationBar.appendChild(el("div", {}, `Загружено ${loadedItems.length} из ${total}`));
    if (loadedItems.length < total) {
      paginationBar.appendChild(el("button", { class: "ghost small", onClick: loadMore }, "Загрузить ещё"));
    } else {
      paginationBar.appendChild(el("span", { class: "dimmed" }, "Это все доноры"));
    }
  }

  await refresh();
}

function paramsForRequest(state) {
  const params = { sort: state.sort, order: state.order, limit: PAGE_SIZE, offset: state.offset };
  ["q", "geo", "language", "link_type", "min_tr", "min_traffic", "min_ref_domains", "min_backlinks"].forEach(k => {
    if (state[k] !== "") params[k] = state[k];
  });
  if (state.is_active === "true") params.is_active = true;
  if (state.is_active === "false") params.is_active = false;
  if (state.used === "true") params.used = true;
  if (state.used === "false") params.used = false;
  return params;
}

function hasFilters(state) {
  return ["geo","language","link_type","min_tr","min_traffic","min_ref_domains","min_backlinks","is_active","used"].some(k => state[k] !== "");
}

function sortHeader(label, key, state, reload, align = "") {
  const isActive = state.sort === key;
  const arrow = isActive ? (state.order === "desc" ? icon("arrowDown", { size: 11 }) : icon("arrowUp", { size: 11 })) : null;
  return el("th", { class: `${align}`, style: { cursor: "pointer", userSelect: "none" }, onClick: () => {
    if (state.sort === key) state.order = state.order === "desc" ? "asc" : "desc";
    else { state.sort = key; state.order = "desc"; }
    reload();
  }},
    el("span", { style: { display: "inline-flex", alignItems: "center", gap: "4px", color: isActive ? "var(--text-1)" : "inherit" } },
      label, arrow,
    ),
  );
}

function buildAdvancedFilters(advanced, state, reload) {
  const make = (label, input) => el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, label), input);
  advanced.appendChild(make("Гео", el("input", { type: "text", value: state.geo, onInput: (e) => state.geo = e.target.value })));
  advanced.appendChild(make("Язык", el("input", { type: "text", value: state.language, onInput: (e) => state.language = e.target.value })));
  advanced.appendChild(make("link_type", selectInput(state.link_type, ["", ...LINK_TYPES], v => state.link_type = v, null, null, "(любой)")));
  advanced.appendChild(make("Мин. DR", el("input", { type: "number", value: state.min_tr, onInput: (e) => state.min_tr = e.target.value })));
  advanced.appendChild(make("Мин. Organic Traffic", el("input", { type: "number", value: state.min_traffic, onInput: (e) => state.min_traffic = e.target.value })));
  advanced.appendChild(make("Мин. Ref Domains", el("input", { type: "number", value: state.min_ref_domains, onInput: (e) => state.min_ref_domains = e.target.value })));
  advanced.appendChild(make("Мин. Backlinks", el("input", { type: "number", value: state.min_backlinks, onInput: (e) => state.min_backlinks = e.target.value })));
  advanced.appendChild(make("Активность", selectInput(state.is_active, ["", "true", "false"], v => state.is_active = v, null, { true: "только активные", false: "только неактивные" }, "все")));
  advanced.appendChild(make("Использовался", selectInput(state.used, ["", "true", "false"], v => state.used = v, null, { true: "да", false: "нет" }, "не важно")));
  advanced.appendChild(el("button", { onClick: reload }, "Применить"));
  advanced.appendChild(el("button", { class: "ghost", onClick: () => {
    ["geo","language","link_type","min_tr","min_traffic","min_ref_domains","min_backlinks","is_active","used"].forEach(k => state[k] = "");
    advanced.querySelectorAll("input,select").forEach(i => i.value = "");
    reload();
  }}, "Сбросить"));
}

function donorRow(d, reload, selected, refreshBulkBar) {
  const isAdmin = auth.isAdmin();
  const menuItems = [
    { label: "Аккаунты донора", icon: "user", onClick: () => openAccounts(d) },
    { label: "История использования", icon: "clock", onClick: () => showUsage(d.id) },
    { label: "Открыть сайт", icon: "external", onClick: () => window.open(ensureUrl(d.donor_url), "_blank") },
  ];
  if (isAdmin) {
    menuItems.push({ separator: true });
    menuItems.push({ label: "Редактировать", icon: "pencil", onClick: () => openDonorForm(d, reload) });
    menuItems.push({ label: d.is_active ? "Деактивировать" : "Уже неактивен", icon: "trash", danger: true, onClick: async () => {
      if (!d.is_active) return;
      if (!confirm("Деактивировать донора?")) return;
      try { await api.deactivateDonor(d.id); toast("Деактивирован", "success"); reload(); }
      catch (e) { toast(e.message, "error"); }
    }});
  }
  const domainText = d.domain || d.donor_url;
  const linkVariant = LINK_TYPE_VARIANT[d.link_type] ?? "";
  const isSelected = selected.has(d.id);

  return el("tr", { style: d.is_active ? null : { opacity: 0.55 } },
    el("td", { class: "compact left" }, isAdmin ? el("input", { type: "checkbox", checked: isSelected ? "" : null, onChange: (e) => {
      if (e.target.checked) selected.add(d.id); else selected.delete(d.id);
      refreshBulkBar();
    }}) : ""),
    el("td", { class: "left truncate", title: d.donor_url },
      el("a", { href: ensureUrl(d.donor_url), target: "_blank", class: "mono", style: { fontWeight: 500 } }, domainText),
      (d.category || !d.is_active) && el("div", { class: "row", style: { gap: "6px", marginTop: "2px" } },
        !d.is_active && el("span", { class: "pill error", style: { fontSize: "10.5px" } }, "неактивен"),
        d.category && el("span", { class: "muted", style: { fontSize: "11.5px" } }, d.category),
      ),
    ),
    el("td", { class: "right tabular mono" }, String(d.tr || 0)),
    el("td", { class: "right tabular mono" }, fmtNumber(d.organic_traffic)),
    el("td", { class: "right tabular mono" }, fmtNumber(d.ref_domains)),
    el("td", { class: "right tabular mono" }, fmtNumber(d.backlinks)),
    el("td", {}, d.geo || el("span", { class: "dimmed" }, "—")),
    el("td", {}, d.language || el("span", { class: "dimmed" }, "—")),
    el("td", {}, el("span", { class: `pill ${linkVariant}` }, d.link_type || "unknown")),
    el("td", { class: "right actions" }, menuButton(menuItems)),
  );
}

function ensureUrl(raw) {
  if (!raw) return "#";
  if (/^https?:\/\//i.test(raw)) return raw;
  return "https://" + raw;
}

function fmtNumber(n) {
  if (!n) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k";
  return String(n);
}

// ---- usage modal ----

async function showUsage(id) {
  try {
    const data = await api.donorUsage(id);
    const body = el("div", {});
    body.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "10px" } },
      el("span", { class: "mono" }, data.donor.donor_url),
    ));
    if (!data.placements.length) {
      body.appendChild(emptyState({ iconName: "info", title: "Пока не использовался" }));
    } else {
      const list = el("div", { class: "feed" });
      data.placements.forEach(p => list.appendChild(el("div", { class: `feed-item ${p.status === "placed" ? "success" : ""}` },
        el("div", { class: "feed-icon" }, icon(p.status === "placed" ? "check" : "clock", { size: 13 })),
        el("div", { class: "feed-body" },
          el("div", { class: "feed-title mono" }, p.target_url),
          el("div", { class: "feed-meta" }, `${p.status} • ${p.result_url || "—"} • ${fmtDate(p.placed_at)}`),
        ),
      )));
      body.appendChild(list);
    }
    openModal({ title: "История использования донора", content: body, size: "lg" });
  } catch (e) { toast(e.message, "error"); }
}

// ---- accounts modal ----

async function openAccounts(donor) {
  const body = el("div", {});
  body.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "12px" } },
    el("span", { class: "mono" }, donor.domain || donor.donor_url),
  ));
  const listWrap = el("div", {});
  body.appendChild(listWrap);
  body.appendChild(el("button", { onClick: () => openAccountForm(donor, null, refresh), style: { marginTop: "12px" } },
    icon("plus", { size: 13 }), el("span", {}, "Новый аккаунт")));

  async function refresh() {
    listWrap.innerHTML = `<div class="loading"><span class="spinner"></span></div>`;
    try {
      const accounts = await api.donorAccounts(donor.id);
      listWrap.innerHTML = "";
      if (!accounts.length) {
        listWrap.appendChild(emptyState({ iconName: "user", title: "Аккаунтов нет", desc: "Аккаунт нужен, чтобы оставить ссылку на доноре. Их можно добавить заранее или сотрудник создаст при отметке размещения." }));
        return;
      }
      const table = el("table", { style: { minWidth: "auto" } });
      table.appendChild(el("thead", {}, el("tr", {},
        el("th", { class: "left" }, "Username"),
        el("th", { class: "left" }, "Email"),
        el("th", { class: "left" }, "Пароль"),
        el("th", { class: "right" }, "Размещений"),
        el("th", { class: "right" }, "Лимит"),
        el("th", { class: "right" }, ""),
      )));
      const tbody = el("tbody");
      accounts.forEach(a => {
        const overLimit = a.max_placements && a.usage_count >= a.max_placements;
        tbody.appendChild(el("tr", { style: a.is_active && !overLimit ? null : { opacity: 0.55 } },
          el("td", { class: "left mono" }, a.account_username || el("span", { class: "dimmed" }, "—")),
          el("td", { class: "left mono", style: { fontSize: "12.5px" } }, a.login_email || el("span", { class: "dimmed" }, "—")),
          el("td", { class: "left" }, passwordCell(a.login_password)),
          el("td", { class: "right tabular mono" }, String(a.usage_count)),
          el("td", { class: "right tabular mono" }, a.max_placements ? String(a.max_placements) : el("span", { class: "dimmed" }, "∞")),
          el("td", { class: "right actions" }, menuButton([
            { label: "Редактировать", icon: "pencil", onClick: () => openAccountForm(donor, a, refresh) },
            a.is_active ? { label: "Деактивировать", icon: "trash", onClick: async () => {
              try { await api.updateDonorAccount(donor.id, a.id, { is_active: false }); toast("Деактивирован", "success"); refresh(); }
              catch (e) { toast(e.message, "error"); }
            }} : { label: "Активировать", icon: "check", onClick: async () => {
              try { await api.updateDonorAccount(donor.id, a.id, { is_active: true }); toast("Активирован", "success"); refresh(); }
              catch (e) { toast(e.message, "error"); }
            }},
            auth.isAdmin() && { separator: true },
            auth.isAdmin() && { label: "Удалить", icon: "trash", danger: true, onClick: async () => {
              if (!confirm("Удалить аккаунт?")) return;
              try { await api.deleteDonorAccount(donor.id, a.id); toast("Удалено", "success"); refresh(); }
              catch (e) { toast(e.message, "error"); }
            }},
          ])),
        ));
      });
      table.appendChild(tbody);
      const tw = el("div", { class: "table-wrap" }, table);
      listWrap.appendChild(tw);
    } catch (e) {
      listWrap.innerHTML = "";
      listWrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  openModal({ title: `Аккаунты на доноре`, content: body, size: "lg" });
  await refresh();
}

function passwordCell(pw) {
  if (!pw) return el("span", { class: "dimmed" }, "—");
  let shown = false;
  const valEl = el("span", { class: "mono", style: { fontSize: "12.5px" } }, "••••••••");
  const eyeBtn = el("button", { class: "copy-btn", type: "button", onClick: () => {
    shown = !shown;
    valEl.textContent = shown ? pw : "••••••••";
  }}, icon(shown ? "eyeOff" : "eye", { size: 13 }));
  const copyBtn = el("button", { class: "copy-btn", type: "button", onClick: async () => {
    const ok = await copy(pw); if (ok) toast("Скопировано", "success");
  }}, icon("copy", { size: 13 }));
  return el("span", { class: "row", style: { gap: "6px", justifyContent: "flex-start" } }, valEl, eyeBtn, copyBtn);
}

function openAccountForm(donor, account, reload) {
  const isEdit = !!account;
  const form = el("form", {});
  const fields = [
    ["account_username", "Имя аккаунта (username)", "text", account?.account_username || ""],
    ["login_email", "Email для входа", "text", account?.login_email || ""],
    ["login_password", "Пароль", "text", account?.login_password || ""],
    ["max_placements", "Лимит размещений (0 = без лимита)", "number", account?.max_placements || 0],
    ["comment", "Комментарий", "text", account?.comment || ""],
  ];
  for (const [name, label, type, value] of fields) {
    form.appendChild(el("div", { class: "field" },
      el("label", {}, label),
      el("input", { name, type, value }),
    ));
  }
  openModal({
    title: isEdit ? "Редактирование аккаунта" : "Новый аккаунт",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
        data.max_placements = parseInt(data.max_placements || 0) || 0;
        try {
          if (isEdit) await api.updateDonorAccount(donor.id, account.id, data);
          else await api.createDonorAccount(donor.id, data);
          toast("Сохранено", "success"); closeModal(); reload();
          // Re-open the accounts modal after creation
          openAccounts(donor);
        } catch (e) { toast(e.message, "error"); }
      }}, "Сохранить"));
      return f;
    })(),
  });
}

// ---- donor form ----

function openDonorForm(donor = null, reload = () => {}) {
  const isEdit = !!donor;
  const form = el("form", {});
  const fields = [
    ["donor_url", "URL или домен", "text", true],
    ["tr", "DR", "number", false],
    ["organic_traffic", "Organic Traffic", "number", false],
    ["ref_domains", "Referring Domains", "number", false],
    ["backlinks", "Backlinks", "number", false],
    ["geo", "GEO", "text", false],
    ["language", "Language", "text", false],
    ["category", "Тематика", "text", false],
    ["comment", "Комментарий", "text", false],
  ];
  const grid = el("div", { class: "row", style: { gap: "10px" } });
  for (const [name, label, type, required] of fields) {
    grid.appendChild(el("div", { class: "field", style: { flex: "1 1 45%", minWidth: "180px", marginBottom: 0 } },
      el("label", {}, label + (required ? " *" : "")),
      el("input", { name, type, value: donor ? donor[name] ?? "" : "", required })
    ));
  }
  form.appendChild(grid);
  form.appendChild(el("div", { class: "field", style: { marginTop: "12px" } },
    el("label", {}, "link_type"),
    selectInput(donor?.link_type || "unknown", LINK_TYPES, null, "link_type"),
  ));

  openModal({
    title: isEdit ? "Редактирование донора" : "Новый донор",
    content: form,
    size: "lg",
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
        ["tr", "organic_traffic", "ref_domains", "backlinks"].forEach(k => data[k] = parseFloat(data[k] || 0));
        try {
          if (isEdit) await api.updateDonor(donor.id, data);
          else await api.createDonor(data);
          toast("Сохранено", "success"); closeModal(); reload();
        } catch (e) { toast(e.message, "error"); }
      }}, isEdit ? "Сохранить" : "Создать"));
      return f;
    })(),
  });
}

// ---- helpers ----

function selectInput(value, options, onChange, name, labels, emptyLabel) {
  // Args: (value, options, onChange?, name?, labels?, emptyLabel?)
  // labels can be either:
  //   - a function (deprecated) — ignored
  //   - object { value: label }
  const sel = document.createElement("select");
  if (name) sel.name = name;
  if (typeof onChange === "function") sel.addEventListener("change", e => onChange(e.target.value));
  options.forEach(o => {
    const opt = document.createElement("option");
    opt.value = o;
    if (o === value) opt.selected = true;
    if (!o) opt.textContent = emptyLabel || "(любой)";
    else if (labels && typeof labels === "object" && labels[o]) opt.textContent = labels[o];
    else opt.textContent = o;
    sel.appendChild(opt);
  });
  return sel;
}

const _timers = new WeakMap();
function debounced(fn, ms = 250) {
  return (...args) => {
    clearTimeout(_timers.get(fn));
    _timers.set(fn, setTimeout(() => fn(...args), ms));
  };
}
