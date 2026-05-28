import { icon } from "./icons.js";

export function openModal({ title, content, onClose, footer, size = "md" }) {
  const root = document.getElementById("modal-root");
  root.innerHTML = "";
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  const modal = document.createElement("div");
  modal.className = "modal";
  if (size === "lg") modal.style.maxWidth = "720px";
  if (size === "sm") modal.style.maxWidth = "420px";

  if (title) {
    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;";
    const h = document.createElement("h3");
    h.textContent = title;
    h.style.margin = "0";
    head.appendChild(h);

    const close = document.createElement("button");
    close.className = "subtle icon small";
    close.appendChild(icon("x", { size: 14 }));
    close.addEventListener("click", () => closeModal(onClose));
    head.appendChild(close);
    modal.appendChild(head);
  }

  if (typeof content === "string") {
    const div = document.createElement("div");
    div.innerHTML = content;
    modal.appendChild(div);
  } else if (content instanceof Node) {
    modal.appendChild(content);
  }

  if (footer) {
    const f = document.createElement("div");
    f.className = "row";
    f.style.marginTop = "20px";
    f.style.justifyContent = "flex-end";
    f.style.gap = "8px";
    if (footer instanceof Node) f.appendChild(footer);
    else f.innerHTML = footer;
    modal.appendChild(f);
  }

  backdrop.appendChild(modal);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(onClose); });
  root.appendChild(backdrop);

  const onKey = (e) => { if (e.key === "Escape") closeModal(onClose); };
  document.addEventListener("keydown", onKey);
  modal._onKey = onKey;

  return { close: () => closeModal(onClose), root: modal };
}

export function closeModal(cb) {
  const root = document.getElementById("modal-root");
  const modal = root.querySelector(".modal");
  if (modal && modal._onKey) document.removeEventListener("keydown", modal._onKey);
  root.innerHTML = "";
  if (cb) cb();
}
