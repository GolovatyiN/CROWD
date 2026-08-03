import { api, auth } from "../api.js";
import { el, fmtRelative, avatar, tableSkeleton, emptyState } from "../components/dom.js";
import { icon } from "../components/icons.js";

const CONTOURS = [["", "Все"], ["internal", "Наши"], ["client", "Клиентские"]];

export async function renderDashboard(host) {
  const user = auth.getUser();
  const state = { kind: "" };  // "" = все, internal = наши, client = клиентские

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, `Привет, ${(user?.full_name || user?.email || "").split(" ")[0] || ""} 👋`),
      el("div", { class: "page-subtitle" }, "Что нового по размещениям и задачам сегодня"),
    ),
  ));

  // Contour toggle — read the whole board as «Все / Наши / Клиентские».
  const seg = el("div", { class: "segmented", style: { marginBottom: "6px" } });
  const splitHint = el("div", { class: "muted", style: { fontSize: "11.5px", marginBottom: "16px" } });
  function rebuildSeg() {
    seg.innerHTML = "";
    CONTOURS.forEach(([val, label]) => {
      seg.appendChild(el("button", {
        class: `seg ${state.kind === val ? "active" : ""}`,
        onClick: () => { if (state.kind !== val) { state.kind = val; rebuildSeg(); paint(); } },
      }, label));
    });
  }
  rebuildSeg();
  host.appendChild(seg);
  host.appendChild(splitHint);

  const board = el("div", {});
  host.appendChild(board);

  async function paint() {
    board.innerHTML = "";
    const cardsHost = el("div", { class: "cards" });
    const colsHost = el("div", { class: "grid-2" });
    board.appendChild(cardsHost);
    board.appendChild(colsHost);

    for (let i = 0; i < 5; i++) cardsHost.appendChild(skeletonCard());
    const leftLoad = panel("", "");
    const rightLoad = panel("", "");
    leftLoad.body.appendChild(tableSkeleton(4, 2));
    rightLoad.body.appendChild(tableSkeleton(4, 2));
    colsHost.appendChild(leftLoad.wrap);
    colsHost.appendChild(rightLoad.wrap);

    let s;
    try { s = await api.stats(state.kind); }
    catch (e) {
      board.innerHTML = "";
      board.appendChild(emptyState({ iconName: "alert", title: "Не удалось загрузить данные", desc: e.message }));
      return;
    }

    // Contour caption: show the наши/клиентские split + remind that the donor
    // base and stop-list are a shared resource (not divided by contour).
    splitHint.textContent = `Размещений всего: наши ${s.placements_internal} · клиентские ${s.placements_client}`
      + (state.kind ? " · доноры и стоп-лист — общий ресурс" : "");

    cardsHost.innerHTML = "";
    colsHost.innerHTML = "";

    // ---- Stat cards ----
    const deltaWeek = s.placements_week - s.placements_prev_week;
    const deltaToday = s.placements_today - s.placements_yesterday;

    cardsHost.appendChild(statCard({
      label: "За сегодня", value: s.placements_today, icon: "zap", tint: "violet",
      delta: deltaToday, deltaLabel: "к вчера",
    }));
    cardsHost.appendChild(statCard({
      label: "За неделю", value: s.placements_week, icon: "check", tint: "success",
      delta: deltaWeek, deltaLabel: "к прошлой",
    }));
    cardsHost.appendChild(statCard({
      label: "За месяц", value: s.placements_month, icon: "clock", tint: "info",
    }));
    cardsHost.appendChild(statCard({
      label: "В работе", value: s.tasks_in_progress, icon: "tasks", tint: "warning",
      sub: `${s.tasks_pending} в очереди`,
    }));
    cardsHost.appendChild(statCard({
      label: "Проблемы", value: s.tasks_problem, icon: "alert", tint: "error",
    }));
    cardsHost.appendChild(statCard({
      label: "Доноры", value: s.donors_active, icon: "donors", tint: "",
      sub: `всего ${s.donors_total}`,
    }));
    cardsHost.appendChild(statCard({
      label: "В стоп-листе", value: s.stop_list_total, icon: "stop", tint: "",
    }));
    cardsHost.appendChild(statCard({
      label: "Строк в планах", value: s.items_total, icon: "plans", tint: "",
      sub: `${s.tasks_done} готово`,
    }));

    // ---- Left column: sparkline + activity feed ----
    const leftCol = el("div", {});
    const sparkPanel = panel("Размещения за 14 дней", `${s.placements_week} за неделю`);
    sparkPanel.body.appendChild(sparkline(s.series));
    leftCol.appendChild(sparkPanel.wrap);

    const actPanel = panel("Последние размещения");
    if (s.recent_activity.length === 0) {
      actPanel.body.appendChild(emptyState({ iconName: "check", title: "Пока пусто", desc: "Здесь появятся последние размещения сотрудников." }));
    } else {
      const feed = el("div", { class: "feed" });
      s.recent_activity.forEach(a => feed.appendChild(activityRow(a)));
      actPanel.body.appendChild(feed);
    }
    leftCol.appendChild(actPanel.wrap);

    // ---- Right column: (clients) + problems + employee progress ----
    const rightCol = el("div", {});

    // Per-client breakdown — the whole point of the client contour. Hidden for
    // the "наши" view (internal placements have no client).
    if (state.kind !== "internal" && (s.by_client || []).length) {
      const clientPanel = panel("По клиентам", `${s.by_client.length}`);
      const maxC = Math.max(1, ...s.by_client.map(c => c.count));
      s.by_client.forEach(c => clientPanel.body.appendChild(clientRow(c, maxC)));
      rightCol.appendChild(clientPanel.wrap);
    }

    const probPanel = panel("Проблемы", String(s.problems.length));
    if (s.problems.length === 0) {
      probPanel.body.appendChild(emptyState({ iconName: "check", title: "Всё чисто", desc: "Нет открытых проблемных задач." }));
    } else {
      const feed = el("div", { class: "feed" });
      s.problems.forEach(p => feed.appendChild(problemRow(p)));
      probPanel.body.appendChild(feed);
    }
    rightCol.appendChild(probPanel.wrap);

    const empPanel = panel("Прогресс по сотрудникам");
    if (s.employees_progress.length === 0) {
      empPanel.body.appendChild(emptyState({ iconName: "users", title: "Пока никого", desc: "Назначьте задачи сотрудникам, чтобы увидеть их прогресс." }));
    } else {
      s.employees_progress.forEach(e => empPanel.body.appendChild(employeeRow(e)));
    }
    rightCol.appendChild(empPanel.wrap);

    colsHost.appendChild(leftCol);
    colsHost.appendChild(rightCol);
  }

  await paint();
}

function clientRow(c, max) {
  const pct = Math.round((c.count / max) * 100);
  return el("div", { style: { padding: "9px 0", borderBottom: "1px solid var(--border)" } },
    el("div", { class: "row", style: { gap: "10px", marginBottom: "6px", alignItems: "center" } },
      el("div", { style: { flex: 1, minWidth: 0, fontSize: "13.5px", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, c.name),
      el("a", { href: `#/clients/${c.client_id}`, class: "mono tabular", style: { fontSize: "13px", color: "var(--text-2)" } }, String(c.count)),
    ),
    el("div", { class: "progress" }, el("div", { class: "bar", style: { width: `${pct}%` } })),
  );
}

// ---- helpers ----

function statCard({ label, value, icon: iconName, tint = "", delta, deltaLabel, sub }) {
  const top = el("div", { class: "top" },
    el("div", { class: `icon-wrap ${tint ? "tint-" + tint : ""}` }, icon(iconName, { size: 15 })),
    el("div", { class: "label" }, label),
  );
  const row = el("div", { class: "row", style: { gap: "10px", alignItems: "baseline" } },
    el("div", { class: "value tabular" }, String(value)),
  );
  if (delta !== undefined) {
    const cls = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
    const arrow = delta > 0 ? icon("arrowUp", { size: 11 }) : delta < 0 ? icon("arrowDown", { size: 11 }) : null;
    row.appendChild(el("div", { class: `delta ${cls}` }, arrow, el("span", {}, `${delta > 0 ? "+" : ""}${delta} ${deltaLabel || ""}`)));
  }
  return el("div", { class: "stat-card" },
    top,
    row,
    sub && el("div", { class: "sub" }, sub),
  );
}

function skeletonCard() {
  return el("div", { class: "stat-card" },
    el("div", { class: "skeleton skeleton-row", style: { width: "60%", height: "12px" } }),
    el("div", { class: "skeleton skeleton-row", style: { width: "40%", height: "26px", marginTop: "6px" } }),
  );
}

function panel(title, badge) {
  const wrap = el("div", { class: "panel" });
  if (title) {
    wrap.appendChild(el("div", { class: "panel-header" },
      el("div", { class: "panel-title" }, title),
      badge && el("div", { class: "muted", style: { fontSize: "12px" } }, badge),
    ));
  }
  const body = el("div", {});
  wrap.appendChild(body);
  return { wrap, body };
}

function sparkline(series) {
  const max = Math.max(1, ...series.map(p => p.count));
  const wrap = el("div", { class: "spark", style: { height: "72px" } });
  series.forEach((p, idx) => {
    const isToday = idx === series.length - 1;
    wrap.appendChild(el("div", {
      class: `bar ${isToday ? "today" : ""}`,
      title: `${p.date}: ${p.count}`,
      style: { height: `${Math.max(2, (p.count / max) * 100)}%` },
    }));
  });
  return el("div", {},
    wrap,
    el("div", { class: "muted", style: { fontSize: "11px", marginTop: "8px", display: "flex", justifyContent: "space-between" } },
      el("span", {}, series[0].date),
      el("span", {}, series[series.length - 1].date),
    ),
  );
}

function activityRow(a) {
  return el("div", { class: "feed-item success" },
    el("div", { class: "feed-icon" }, icon("check", { size: 14 })),
    el("div", { class: "feed-body" },
      el("div", { class: "feed-title" },
        el("b", {}, a.employee_name),
        " разместил ",
        a.result_url
          ? el("a", { href: a.result_url, target: "_blank", class: "mono" }, shortUrl(a.result_url))
          : el("span", { class: "mono" }, shortUrl(a.target_url)),
      ),
      el("div", { class: "feed-meta" },
        `${shortUrl(a.target_url)} → ${shortUrl(a.donor_url)} • ${fmtRelative(a.placed_at)}`
      ),
    ),
  );
}

function problemRow(p) {
  return el("div", { class: "feed-item error" },
    el("div", { class: "feed-icon" }, icon("alert", { size: 14 })),
    el("div", { class: "feed-body" },
      el("div", { class: "feed-title" },
        el("a", { href: `#/plans/${p.anchor_plan_id}` }, p.plan_name || "Без названия"),
        " — ",
        el("span", { class: "mono" }, shortUrl(p.target_url || p.target_domain)),
      ),
      el("div", { class: "feed-meta" }, (p.comment || "Без описания") + " • " + fmtRelative(p.updated_at)),
    ),
  );
}

function employeeRow(e) {
  const total = Math.max(1, e.total);
  const donePct = Math.round((e.done / total) * 100);
  const inProgressPct = Math.round((e.in_progress / total) * 100);
  return el("div", { style: { padding: "10px 0", borderBottom: "1px solid var(--border)" } },
    el("div", { class: "row", style: { gap: "10px", marginBottom: "6px" } },
      avatar(e.name, 26),
      el("div", { style: { flex: 1, minWidth: 0 } },
        el("div", { style: { fontSize: "13.5px", fontWeight: 500 } }, e.name),
        el("div", { class: "muted", style: { fontSize: "11.5px" } }, `${e.done} готово • ${e.in_progress} в работе${e.problems ? " • " + e.problems + " проблем" : ""}`),
      ),
      el("div", { class: "mono tabular", style: { fontSize: "13px", color: "var(--text-2)" } }, `${e.done}/${e.total}`),
    ),
    el("div", { class: "progress" }, el("div", { class: "bar", style: { width: `${donePct}%` } })),
  );
}

function shortUrl(u) {
  if (!u) return "—";
  try {
    const x = new URL(u);
    let s = x.host + x.pathname;
    if (s.length > 48) s = s.slice(0, 46) + "…";
    return s;
  } catch {
    return u.length > 48 ? u.slice(0, 46) + "…" : u;
  }
}
