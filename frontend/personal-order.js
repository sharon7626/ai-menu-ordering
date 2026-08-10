const statusPanel = document.querySelector("#order-status");
const orderCard = document.querySelector("#order-card");
const restaurantName = document.querySelector("#restaurant-name");
const orderNumber = document.querySelector("#order-number");
const customerName = document.querySelector("#customer-name");
const orderItems = document.querySelector("#order-items");
const totalAmount = document.querySelector("#total-amount");
const createdAt = document.querySelector("#created-at");
const backToGroup = document.querySelector("#back-to-group");
const orderModeLabel = document.querySelector("#order-mode-label");

function pathValues() {
  const groupMatch = window.location.pathname.match(
    /^\/groups\/([^/]+)\/orders\/([^/]+)$/,
  );
  if (groupMatch) {
    const publicCode = decodeURIComponent(groupMatch[1]).toUpperCase();
    return {
      mode: "group",
      apiUrl: `/api/groups/${encodeURIComponent(publicCode)}/orders/${encodeURIComponent(groupMatch[2])}`,
      backUrl: `/groups/${publicCode}`,
      backText: "返回團購菜單",
      modeText: "團購個人訂單",
    };
  }
  const storeMatch = window.location.pathname.match(
    /^\/stores\/([a-z]{8})\/orders\/([^/]+)$/,
  );
  if (storeMatch) {
    const publicSlug = storeMatch[1];
    return {
      mode: "store",
      apiUrl: `/api/stores/${publicSlug}/orders/${encodeURIComponent(storeMatch[2])}`,
      backUrl: `/stores/${publicSlug}`,
      backText: "返回店家菜單",
      modeText: "店家個人訂單",
    };
  }
  return null;
}

function tokenFromFragment() {
  return new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
}

function formatPrice(amount) {
  return `NT$ ${amount.toLocaleString("zh-TW")}`;
}

function showError(message) {
  statusPanel.textContent = message;
  statusPanel.dataset.state = "error";
  statusPanel.hidden = false;
  orderCard.hidden = true;
}

function renderOrder(order, values) {
  restaurantName.textContent = order.restaurant_name;
  orderNumber.textContent = `訂單編號 ${order.public_order_number}`;
  customerName.textContent = order.customer_name;
  orderItems.replaceChildren();
  order.items.forEach((item) => {
    const row = document.createElement("li");
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.item_name;
    const quantity = document.createElement("span");
    quantity.textContent = `單價 ${formatPrice(item.unit_price)} × ${item.quantity}`;
    details.append(name, quantity);
    if (item.note) {
      const note = document.createElement("span");
      note.className = "item-note";
      note.textContent = `備註：${item.note}`;
      details.append(note);
    }
    const subtotal = document.createElement("strong");
    subtotal.textContent = formatPrice(item.subtotal);
    row.append(details, subtotal);
    orderItems.append(row);
  });
  totalAmount.textContent = formatPrice(order.total_amount);
  createdAt.textContent = `送單時間：${new Date(order.created_at).toLocaleString("zh-TW")}`;
  orderModeLabel.textContent = values.modeText;
  backToGroup.href = values.backUrl;
  backToGroup.textContent = values.backText;
  statusPanel.hidden = true;
  orderCard.hidden = false;
}

async function loadOrder() {
  const values = pathValues();
  const token = tokenFromFragment();
  if (!values || !token) {
    showError("缺少個人訂單查看資訊，請使用送單成功時取得的完整連結。");
    return;
  }

  try {
    const response = await fetch(values.apiUrl, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "訂單暫時無法讀取，請稍後再試。",
      );
    }
    renderOrder(result, values);
  } catch (error) {
    showError(error.message || "訂單暫時無法讀取，請稍後再試。");
  }
}

loadOrder();
