const statusPanel = document.querySelector("#my-orders-status");
const content = document.querySelector("#my-orders-content");
const list = document.querySelector("#my-orders-list");
const empty = document.querySelector("#my-orders-empty");
const emptyTitle = document.querySelector("#my-orders-empty-title");
const emptyCopy = document.querySelector("#my-orders-empty-copy");
const storesList = document.querySelector("#my-stores-list");
const storesEmpty = document.querySelector("#my-stores-empty");
const claimForm = document.querySelector("#store-claim-form");
const claimInput = document.querySelector("#store-management-url");
const claimButton = document.querySelector("#store-claim-button");
const claimStatus = document.querySelector("#store-claim-status");
const viewButtons = document.querySelectorAll("[data-archive-view]");
let showingArchived = false;

function formatPrice(amount) {
  return `NT$ ${amount.toLocaleString("zh-TW")}`;
}

function showError(message) {
  statusPanel.textContent = message;
  statusPanel.dataset.state = "error";
  statusPanel.hidden = false;
  content.hidden = true;
}

function buildLink(label, href, secondary = false) {
  const link = document.createElement("a");
  link.textContent = label;
  link.href = href;
  if (secondary) link.className = "my-secondary-link";
  return link;
}

function renderStores(menus) {
  const stores = menus.filter((menu) => menu.menu_type === "store_fixed");
  storesList.replaceChildren();
  storesEmpty.hidden = stores.length > 0;
  stores.forEach((store) => {
    const card = document.createElement("article");
    card.className = "my-card my-store-card";

    const heading = document.createElement("div");
    const badge = document.createElement("p");
    badge.className = "my-menu-type";
    badge.textContent = "店家固定菜單";
    const name = document.createElement("h3");
    name.textContent = store.restaurant_name;
    const meta = document.createElement("p");
    meta.textContent = `${store.category_count} 個分類 · ${store.item_count} 個品項 · 第 ${store.version} 版`;
    heading.append(badge, name, meta);

    const updated = document.createElement("p");
    updated.textContent = `最近更新：${new Date(store.updated_at).toLocaleDateString("zh-TW")}`;

    const actions = document.createElement("div");
    actions.className = "my-card-actions";
    actions.append(
      buildLink("調整固定菜單", `/stores/${store.public_slug}/menu-update`),
      buildLink("查看店家收到的訂單", `/stores/${store.public_slug}/manage`, true),
      buildLink("開啟顧客點餐頁", `/stores/${store.public_slug}`, true),
    );
    card.append(heading, updated, actions);
    storesList.append(card);
  });
}

function renderOrders(orders) {
  list.replaceChildren();
  empty.hidden = orders.length > 0;
  orders.forEach((order) => {
    const card = document.createElement("article");
    card.className = "my-card";
    const heading = document.createElement("div");
    const name = document.createElement("h2");
    name.textContent = order.restaurant_name;
    const number = document.createElement("p");
    number.textContent = `${order.mode === "group" ? "團購" : "店家"}・訂單 ${order.public_order_number}`;
    heading.append(name, number);
    const meta = document.createElement("p");
    meta.textContent = `${order.customer_name}・${formatPrice(order.total_amount)}・${new Date(order.created_at).toLocaleDateString("zh-TW")}`;
    const link = document.createElement("a");
    link.href = order.order_url;
    link.textContent = "查看訂單明細";
    const actions = document.createElement("div");
    actions.className = "my-card-actions";
    const archiveButton = document.createElement("button");
    archiveButton.type = "button";
    archiveButton.className = "my-secondary-button";
    archiveButton.textContent = showingArchived ? "恢復訂單" : "封存訂單";
    archiveButton.addEventListener("click", () => updateArchive(order, archiveButton));
    actions.append(archiveButton, link);
    card.append(heading, meta, actions);
    list.append(card);
  });
  statusPanel.hidden = true;
  content.hidden = false;
}

async function updateArchive(order, button) {
  button.disabled = true;
  try {
    const headers = await window.AppAuth.getAuthorizationHeaders();
    const action = showingArchived ? "restore" : "archive";
    const response = await fetch(`${order.archive_api_url}/${action}`, {
      method: "POST",
      headers,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "訂單狀態暫時無法更新。");
    await loadOrders();
  } catch (error) {
    showError(error.message || "訂單狀態暫時無法更新。");
    button.disabled = false;
  }
}

async function loadOrders() {
  try {
    const headers = window.AppAuth?.getAuthorizationHeaders
      ? await window.AppAuth.getAuthorizationHeaders()
      : {};
    if (!headers.Authorization) {
      throw new Error("請先回首頁使用 Google 登入，再查看我的訂單。");
    }
    const response = await fetch(`/api/me/orders?archived=${showingArchived}`, {
      headers,
      cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error("我的訂單暫時無法讀取，請重新登入後再試。");
    }
    emptyTitle.textContent = showingArchived ? "目前沒有已封存的訂單" : "還沒有已保存的訂單";
    emptyCopy.textContent = showingArchived
      ? "封存的訂單會保留明細，並可隨時恢復。"
      : "登入狀態下完成送單，之後就能從這裡跨裝置找回。";
    renderOrders(result.orders);
  } catch (error) {
    showError(error.message || "我的訂單暫時無法讀取。");
  }
}

async function loadStores(headers) {
  const response = await fetch("/api/me/menus", { headers, cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error("我的店家固定菜單暫時無法讀取，請重新登入後再試。");
  renderStores(result.menus);
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
    const headers = await window.AppAuth.getAuthorizationHeaders();
    headers["X-Management-Token"] = managementToken;
    const response = await fetch(`/api/me/stores/${publicSlug}/claim`, {
      method: "POST",
      headers,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "無法認領這個店家，請確認管理連結是否正確。");
    claimInput.value = "";
    claimStatus.textContent = "店家固定菜單已儲存到你的帳號。";
    const authHeaders = await window.AppAuth.getAuthorizationHeaders();
    await loadStores(authHeaders);
  } catch (error) {
    claimStatus.textContent = error.message || "店家固定菜單暫時無法儲存。";
  } finally {
    claimButton.disabled = false;
  }
}

async function loadDashboard() {
  try {
    const headers = window.AppAuth?.getAuthorizationHeaders
      ? await window.AppAuth.getAuthorizationHeaders()
      : {};
    if (!headers.Authorization) {
      throw new Error("請先回首頁使用 Google 登入，再查看我的訂單。");
    }
    await Promise.all([loadStores(headers), loadOrders()]);
  } catch (error) {
    showError(error.message || "帳號資料暫時無法讀取。");
  }
}

viewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showingArchived = button.dataset.archiveView === "archived";
    viewButtons.forEach((candidate) => {
      candidate.setAttribute(
        "aria-pressed",
        String(candidate.dataset.archiveView === button.dataset.archiveView),
      );
    });
    statusPanel.textContent = showingArchived ? "已封存訂單載入中" : "訂單載入中";
    statusPanel.dataset.state = "loading";
    statusPanel.hidden = false;
    loadOrders();
  });
});

claimForm.addEventListener("submit", claimStore);
loadDashboard();
