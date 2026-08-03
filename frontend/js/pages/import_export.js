import { api, auth } from "../api.js";
import { el, emptyState, submitButton } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export async function renderImportExport(host) {
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Импорт / экспорт"),
      el("div", { class: "page-subtitle" }, "Загрузка CSV/XLSX с автоматическим распознаванием колонок"),
    ),
  ));

  host.appendChild(section({
    title: "База доноров",
    hint: "Domain (или url/donor_url/website/host) — обязательно. Опционально: DR (или tr), Organic Traffic (или traffic), Referring Domains (или ref_domains), Backlinks, GEO (или country), Language (или lang), link_type (dofollow / nofollow / mixed / error / unknown), Category, Comment. Регистр и пробелы в заголовках не важны.",
    importFn: (file) => api.importDonors(file),
    exportFn: () => api.exportDonors(),
  }));

  // Clients + projects for the "import as client plan" selector. Preselect comes
  // from a project's "Импортировать план" action (via sessionStorage).
  let clients = [], clientProjects = [], projectsError = null;
  try {
    [clients, clientProjects] = await Promise.all([api.clients(), api.clientProjects()]);
  } catch (e) {
    projectsError = e.message;
  }
  const clientName = Object.fromEntries(clients.map(c => [c.id, c.name]));
  const preselectProject = sessionStorage.getItem("import_client_project") || "";
  sessionStorage.removeItem("import_client_project");

  host.appendChild(section({
    title: "Анкор-план",
    hint: "Обязательно: target_url (или url/page) либо target_domain. Опционально: anchor_text, anchor_type (тип анкора), geo, language, priority, requirements. Формат 2 — добавьте колонку quantity (количество): такая строка станет агрегированной позицией на N размещений без создания N одинаковых строк; задания создаются кнопкой «Распределить».",
    extraFields: [{ name: "plan_name", label: "Название плана", placeholder: "по умолчанию — имя файла" }],
    selectFields: [{
      name: "client_project",
      label: "Для кого этот план?",
      value: preselectProject,
      options: [
        { value: "", label: "Наш проект компании (внутренний)" },
        ...clientProjects.map(p => ({ value: String(p.id), label: `Клиент: ${clientName[p.client_id] || "—"} → ${p.name}` })),
      ],
    }],
    importFn: async (file, extra) => api.importPlan(file, extra.plan_name || "", extra.client_project || null),
  }));

  // Guidance right under the plan section: how to make it a CLIENT plan.
  if (projectsError) {
    host.appendChild(callout("warning",
      "Не удалось загрузить список клиентских проектов: ", el("b", {}, projectsError),
      ". Импорт «нашего» плана работает; для клиентского — обновите страницу или сообщите об ошибке."));
  } else if (!clientProjects.length) {
    host.appendChild(callout("info",
      "План привязывается к ", el("b", {}, "проекту клиента"), ", а не к клиенту напрямую. Даже если клиент уже создан — откройте ",
      el("a", { href: "#/clients", style: { fontWeight: 600, textDecoration: "underline" } }, "«Клиенты»"),
      ", нажмите на клиента и создайте ему ", el("b", {}, "проект"), " (кнопка «Создать проект»). После этого проект появится здесь в поле «Для кого этот план?» — или прямо из проекта нажмите «Импортировать план»."));
  } else {
    host.appendChild(callout("info",
      "Оставьте «Наш проект компании» для внутреннего плана, либо выберите клиента и проект в поле «Для кого этот план?», чтобы загрузить его как клиентский."));
  }

  host.appendChild(section({
    title: "Стоп-лист",
    hint: "Два формата на выбор. 1) Таблица: колонки donor_url + target_url (либо target_domain), опционально result_url, comment. 2) Матрица: в верхней строке — целевые домены (бренды), в каждом столбце под ними — доноры этого бренда. Домены-доноры блокируются для всего бренда.",
    selectFields: [{
      name: "stoplist_client",
      label: "Для кого этот стоп-лист?",
      value: "",
      options: [
        { value: "", label: "Наш стоп-лист (внутренний)" },
        ...clients.map(c => ({ value: String(c.id), label: `Клиент: ${c.name}` })),
      ],
    }],
    importFn: (file, extra) => api.importStopList(file, extra.stoplist_client || null),
    exportFn: () => api.exportStopList(),
  }));
  host.appendChild(callout("info",
    "Стоп-листы изолированы: клиентский план подбирает доноров только по стоп-листу своего клиента, наш — только по нашему. Разные клиенты друг на друга не влияют. Общая — только база доноров."));

  // Disk & maintenance — visible to any admin. Shows what's using the volume
  // and lets them run the retention prune on demand.
  if (auth.isAdmin()) {
    host.appendChild(maintenancePanel());
  }

  // Reset all data — Super-Admin only. Wipes operational data so the
  // dashboard goes back to zero, without a manual SQL trip.
  if (auth.isSuperAdmin()) {
    host.appendChild(dangerZone());
  }
}

const TABLE_LABELS = {
  link_check_results: "История проверок ссылок",
  link_checks: "Очередь проверок",
  stop_list_entries: "Стоп-лист",
  placements: "Размещения",
  notifications: "Уведомления",
  audit_logs: "Журнал действий",
  import_logs: "Логи импорта",
  anchor_plan_items: "Строки планов",
  donors: "Доноры",
};

function fmtBytes(n) {
  if (n == null) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

function maintenancePanel() {
  const wrap = el("div", { class: "panel" });
  wrap.appendChild(el("div", { class: "panel-header" },
    el("div", { class: "panel-title" }, icon("donors", { size: 15 }), el("span", { style: { marginLeft: "6px" } }, "Диск и обслуживание")),
    el("button", { class: "ghost small", type: "button", onClick: () => load() }, icon("refresh", { size: 13 }), el("span", {}, "Обновить")),
  ));
  const body = el("div", {});
  wrap.appendChild(body);

  async function load() {
    body.innerHTML = "";
    body.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px" } }, "Загрузка…"));
    let s;
    try { s = await api.maintenanceStorage(); }
    catch (e) { body.innerHTML = ""; body.appendChild(el("div", { style: { fontSize: "12.5px", color: "var(--error)" } }, e.message)); return; }
    body.innerHTML = "";

    body.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "12px", lineHeight: 1.5 } },
      "История проверок ссылок и старые уведомления/логи чистятся автоматически раз в сутки, чтобы том не заполнялся. Текущий статус каждой ссылки при этом сохраняется. Ниже — что занимает место; очистку можно запустить вручную."));

    const isPg = s.dialect === "postgresql";
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { class: "left" }, "Таблица"),
      el("th", { class: "right" }, "Строк"),
      isPg ? el("th", { class: "right" }, "Размер") : null,
    )));
    const tb = el("tbody");
    Object.entries(s.counts).filter(([, v]) => v != null).forEach(([name, cnt]) => {
      tb.appendChild(el("tr", {},
        el("td", { class: "left", style: { fontSize: "12.5px" } }, TABLE_LABELS[name] || name),
        el("td", { class: "right tabular mono", style: { fontSize: "12.5px" } }, Number(cnt).toLocaleString("ru")),
        isPg ? el("td", { class: "right tabular mono muted", style: { fontSize: "12px" } }, fmtBytes(s.table_bytes?.[name])) : null,
      ));
    });
    table.appendChild(tb);
    body.appendChild(el("div", { class: "table-wrap" }, table));

    const r = s.retention || {};
    body.appendChild(el("div", { class: "muted", style: { fontSize: "12px", marginTop: "10px" } },
      (s.db_bytes != null ? `Размер БД: ${fmtBytes(s.db_bytes)} · ` : "")
      + `хранение истории: ${r.link_check_results_retention_days} дн / ≤${r.link_check_results_keep_per_placement} на размещение · авто-очистка ${r.enabled ? "вкл" : "выкл"}`));

    body.appendChild(el("div", { style: { marginTop: "14px" } },
      submitButton("Очистить историю сейчас", async () => {
        try {
          const res = await api.maintenancePrune();
          const d = res.deleted || {};
          const total = Object.values(d).filter(n => typeof n === "number" && n > 0).reduce((a, b) => a + b, 0);
          toast(total ? `Удалено строк: ${total.toLocaleString("ru")}` : "Нечего чистить — всё в пределах срока хранения", "success");
          load();
        } catch (e) { toast(e.message, "error"); }
      }, { iconName: "trash" })));
  }
  load();
  return wrap;
}

function dangerZone() {
  const wrap = el("div", { class: "panel", style: { borderColor: "var(--error)" } });
  wrap.appendChild(el("div", { class: "panel-header" },
    el("div", { class: "panel-title", style: { color: "var(--error)" } },
      icon("alert", { size: 15 }), el("span", { style: { marginLeft: "6px" } }, "Опасная зона")),
  ));
  wrap.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "14px" } },
    "Полностью очищает доноров, анкор-планы, размещения, стоп-лист и почтовые аккаунты — дашборд обнуляется. Сотрудники и журнал действий сохраняются. Действие необратимо."));
  wrap.appendChild(el("button", { class: "danger", type: "button", onClick: openResetModal },
    icon("trash", { size: 14 }), el("span", {}, "Сбросить все данные")));
  return wrap;
}

const RESET_WORD = "СБРОСИТЬ";

function openResetModal() {
  const input = el("input", { type: "text", placeholder: `Введите ${RESET_WORD}`, autocomplete: "off" });

  const confirmBtn = submitButton("Сбросить всё", async () => {
    try {
      const r = await api.resetAllData();
      const d = (r && r.deleted) || {};
      toast(`Система очищена: доноров ${d.donors || 0}, планов ${d.plans || 0}, размещений ${d.placements || 0}`, "success");
      closeModal();
      location.hash = "#/dashboard";
    } catch (e) {
      toast(e.message, "error");
    }
  }, { className: "danger", iconName: "trash" });
  confirmBtn.disabled = true;

  input.addEventListener("input", () => {
    confirmBtn.disabled = input.value.trim() !== RESET_WORD;
  });

  const content = el("div", {},
    el("div", { style: { fontSize: "13px", marginBottom: "12px", lineHeight: 1.5 } },
      "Будут безвозвратно удалены ", el("b", {}, "все доноры, анкор-планы, размещения, стоп-лист и почтовые аккаунты"), ". ",
      "Сотрудники и журнал действий сохранятся. Для подтверждения введите ",
      el("b", { style: { color: "var(--error)" } }, RESET_WORD), " ниже."),
    el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, "Подтверждение"), input),
  );

  const footer = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
    el("button", { class: "ghost", type: "button", onClick: () => closeModal() }, "Отмена"),
    confirmBtn,
  );

  openModal({ title: "Сбросить все данные?", content, footer });
  setTimeout(() => input.focus(), 50);
}

function section({ title, hint, importFn, exportFn, extraFields = [], selectFields = [] }) {
  const wrap = el("div", { class: "panel" });
  wrap.appendChild(el("div", { class: "panel-header" },
    el("div", { class: "panel-title" }, title),
    exportFn && el("button", { class: "ghost small", onClick: () => exportFn() }, icon("download", { size: 13 }), el("span", {}, "Скачать CSV")),
  ));
  wrap.appendChild(el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "12px" } }, hint));

  let pickedFile = null;
  const fileInput = el("input", { type: "file", accept: ".csv,.xlsx,.xls", style: { display: "none" } });
  const submitBtn = el("button", { class: "cta", type: "button", disabled: "" }, icon("upload", { size: 14 }), el("span", {}, "Загрузить"));

  const dz = el("label", { class: "dropzone" },
    icon("upload", { size: 32, stroke: 1.4, className: "file-icon" }),
    el("div", { class: "dropzone-title" }, "Перетащите файл сюда или нажмите для выбора"),
    el("div", { class: "dropzone-sub" }, "CSV, XLSX до 20 МБ"),
    fileInput,
  );
  const fileLabel = el("div", { class: "picked-file", style: { display: "none" } });
  dz.appendChild(fileLabel);

  function setFile(f) {
    pickedFile = f;
    if (f) {
      fileLabel.style.display = "inline-flex";
      fileLabel.innerHTML = "";
      fileLabel.appendChild(icon("file", { size: 13 }));
      fileLabel.appendChild(el("span", {}, f.name));
      const sizeKb = Math.round(f.size / 1024);
      fileLabel.appendChild(el("span", { class: "muted" }, `· ${sizeKb} КБ`));
      submitBtn.disabled = false;
    } else {
      fileLabel.style.display = "none";
      submitBtn.disabled = true;
    }
  }

  fileInput.addEventListener("change", (e) => setFile(e.target.files[0] || null));
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag-over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag-over");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });

  wrap.appendChild(dz);

  // Extra fields (text inputs + optional <select> fields). Both feed `extras`.
  const extraInputs = {};
  if (extraFields.length || selectFields.length) {
    const row = el("div", { class: "row", style: { marginTop: "12px" } });
    extraFields.forEach(f => {
      const input = el("input", { type: "text", name: f.name, placeholder: f.placeholder || "" });
      extraInputs[f.name] = input;
      row.appendChild(el("div", { class: "field", style: { flex: 1, marginBottom: 0 } },
        el("label", {}, f.label),
        input,
      ));
    });
    selectFields.forEach(f => {
      const sel = el("select", { name: f.name },
        ...(f.options || []).map(o => el("option", { value: o.value, selected: String(o.value) === String(f.value ?? "") }, o.label)));
      extraInputs[f.name] = sel;
      row.appendChild(el("div", { class: "field", style: { flex: 1, marginBottom: 0 } },
        el("label", {}, f.label),
        sel,
      ));
    });
    wrap.appendChild(row);
  }

  const actions = el("div", { class: "row", style: { marginTop: "14px", justifyContent: "flex-end" } });
  const clearBtn = el("button", { type: "button", class: "ghost", onClick: () => setFile(null) }, "Очистить");
  actions.appendChild(clearBtn);
  actions.appendChild(submitBtn);
  wrap.appendChild(actions);

  const result = el("div", {});
  wrap.appendChild(result);

  submitBtn.addEventListener("click", async () => {
    if (!pickedFile) { toast("Выберите файл", "error"); return; }
    submitBtn.disabled = true;
    const spinner = el("span", { class: "spinner", style: { display: "inline-block", width: "12px", height: "12px", border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.8s linear infinite" } });
    submitBtn.innerHTML = "";
    submitBtn.appendChild(spinner);
    submitBtn.appendChild(el("span", {}, "Импортируем…"));
    try {
      const extras = {};
      Object.entries(extraInputs).forEach(([k, input]) => extras[k] = input.value);
      const r = await importFn(pickedFile, extras);
      result.innerHTML = "";
      result.appendChild(resultBlock(r));
      toast("Импорт завершён", "success");
      setFile(null);
    } catch (e) {
      result.innerHTML = "";
      result.appendChild(el("div", { class: "import-result error" }, el("b", {}, "Ошибка: "), e.message));
      toast(e.message, "error");
    } finally {
      submitBtn.disabled = pickedFile ? false : true;
      submitBtn.innerHTML = "";
      submitBtn.appendChild(icon("upload", { size: 14 }));
      submitBtn.appendChild(el("span", {}, "Загрузить"));
    }
  });

  return wrap;
}

function callout(variant, ...children) {
  const c = variant === "warning"
    ? { bg: "var(--warning-bg)", border: "var(--warning-border)" }
    : { bg: "var(--info-bg)", border: "var(--info-border)" };
  return el("div", {
    style: {
      fontSize: "12.5px", color: "var(--text-2)", lineHeight: 1.5,
      margin: "-6px 0 18px", padding: "10px 12px",
      background: c.bg, border: `1px solid ${c.border}`, borderRadius: "8px",
    },
  }, ...children);
}

function resultBlock(r) {
  const wrap = el("div", { class: "import-result success", style: { marginTop: "12px" } });
  const stats = el("div", { class: "stats" });
  stats.appendChild(el("div", { class: "stat" }, "Всего: ", el("b", {}, String(r.rows_total))));
  if (r.rows_inserted) stats.appendChild(el("div", { class: "stat" }, "Добавлено: ", el("b", {}, String(r.rows_inserted))));
  if (r.rows_updated) stats.appendChild(el("div", { class: "stat" }, "Обновлено: ", el("b", {}, String(r.rows_updated))));
  if (r.rows_skipped) stats.appendChild(el("div", { class: "stat" }, "Пропущено: ", el("b", {}, String(r.rows_skipped))));
  if (r.rows_failed) stats.appendChild(el("div", { class: "stat" }, "Ошибок: ", el("b", {}, String(r.rows_failed))));
  if (r.plan_id) stats.appendChild(el("div", { class: "stat" }, "ID плана: ", el("b", {}, String(r.plan_id))));
  wrap.appendChild(stats);

  if (r.errors && r.errors.length) {
    const errBlock = el("div", { style: { marginTop: "10px" } });
    errBlock.appendChild(el("div", { style: { fontWeight: 600, color: "var(--error)", marginBottom: "4px" } }, `Не удалось обработать ${r.errors.length} строк`));
    const list = el("ul", { style: { color: "var(--error)", margin: 0, paddingLeft: "18px", fontSize: "12.5px" } });
    r.errors.slice(0, 10).forEach(e => list.appendChild(el("li", {}, `строка ${e.row}: ${e.error}`)));
    errBlock.appendChild(list);
    wrap.appendChild(errBlock);
  }
  if (r.plan_id) {
    wrap.appendChild(el("div", { style: { marginTop: "10px" } },
      el("a", { href: `#/plans/${r.plan_id}` },
        el("button", { class: "ghost small" }, "Открыть план →"),
      ),
    ));
  }
  return wrap;
}
