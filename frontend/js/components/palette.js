import { api, auth } from "../api.js";
import { el, clear } from "./dom.js";
import { icon } from "./icons.js";

const STATIC_ITEMS = [
  { type: "page", title: "Сводка", hash: "#/dashboard", icon: "dashboard" },
  { type: "page", title: "Мои задачи", hash: "#/my-tasks", icon: "tasks" },
  { type: "page", title: "Анкор-планы", hash: "#/plans", icon: "plans" },
  { type: "page", title: "Доноры", hash: "#/donors", icon: "donors" },
  { type: "page", title: "Стоп-лист", hash: "#/stop-list", icon: "stop" },
  { type: "page", title: "Импорт / экспорт", hash: "#/import-export", icon: "swap", adminOnly: true },
  { type: "page", title: "Сотрудники", hash: "#/users", icon: "users", adminOnly: true },
];

let opened = false;

export function setupPalette() {
  document.addEventListener("keydown", (e) => {
    const isMac = navigator.platform.toLowerCase().includes("mac");
    const meta = isMac ? e.metaKey : e.ctrlKey;
    if (meta && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      open();
    } else if (e.key === "Escape" && opened) {
      e.preventDefault(); close();
    }
  });
}

function close() {
  const backdrop = document.getElementById("palette-root");
  if (backdrop) backdrop.remove();
  opened = false;
}

function open() {
  if (opened) return;
  opened = true;
  const isAdmin = auth.isAdmin();
  const pages = STATIC_ITEMS.filter(p => !p.adminOnly || isAdmin);

  const backdrop = el("div", { id: "palette-root", class: "palette-backdrop", onClick: (e) => {
    if (e.target.id === "palette-root") close();
  }});
  const palette = el("div", { class: "palette" });
  const input = el("input", { type: "search", placeholder: "Поиск страниц, доноров, планов…", autocomplete: "off" });
  palette.appendChild(el("div", { class: "palette-input" }, icon("search", { size: 16 }), input));
  const results = el("div", { class: "palette-results" });
  palette.appendChild(results);
  palette.appendChild(el("div", { class: "palette-hint" },
    el("span", {}, el("span", { class: "kbd" }, "↑↓"), " навигация · ", el("span", { class: "kbd" }, "↵"), " открыть"),
    el("span", {}, el("span", { class: "kbd" }, "Esc"), " закрыть"),
  ));
  backdrop.appendChild(palette);
  document.body.appendChild(backdrop);
  input.focus();

  let activeIdx = 0;
  let currentItems = [];

  async function render(q) {
    clear(results);
    currentItems = [];

    // pages
    const matchingPages = q
      ? pages.filter(p => p.title.toLowerCase().includes(q.toLowerCase()))
      : pages;
    if (matchingPages.length) {
      results.appendChild(el("div", { class: "palette-section-title" }, "Страницы"));
      matchingPages.forEach(p => {
        const node = pageItem(p);
        results.appendChild(node);
        currentItems.push({ node, action: () => { close(); location.hash = p.hash; } });
      });
    }

    // donors search (if query is non-empty)
    if (q && q.length >= 2) {
      try {
        const dataD = await api.donors({ q, limit: 6, sort: "tr", order: "desc" });
        if (dataD.items && dataD.items.length) {
          results.appendChild(el("div", { class: "palette-section-title" }, "Доноры"));
          dataD.items.forEach(d => {
            const node = donorItem(d);
            results.appendChild(node);
            currentItems.push({ node, action: () => { close(); location.hash = "#/donors"; } });
          });
        }
      } catch {}
      // plans
      try {
        const plans = await api.plans();
        const matches = plans.filter(p => p.plan_name.toLowerCase().includes(q.toLowerCase())).slice(0, 6);
        if (matches.length) {
          results.appendChild(el("div", { class: "palette-section-title" }, "Анкор-планы"));
          matches.forEach(p => {
            const node = planItem(p);
            results.appendChild(node);
            currentItems.push({ node, action: () => { close(); location.hash = `#/plans/${p.id}`; } });
          });
        }
      } catch {}
    }

    if (!currentItems.length) {
      results.appendChild(el("div", { class: "palette-empty" }, q ? "Ничего не найдено" : "Введите запрос или выберите страницу"));
    }
    activeIdx = 0;
    refreshActive();
  }

  function refreshActive() {
    currentItems.forEach((it, i) => it.node.classList.toggle("active", i === activeIdx));
    if (currentItems[activeIdx]) {
      currentItems[activeIdx].node.scrollIntoView({ block: "nearest" });
    }
  }

  let timer;
  input.addEventListener("input", (e) => {
    clearTimeout(timer);
    const v = e.target.value;
    timer = setTimeout(() => render(v), 180);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(currentItems.length - 1, activeIdx + 1);
      refreshActive();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(0, activeIdx - 1);
      refreshActive();
    } else if (e.key === "Enter") {
      e.preventDefault();
      currentItems[activeIdx] && currentItems[activeIdx].action();
    }
  });

  render("");
}

function pageItem(p) {
  return el("div", { class: "palette-item" },
    icon(p.icon, { size: 15 }),
    el("span", {}, p.title),
    el("span", { class: "palette-meta" }, "Страница"),
  );
}
function donorItem(d) {
  return el("div", { class: "palette-item" },
    icon("donors", { size: 15 }),
    el("span", { class: "mono" }, d.domain || d.donor_url),
    el("span", { class: "palette-meta" }, `DR ${d.tr || 0}`),
  );
}
function planItem(p) {
  return el("div", { class: "palette-item" },
    icon("plans", { size: 15 }),
    el("span", {}, p.plan_name),
    el("span", { class: "palette-meta" }, `${p.total_rows} строк`),
  );
}
