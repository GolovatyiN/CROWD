// Minimal icon set (heroicons outline, hand-picked).
// Use: icon("plus", { size: 16 }) → returns SVG element.

const PATHS = {
  dashboard: `<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>`,
  donors: `<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/>`,
  plans: `<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 15h4"/>`,
  tasks: `<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>`,
  stop: `<path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z"/><path d="M9 12h6"/>`,
  swap: `<path d="M7 16V4M3 8l4-4 4 4"/><path d="M17 8v12M13 16l4 4 4-4"/>`,
  users: `<circle cx="9" cy="8" r="4"/><path d="M2 21c0-3.9 3.1-7 7-7s7 3.1 7 7"/><circle cx="17" cy="7" r="3"/><path d="M22 19c0-2.8-2.2-5-5-5"/>`,
  logout: `<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>`,
  menu: `<path d="M4 7h16M4 12h16M4 17h16"/>`,
  sidebar: `<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>`,
  search: `<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>`,
  filter: `<path d="M3 5h18l-7 9v6l-4-2v-4z"/>`,
  plus: `<path d="M12 5v14M5 12h14"/>`,
  pencil: `<path d="M17 3l4 4-12 12H5v-4z"/>`,
  trash: `<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/>`,
  check: `<path d="M5 12l5 5L20 7"/>`,
  x: `<path d="M6 6l12 12M18 6L6 18"/>`,
  alert: `<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.8L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z"/>`,
  info: `<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>`,
  external: `<path d="M14 3h7v7"/><path d="M21 3l-9 9"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>`,
  chevronDown: `<path d="M6 9l6 6 6-6"/>`,
  chevronLeft: `<path d="M15 18l-6-6 6-6"/>`,
  dots: `<circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/>`,
  arrowUp: `<path d="M12 19V5M5 12l7-7 7 7"/>`,
  arrowDown: `<path d="M12 5v14M5 12l7 7 7-7"/>`,
  arrowRight: `<path d="M5 12h14M13 5l7 7-7 7"/>`,
  copy: `<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>`,
  eye: `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>`,
  eyeOff: `<path d="M17.94 17.94A10.3 10.3 0 0 1 12 20c-7 0-11-8-11-8a18.5 18.5 0 0 1 5.1-5.9"/><path d="M9.9 4.2A11 11 0 0 1 12 4c7 0 11 8 11 8a18.6 18.6 0 0 1-2.2 3.1"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2"/><path d="M1 1l22 22"/>`,
  upload: `<path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 21h14a2 2 0 0 0 2-2v-4"/>`,
  download: `<path d="M12 21V9M7 16l5 5 5-5"/><path d="M5 3h14a2 2 0 0 1 2 2v4"/>`,
  file: `<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>`,
  link: `<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.5-1.5"/>`,
  clock: `<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>`,
  zap: `<path d="M13 2L3 14h7l-2 8 10-12h-7z"/>`,
  database: `<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/>`,
  target: `<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>`,
  user: `<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>`,
  more: `<circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/>`,
  refresh: `<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.5 9a9 9 0 0 1 14.8-3.4L23 10"/><path d="M20.5 15a9 9 0 0 1-14.8 3.4L1 14"/>`,
};

export function icon(name, { size = 16, stroke = 1.7, className = "" } = {}) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", stroke);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  if (className) svg.setAttribute("class", className);
  svg.innerHTML = PATHS[name] || "";
  return svg;
}

export function iconHTML(name, opts = {}) {
  const size = opts.size || 16;
  const stroke = opts.stroke || 1.7;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || ""}</svg>`;
}
