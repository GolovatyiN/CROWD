const TOKEN_KEY = "crowd_token";
const USER_KEY = "crowd_user";

export const auth = {
  getToken() { return localStorage.getItem(TOKEN_KEY); },
  setToken(t) { localStorage.setItem(TOKEN_KEY, t); },
  clearToken() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); },
  getUser() { try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; } },
  setUser(u) { localStorage.setItem(USER_KEY, JSON.stringify(u)); },
  isAdmin() { const u = this.getUser(); return u && u.role === "admin"; },
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

export const api = {
  // auth
  login: (email, password) => request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),

  // users
  users: (params = {}) => request(`/users?${qs(params)}`),
  createUser: (data) => request("/users", { method: "POST", body: data }),
  updateUser: (id, data) => request(`/users/${id}`, { method: "PATCH", body: data }),
  deactivateUser: (id) => request(`/users/${id}`, { method: "DELETE" }),

  // donors — paginated
  donors: (params = {}) => request(`/donors?${qs(params)}`),
  createDonor: (data) => request("/donors", { method: "POST", body: data }),
  updateDonor: (id, data) => request(`/donors/${id}`, { method: "PATCH", body: data }),
  deactivateDonor: (id) => request(`/donors/${id}`, { method: "DELETE" }),
  bulkDeactivateDonors: (ids) => request("/donors/bulk-deactivate", { method: "POST", body: { ids } }),
  bulkActivateDonors: (ids) => request("/donors/bulk-activate", { method: "POST", body: { ids } }),
  donorUsage: (id) => request(`/donors/${id}/usage`),
  donorAccounts: (id) => request(`/donors/${id}/accounts`),
  createDonorAccount: (id, data) => request(`/donors/${id}/accounts`, { method: "POST", body: { ...data, donor_id: id } }),
  updateDonorAccount: (donorId, accId, data) => request(`/donors/${donorId}/accounts/${accId}`, { method: "PATCH", body: data }),
  deleteDonorAccount: (donorId, accId) => request(`/donors/${donorId}/accounts/${accId}`, { method: "DELETE" }),
  importDonors: (file) => uploadFile("/donors/import", file),
  exportDonors: () => downloadFile("/donors/export", "donors.csv"),

  // plans
  plans: (params = {}) => request(`/anchor-plans?${qs(params)}`),
  plan: (id) => request(`/anchor-plans/${id}`),
  deletePlan: (id) => request(`/anchor-plans/${id}`, { method: "DELETE" }),
  planItems: (id, params = {}) => request(`/anchor-plans/${id}/items?${qs(params)}`),
  updateItem: (id, data) => request(`/anchor-plans/items/${id}`, { method: "PATCH", body: data }),
  importPlan: (file, planName) => uploadFile("/anchor-plans/import", file, { plan_name: planName }),
  autoMatch: (id) => request(`/anchor-plans/${id}/auto-match`, { method: "POST" }),
  rematchAll: (id) => request(`/anchor-plans/${id}/rematch-all`, { method: "POST" }),
  reinferGeo: (id) => request(`/anchor-plans/${id}/reinfer-geo`, { method: "POST" }),
  matchOne: (itemId) => request(`/anchor-plans/items/${itemId}/match-now`, { method: "POST" }),
  candidates: (itemId, limit = 30) => request(`/anchor-plans/items/${itemId}/candidates?limit=${limit}`),
  setDonor: (itemId, donor_id) => request(`/anchor-plans/items/${itemId}/set-donor`, { method: "POST", body: { donor_id } }),
  assign: (id, item_ids, assigned_to) => request(`/anchor-plans/${id}/assign`, { method: "POST", body: { item_ids, assigned_to } }),
  exportPlan: (id) => downloadFile(`/anchor-plans/${id}/export`, `plan_${id}.csv`),

  // placements
  placements: (params = {}) => request(`/placements?${qs(params)}`),
  myTasks: (params = {}) => request(`/my-tasks?${qs(params)}`),
  takeTask: (itemId) => request(`/my-tasks/${itemId}/take`, { method: "POST" }),
  markPlaced: (id, data) => request(`/placements/${id}/mark-placed`, { method: "POST", body: data }),
  markProblem: (id, data) => request(`/placements/${id}/mark-problem`, { method: "POST", body: data }),

  // stop list
  stopList: (params = {}) => request(`/stop-list?${qs(params)}`),
  importStopList: (file) => uploadFile("/stop-list/import", file),
  exportStopList: () => downloadFile("/stop-list/export", "stop_list.csv"),
  deleteStopEntry: (id) => request(`/stop-list/${id}`, { method: "DELETE" }),

  // dashboard
  stats: () => request("/dashboard/stats"),
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
