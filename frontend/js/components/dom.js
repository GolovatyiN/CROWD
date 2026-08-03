// Tiny DOM helpers + UI components used across pages.

import { icon } from "./icons.js";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => {
    if (v == null || v === false) return;
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  });
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export const STATUS_LABELS = {
  new: "Новая",
  donor_selected: "Донор подобран",
  assigned: "Назначена",
  in_progress: "В работе",
  placed: "Размещено",
  done: "Готово",
  rejected: "Отклонено",
  problem: "Проблема",
  inactive: "Неактивен",
  active: "Активен",
};

const STATUS_CLASS = {
  new: "muted",
  donor_selected: "info",
  assigned: "info",
  in_progress: "warning",
  placed: "success",
  done: "success",
  rejected: "error",
  problem: "error",
  inactive: "error",
  active: "success",
};

export const ROLE_LABELS = {
  super_admin: "Super Admin",
  admin: "Админ",
  user: "Сотрудник",
  employee: "Сотрудник", // legacy fallback for any rows that escape the migration
};

export function statusPill(status) {
  return el("span", { class: `pill ${STATUS_CLASS[status] || ""}` }, STATUS_LABELS[status] || status || "—");
}

export function pill(text, variant = "") {
  return el("span", { class: `pill ${variant}` }, text);
}

// Тип размещения: «Наши» (internal) / «Клиентские» (client). Единый бейдж —
// используется в списках планов, задачах, размещениях и т.д.
export function kindBadge(kind) {
  const isClient = kind === "client";
  return el("span", {
    class: `pill ${isClient ? "violet" : "muted"}`,
    title: isClient ? "Клиентское размещение" : "Внутреннее (наше) размещение",
  }, isClient ? "Клиентские" : "Наши");
}

// The backend stores timestamps as naive UTC and serialises them WITHOUT a
// timezone marker (e.g. "2026-06-03T17:55:00"). A timezone-less datetime string
// is parsed by JS as *local* time, which made every time render ~UTC (3h behind
// Moscow). Treat any tz-less string as UTC so the browser converts it to the
// user's local time correctly. Strings that already carry Z/+hh:mm are kept.
function parseServerDate(s) {
  if (s instanceof Date) return s;
  if (typeof s === "string") {
    const str = s.trim();
    const hasTz = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(str);
    const isDateTime = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(str);
    if (isDateTime && !hasTz) return new Date(str.replace(" ", "T") + "Z");
  }
  return new Date(s);
}

export function fmtDate(s) {
  if (!s) return "—";
  try { return parseServerDate(s).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
  catch { return s; }
}

export function fmtRelative(s) {
  if (!s) return "—";
  const now = new Date();
  const then = parseServerDate(s);
  const diff = (now - then) / 1000;
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} дн назад`;
  return then.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

export function initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map(p => p[0] || "").join("").toUpperCase() || "?";
}

export function avatar(name, size = 28) {
  const node = el("div", { class: "avatar", style: { width: `${size}px`, height: `${size}px`, fontSize: `${Math.max(10, size * 0.42)}px` } }, initials(name));
  return node;
}

// ----- Empty state -----
export function emptyState({ iconName = "info", title, desc, action } = {}) {
  const wrap = el("div", { class: "empty" },
    el("div", { class: "icon-circle" }, icon(iconName, { size: 22 })),
    title && el("div", { class: "title" }, title),
    desc && el("div", { class: "desc" }, desc),
    action,
  );
  return wrap;
}

// ----- Loading skeleton (table rows) -----
export function tableSkeleton(rows = 5, cols = 4) {
  const wrap = el("div", {});
  for (let r = 0; r < rows; r++) {
    const row = el("div", { class: "skeleton-block" });
    for (let c = 0; c < cols; c++) {
      const w = 30 + Math.floor(Math.random() * 60);
      row.appendChild(el("div", { class: "skeleton skeleton-row", style: { width: `${w}%` } }));
    }
    wrap.appendChild(row);
  }
  return wrap;
}

// ----- Dropdown menu -----
let openMenu = null;
function closeOpenMenu() {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
    document.removeEventListener("mousedown", onDocClick, true);
    window.removeEventListener("scroll", closeOpenMenu, true);
    window.removeEventListener("resize", closeOpenMenu, true);
  }
}
function onDocClick(e) {
  if (openMenu && !openMenu.contains(e.target)) closeOpenMenu();
}

export function menuButton(items, opts = {}) {
  const btn = el("button", {
    class: "ghost icon small",
    title: "Действия",
    onClick: (e) => {
      e.stopPropagation();
      if (openMenu) { closeOpenMenu(); return; }
      const menu = el("div", { class: "menu" });
      items.filter(Boolean).forEach(item => {
        if (item.separator) { menu.appendChild(el("div", { class: "menu-separator" })); return; }
        const mi = el("div", { class: `menu-item ${item.danger ? "danger" : ""}`, onClick: () => {
          closeOpenMenu();
          item.onClick && item.onClick();
        }},
          item.icon ? icon(item.icon, { size: 14 }) : null,
          el("span", {}, item.label),
        );
        menu.appendChild(mi);
      });
      document.body.appendChild(menu);
      const rect = btn.getBoundingClientRect();
      menu.style.position = "fixed";
      menu.style.top = `${rect.bottom + 4}px`;
      const right = window.innerWidth - rect.right;
      menu.style.right = `${right}px`;
      openMenu = menu;
      setTimeout(() => {
        document.addEventListener("mousedown", onDocClick, true);
        window.addEventListener("scroll", closeOpenMenu, true);
        window.addEventListener("resize", closeOpenMenu, true);
      }, 0);
    }
  }, icon("more", { size: 15 }));
  return btn;
}

// ----- Copy to clipboard -----
export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function copyButton(text, onCopied) {
  return el("button", {
    class: "copy-btn", type: "button", title: "Скопировать",
    onClick: async (e) => {
      e.preventDefault(); e.stopPropagation();
      const ok = await copy(text);
      if (ok && onCopied) onCopied();
    }
  }, icon("copy", { size: 13 }));
}

// ----- Search input with leading icon -----
export function searchInput({ placeholder = "Поиск…", value = "", onInput, onEnter } = {}) {
  const wrap = el("div", { class: "input-wrap", style: { flex: "1", minWidth: "180px" } });
  wrap.appendChild(icon("search", { size: 14 }));
  const input = el("input", { type: "search", placeholder, value,
    onInput: (e) => onInput && onInput(e.target.value),
    onKeydown: (e) => { if (e.key === "Enter" && onEnter) onEnter(e.target.value); },
  });
  wrap.appendChild(input);
  return wrap;
}

// ----- Section header (for panels) -----
export function panelHeader(title, ...actions) {
  return el("div", { class: "panel-header" },
    el("div", { class: "panel-title" }, title),
    el("div", { class: "panel-actions" }, ...actions),
  );
}

// ----- Async button with built-in loading state -----
// Wraps any async click handler: disables the button, swaps its label for a
// spinner while the promise is in flight, then restores it. The handler keeps
// full ownership of its own success/error toasts — this only manages the
// busy UI so the user always sees that something is happening.
export function busyClick(btn, asyncFn) {
  btn.addEventListener("click", async (e) => {
    if (btn.disabled) return;
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.innerHTML = "";
    btn.appendChild(el("span", { class: "spinner", style: {
      width: "13px", height: "13px", borderWidth: "2px", borderTopColor: "currentColor",
    }}));
    try {
      await asyncFn(e);
    } finally {
      // The handler may have removed the button from the DOM (e.g. closed a
      // modal) — restoring innerHTML on a detached node is harmless.
      btn.disabled = false;
      btn.innerHTML = original;
    }
  });
  return btn;
}

// Convenience: build a primary action button that auto-shows loading.
export function submitButton(label, asyncFn, { className = "", iconName } = {}) {
  const btn = el("button", { class: className, type: "button" },
    iconName ? icon(iconName, { size: 14 }) : null,
    el("span", {}, label));
  return busyClick(btn, asyncFn);
}

// ----- Sortable table header -----
export function sortHeader(label, key, state, reload, align = "") {
  const isActive = state.sort === key;
  const arrow = isActive
    ? icon(state.order === "desc" ? "arrowDown" : "arrowUp", { size: 11 })
    : null;
  return el("th", {
    class: align,
    style: { cursor: "pointer", userSelect: "none" },
    onClick: () => {
      if (state.sort === key) state.order = state.order === "desc" ? "asc" : "desc";
      else { state.sort = key; state.order = "desc"; }
      reload();
    },
  },
    el("span", {
      style: {
        display: "inline-flex", alignItems: "center", gap: "4px",
        color: isActive ? "var(--text-1)" : "inherit",
        fontWeight: isActive ? 600 : 500,
      },
    }, label, arrow),
  );
}

export { icon };
