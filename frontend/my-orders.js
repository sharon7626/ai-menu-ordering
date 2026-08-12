const statusPanel = document.querySelector("#my-orders-status");
const content = document.querySelector("#my-orders-content");
const list = document.querySelector("#my-orders-list");
const empty = document.querySelector("#my-orders-empty");
const emptyTitle = document.querySelector("#my-orders-empty-title");
const emptyCopy = document.querySelector("#my-orders-empty-copy");
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

loadOrders();
