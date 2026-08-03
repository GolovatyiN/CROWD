const TOKEN_KEY = "crowd_token";
const USER_KEY = "crowd_user";

export const auth = {
  getToken() { return localStorage.getItem(TOKEN_KEY); },
  setToken(t) { localStorage.setItem(TOKEN_KEY, t); },
  clearToken() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); },
  getUser() { try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; } },
  setUser(u) { localStorage.setItem(USER_KEY, JSON.stringify(u)); },
  role() { const u = this.getUser(); return u ? u.role : null; },
  isAdmin() { const r = this.role(); return r === "admin" || r === "super_admin"; },
  isSuperAdmin() { return this.role() === "super_admin"; },
  isUser() { return this.role() === "user"; },
};

async function request(path, opts = {}) {
  const headers = opts.headers ? { ...opts.headers } : {};
  if (!(opts.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  const token = auth.getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const body = opts.body instanceof FormData ? opts.body : (opts.body ? JSON.stringify(opts.body) : undefined);

  const res = await fetch(path, { method: opts.method || "GET", headers, body });
  // 401 from /auth/login means wrong credentials — let the normal error
  // handling below surface the server's detail message ("Неверный email или
  // пароль"). For everything else, a 401 means the session died: clear local
  // state and bounce to login.
  if (res.status === 401 && path !== "/auth/login") {
    auth.clearToken();
    if (location.hash !== "#/login") location.hash = "#/login";
    throw new Error("Сессия истекла");
  }
  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    let detail = res.statusText;
    if (ct.includes("application/json")) {
      try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
    } else {
      try { detail = await res.text(); } catch {}
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (opts.raw) return res;
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

// ---- tiny short-TTL GET cache ----
// Session-stable lookups (e.g. the employee list, used on several pages) are
// re-fetched on every navigation today. Caching them for a few seconds cuts
// redundant round-trips when hopping between tabs, without risking stale data
// — any mutation calls cacheInvalidate() to drop the relevant entries.
const _cache = new Map();
function cacheInvalidate(prefix) {
  for (const k of [..._cache.keys()]) if (k.startsWith(prefix)) _cache.delete(k);
}
async function cachedRequest(path, ttlMs) {
  const hit = _cache.get(path);
  if (hit && Date.now() - hit.at < ttlMs) return hit.data;
  const data = await request(path);
  _cache.set(path, { at: Date.now(), data });
  return data;
}

export const api = {
  // auth
  login: (email, password) => request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),

  // users — cached 30s (employee roster changes rarely; reused as a lookup
  // on plan details, accounts and the users page). Mutations invalidate it.
  users: (params = {}) => cachedRequest(`/users?${qs(params)}`, 30000),
  createUser: (data) => request("/users", { method: "POST", body: data }).then(r => { cacheInvalidate("/users"); return r; }),
  updateUser: (id, data) => request(`/users/${id}`, { method: "PATCH", body: data }).then(r => { cacheInvalidate("/users"); return r; }),
  deactivateUser: (id) => request(`/users/${id}`, { method: "DELETE" }).then(r => { cacheInvalidate("/users"); return r; }),

  // audit
  auditLogs: (params = {}) => request(`/audit-logs?${qs(params)}`),

  // email accounts (shared pool used to sign up on donors)
  emailAccounts: (params = {}) => request(`/email-accounts?${qs(params)}`),
  emailAccountEmployeeStats: () => request("/email-accounts/stats/by-employee"),
  emailAccountDonors: (id) => request(`/email-accounts/${id}/donors`),
  createEmailAccount: (data) => request("/email-accounts", { method: "POST", body: data }),
  updateEmailAccount: (id, data) => request(`/email-accounts/${id}`, { method: "PATCH", body: data }),
  deleteEmailAccount: (id) => request(`/email-accounts/${id}`, { method: "DELETE" }),

  // donors — paginated
  donors: (params = {}) => request(`/donors?${qs(params)}`),
  createDonor: (data) => request("/donors", { method: "POST", body: data }),
  updateDonor: (id, data) => request(`/donors/${id}`, { method: "PATCH", body: data }),
  deactivateDonor: (id) => request(`/donors/${id}`, { method: "DELETE" }),
  bulkDeactivateDonors: (ids) => request("/donors/bulk-deactivate", { method: "POST", body: { ids } }),
  bulkActivateDonors: (ids) => request("/donors/bulk-activate", { method: "POST", body: { ids } }),
  bulkDeleteDonors: (ids) => request("/donors/bulk-delete", { method: "POST", body: { ids } }),
  deleteAllDonors: () => request("/donors/bulk-delete", { method: "POST", body: { all: true } }),
  donorUsage: (id) => request(`/donors/${id}/usage`),
  donorStats: () => request(`/donors/stats`),
  donorAccounts: (id) => request(`/donors/${id}/accounts`),
  createDonorAccount: (id, data) => request(`/donors/${id}/accounts`, { method: "POST", body: { ...data, donor_id: id } }),
  updateDonorAccount: (donorId, accId, data) => request(`/donors/${donorId}/accounts/${accId}`, { method: "PATCH", body: data }),
  deleteDonorAccount: (donorId, accId) => request(`/donors/${donorId}/accounts/${accId}`, { method: "DELETE" }),
  importDonors: (file) => uploadFile("/donors/import", file),
  exportDonors: () => downloadFile("/donors/export", "donors.csv"),

  // plans
  plans: (params = {}) => request(`/anchor-plans?${qs(params)}`),
  plan: (id) => request(`/anchor-plans/${id}`),
  updatePlan: (id, data) => request(`/anchor-plans/${id}`, { method: "PATCH", body: data }),
  deletePlan: (id) => request(`/anchor-plans/${id}`, { method: "DELETE" }),
  planItems: (id, params = {}) => request(`/anchor-plans/${id}/items?${qs(params)}`),
  updateItem: (id, data) => request(`/anchor-plans/items/${id}`, { method: "PATCH", body: data }),
  importPlan: (file, planName, clientProjectId) => uploadFile("/anchor-plans/import", file, {
    plan_name: planName,
    ...(clientProjectId ? { client_project_id: clientProjectId } : {}),
  }),
  autoMatch: (id) => request(`/anchor-plans/${id}/auto-match`, { method: "POST" }),
  rematchAll: (id) => request(`/anchor-plans/${id}/rematch-all`, { method: "POST" }),
  reinferGeo: (id) => request(`/anchor-plans/${id}/reinfer-geo`, { method: "POST" }),
  matchOne: (itemId) => request(`/anchor-plans/items/${itemId}/match-now`, { method: "POST" }),
  candidates: (itemId, limit = 30) => request(`/anchor-plans/items/${itemId}/candidates?limit=${limit}`),
  setDonor: (itemId, donor_id) => request(`/anchor-plans/items/${itemId}/set-donor`, { method: "POST", body: { donor_id } }),
  assign: (id, item_ids, assigned_to) => request(`/anchor-plans/${id}/assign`, { method: "POST", body: { item_ids, assigned_to } }),
  // Aggregate ("Формат 2") buckets: materialise `count` work-units from a bucket.
  spawnUnits: (itemId, count, do_match = true) => request(`/anchor-plans/items/${itemId}/spawn?count=${count}&do_match=${do_match}`, { method: "POST" }),
  planItemChildren: (id, parentId, params = {}) => request(`/anchor-plans/${id}/items?${qs({ ...params, parent_id: parentId })}`),
  exportPlan: (id) => downloadFile(`/anchor-plans/${id}/export`, `plan_${id}.csv`),

  // placements
  placements: (params = {}) => request(`/placements?${qs(params)}`),
  myTasks: (params = {}) => request(`/my-tasks?${qs(params)}`),
  takeTask: (itemId) => request(`/my-tasks/${itemId}/take`, { method: "POST" }),
  markPlaced: (id, data) => request(`/placements/${id}/mark-placed`, { method: "POST", body: data }),
  markProblem: (id, data) => request(`/placements/${id}/mark-problem`, { method: "POST", body: data }),

  // stop list
  stopList: (params = {}) => request(`/stop-list?${qs(params)}`),
  importStopList: (file, clientId) => uploadFile("/stop-list/import", file, clientId ? { client_id: clientId } : {}),
  exportStopList: () => downloadFile("/stop-list/export", "stop_list.csv"),
  deleteStopEntry: (id) => request(`/stop-list/${id}`, { method: "DELETE" }),

  // clients & client projects
  clients: (params = {}) => request(`/clients?${qs(params)}`),
  client: (id) => request(`/clients/${id}`),
  createClient: (data) => request("/clients", { method: "POST", body: data }),
  updateClient: (id, data) => request(`/clients/${id}`, { method: "PATCH", body: data }),
  archiveClient: (id) => request(`/clients/${id}`, { method: "DELETE" }),
  clientProjects: (params = {}) => request(`/client-projects?${qs(params)}`),
  clientProject: (id) => request(`/client-projects/${id}`),
  createClientProject: (data) => request("/client-projects", { method: "POST", body: data }),
  updateClientProject: (id, data) => request(`/client-projects/${id}`, { method: "PATCH", body: data }),
  archiveClientProject: (id) => request(`/client-projects/${id}`, { method: "DELETE" }),

  // client portal (role=client) — hard-scoped server-side to the caller's client
  clientSummary: () => request("/client/summary"),
  clientMyProjects: () => request("/client/projects"),
  clientMyProject: (id) => request(`/client/projects/${id}`),
  clientMyProjectPlacements: (id) => request(`/client/projects/${id}/placements`),
  clientProjectReport: (id) => downloadFile(`/client/projects/${id}/report`, `report_${id}.csv`),
  clientProjectReportInternal: (id) => downloadFile(`/client-projects/${id}/report`, `project_${id}_report.csv`),

  // link monitor + ready-link checks
  linkMonitorSummary: (params = {}) => request(`/link-monitor/summary?${qs(params)}`),
  linkMonitorItems: (params = {}) => request(`/link-monitor/items?${qs(params)}`),
  recheckPlacement: (id) => request(`/placements/${id}/recheck`, { method: "POST" }),
  placementChecks: (id) => request(`/placements/${id}/checks`),
  linkCheckStatus: () => request("/admin/link-check/status"),
  linkCheckRun: (limit = 50) => request(`/admin/link-check/run?limit=${limit}`, { method: "POST" }),

  // notifications
  notificationsList: (params = {}) => request(`/notifications?${qs(params)}`),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: "POST" }),
  markAllNotificationsRead: () => request("/notifications/read-all", { method: "POST" }),

  // dashboard
  stats: (kind, clientId) => {
    const p = {};
    if (kind) p.kind = kind;
    if (clientId) p.client_id = clientId;
    const q = qs(p);
    return request(`/dashboard/stats${q ? `?${q}` : ""}`);
  },

  // admin maintenance
  resetAllData: () => request("/admin/reset-data", { method: "POST" }).then(r => {
    // The reset wipes everything except users — drop any cached GETs so the
    // next page load reflects the empty state.
    cacheInvalidate("/");
    return r;
  }),
};

function qs(params) {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    usp.set(k, v);
  });
  return usp.toString();
}

async function uploadFile(url, file, extra = {}) {
  const fd = new FormData();
  fd.append("file", file);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  return request(url, { method: "POST", body: fd });
}

async function downloadFile(url, filename) {
  const res = await request(url, { raw: true });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
