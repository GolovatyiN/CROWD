import { api, auth } from "../api.js";
import { el, fmtDate, emptyState, tableSkeleton, menuButton, sortHeader, submitButton } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { openModal, closeModal } from "../components/modal.js";
import { toast } from "../components/toast.js";

// Rename a plan via a small modal. `onDone(newName)` lets callers update the
// UI without a full reload; falls back to nothing if omitted.
export function renamePlan(plan, onDone) {
  const input = el("input", { type: "text", value: plan.plan_name || "", placeholder: "Название плана" });
  const form = el("form", {}, el("div", { class: "field" }, el("label", {}, "Название анкор-плана"), input));
  openModal({
    title: "Переименовать план",
    content: form,
    footer: (() => {
      const f = document.createElement("div"); f.className = "row"; f.style.justifyContent = "flex-end"; f.style.gap = "8px";
      f.appendChild(el("button", { class: "ghost", onClick: () => closeModal() }, "Отмена"));
      f.appendChild(submitButton("Сохранить", async () => {
        const name = input.value.trim();
        if (!name) { toast("Введите название", "error"); return; }
        try {
          const updated = await api.updatePlan(plan.id, { plan_name: name });
          plan.plan_name = updated.plan_name;
          toast("Переименовано", "success");
          closeModal();
          if (onDone) onDone(updated.plan_name);
        } catch (e) { toast(e.message, "error"); }
      }));
      return f;
    })(),
  });
  setTimeout(() => input.focus(), 50);
}

export async function renderPlans(host) {
  const isAdmin = auth.isAdmin();
  const state = { sort: "created_at", order: "desc" };

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Анкор-планы"),
      el("div", { class: "page-subtitle" }, "Списки целевых ссылок и анкоров"),
    ),
    el("div", { class: "page-actions" },
      isAdmin && el("button", { onClick: () => location.hash = "#/import-export" }, icon("plus", { size: 14 }), el("span", {}, "Импортировать план")),
    ),
  ));

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(5, 6));
    let data;
    try { data = await api.plans({ sort: state.sort, order: state.order }); }
    catch (e) {
      wrap.innerHTML = "";
      wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
      return;
    }
    wrap.innerHTML = "";
    if (!data.length) {
      wrap.appendChild(emptyState({
        iconName: "plans",
        title: "Пока нет анкор-планов",
        desc: "Загрузите свой первый анкор-план в формате CSV или XLSX.",
        action: isAdmin && el("button", { onClick: () => location.hash = "#/import-export" }, icon("upload", { size: 14 }), el("span", {}, "Импортировать план")),
      }));
      return;
    }
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      sortHeader("Название", "plan_name", state, load, "left"),
      sortHeader("Всего", "total_rows", state, load, "right"),
      sortHeader("Готово", "completed_rows", state, load, "right"),
      sortHeader("В работе", "pending_rows", state, load, "right"),
      sortHeader("Проблем", "problem_rows", state, load, "right"),
      el("th", {}, "Прогресс"),
      sortHeader("Загружен", "created_at", state, load),
      el("th", { class: "right" }, ""),
    )));
    const tbody = el("tbody");
    data.forEach(p => tbody.appendChild(planRow(p, load, isAdmin)));
    table.appendChild(tbody);
    wrap.appendChild(table);
  }
  await load();
}

function planRow(p, reload, isAdmin) {
  const pct = p.total_rows ? Math.round((p.completed_rows / p.total_rows) * 100) : 0;
  return el("tr", {},
    el("td", { class: "left" },
      el("a", { href: `#/plans/${p.id}`, style: { fontWeight: 500 } }, p.plan_name),
      p.uploaded_file_name && el("div", { class: "mono", style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: "2px" } }, p.uploaded_file_name),
    ),
    el("td", { class: "right tabular mono" }, String(p.total_rows)),
    el("td", { class: "right tabular mono", style: { color: "var(--success)" } }, String(p.completed_rows)),
    el("td", { class: "right tabular mono", style: { color: "var(--warning)" } }, String(p.pending_rows)),
    el("td", { class: "right tabular mono", style: { color: p.problem_rows ? "var(--error)" : "var(--text-3)" } }, String(p.problem_rows)),
    el("td", { style: { minWidth: "160px" } },
      el("div", { class: "row", style: { gap: "8px" } },
        el("div", { class: `progress ${pct >= 100 ? "success" : ""}`, style: { flex: 1 } },
          el("div", { class: "bar", style: { width: `${pct}%` } })),
        el("span", { class: "muted tabular", style: { fontSize: "11.5px" } }, `${pct}%`),
      ),
    ),
    el("td", { class: "muted", style: { fontSize: "12px" } }, fmtDate(p.created_at)),
    el("td", { class: "right actions" },
      menuButton([
        { label: "Открыть", icon: "external", onClick: () => location.hash = `#/plans/${p.id}` },
        isAdmin && { label: "Переименовать", icon: "pencil", onClick: () => renamePlan(p, reload) },
        { label: "Экспорт CSV", icon: "download", onClick: () => api.exportPlan(p.id) },
        isAdmin && { separator: true },
        isAdmin && {
          label: "Удалить план", icon: "trash", danger: true,
          onClick: async () => {
            if (!confirm("Удалить план со всеми его строками?")) return;
            try { await api.deletePlan(p.id); toast("Удалено", "success"); reload(); }
            catch (e) { toast(e.message, "error"); }
          }
        },
      ]),
    ),
  );
}
