import { api } from "../api.js";
import { el, fmtRelative, fmtDate, emptyState, tableSkeleton, pill } from "../components/dom.js";
import { icon } from "../components/icons.js";
import { toast } from "../components/toast.js";

const SEV_VARIANT = { error: "error", warning: "warning", info: "info" };

export async function renderNotifications(host) {
  host.appendChild(el("div", { class: "page-header" },
    el("div", {},
      el("div", { class: "page-title" }, "Уведомления"),
      el("div", { class: "page-subtitle" }, "Проблемы с размещениями требуют внимания"),
    ),
    el("div", { class: "page-actions" },
      el("button", { class: "ghost", onClick: async () => {
        try { await api.markAllNotificationsRead(); toast("Все прочитаны", "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      } }, icon("check", { size: 14 }), el("span", {}, "Прочитать все")),
    ),
  ));

  const wrap = el("div", {});
  host.appendChild(wrap);

  async function load() {
    wrap.innerHTML = "";
    wrap.appendChild(tableSkeleton(4, 1));
    let data;
    try { data = await api.notificationsList({ limit: 100 }); }
    catch (e) { wrap.innerHTML = ""; wrap.appendChild(emptyState({ iconName: "alert", title: "Ошибка", desc: e.message })); return; }
    wrap.innerHTML = "";
    if (!data.items.length) {
      wrap.appendChild(emptyState({ iconName: "check", title: "Уведомлений нет", desc: "Здесь появятся оповещения, когда с размещениями что-то не так." }));
      return;
    }
    data.items.forEach(n => wrap.appendChild(card(n, load)));
  }

  function card(n, reload) {
    const row = el("div", {
      style: {
        display: "flex", gap: "12px", alignItems: "flex-start", padding: "12px 14px",
        border: "1px solid var(--border)", borderRadius: "10px", marginBottom: "8px",
        background: n.is_read ? "transparent" : "var(--surface)",
        opacity: n.is_read ? 0.7 : 1,
      },
    });
    const dot = el("span", { style: {
      width: "8px", height: "8px", borderRadius: "50%", marginTop: "6px", flex: "0 0 auto",
      background: n.is_read ? "var(--border)" : (n.severity === "error" ? "var(--error)" : n.severity === "warning" ? "var(--warning)" : "var(--accent)"),
    } });
    const main = el("div", { style: { flex: 1, minWidth: 0 } },
      el("div", { class: "row", style: { gap: "8px", alignItems: "center", flexWrap: "wrap" } },
        el("div", { style: { fontWeight: 500, fontSize: "13.5px" } }, n.title),
        pill(n.severity === "error" ? "критично" : n.severity === "warning" ? "внимание" : "инфо", SEV_VARIANT[n.severity] || "muted"),
      ),
      n.body && el("div", { class: "muted", style: { fontSize: "12.5px", marginTop: "3px" } }, n.body),
      el("div", { class: "dimmed", style: { fontSize: "11.5px", marginTop: "4px" }, title: fmtDate(n.created_at) }, fmtRelative(n.created_at)),
    );
    const actions = el("div", { class: "row", style: { gap: "6px", flex: "0 0 auto" } });
    if (n.entity_type === "placement") {
      actions.appendChild(el("button", { class: "subtle icon small", title: "К контролю ссылок",
        onClick: () => { location.hash = "#/link-monitor"; } }, icon("external", { size: 14 })));
    }
    if (!n.is_read) {
      actions.appendChild(el("button", { class: "subtle icon small", title: "Прочитано",
        onClick: async () => { try { await api.markNotificationRead(n.id); reload(); } catch (e) { toast(e.message, "error"); } } }, icon("check", { size: 14 })));
    }
    row.appendChild(dot); row.appendChild(main); row.appendChild(actions);
    return row;
  }

  await load();
}
