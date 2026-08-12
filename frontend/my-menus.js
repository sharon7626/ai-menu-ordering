const statusPanel = document.querySelector("#my-menus-status");
const content = document.querySelector("#my-menus-content");
const list = document.querySelector("#my-menus-list");
const empty = document.querySelector("#my-menus-empty");

async function authHeaders() {
  return window.AppAuth?.getAuthorizationHeaders
    ? window.AppAuth.getAuthorizationHeaders()
    : {};
}

function showError(message) {
  statusPanel.textContent = message;
  statusPanel.dataset.state = "error";
  statusPanel.hidden = false;
}

function renderMenus(menus) {
  list.replaceChildren();
  empty.hidden = menus.length > 0;
  menus.forEach((menu) => {
    const card = document.createElement("article");
    card.className = "my-card";
    const heading = document.createElement("div");
    const name = document.createElement("h2");
    name.textContent = menu.restaurant_name;
    const meta = document.createElement("p");
    meta.textContent = `${menu.category_count} 個分類・${menu.item_count} 個品項`;
    heading.append(name, meta);
    const saved = document.createElement("p");
    saved.textContent = `最近使用 ${new Date(menu.updated_at).toLocaleDateString("zh-TW")}`;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "用這份菜單建立團購";
    button.addEventListener("click", () => createGroup(menu.id, button));
    card.append(heading, saved, button);
    list.append(card);
  });
  statusPanel.hidden = true;
  content.hidden = false;
}

async function createGroup(menuId, button) {
  button.disabled = true;
  try {
    const headers = await authHeaders();
    const response = await fetch(`/api/me/menus/${menuId}/groups`, { method: "POST", headers });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "團購建立失敗。");
    window.location.assign(result.management_url);
  } catch (error) {
    showError(error.message || "團購建立失敗。");
    button.disabled = false;
  }
}

async function loadMenus() {
  try {
    const headers = await authHeaders();
    if (!headers.Authorization) throw new Error("請先回首頁使用 Google 登入。");
    const response = await fetch("/api/me/menus", { headers, cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error("我的菜單暫時無法讀取。");
    renderMenus(result.menus);
  } catch (error) {
    showError(error.message || "我的菜單暫時無法讀取。");
  }
}

loadMenus();
