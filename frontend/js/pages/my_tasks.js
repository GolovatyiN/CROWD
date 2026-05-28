import { api } from "../api.js";
import { el, statusPill, STATUS_LABELS, emptyState, copyButton, copy } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

const VISIBLE_STATUSES = ["", "assigned", "donor_selected", "in_progress", "placed", "problem"];

const SORT_OPTIONS = [
  { key: "updated_at", label: "По дате обновления" },
  { key: "id", label: "По порядку загрузки" },
  { key: "target_domain", label: "По домену" },
  { key: "status", label: "По статусу" },
  { key: "geo", label: "По гео" },
];

export async function renderMyTasks(host) {
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Мои задачи"),
      el("div", { class: "page-subtitle" }, "Берите задачи в работу и отмечайте размещения"),
    ),
    el("div", { class: "page-actions" },
      sortDropdown(),
    ),
  ));

  const state = { status: "", sort: "updated_at", order: "desc" };

  function sortDropdown() {
    const sel = el("select", { style: { width: "auto", minWidth: "200px" }, onChange: (e) => {
      state.sort = e.target.value;
      renderMyTasks2();
    }});
    SORT_OPTIONS.forEach(o => {
      const opt = el("option", { value: o.key }, o.label);
      if (o.key === "updated_at") opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }
  const filterBar = el("div", { class: "row", style: { marginBottom: "12px", gap: "6px" } });
  VISIBLE_STATUSES.forEach(s => {
    const isActive = state.status === s;
    const btn = el("button", { class: isActive ? "" : "ghost small", style: !isActive ? null : { height: "32px" },
      onClick: () => { state.status = s; renderMyTasks2(); }
    }, s ? (STATUS_LABELS[s] || s) : "Все");
    filterBar.appendChild(btn);
  });
  host.appendChild(filterBar);

  const wrap = el("div", {});
  host.appendChild(wrap);

  async function renderMyTasks2() {
    // refresh filter bar
    filterBar.innerHTML = "";
    VISIBLE_STATUSES.forEach(s => {
      const isActive = state.status === s;
      const btn = el("button", { class: isActive ? "" : "ghost small",
        onClick: () => { state.status = s; renderMyTasks2(); }
      }, s ? (STATUS_LABELS[s] || s) : "Все");
      filterBar.appendChild(btn);
    });

    wrap.innerHTML = "";
    wrap.appendChild(el("div", { class: "task-grid" },
      ...Array(3).fill(0).map(() => skeletonCard())
    ));
    try {
      const params = { sort: state.sort, order: state.order };
      if (state.status) params.status = state.status;
      const data = await api.myTasks(params);
      wrap.innerHTML = "";
      if (!data.length) {
        wrap.appendChild(emptyState({
          iconName: "tasks",
          title: state.status ? "По выбранному фильтру задач нет" : "Назначенных задач пока нет",
          desc: state.status ? "Попробуйте другой фильтр." : "Когда менеджер назначит на вас задачи, они появятся здесь.",
        }));
        return;
      }
      const grid = el("div", { class: "task-grid" });
      data.forEach(t => grid.appendChild(taskCard(t, renderMyTasks2)));
      wrap.appendChild(grid);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    }
  }

  await renderMyTasks2();
}

function skeletonCard() {
  return el("div", { class: "task-card" },
    el("div", { class: "skeleton skeleton-row", style: { width: "75%", height: "14px" } }),
    el("div", { class: "skeleton skeleton-row", style: { width: "45%", height: "12px" } }),
    el("div", { class: "skeleton skeleton-row", style: { width: "100%", height: "60px", borderRadius: "8px", marginTop: "6px" } }),
  );
}

function taskCard(t, reload) {
  const donor = t.donor;
  const placement = t.placement;
  const isPlaced = placement?.status === "placed";

  const card = el("div", { class: "task-card" });

  // Header: target + status
  card.appendChild(el("div", { class: "target-row" },
    el("div", { class: "target" },
      el("div", { class: "anchor-label" }, "Целевая ссылка"),
      el("a", { href: t.target_url, target: "_blank" }, t.target_url),
    ),
    statusPill(t.status),
  ));

  // Anchor + meta
  card.appendChild(el("div", {},
    el("div", { class: "anchor-label" }, "Анкор"),
    el("div", { class: "anchor" }, t.anchor_text || el("span", { class: "dimmed" }, "(без анкора)")),
  ));
  card.appendChild(el("div", { class: "meta" },
    t.geo && el("span", {}, icon("target", { size: 12 }), " ", t.geo),
    t.language && el("span", {}, "🌐 " + t.language),
    t.required_link_type && el("span", {}, el("span", { class: "pill" }, t.required_link_type)),
  ));

  // Donor block
  if (donor) {
    card.appendChild(el("div", { class: "donor-row" },
      el("div", { class: "anchor-label" }, "Донор"),
      el("a", { href: donor.donor_url, target: "_blank" }, donor.donor_url),
      el("div", { class: "muted", style: { fontSize: "11.5px" } }, `${donor.geo || "—"} · ${donor.language || "—"} · ${donor.link_type}`),
    ));
  } else {
    card.appendChild(el("div", { class: "donor-row" },
      el("div", { class: "anchor-label" }, "Донор"),
      el("div", { class: "dimmed", style: { fontSize: "13px" } }, "Ещё не подобран"),
    ));
  }

  // Suggested account
  if (t.suggested_account && !placement) {
    card.appendChild(el("div", { class: "muted", style: { fontSize: "12px" } },
      icon("info", { size: 12 }), " Рекомендуем аккаунт: ",
      el("span", { class: "mono" }, t.suggested_account.account_username || t.suggested_account.login_email),
    ));
  }

  // Credentials (if placement exists and has credentials)
  if (placement && (placement.login_email || placement.account_username)) {
    const creds = el("div", { class: "credentials" });
    if (placement.account_username) creds.appendChild(credRow("Логин", placement.account_username));
    if (placement.login_email) creds.appendChild(credRow("Email", placement.login_email));
    if (placement.login_password) creds.appendChild(credRow("Пароль", placement.login_password, true));
    card.appendChild(creds);
  }

  // Result url
  if (placement?.result_url) {
    card.appendChild(el("div", { class: "donor-row", style: { background: "var(--success-bg)", border: "1px solid var(--success-border)" } },
      el("div", { class: "anchor-label", style: { color: "var(--success)" } }, "Результат"),
      el("a", { href: placement.result_url, target: "_blank" }, placement.result_url),
    ));
  }

  // Actions
  const actions = el("div", { class: "actions" });
  if (!placement) {
    actions.appendChild(el("button", { onClick: async () => {
      try { await api.takeTask(t.item_id); toast("Взято в работу", "success"); reload(); }
      catch (e) { toast(e.message, "error"); }
    }}, icon("zap", { size: 13 }), el("span", {}, "Взять в работу")));
  } else if (!isPlaced) {
    actions.appendChild(el("button", { onClick: () => openPlacedForm(placement, t, reload) },
      icon("check", { size: 13 }), el("span", {}, "Отметить размещение")));
    actions.appendChild(el("button", { class: "ghost", onClick: () => openProblemForm(placement, reload) },
      icon("alert", { size: 13 }), el("span", {}, "Проблема")));
  } else {
    actions.appendChild(el("button", { class: "ghost small", onClick: () => openPlacedForm(placement, t, reload) },
      icon("pencil", { size: 12 }), el("span", {}, "Изменить")));
  }
  card.appendChild(actions);

  return card;
}

function credRow(key, val, masked = false) {
  let display = val;
  let shown = !masked;
  const valEl = el("span", { class: "val" }, masked ? "••••••••" : val);
  const eye = masked ? el("button", { class: "copy-btn", type: "button", title: "Показать",
    onClick: () => { shown = !shown; valEl.textContent = shown ? val : "••••••••"; },
  }, icon("eye", { size: 13 })) : null;
  const copyBtn = el("button", { class: "copy-btn", type: "button", title: "Скопировать",
    onClick: async () => {
      const ok = await copy(val);
      if (ok) toast("Скопировано", "success");
    },
  }, icon("copy", { size: 13 }));
  return el("div", { class: "cred" },
    el("span", { class: "key" }, key),
    valEl,
    eye,
    copyBtn,
  );
}

function openPlacedForm(placement, task, reload) {
  const form = el("form", {});
  const fields = [
    ["result_url", "Ссылка на результат *", true, placement.result_url || "", "url"],
    ["login_email", "Email для входа", false, placement.login_email || "", "email"],
    ["login_password", "Пароль", false, placement.login_password || "", "text"],
    ["account_username", "Имя аккаунта", false, placement.account_username || task?.suggested_account?.account_username || "", "text"],
  ];
  for (const [name, label, required, value, type] of fields) {
    form.appendChild(el("div", { class: "field" },
      el("label", {}, label),
      el("input", { name, type, value, required: required ? "" : null })
    ));
  }
  form.appendChild(el("div", { class: "field" },
    el("label", {}, "Комментарий"),
    el("textarea", { name: "comment", rows: 2 }, placement.comment || "")
  ));

  openModal({
    title: "Отметить размещение",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { onClick: async () => {
        const data = {};
        new FormData(form).forEach((v, k) => data[k] = v);
        try { await api.markPlaced(placement.id, data); toast("Размещение зафиксировано", "success"); closeModal(); reload(); }
        catch (e) { toast(e.message, "error"); }
      }}, "Сохранить"));
      return f;
    })(),
  });
}

function openProblemForm(placement, reload) {
  const form = el("form", {});
  form.appendChild(el("div", { class: "field" },
    el("label", {}, "Что пошло не так?"),
    el("textarea", { name: "comment", rows: 4, placeholder: "Опишите проблему — она появится в ленте для менеджера" }, placement.comment || "")
  ));
  openModal({
    title: "Отметить как проблему",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(el("button", { class: "danger", onClick: async () => {
        const comment = form.querySelector("[name=comment]").value;
        try { await api.markProblem(placement.id, { comment }); toast("Отмечено", "success"); closeModal(); reload(); }
        catch (e) { toast(e.message, "error"); }
      }}, "Отправить"));
      return f;
    })(),
  });
}
