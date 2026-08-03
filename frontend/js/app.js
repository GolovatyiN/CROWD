import { auth, api } from "./api.js";
import { toast } from "./components/toast.js";
import { el, clear, avatar, initials } from "./components/dom.js";
import { icon } from "./components/icons.js";
import { setupPalette } from "./components/palette.js";

import { renderLogin } from "./pages/login.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderDonors } from "./pages/donors.js";
import { renderPlans } from "./pages/anchor_plans.js";
import { renderPlanDetails } from "./pages/plan_details.js";
import { renderMyTasks } from "./pages/my_tasks.js";
import { renderStopList } from "./pages/stop_list.js";
import { renderUsers } from "./pages/users.js";
import { renderImportExport } from "./pages/import_export.js";
import { renderAudit } from "./pages/audit.js";
import { renderEmailAccounts } from "./pages/email_accounts.js";
import { renderClients, renderClientDetail } from "./pages/clients.js";
import { renderClientDashboard, renderClientProject } from "./pages/client_cabinet.js";

// roles: who can SEE each nav item. user / admin / super_admin.
const NAV = [
  { hash: "#/dashboard", title: "Сводка", icon: "dashboard", roles: ["admin", "super_admin"], group: "main" },
  { hash: "#/my-tasks", title: "Мои задачи", icon: "tasks", roles: ["user", "admin", "super_admin"], group: "main" },
  { hash: "#/plans", title: "Анкор-планы", icon: "plans", roles: ["admin", "super_admin"], group: "data" },
  { hash: "#/donors", title: "Доноры", icon: "donors", roles: ["admin", "super_admin"], group: "data" },
  { hash: "#/clients", title: "Клиенты", icon: "users", roles: ["admin", "super_admin"], group: "data" },
  { hash: "#/stop-list", title: "Стоп-лист", icon: "stop", roles: ["user", "admin", "super_admin"], group: "data" },
  { hash: "#/email-accounts", title: "Аккаунты", icon: "user", roles: ["user", "admin", "super_admin"], group: "data" },
  { hash: "#/import-export", title: "Импорт / экспорт", icon: "swap", roles: ["admin", "super_admin"], group: "admin" },
  { hash: "#/users", title: "Сотрудники", icon: "users", roles: ["super_admin"], group: "admin" },
  { hash: "#/audit", title: "Журнал действий", icon: "file", roles: ["super_admin"], group: "admin" },
  // Client cabinet — only role 'client' sees this (and nothing else).
  { hash: "#/client/projects", title: "Мои проекты", icon: "plans", roles: ["client"], group: "client" },
];

const GROUP_LABELS = { main: "Работа", data: "Данные", admin: "Администрирование", client: "Кабинет" };

function canSee(item, user) {
  return item.roles.includes(user.role);
}

const ROUTES = [
  { pattern: /^#\/login$/, render: renderLogin, public: true, roles: null },
  { pattern: /^#\/dashboard$/, render: renderDashboard, roles: ["admin", "super_admin"] },
  { pattern: /^#\/donors$/, render: renderDonors, roles: ["admin", "super_admin"] },
  { pattern: /^#\/plans$/, render: renderPlans, roles: ["admin", "super_admin"] },
  { pattern: /^#\/plans\/(\d+)$/, render: (host, m) => renderPlanDetails(host, parseInt(m[1])), roles: ["admin", "super_admin"] },
  { pattern: /^#\/clients$/, render: renderClients, roles: ["admin", "super_admin"] },
  { pattern: /^#\/clients\/(\d+)$/, render: (host, m) => renderClientDetail(host, parseInt(m[1])), roles: ["admin", "super_admin"] },
  { pattern: /^#\/client\/projects$/, render: renderClientDashboard, roles: ["client"] },
  { pattern: /^#\/client\/projects\/(\d+)$/, render: (host, m) => renderClientProject(host, parseInt(m[1])), roles: ["client"] },
  { pattern: /^#\/my-tasks$/, render: renderMyTasks, roles: ["user", "admin", "super_admin"] },
  { pattern: /^#\/stop-list$/, render: renderStopList, roles: ["user", "admin", "super_admin"] },
  { pattern: /^#\/email-accounts$/, render: renderEmailAccounts, roles: ["user", "admin", "super_admin"] },
  { pattern: /^#\/users$/, render: renderUsers, roles: ["super_admin"] },
  { pattern: /^#\/audit$/, render: renderAudit, roles: ["super_admin"] },
  { pattern: /^#\/import-export$/, render: renderImportExport, roles: ["admin", "super_admin"] },
];

const COLLAPSE_KEY = "crowd_sidebar_collapsed";

function buildSidebar(user) {
  const collapsed = localStorage.getItem(COLLAPSE_KEY) === "1";
  const roleLabel = user.role === "super_admin" ? "Super Admin"
    : user.role === "admin" ? "Админ"
    : "Сотрудник";

  const headerBrand = el("div", { class: "brand" },
    el("div", { class: "brand-logo" }, "C"),
    el("div", { class: "brand-text" }, "Crowd"),
  );
  const collapseBtn = el("button", {
    class: "collapse-btn", title: collapsed ? "Развернуть" : "Свернуть",
    onClick: () => {
      const isCollapsed = document.querySelector(".layout").classList.toggle("collapsed");
      localStorage.setItem(COLLAPSE_KEY, isCollapsed ? "1" : "0");
    }
  }, icon("sidebar", { size: 16 }));

  const navEl = el("nav", { class: "nav" });
  const groups = {};
  NAV.filter(n => canSee(n, user)).forEach(n => {
    (groups[n.group] = groups[n.group] || []).push(n);
  });
  Object.entries(groups).forEach(([groupKey, items]) => {
    navEl.appendChild(el("div", { class: "nav-section" }, GROUP_LABELS[groupKey] || ""));
    items.forEach(n => {
      const a = el("a", {
        href: n.hash,
        class: location.hash === n.hash || location.hash.startsWith(n.hash + "/") ? "active" : "",
        title: n.title,
      }, icon(n.icon, { size: 17 }), el("span", {}, n.title));
      navEl.appendChild(a);
    });
  });

  const userBlock = el("div", { class: "user-block", title: user.email },
    avatar(user.full_name || user.email, 30),
    el("div", { style: { flex: 1, minWidth: 0 } },
      el("div", { class: "name" }, user.full_name || user.email),
      el("div", { class: "role" }, roleLabel),
    ),
    el("button", {
      class: "logout-btn", title: "Выйти",
      onClick: (e) => { e.preventDefault(); auth.clearToken(); location.hash = "#/login"; }
    }, icon("logout", { size: 14 })),
  );

  const sidebar = el("aside", { class: "sidebar" },
    el("div", { class: "sidebar-header" }, headerBrand, collapseBtn),
    navEl,
    el("div", { class: "sidebar-bottom" }, userBlock),
  );

  return { sidebar, collapsed };
}

function renderShell() {
  const user = auth.getUser();
  const app = document.getElementById("app");
  clear(app);

  if (!user) {
    const wrap = el("div", { id: "page" });
    app.appendChild(wrap);
    return wrap;
  }

  const { sidebar, collapsed } = buildSidebar(user);
  const main = el("main", { class: "main", id: "page" });

  // Mobile top bar
  const mobileBar = el("div", { class: "mobile-bar" },
    el("button", { class: "hamburger", onClick: () => {
      document.querySelector(".layout").classList.toggle("open");
      document.querySelector(".mobile-overlay").classList.toggle("show");
    }}, icon("menu", { size: 18 })),
    el("div", { class: "brand" },
      el("div", { class: "brand-logo", style: { width: "24px", height: "24px", fontSize: "12px", background: "var(--accent)", color: "#fff" } }, "C"),
      el("div", {}, "Crowd"),
    ),
    el("div", { class: "spacer" }),
    el("button", { class: "subtle icon small", title: "Поиск (⌘K)", onClick: () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, ctrlKey: true }));
    }}, icon("search", { size: 16 })),
  );

  const overlay = el("div", { class: "mobile-overlay", onClick: () => {
    document.querySelector(".layout").classList.remove("open");
    document.querySelector(".mobile-overlay").classList.remove("show");
  }});

  main.insertBefore(mobileBar, main.firstChild);
  const layout = el("div", { class: `layout ${collapsed ? "collapsed" : ""}` }, sidebar, main);
  app.appendChild(layout);
  app.appendChild(overlay);
  return main;
}

async function route() {
  if (!location.hash || location.hash === "#" || location.hash === "#/") {
    location.hash = auth.getToken() ? "#/dashboard" : "#/login";
    return;
  }
  const isPublic = location.hash === "#/login";
  if (!isPublic && !auth.getToken()) {
    location.hash = "#/login";
    return;
  }
  if (auth.getToken() && !auth.getUser()) {
    try { const me = await api.me(); auth.setUser(me); }
    catch (e) { auth.clearToken(); location.hash = "#/login"; return; }
  }

  const host = renderShell();
  const me = auth.getUser();
  // A 'user' landing on / should go straight to My Tasks (their main view).
  if (me && me.role === "user" && (location.hash === "#/dashboard" || location.hash === "#/")) {
    location.hash = "#/my-tasks";
    return;
  }
  // A client lands in their cabinet, never on internal pages.
  if (me && me.role === "client" && (location.hash === "#/dashboard" || location.hash === "#/" || location.hash === "#/my-tasks")) {
    location.hash = "#/client/projects";
    return;
  }
  let matched = false;
  for (const r of ROUTES) {
    const m = location.hash.match(r.pattern);
    if (m) {
      if (r.roles && me && !r.roles.includes(me.role)) {
        host.appendChild(el("div", { class: "empty" },
          el("div", { class: "icon-circle" }, icon("alert", { size: 22 })),
          el("div", { class: "title" }, "Доступ ограничен"),
          el("div", { class: "desc" }, "Этот раздел недоступен для вашей роли."),
        ));
        matched = true;
        break;
      }
      try {
        await r.render(host, m);
      } catch (e) {
        console.error(e);
        toast(e.message || "Ошибка отображения", "error");
      }
      matched = true;
      break;
    }
  }
  if (!matched) {
    host.appendChild(el("div", { class: "empty" },
      el("div", { class: "icon-circle" }, icon("alert", { size: 22 })),
      el("div", { class: "title" }, "Страница не найдена"),
    ));
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => {
  setupPalette();
  route();
});
