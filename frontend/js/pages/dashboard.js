import { api, auth } from "../api.js";
import { el, fmtRelative, avatar, tableSkeleton, emptyState } from "../components/dom.js";
import { icon } from "../components/icons.js";

const CONTOURS = [["", "Все"], ["internal", "Наши"], ["client", "Клиентские"]];

export async function renderDashboard(host) {
  const user = auth.getUser();
  const state = { kind: "", client_id: "" };  // kind: "" все / internal наши / client клиентские

  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, `Привет, ${(user?.full_name || user?.email || "").split(" ")[0] || ""} 👋`),
      el("div", { class: "page-subtitle" }, "Что нового по размещениям и задачам сегодня"),
    ),
  ));

  // Contour toggle + (in the client contour) a specific-client picker, so
  // several clients can be read one at a time instead of lumped together.
  const seg = el("div", { class: "segmented" });
  const clientSel = document.createElement("select");
  clientSel.style.cssText = "width:auto;min-width:190px;";
  clientSel.addEventListener("change", () => { state.client_id = clientSel.value; paint(); });
  const clientWrap = el("div", { style: { display: "none" } }, clientSel);
  const controls = el("div", { class: "row", style: { gap: "10px", alignItems: "center", flexWrap: "wrap", marginBottom: "6px" } }, seg, clientWrap);
  const splitHint = el("div", { class: "muted", style: { fontSize: "11.5px", marginBottom: "16px" } });
  host.appendChild(controls);
  host.appendChild(splitHint);

  const board = el("div", {});
  host.appendChild(board);

  // Client list for the picker (few rows, loaded once).
  let clients = [];
  try { clients = await api.clients(); } catch { /* ignore */ }
  clients.sort((a, b) => (a.name || "").localeCompare(b.name || "", "ru"));

  function rebuildClientSel() {
    clientWrap.style.display = state.kind === "client" ? "" : "none";
    clientSel.innerHTML = "";
    const all = document.createElement("option");
    all.value = ""; all.textContent = "Все клиенты";
    clientSel.appendChild(all);
    clients.forEach(c => {
      const o = document.createElement("option");
      o.value = String(c.id); o.textContent = c.name || `Клиент #${c.id}`;
      if (String(state.client_id) === String(c.id)) o.selected = true;
      clientSel.appendChild(o);
    });
  }

  function rebuildSeg() {
    seg.innerHTML = "";
    CONTOURS.forEach(([val, label]) => {
      seg.appendChild(el("button", {
        class: `seg ${state.kind === val ? "active" : ""}`,
        onClick: () => {
          if (state.kind === val) return;
          state.kind = val;
          if (val !== "client") state.client_id = "";  // client filter only lives in the client contour
          rebuildSeg(); rebuildClientSel(); paint();
        },
      }, label));
    });
  }

  // Jump straight to one client from the «По клиентам» panel.
  function pickClient(id) {
    state.kind = "client"; state.client_id = String(id);
    rebuildSeg(); rebuildClientSel(); paint();
  }

  rebuildSeg();
  rebuildClientSel();

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
    try { s = await api.stats(state.kind, state.client_id); }
    catch (e) {
      board.innerHTML = "";
      board.appendChild(emptyState({ iconName: "alert", title: "Не удалось загрузить данные", desc: e.message }));
      return;
    }

    // Caption: scoped to a single client, or the наши/клиентские split. Either
    // way the donor base and stop-list stay a shared resource (not per-contour).
    const selName = state.client_id
      ? (clients.find(c => String(c.id) === String(state.client_id))?.name || `Клиент #${state.client_id}`)
      : "";
    splitHint.textContent = selName
      ? `Клиент: ${selName} · размещений ${s.placements_total} · доноры и стоп-лист — общий ресурс`
      : `Размещений всего: наши ${s.placements_internal} · клиентские ${s.placements_client}`
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
      s.by_client.forEach(c => clientPanel.body.appendChild(clientRow(c, maxC, pickClient, state.client_id)));
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

function clientRow(c, max, onPick, selectedId) {
  const pct = Math.round((c.count / max) * 100);
  const active = String(selectedId) === String(c.client_id);
  const name = el("button", {
    title: "Показать сводку по этому клиенту",
    onClick: onPick ? () => onPick(c.client_id) : undefined,
    style: {
      flex: 1, minWidth: 0, textAlign: "left", background: "none", border: "none", padding: 0,
      cursor: onPick ? "pointer" : "default", fontSize: "13.5px", fontWeight: active ? 700 : 500,
      color: active ? "var(--accent)" : "var(--text-1)",
      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
    },
  }, c.name);
  return el("div", { style: { padding: "9px 0", borderBottom: "1px solid var(--border)" } },
    el("div", { class: "row", style: { gap: "10px", marginBottom: "6px", alignItems: "center" } },
      name,
      el("a", { href: `#/clients/${c.client_id}`, class: "mono tabular", title: "Открыть карточку клиента",
        style: { fontSize: "13px", color: "var(--text-2)" } }, String(c.count)),
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
