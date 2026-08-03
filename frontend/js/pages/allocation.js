import { api } from "../api.js";
import { el, emptyState, tableSkeleton, submitButton, pill } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

export async function renderAllocation(host) {
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Распределение работы"),
      el("div", { class: "page-subtitle" }, "Соотношение «наши / клиентские» и дневные планы сотрудников"),
    ),
  ));

  const body = el("div", {});
  host.appendChild(body);
  body.appendChild(tableSkeleton(4, 5));

  let data, users;
  try { [data, users] = await Promise.all([api.allocation(), api.users().catch(() => [])]); }
  catch (e) { body.innerHTML = ""; body.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }
  body.innerHTML = "";

  const employees = (users || []).filter(u => u.is_active && ["user", "teamlead"].includes(u.role));
  const empById = Object.fromEntries(employees.map(u => [u.id, u]));
  const overrideByUser = Object.fromEntries((data.employees || []).map(r => [r.user_id, r]));

  // ---- Global card ----
  const g = data.global || { internal_pct: 50, daily_target: 0 };
  const gInternal = el("input", { type: "number", min: "0", max: "100", value: g.internal_pct ?? 50, style: { width: "80px" } });
  const gTarget = el("input", { type: "number", min: "0", value: g.daily_target ?? 0, style: { width: "90px" } });
  body.appendChild(el("div", { class: "panel", style: { marginBottom: "16px" } },
    el("div", { class: "panel-header" }, el("div", { class: "panel-title" }, "Глобально (по умолчанию)")),
    el("div", { class: "row", style: { gap: "16px", alignItems: "flex-end", flexWrap: "wrap" } },
      el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, "Внутренних, %"), gInternal),
      el("div", { class: "muted", style: { paddingBottom: "8px" } }, ratioHint(gInternal)),
      el("div", { class: "field", style: { marginBottom: 0 } }, el("label", {}, "Дневной план (шт.)"), gTarget),
      submitButton("Сохранить", async () => {
        try {
          await api.saveAllocation({ scope: "global", internal_pct: parseInt(gInternal.value) || 0, daily_target: parseInt(gTarget.value) || 0 });
          toast("Сохранено", "success");
        } catch (e) { toast(e.message, "error"); }
      }),
    ),
  ));

  // ---- Employees table ----
  if (!employees.length) {
    body.appendChild(emptyState({ iconName: "users", title: "Нет сотрудников", desc: "Добавьте сотрудников, чтобы распределять работу." }));
    return;
  }
  const wrap = el("div", { class: "table-wrap" });
  body.appendChild(wrap);
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "Сотрудник"),
    el("th", {}, "Соотношение"),
    el("th", { class: "right" }, "Дн. план"),
    el("th", { class: "right" }, "Сегодня (внутр / клиент)"),
    el("th", {}, "Отклонение"),
    el("th", { class: "right" }, ""),
  )));
  const tbody = el("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);

  // Render rows, then load per-employee plan/fact in parallel.
  const rows = {};
  employees.forEach(u => {
    const ov = overrideByUser[u.id];
    const ip = ov ? ov.internal_pct : g.internal_pct;
    const dt = ov ? ov.daily_target : g.daily_target;
    const factCell = el("td", { class: "right tabular mono muted" }, "…");
    const devCell = el("td", {}, el("span", { class: "dimmed" }, "…"));
    rows[u.id] = { factCell, devCell };
    tbody.appendChild(el("tr", {},
      el("td", { class: "left" }, u.full_name || u.email, ov ? pill("своё", "info") : null),
      el("td", {}, `${ip}% / ${100 - ip}%`),
      el("td", { class: "right tabular mono" }, String(dt || "—")),
      factCell, devCell,
      el("td", { class: "right actions" }, el("div", { class: "row", style: { gap: "6px", justifyContent: "flex-end" } },
        el("button", { class: "subtle small", onClick: () => overrideModal(u, ov, g, () => location.reload()) }, "Настроить"),
        el("button", { class: "small", onClick: () => assignModal(u, dt) }, icon("plus", { size: 13 }), el("span", {}, "Раздать")),
      )),
    ));
  });

  // Fill plan/fact
  await Promise.all(employees.map(async u => {
    try {
      const p = await api.allocationPlan(u.id);
      rows[u.id].factCell.textContent = `${p.done_internal} / ${p.done_client}`;
      const dv = p.deviation_pct;
      rows[u.id].devCell.innerHTML = "";
      rows[u.id].devCell.appendChild(dv == null ? el("span", { class: "dimmed" }, "—")
        : pill(`${dv > 0 ? "+" : ""}${dv}%`, Math.abs(dv) <= 10 ? "success" : Math.abs(dv) <= 25 ? "warning" : "error"));
    } catch { rows[u.id].factCell.textContent = "—"; }
  }));
}

function ratioHint(input) {
  const v = parseInt(input.value) || 0;
  return `наши ${v}% · клиентские ${100 - v}%`;
}

function overrideModal(user, override, glob, onDone) {
  const ip = el("input", { type: "number", min: "0", max: "100", value: (override ? override.internal_pct : glob.internal_pct) ?? 50, style: { width: "90px" } });
  const dt = el("input", { type: "number", min: "0", value: (override ? override.daily_target : glob.daily_target) ?? 0, style: { width: "100px" } });
  const content = el("div", {},
    el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "10px" } }, `Персональные настройки для «${user.full_name || user.email}». Переопределяют глобальные.`),
    el("div", { class: "field" }, el("label", {}, "Внутренних, %"), ip),
    el("div", { class: "field" }, el("label", {}, "Дневной план (шт.)"), dt),
  );
  const footer = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
    el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"),
    submitButton("Сохранить", async () => {
      try {
        await api.saveAllocation({ scope: "employee", user_id: user.id, internal_pct: parseInt(ip.value) || 0, daily_target: parseInt(dt.value) || 0 });
        toast("Сохранено", "success"); closeModal(); onDone && onDone();
      } catch (e) { toast(e.message, "error"); }
    }),
  );
  openModal({ title: "Настройка сотрудника", content, footer });
}

function assignModal(user, defaultCount) {
  const count = el("input", { type: "number", min: "1", value: defaultCount || 25, style: { width: "100px" } });
  const out = el("div", { style: { marginTop: "10px" } });
  const content = el("div", {},
    el("div", { class: "muted", style: { fontSize: "12.5px", marginBottom: "10px" } },
      `Авто-раздача подобранных задач «${user.full_name || user.email}» с учётом соотношения и ограничений (гео/язык/стоп-лист уже учтены при подборе).`),
    el("div", { class: "field" }, el("label", {}, "Сколько задач"), count),
    out,
  );
  const footer = el("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
    el("button", { class: "ghost", onClick: () => closeModal() }, "Закрыть"),
    submitButton("Раздать", async () => {
      try {
        const r = await api.autoAssign({ user_id: user.id, count: parseInt(count.value) || 0 });
        out.innerHTML = "";
        out.appendChild(el("div", { class: "import-result success", style: { marginTop: "8px" } },
          el("div", {}, `Назначено: ${r.assigned} (внутр. ${r.internal} / клиент. ${r.client})`),
          (r.shortfall ? el("div", { class: "muted" }, `Не хватило задач: ${r.shortfall}`) : null),
          (r.deviation ? el("div", { class: "muted" }, `Отклонение от соотношения: ${r.deviation > 0 ? "+" : ""}${r.deviation} внутр.`) : null),
          (r.note ? el("div", { class: "muted" }, r.note) : null),
        ));
        toast(`Назначено ${r.assigned}`, "success");
      } catch (e) { toast(e.message, "error"); }
    }),
  );
  openModal({ title: "Раздать задачи", content, footer });
}
