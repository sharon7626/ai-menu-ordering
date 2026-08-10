const statusPanel = document.querySelector("#management-status");
const managementContent = document.querySelector("#management-content");
const storeCode = document.querySelector("#store-code");
const restaurantName = document.querySelector("#restaurant-name");
const serviceState = document.querySelector("#service-state");
const orderCount = document.querySelector("#order-count");
const grandTotal = document.querySelector("#grand-total");
const emptyOrders = document.querySelector("#empty-orders");
const ordersList = document.querySelector("#orders-list");
const publicMenuLink = document.querySelector("#public-menu-link");
const updateMenuLink = document.querySelector("#update-menu-link");
const emptySummary = document.querySelector("#empty-summary");
const summaryList = document.querySelector("#summary-list");
const downloadExcelButton = document.querySelector("#download-excel");
const downloadStatus = document.querySelector("#download-status");
let currentStore = null;
let managementToken = "";

function slugFromPath() {
  const match = window.location.pathname.match(/^\/stores\/([a-z]{8})\/manage$/);
  return match ? match[1] : "";
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
  managementContent.hidden = true;
}

function renderManagement(store, token) {
  currentStore = store;
  document.title = `${store.restaurant_name}｜店家訂單後台`;
  storeCode.textContent = `店家識別碼：${store.public_slug}`;
  restaurantName.textContent = store.restaurant_name;
  serviceState.textContent = store.active ? "目前開放接單" : "目前暫停接單";
  serviceState.dataset.state = store.active ? "active" : "inactive";
  orderCount.textContent = `${store.order_count} 張訂單`;
  grandTotal.textContent = `合計 ${formatPrice(store.grand_total)}`;
  publicMenuLink.href = `/stores/${store.public_slug}`;
  updateMenuLink.href = `/stores/${store.public_slug}/menu-update#token=${encodeURIComponent(token)}`;
  downloadExcelButton.disabled = store.order_count === 0;
  downloadExcelButton.title = store.order_count === 0
    ? "目前沒有訂單可匯出"
    : "下載目前店家的訂單資料";
  summaryList.replaceChildren();
  emptySummary.hidden = store.summary.length > 0;

  const summariesByItem = new Map();
  store.summary.forEach((item) => {
    if (!summariesByItem.has(item.item_id)) {
      summariesByItem.set(item.item_id, []);
    }
    summariesByItem.get(item.item_id).push(item);
  });
  summariesByItem.forEach((items) => {
    const firstItem = items[0];
    const card = document.createElement("article");
    card.className = "summary-item";
    const details = document.createElement("div");
    const name = document.createElement("h3");
    name.textContent = firstItem.item_name;
    const price = document.createElement("p");
    price.textContent = `單價 ${formatPrice(firstItem.unit_price)}`;
    details.append(name, price);
    const demands = document.createElement("div");
    demands.className = "summary-demands";
    items.forEach((item) => {
      const demand = document.createElement("div");
      demand.className = "summary-demand";
      const note = document.createElement("p");
      note.className = "summary-note";
      note.textContent = item.note ? `需求：${item.note}` : "一般（無備註）";
      const totals = document.createElement("div");
      totals.className = "summary-totals";
      const quantity = document.createElement("strong");
      quantity.textContent = `${item.total_quantity} 份`;
      const amount = document.createElement("span");
      amount.textContent = formatPrice(item.total_amount);
      totals.append(quantity, amount);
      demand.append(note, totals);
      demands.append(demand);
    });
    card.append(details, demands);
    summaryList.append(card);
  });
  ordersList.replaceChildren();
  emptyOrders.hidden = store.orders.length > 0;

  store.orders.forEach((order) => {
    const card = document.createElement("article");
    card.className = "order-card";
    const heading = document.createElement("div");
    heading.className = "order-heading";
    const title = document.createElement("h3");
    title.textContent = order.customer_name;
    const total = document.createElement("strong");
    total.textContent = formatPrice(order.total_amount);
    heading.append(title, total);

    const list = document.createElement("ul");
    order.items.forEach((item) => {
      const row = document.createElement("li");
      row.textContent = item.note
        ? `${item.item_name} × ${item.quantity}（${formatPrice(item.subtotal)}）｜備註：${item.note}`
        : `${item.item_name} × ${item.quantity}（${formatPrice(item.subtotal)}）`;
      list.append(row);
    });
    const time = document.createElement("p");
    time.textContent = `送單時間：${new Date(order.created_at).toLocaleString("zh-TW")}`;
    card.append(heading, list, time);
    ordersList.append(card);
  });

  statusPanel.hidden = true;
  managementContent.hidden = false;
}

async function loadManagement() {
  const slug = slugFromPath();
  const token = tokenFromFragment();
  if (!slug || !token) {
    showError("缺少店家管理資訊，請使用建立店家時取得的完整管理連結。");
    return;
  }
  managementToken = token;
  try {
    const response = await fetch(`/api/stores/${slug}/management`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "店家訂單暫時無法讀取，請稍後再試。",
      );
    }
    renderManagement(result, token);
  } catch (error) {
    showError(error.message || "店家訂單暫時無法讀取，請稍後再試。");
  }
}

downloadExcelButton.addEventListener("click", async () => {
  if (!currentStore || !managementToken || currentStore.order_count === 0) {
    return;
  }
  downloadExcelButton.disabled = true;
  downloadStatus.textContent = "正在整理 Excel 表格…";
  downloadStatus.dataset.state = "loading";
  downloadStatus.hidden = false;
  try {
    const latestResponse = await fetch(
      `/api/stores/${currentStore.public_slug}/management`,
      {
        headers: { Authorization: `Bearer ${managementToken}` },
        cache: "no-store",
      },
    );
    const latestStore = await latestResponse.json();
    if (!latestResponse.ok) {
      throw new Error("無法取得最新訂單，請重新整理後再試一次。");
    }
    renderManagement(latestStore, managementToken);
    downloadExcelButton.disabled = true;
    if (latestStore.order_count === 0) {
      throw new Error("目前還沒有顧客訂單，請有人完成送單後再下載。");
    }

    const response = await fetch(
      `/api/stores/${latestStore.public_slug}/management.xlsx?download=${Date.now()}`,
      {
        headers: { Authorization: `Bearer ${managementToken}` },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      throw new Error("Excel 表格下載失敗，請稍後再試一次。");
    }
    if (Number(response.headers.get("X-Order-Count")) !== latestStore.order_count) {
      throw new Error("訂單資料仍在更新，請稍後再下載一次。");
    }
    const workbookBytes = await response.arrayBuffer();
    const signature = new Uint8Array(workbookBytes, 0, Math.min(2, workbookBytes.byteLength));
    if (workbookBytes.byteLength < 1000 || signature[0] !== 0x50 || signature[1] !== 0x4b) {
      throw new Error("下載的 Excel 檔案內容不完整，請重新整理後再試一次。");
    }
    const blob = new Blob([workbookBytes], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${latestStore.restaurant_name}-店家訂單.xlsx`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    downloadStatus.textContent = "Excel 已下載，內含餐點彙整、顧客合計與顧客明細。";
    downloadStatus.dataset.state = "success";
  } catch (error) {
    downloadStatus.textContent = error.message || "Excel 表格下載失敗，請稍後再試一次。";
    downloadStatus.dataset.state = "error";
  } finally {
    downloadExcelButton.disabled = !currentStore || currentStore.order_count === 0;
  }
});

loadManagement();
