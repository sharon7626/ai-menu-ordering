const ADMIN_ORDERS_URL = "/api/admin/orders";

const orderSummary = document.querySelector("#order-summary");
const ordersStatus = document.querySelector("#orders-status");
const ordersList = document.querySelector("#orders-list");

function formatPrice(amount) {
  return `NT$ ${amount.toLocaleString("zh-TW")}`;
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("zh-TW", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function showStatus(message, state) {
  ordersStatus.replaceChildren();
  ordersStatus.textContent = message;
  ordersStatus.dataset.state = state;
  ordersStatus.hidden = false;
}

function createOrderItem(item) {
  const listItem = document.createElement("li");
  listItem.className = "order-item";

  const name = document.createElement("p");
  name.className = "item-name";
  name.textContent = item.item_name;

  const details = document.createElement("p");
  details.className = "item-details";
  details.textContent = `單價 ${formatPrice(item.unit_price)} × ${item.quantity}`;

  const subtotal = document.createElement("p");
  subtotal.className = "item-subtotal";
  subtotal.textContent = formatPrice(item.subtotal);

  listItem.append(name, details, subtotal);
  return listItem;
}

function createOrderCard(order) {
  const article = document.createElement("article");
  article.className = "order-card";
  article.setAttribute("aria-labelledby", `order-${order.order_id}`);

  const header = document.createElement("header");
  header.className = "order-card-header";

  const title = document.createElement("h2");
  title.id = `order-${order.order_id}`;
  title.className = "order-title";
  title.textContent = `訂單 #${order.order_id}`;

  const customer = document.createElement("p");
  customer.className = "customer-name";
  customer.textContent = `顧客：${order.customer_name}`;

  const time = document.createElement("time");
  time.className = "order-time";
  time.dateTime = order.created_at;
  time.textContent = `建立時間：${formatDateTime(order.created_at)}`;

  const total = document.createElement("p");
  total.className = "order-total";
  total.textContent = formatPrice(order.total_amount);

  header.append(title, customer, time, total);

  const items = document.createElement("ul");
  items.className = "order-items";
  order.items.forEach((item) => items.append(createOrderItem(item)));

  article.append(header, items);
  return article;
}

function renderOrders(orders) {
  ordersList.replaceChildren();
  orderSummary.textContent = `共 ${orders.length} 張訂單`;

  if (orders.length === 0) {
    showStatus("目前沒有訂單", "empty");
    return;
  }

  const fragment = document.createDocumentFragment();
  orders.forEach((order) => fragment.append(createOrderCard(order)));
  ordersList.append(fragment);
  ordersStatus.hidden = true;
}

async function loadOrders() {
  try {
    const response = await fetch(ADMIN_ORDERS_URL);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const result = await response.json();
    renderOrders(Array.isArray(result.orders) ? result.orders : []);
  } catch (error) {
    console.error("訂單載入失敗：", error);
    orderSummary.textContent = "訂單載入失敗";
    showStatus("訂單暫時無法載入，請稍後重新整理頁面。", "error");
  }
}

loadOrders();
