import { api } from "../api.js";
import { el, statusPill, STATUS_LABELS, emptyState, tableSkeleton, copy, sortHeader, submitButton } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

// Table view tuned for high-throughput work (200+ placements/day).
// Workflow per row:
//   1. Click "Взять" (or skip — happens automatically when result is entered)
//   2. Open donor URL in new tab (one click on the donor cell)
//   3. Post the link there, copy resulting URL
//   4. Paste into "Результат" input → Enter → row is marked placed
//   5. Move to next row

const VISIBLE_STATUSES = ["", "assigned", "donor_selected", "in_progress", "placed", "problem"];

export async function renderMyTasks(host) {
  const state = { status: "", sort: "id", order: "asc" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Мои задачи"),
      el("div", { class: "page-subtitle" }, "Вставь ссылку на результат и нажми Enter — задача автоматически закроется"),
    ),
  ));

  // Status filter pills
  const filterBar = el("div", { class: "row", style: { marginBottom: "12px", gap: "6px" } });
  function rebuildFilters() {
    filterBar.innerHTML = "";
    VISIBLE_STATUSES.forEach(s => {
      const active = state.status === s;
      filterBar.appendChild(el("button", {
        class: active ? "" : "ghost small",
        onClick: () => { state.status = s; rebuildFilters(); load(); },
      }, s ? (STATUS_LABELS[s] || s) : "Все"));
    });
  }
  rebuildFilters();
  host.appendChild(filterBar);

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  // Email accounts available to this user (issued to them + shared pool).
  // Loaded once and reused for every row's account picker.
  let myAccounts = [];

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(8, 9));
    try {
      const params = { sort: state.sort, order: state.order };
      if (state.status) params.status = state.status;
      const [data, accounts] = await Promise.all([
        api.myTasks(params),
        api.emailAccounts({ is_active: true, sort: "email", order: "asc" }).catch(() => []),
      ]);
      myAccounts = accounts || [];
      render(data);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  function render(items) {
    wrap.innerHTML = "";
    if (!items.length) {
      wrap.appendChild(emptyState({
        iconName: "tasks",
        title: state.status ? "По выбранному фильтру задач нет" : "Назначенных задач пока нет",
        desc: state.status ? "Попробуйте другой фильтр." : "Когда менеджер назначит задачи, они появятся здесь.",
      }));
      return;
    }

    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "compact left" }, "#"),
      sortHeader("Целевая ссылка", "target_url", state, load, "left"),
      sortHeader("Анкор", "anchor_text", state, load, "left"),
      sortHeader("Гео", "geo", state, load),
      sortHeader("Язык", "language", state, load),
      el("th", { class: "left" }, "Донор"),
      el("th", { class: "left" }, "Аккаунт для входа"),
      sortHeader("Статус", "status", state, load),
      el("th", { class: "left" }, "Результат"),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    items.forEach((t, idx) => tbody.appendChild(taskRow(t, idx + 1, load, myAccounts)));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  await load();
}

function taskRow(t, num, reload, accounts) {
  const donor = t.donor;
  let placement = t.placement;
  const isPlaced = placement?.status === "placed";

  // The account the employee will use to log into the donor and place the
  // link. Pre-selected: whatever's already saved on the placement, else the
  // first available account. Lives in the row closure so submitResult sees it.
  let selectedAccount = null;
  if (placement?.login_email) {
    selectedAccount = (accounts || []).find(a => a.email === placement.login_email)
      || { email: placement.login_email, password: placement.login_password || "" };
  } else if (accounts && accounts.length) {
    selectedAccount = accounts[0];
  }

  // ----- Result URL input (autosave on Enter / blur) -----
  const resultInput = el("input", {
    type: "url",
    placeholder: placement ? "URL и Enter" : "—",
    value: placement?.result_url || "",
    disabled: !placement || isPlaced ? "" : null,
    style: {
      fontSize: "12.5px",
      fontFamily: "var(--mono)",
      minWidth: "200px",
      maxWidth: "320px",
    },
    onKeydown: (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitResult(e.target.value);
      }
    },
    onBlur: (e) => {
      // Only save (without finishing) if there is text and status not yet placed.
      const v = e.target.value.trim();
      if (!placement || isPlaced || !v || v === (placement.result_url || "")) return;
      // Just save the URL without changing status (separate API call would be nice; for now we no-op
      // and require Enter to confirm placement).
    },
  });

  async function submitResult(v) {
    const url = (v || "").trim();
    if (!url) { toast("Введите ссылку на результат", "error"); return; }
    try {
      // Auto-take if not already in progress
      if (!placement) {
        const p = await api.takeTask(t.item_id);
        placement = p;
      }
      await api.markPlaced(placement.id, {
        result_url: url,
        login_email: selectedAccount?.email || placement.login_email || "",
        login_password: selectedAccount?.password || placement.login_password || "",
        account_username: selectedAccount?.label || placement.account_username || "",
        comment: placement.comment || "",
      });
      toast("Размещение зафиксировано", "success");
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  // ----- Account cell: pick a login, see its email + password right here ---
  const accountCell = el("div", { style: { fontSize: "12px", textAlign: "left", minWidth: "200px" } });

  const credsBox = el("div", { style: { marginTop: "4px" } });
  function renderCreds() {
    credsBox.innerHTML = "";
    if (!selectedAccount || !selectedAccount.email) return;
    credsBox.appendChild(el("div", { class: "mono", style: { display: "flex", alignItems: "center", gap: "4px", fontSize: "11.5px" } },
      el("span", {}, selectedAccount.email),
      copyMicroBtn(selectedAccount.email),
    ));
    if (selectedAccount.password) credsBox.appendChild(passwordRow(selectedAccount.password));
  }

  if (isPlaced) {
    // Done — just show what was used, read-only.
    if (selectedAccount?.email) { renderCreds(); accountCell.appendChild(credsBox); }
    else accountCell.appendChild(el("span", { class: "dimmed" }, "—"));
  } else if (accounts && accounts.length) {
    const sel = document.createElement("select");
    sel.style.fontSize = "12px";
    accounts.forEach((a, i) => {
      const o = document.createElement("option");
      o.value = String(a.id);
      o.textContent = a.label ? `${a.email} · ${a.label}` : a.email;
      if (selectedAccount && a.id === selectedAccount.id) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener("change", (e) => {
      selectedAccount = accounts.find(a => String(a.id) === e.target.value) || null;
      renderCreds();
    });
    accountCell.appendChild(sel);
    accountCell.appendChild(credsBox);
    renderCreds();
  } else {
    accountCell.appendChild(el("span", { class: "dimmed", style: { fontSize: "11.5px" } },
      "нет выданных аккаунтов"));
  }

  // ----- Actions cell -----
  const actions = el("div", { class: "row", style: { gap: "4px", justifyContent: "flex-end", flexWrap: "nowrap" } });
  if (!placement) {
    actions.appendChild(el("button", { class: "ghost small", title: "Взять в работу",
      onClick: async () => {
        try { await api.takeTask(t.item_id); toast("Взято", "success"); reload(); }
        catch (e) { toast(e.message, "error"); }
      }
    }, icon("zap", { size: 12 }), el("span", {}, "Взять")));
  } else if (!isPlaced) {
    actions.appendChild(el("button", { class: "ghost small", title: "Отметить размещение (открыть форму с кредами)",
      onClick: () => openPlacedForm(placement, t, reload),
    }, icon("check", { size: 12 })));
    actions.appendChild(el("button", { class: "ghost small", title: "Проблема",
      onClick: () => openProblemForm(placement, reload),
    }, icon("alert", { size: 12 })));
  } else {
    actions.appendChild(el("button", { class: "subtle small", title: "Изменить",
      onClick: () => openPlacedForm(placement, t, reload),
    }, icon("pencil", { size: 12 })));
  }

  // ----- Donor cell -----
  const donorCell = donor ? donorCellBlock(donor) : el("span", { class: "dimmed" }, "не подобран");

  const displayTarget = t.target_url || t.target_domain || "";
  return el("tr", {},
    el("td", { class: "left compact muted tabular mono", style: { fontSize: "11.5px" } }, String(num)),
    el("td", { class: "left truncate", title: displayTarget || "" },
      displayTarget
        ? el("div", { style: { display: "flex", alignItems: "center", gap: "4px" } },
            el("a", {
              href: displayTarget.startsWith("http") ? displayTarget : "https://" + displayTarget,
              target: "_blank",
              class: "mono",
              style: { fontSize: "12.5px" },
            }, shortenUrl(displayTarget)),
            copyMicroBtn(displayTarget),
          )
        : el("span", { class: "dimmed" }, "—"),
    ),
    el("td", { class: "left", style: { maxWidth: "200px" } },
      t.anchor_text ? el("span", { style: { fontSize: "13px" } }, t.anchor_text) : el("span", { class: "dimmed" }, "—"),
    ),
    el("td", { class: "muted", style: { fontSize: "12px" } }, t.geo || el("span", { class: "dimmed" }, "—")),
    el("td", { class: "muted", style: { fontSize: "12px" } }, t.language || el("span", { class: "dimmed" }, "—")),
    el("td", {}, t.required_link_type ? el("span", { class: "pill" }, t.required_link_type) : el("span", { class: "dimmed" }, "—")),
    el("td", { class: "left" }, donorCell),
    el("td", { class: "left" }, accountCell),
    el("td", {}, statusPill(t.status)),
    el("td", { class: "left" }, resultInput),
    el("td", { class: "right actions" }, actions),
  );
}

function donorCellBlock(donor) {
  const url = donor.donor_url || donor.domain || "";
  const href = url.startsWith("http") ? url : "https://" + url;
  const linkClass = donor.link_type === "dofollow" ? "success"
    : donor.link_type === "nofollow" ? "muted"
    : donor.link_type === "mixed" ? "info"
    : donor.link_type === "error" ? "error"
    : "";
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", gap: "2px", alignItems: "flex-start" } });
  wrap.appendChild(el("div", { style: { display: "flex", alignItems: "center", gap: "4px" } },
    el("a", { href, target: "_blank", class: "mono", style: { fontSize: "12.5px", fontWeight: 500 } }, donor.domain || donor.donor_url),
    copyMicroBtn(url),
  ));
  const meta = [];
  if (donor.geo) meta.push(donor.geo);
  if (donor.language) meta.push(donor.language);
  if (donor.tr) meta.push("DR " + donor.tr);
  const metaRow = el("div", { class: "row", style: { gap: "4px", flexWrap: "wrap", justifyContent: "flex-start", fontSize: "11px" } });
  if (meta.length) metaRow.appendChild(el("span", { class: "muted" }, meta.join(" · ")));
  if (donor.link_type) metaRow.appendChild(el("span", { class: `pill ${linkClass}`, style: { fontSize: "10px" } }, donor.link_type));
  if (metaRow.children.length) wrap.appendChild(metaRow);
  return wrap;
}

function shortenUrl(url) {
  if (!url) return "—";
  try {
    const u = new URL(url);
    const path = u.pathname.length > 32 ? u.pathname.slice(0, 30) + "…" : u.pathname;
    return u.host + path;
  } catch {
    return url.length > 48 ? url.slice(0, 46) + "…" : url;
  }
}

function copyMicroBtn(text) {
  return el("button", {
    class: "subtle icon small",
    style: { width: "20px", height: "20px", padding: 0, opacity: 0.7 },
    title: "Скопировать",
    onClick: async (e) => {
      e.preventDefault(); e.stopPropagation();
      const ok = await copy(text);
      if (ok) toast("Скопировано", "success");
    },
  }, icon("copy", { size: 11 }));
}

function passwordRow(pw) {
  let shown = false;
  const span = el("span", { class: "mono", style: { fontSize: "11px" } }, "••••••••");
  const eye = el("button", {
    class: "subtle icon small",
    style: { width: "18px", height: "18px", padding: 0, opacity: 0.7 },
    title: "Показать пароль",
    onClick: () => {
      shown = !shown;
      span.textContent = shown ? pw : "••••••••";
    },
  }, icon(shown ? "eyeOff" : "eye", { size: 10 }));
  const cp = el("button", {
    class: "subtle icon small",
    style: { width: "18px", height: "18px", padding: 0, opacity: 0.7 },
    title: "Скопировать пароль",
    onClick: async () => {
      const ok = await copy(pw);
      if (ok) toast("Пароль скопирован", "success");
    },
  }, icon("copy", { size: 10 }));
  return el("div", { class: "muted", style: { display: "flex", alignItems: "center", gap: "4px", fontSize: "11px" } },
    span, eye, cp,
  );
}

// ----- Detailed forms (kept for credential edits) -----

async function openPlacedForm(placement, task, reload) {
  const form = el("form", {});
  // --- Picker for the shared email-account pool --------------------------
  const pickerSelect = document.createElement("select");
  pickerSelect.style.flex = "1";
  const ph = document.createElement("option");
  ph.value = ""; ph.textContent = "— выбрать из моих аккаунтов —";
  pickerSelect.appendChild(ph);
  pickerSelect.disabled = true;  // enabled when accounts load

  const pickerWrap = el("div", { class: "field" },
    el("label", {}, "Аккаунт из пула"),
    el("div", { class: "row", style: { gap: "8px" } },
      pickerSelect,
      el("a", { href: "#/email-accounts", target: "_blank", class: "ghost", style: { padding: "0 10px", height: "34px", display: "inline-flex", alignItems: "center", border: "1px solid var(--border)", borderRadius: "var(--r-md)", fontSize: "12.5px" } }, "Управление"),
    ),
  );
  form.appendChild(pickerWrap);

  // --- Editable credentials ---------------------------------------------
  const emailInput = el("input", { name: "login_email", type: "email", value: placement.login_email || "" });
  const pwInput = el("input", { name: "login_password", type: "text", value: placement.login_password || "" });
  const userInput = el("input", { name: "account_username", type: "text", value: placement.account_username || task?.suggested_account?.account_username || "" });
  const resultInput = el("input", { name: "result_url", type: "url", value: placement.result_url || "", required: "" });

  form.appendChild(el("div", { class: "field" }, el("label", {}, "Ссылка на результат *"), resultInput));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Email для входа"), emailInput));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Пароль"), pwInput));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Имя аккаунта (username)"), userInput));
  form.appendChild(el("div", { class: "field" }, el("label", {}, "Комментарий"),
    el("textarea", { name: "comment", rows: 2 }, placement.comment || "")));

  // Wire up the picker to autofill email/password when chosen.
  pickerSelect.addEventListener("change", (e) => {
    const picked = accountById[e.target.value];
    if (picked) {
      emailInput.value = picked.email;
      pwInput.value = picked.password || "";
    }
  });

  // Load accounts in background; once arrived, populate the dropdown.
  const accountById = {};
  api.emailAccounts({ is_active: true, sort: "email", order: "asc" }).then(accounts => {
    accounts.forEach(a => {
      accountById[String(a.id)] = a;
      const opt = document.createElement("option");
      opt.value = String(a.id);
      opt.textContent = a.label ? `${a.email}  ·  ${a.label}` : a.email;
      pickerSelect.appendChild(opt);
    });
    pickerSelect.disabled = false;
    if (!accounts.length) {
      ph.textContent = "— нет сохранённых аккаунтов —";
    }
  }).catch(() => {});

  openModal({
    title: "Отметить размещение",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(submitButton("Сохранить", async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
        try { await api.markPlaced(placement.id, data); toast("Сохранено", "success"); closeModal(); reload(); }
        catch (e) { toast(e.message, "error"); }
      }));
      return f;
    })(),
  });
}

function openProblemForm(placement, reload) {
  const form = el("form", {});
  form.appendChild(el("div", { class: "field" },
    el("label", {}, "Что пошло не так?"),
    el("textarea", { name: "comment", rows: 4, placeholder: "Опишите проблему — она появится у менеджера" }, placement.comment || ""),
  ));
  openModal({
    title: "Отметить как проблему",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(submitButton("Отправить", async () => {
        const comment = form.querySelector("[name=comment]").value;
        try { await api.markProblem(placement.id, { comment }); toast("Отмечено", "success"); closeModal(); reload(); }
        catch (e) { toast(e.message, "error"); }
      }, { className: "danger" }));
      return f;
    })(),
  });
}
