const statusPanel = document.querySelector("#my-menus-status");
const content = document.querySelector("#my-menus-content");
const list = document.querySelector("#my-menus-list");
const empty = document.querySelector("#my-menus-empty");
const claimForm = document.querySelector("#menu-store-claim-form");
const claimInput = document.querySelector("#menu-store-management-url");
const claimButton = document.querySelector("#menu-store-claim-button");
const claimStatus = document.querySelector("#menu-store-claim-status");

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

function buildLink(label, href, secondary = false) {
  const link = document.createElement("a");
  link.textContent = label;
  link.href = href;
  if (secondary) link.className = "my-secondary-button";
  return link;
}

function renderMenus(menus) {
  list.replaceChildren();
  empty.hidden = menus.length > 0;
  menus.forEach((menu) => {
    const card = document.createElement("article");
    card.className = "my-card";

    const heading = document.createElement("div");
    const badge = document.createElement("p");
    badge.className = "my-menu-type";
    badge.textContent = menu.menu_type === "store_fixed"
      ? "店家固定菜單"
      : "團購常用菜單";
    const name = document.createElement("h2");
    name.textContent = menu.restaurant_name;
    const meta = document.createElement("p");
    const version = menu.menu_type === "store_fixed" ? ` · 第 ${menu.version} 版` : "";
    meta.textContent = `${menu.category_count} 個分類 · ${menu.item_count} 個品項${version}`;
    heading.append(badge, name, meta);

    const saved = document.createElement("p");
    saved.textContent = `最近更新：${new Date(menu.updated_at).toLocaleDateString("zh-TW")}`;

    const actions = document.createElement("div");
    actions.className = "my-card-actions";
    if (menu.menu_type === "store_fixed") {
      actions.append(
        buildLink("調整固定菜單", `/stores/${menu.public_slug}/menu-update`),
        buildLink("查看店家訂單", `/stores/${menu.public_slug}/manage`, true),
        buildLink("公開點餐頁", `/stores/${menu.public_slug}`, true),
      );
    } else {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "用這份菜單建立團購";
      button.addEventListener("click", () => createGroup(menu.id, button));
      actions.append(button);
    }

    card.append(heading, saved, actions);
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
    if (!response.ok) throw new Error(result.detail || "建立團購失敗，請稍後再試。");
    window.location.assign(result.management_url);
  } catch (error) {
    showError(error.message || "建立團購失敗，請稍後再試。");
    button.disabled = false;
  }
}

function parseStoreManagementUrl(rawValue) {
  let url;
  try {
    url = new URL(rawValue);
  } catch {
    throw new Error("請貼上完整的店家管理網址。");
  }
  if (url.origin !== window.location.origin) {
    throw new Error("請使用目前席間網站產生的店家管理網址。");
  }
  const match = url.pathname.match(/^\/stores\/([a-z0-9-]+)\/(?:manage|menu-update)\/?$/i);
  const token = new URLSearchParams(url.hash.slice(1)).get("token");
  if (!match || !token) {
    throw new Error("這個網址缺少店家管理資訊，請複製包含 #token= 的完整網址。");
  }
  return { publicSlug: match[1].toLowerCase(), managementToken: token };
}

async function claimStore(event) {
  event.preventDefault();
  claimButton.disabled = true;
  claimStatus.textContent = "正在確認店家管理權限…";
  try {
    const { publicSlug, managementToken } = parseStoreManagementUrl(claimInput.value.trim());
    const headers = await authHeaders();
    headers["X-Management-Token"] = managementToken;
    const response = await fetch(`/api/me/stores/${publicSlug}/claim`, {
      method: "POST",
      headers,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "無法認領這個店家，請確認管理連結是否正確。");
    claimInput.value = "";
    claimStatus.textContent = "固定菜單已加入我的菜單，可以從上方進入調整。";
    await loadMenus();
  } catch (error) {
    claimStatus.textContent = error.message || "店家固定菜單暫時無法加入。";
  } finally {
    claimButton.disabled = false;
  }
}

async function loadMenus() {
  try {
    const headers = await authHeaders();
    if (!headers.Authorization) throw new Error("請先使用 Google 登入。");
    const response = await fetch("/api/me/menus", { headers, cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "無法讀取我的菜單。");
    renderMenus(result.menus);
  } catch (error) {
    showError(error.message || "無法讀取我的菜單。");
  }
}

claimForm.addEventListener("submit", claimStore);
loadMenus();
