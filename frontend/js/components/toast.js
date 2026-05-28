import { iconHTML } from "./icons.js";

const ICONS = {
  success: "check",
  error: "alert",
  warning: "alert",
  info: "info",
};

export function toast(message, type = "") {
  const root = document.getElementById("toast-root");
  if (!root) return;
  const el = document.createElement("div");
  el.className = "toast " + (type || "");
  const iconName = ICONS[type];
  el.innerHTML = (iconName ? iconHTML(iconName, { size: 16 }) : "") + `<span>${escapeHtml(message)}</span>`;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    el.style.transition = "opacity .25s, transform .25s";
    setTimeout(() => el.remove(), 250);
  }, 3200);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
