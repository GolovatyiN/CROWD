import { api, auth } from "../api.js";
import { el } from "../components/dom.js";
import { toast } from "../components/toast.js";

export function renderLogin(host) {
  if (auth.getToken()) { location.hash = "#/dashboard"; return; }

  // strip the layout — login uses full-screen background
  host.parentElement && (host.parentElement.style.background = "var(--bg)");

  const card = el("div", { class: "login-card" },
    el("div", { class: "brand" },
      el("div", { class: "brand-logo" }, "C"),
      el("div", {}, "Crowd"),
    ),
    el("h1", {}, "Вход в систему"),
    el("div", { class: "subtitle" }, "Войдите, чтобы продолжить работу"),
    loginForm(),
  );
  const page = el("div", { class: "login-page" }, card);
  host.appendChild(page);
}

function loginForm() {
  const form = el("form", { onSubmit: async (e) => {
    e.preventDefault();
    const email = form.querySelector("input[name=email]").value;
    const password = form.querySelector("input[name=password]").value;
    const btn = form.querySelector("button");
    btn.disabled = true; btn.textContent = "Входим…";
    try {
      const res = await api.login(email, password);
      auth.setToken(res.access_token);
      auth.setUser(res.user);
      toast(`Добро пожаловать, ${res.user.full_name || res.user.email}`, "success");
      location.hash = "#/dashboard";
    } catch (err) {
      toast(err.message || "Ошибка входа", "error");
      btn.disabled = false; btn.textContent = "Войти";
    }
  }},
    el("div", { class: "field" },
      el("label", {}, "Email или логин"),
      el("input", { name: "email", type: "text", required: true, autocomplete: "username", value: "admin@crowd.local" })
    ),
    el("div", { class: "field" },
      el("label", {}, "Пароль"),
      el("input", { name: "password", type: "password", required: true, autocomplete: "current-password" })
    ),
    el("button", { type: "submit", style: { width: "100%", height: "38px", marginTop: "6px" } }, "Войти"),
  );
  return form;
}
