// Client cabinet — read-only view for role='client'. All data is scoped and
// whitelisted server-side (/client/*); this page just renders it.
import { api } from "../api.js";
import { el, fmtDate, emptyState, tableSkeleton, pill } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { toast } from "../components/toast.js";

const PROJECT_STATUS = { active: "Активен", paused: "На паузе", done: "Завершён", archived: "В архиве" };
// Placeholder link statuses — the automated link check (Фаза 5) will fill these.
const LINK_STATUS = { placed: "Размещена", done: "Размещена", problem: "Проблема" };

function statChip(status) {
  const v = status === "placed" || status === "done" ? "success" : status === "problem" ? "error" : "muted";
  return pill(LINK_STATUS[status] || status || "—", v);
}

function statCard(label, value, sub) {
  return el("div", { class: "stat-card" },
    el("div", { class: "stat-label" }, label),
    el("div", { class: "stat-value" }, String(value)),
    sub && el("div", { class: "stat-sub muted" }, sub),
  );
}

// ---------------- Dashboard: my projects ----------------

export async function renderClientDashboard(host) {
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Мои проекты"),
      el("div", { class: "page-subtitle" }, "Ход размещений по вашим кампаниям"),
    ),
  ));

  const cards = el("div", { class: "stat-row", style: { marginBottom: "16px" } });
  host.appendChild(cards);
  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);
  wrap.appendChild(tableSkeleton(4, 5));

  let summary, projects;
  try {
    [summary, projects] = await Promise.all([api.clientSummary(), api.clientMyProjects()]);
  } catch (e) {
    wrap.innerHTML = "";
    wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    return;
  }

  cards.appendChild(statCard("Проектов", summary.projects || 0));
  cards.appendChild(statCard("Размещено ссылок", summary.placements_done || 0, `из ${summary.placements_total || 0} в работе`));

  wrap.innerHTML = "";
  if (!projects.length) {
    wrap.appendChild(emptyState({ iconName: "plans", title: "Пока нет проектов", desc: "Как только менеджер заведёт проект, он появится здесь." }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "Проект"),
    el("th", {}, "GEO / язык"),
    el("th", { class: "right" }, "План"),
    el("th", { class: "right" }, "Размещено / всего"),
    el("th", {}, "Статус"),
    el("th", {}, "Прогресс"),
  )));
  const tbody = el("tbody");
  projects.forEach(p => {
    const pct = p.total_rows ? Math.round((p.completed_rows / p.total_rows) * 100) : 0;
    tbody.appendChild(el("tr", {},
      el("td", { class: "left" },
        el("a", { href: `#/client/projects/${p.id}`, style: { fontWeight: 500 } }, p.name),
        p.promoted_domain && el("div", { class: "mono", style: { fontSize: "11.5px", color: "var(--text-3)" } }, p.promoted_domain),
      ),
      el("td", { class: "muted", style: { fontSize: "12px" } }, `${p.geo || "—"} / ${p.language || "—"}`),
      el("td", { class: "right tabular mono" }, String(p.planned_count || 0)),
      el("td", { class: "right tabular mono" }, `${p.completed_rows || 0} / ${p.total_rows || 0}`),
      el("td", {}, pill(PROJECT_STATUS[p.status] || p.status, p.status === "active" ? "success" : "muted")),
      el("td", { style: { minWidth: "140px" } },
        el("div", { class: "row", style: { gap: "8px" } },
          el("div", { class: `progress ${pct >= 100 ? "success" : ""}`, style: { flex: 1 } }, el("div", { class: "bar", style: { width: `${pct}%` } })),
          el("span", { class: "muted tabular", style: { fontSize: "11.5px" } }, `${pct}%`),
        ),
      ),
    ));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
}

// ---------------- Project detail: placements ----------------

export async function renderClientProject(host, projectId) {
  let project, placements;
  try {
    [project, placements] = await Promise.all([api.clientMyProject(projectId), api.clientMyProjectPlacements(projectId)]);
  } catch (e) {
    host.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message }));
    return;
  }

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "row", style: { gap: "8px", alignItems: "center" } },
        el("a", { href: "#/client/projects", class: "subtle", style: { display: "inline-flex", padding: "2px" } }, icon("chevronLeft", { size: 16 })),
        el("div", { class: "page-title" }, project.name),
        pill(PROJECT_STATUS[project.status] || project.status, project.status === "active" ? "success" : "muted"),
      ),
      el("div", { class: "page-subtitle" }, `${project.promoted_domain || ""} · план ${project.planned_count} · размещено ${project.completed_rows}/${project.total_rows}`),
    ),
    el("div", { class: "page-actions" },
      el("button", { class: "ghost", onClick: () => downloadReport(project, placements) }, icon("download", { size: 14 }), el("span", {}, "Скачать отчёт")),
    ),
  ));

  const wrap = el("div", { class: "table-wrap" });
  host.appendChild(wrap);
  if (!placements.length) {
    wrap.appendChild(emptyState({ iconName: "tasks", title: "Размещений пока нет", desc: "Готовые размещения появятся здесь по мере выполнения." }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { class: "left" }, "Целевой URL"),
    el("th", { class: "left" }, "Анкор"),
    el("th", { class: "left" }, "Донор"),
    el("th", { class: "left" }, "Ready link"),
    el("th", {}, "Статус"),
    el("th", {}, "Дата"),
  )));
  const tbody = el("tbody");
  placements.forEach(p => tbody.appendChild(el("tr", {},
    el("td", { class: "left truncate mono", style: { fontSize: "12px" }, title: p.target_url }, p.target_url),
    el("td", { class: "left" }, p.anchor_text || el("span", { class: "dimmed" }, "— (безанкор)")),
    el("td", { class: "left mono", style: { fontSize: "12px" } }, p.donor_domain || "—"),
    el("td", { class: "left" }, p.result_url
      ? el("a", { href: p.result_url, target: "_blank", rel: "noopener", class: "mono", style: { fontSize: "12px" } }, "открыть ↗")
      : el("span", { class: "dimmed" }, "—")),
    el("td", {}, statChip(p.status)),
    el("td", { class: "muted", style: { fontSize: "12px" } }, fmtDate(p.placed_at)),
  )));
  table.appendChild(tbody);
  wrap.appendChild(table);
}

function downloadReport(project, placements) {
  // Client-side CSV of what the client already sees (Фаза 10 adds a server report).
  const head = ["target_url", "anchor", "donor_domain", "ready_link", "status", "placed_at"];
  const rows = placements.map(p => [p.target_url, p.anchor_text, p.donor_domain, p.result_url, p.status, p.placed_at || ""]);
  const csv = [head, ...rows].map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  a.download = `report_${project.name}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  toast("Отчёт скачан", "success");
}
