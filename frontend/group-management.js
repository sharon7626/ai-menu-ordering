const statusPanel = document.querySelector("#management-status");
const managementContent = document.querySelector("#management-content");
const groupCode = document.querySelector("#group-code");
const restaurantName = document.querySelector("#restaurant-name");
const groupState = document.querySelector("#group-state");
const orderCount = document.querySelector("#order-count");
const emptyOrders = document.querySelector("#empty-orders");
const ordersList = document.querySelector("#orders-list");
const grandTotal = document.querySelector("#grand-total");
const emptySummary = document.querySelector("#empty-summary");
const summaryList = document.querySelector("#summary-list");
const closeGroupButton = document.querySelector("#close-group");
const claimGroupButton = document.querySelector("#claim-group");
const actionStatus = document.querySelector("#action-status");
const copySummaryButton = document.querySelector("#copy-summary");
const downloadExcelButton = document.querySelector("#download-excel");
const textSummary = document.querySelector("#text-summary");
let currentGroup = null;
let managementToken = "";
let accountMode = false;

function codeFromPath() {
  const match = window.location.pathname.match(/^\/groups\/([^/]+)\/manage$/);
  return match ? decodeURIComponent(match[1]).toUpperCase() : "";
}

function tokenFromFragment() {
  return new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
}

function managementApiPath(publicCode, suffix) {
  const encodedCode = encodeURIComponent(publicCode);
  return accountMode
    ? `/api/me/groups/${encodedCode}/${suffix}`
    : `/api/groups/${encodedCode}/${suffix}`;
}

async function managementHeaders() {
  if (!accountMode) {
    return { Authorization: `Bearer ${managementToken}` };
  }
  return window.AppAuth?.getAuthorizationHeaders
    ? window.AppAuth.getAuthorizationHeaders()
    : {};
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

function renderManagement(group) {
  currentGroup = group;
  groupCode.textContent = `團購代碼：${group.public_code}`;
  restaurantName.textContent = group.restaurant_name;
  groupState.textContent = group.status === "open" ? "團購進行中" : "團購已截止";
  groupState.dataset.state = group.status;
  closeGroupButton.hidden = group.status === "closed";
  closeGroupButton.disabled = false;
  orderCount.textContent = `${group.order_count} 張訂單`;
  downloadExcelButton.disabled = group.order_count === 0;
  downloadExcelButton.title = group.order_count === 0 ? "目前沒有訂單可匯出" : "下載目前畫面中的訂單資料";
  grandTotal.textContent = `總金額 ${formatPrice(group.grand_total)}`;
  summaryList.replaceChildren();
  emptySummary.hidden = group.summary.length > 0;
  const summariesByItem = new Map();
  group.summary.forEach((item) => {
    if (!summariesByItem.has(item.item_id)) {
      summariesByItem.set(item.item_id, []);
    }
    summariesByItem.get(item.item_id).push(item);
  });
  summariesByItem.forEach((items) => {
    const firstItem = items[0];
    const row = document.createElement("article");
    row.className = "summary-item";
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
    row.append(details, demands);
    summaryList.append(row);
  });

  ordersList.replaceChildren();
  emptyOrders.hidden = group.orders.length > 0;

  group.orders.forEach((order) => {
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

  textSummary.value = group.text_summary;

  statusPanel.hidden = true;
  managementContent.hidden = false;
}

async function loadManagement() {
  const publicCode = codeFromPath();
  const token = tokenFromFragment();
  if (!publicCode) {
    showError("缺少團購資訊，請從我的團購或完整管理連結重新進入。");
    return;
  }
  managementToken = token;
  accountMode = !token;
  claimGroupButton.hidden = accountMode;

  try {
    const headers = await managementHeaders();
    if (!headers.Authorization) {
      throw new Error("請先在首頁使用 Google 登入，再開啟我的團購。");
    }
    const response = await fetch(managementApiPath(publicCode, "management"), {
      headers,
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "團購管理資料暫時無法讀取，請稍後再試。",
      );
    }
    renderManagement(result);
  } catch (error) {
    showError(error.message || "團購管理資料暫時無法讀取，請稍後再試。");
  }
}

claimGroupButton.addEventListener("click", async () => {
  if (!currentGroup || !managementToken) return;
  claimGroupButton.disabled = true;
  try {
    const authHeaders = window.AppAuth?.getAuthorizationHeaders
      ? await window.AppAuth.getAuthorizationHeaders()
      : {};
    if (!authHeaders.Authorization) {
      throw new Error("請先在首頁使用 Google 登入，再保存這個團購。");
    }
    const response = await fetch(`/api/me/groups/${currentGroup.public_code}/claim`, {
      method: "POST",
      headers: { ...authHeaders, "X-Management-Token": managementToken },
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "團購暫時無法保存。");
    actionStatus.textContent = result.message;
    actionStatus.dataset.state = "success";
    actionStatus.hidden = false;
    claimGroupButton.hidden = true;
  } catch (error) {
    actionStatus.textContent = error.message || "團購暫時無法保存。";
    actionStatus.dataset.state = "error";
    actionStatus.hidden = false;
    claimGroupButton.disabled = false;
  }
});

closeGroupButton.addEventListener("click", async () => {
  if (!currentGroup || currentGroup.status === "closed") {
    return;
  }
  if (!window.confirm("確定要關閉團購嗎？關閉後其他人就不能再送出新訂單。")) {
    return;
  }

  closeGroupButton.disabled = true;
  actionStatus.textContent = "正在關閉團購…";
  actionStatus.dataset.state = "loading";
  actionStatus.hidden = false;
  try {
    const response = await fetch(managementApiPath(currentGroup.public_code, "close"), {
      method: "POST",
      headers: await managementHeaders(),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "團購暫時無法關閉，請稍後再試。",
      );
    }
    renderManagement(result);
    actionStatus.textContent = "團購已關閉，之後不再接受新訂單。";
    actionStatus.dataset.state = "success";
    actionStatus.hidden = false;
  } catch (error) {
    closeGroupButton.disabled = false;
    actionStatus.textContent = error.message || "團購暫時無法關閉，請稍後再試。";
    actionStatus.dataset.state = "error";
    actionStatus.hidden = false;
  }
});

copySummaryButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(textSummary.value);
    actionStatus.textContent = "文字摘要已複製，可以貼到通訊軟體。";
    actionStatus.dataset.state = "success";
    actionStatus.hidden = false;
  } catch (error) {
    textSummary.focus();
    textSummary.select();
    actionStatus.textContent = "瀏覽器無法自動複製，已選取文字，請按 Ctrl+C。";
    actionStatus.dataset.state = "error";
    actionStatus.hidden = false;
  }
});

downloadExcelButton.addEventListener("click", async () => {
  if (!currentGroup) return;
  downloadExcelButton.disabled = true;
  actionStatus.textContent = "正在整理 Excel 表格…";
  actionStatus.dataset.state = "loading";
  actionStatus.hidden = false;
  try {
    const latestResponse = await fetch(
      managementApiPath(currentGroup.public_code, "management"),
      {
        headers: await managementHeaders(),
        cache: "no-store",
      },
    );
    const latestGroup = await latestResponse.json();
    if (!latestResponse.ok) {
      throw new Error("無法取得最新訂單，請重新整理後再試一次。");
    }
    renderManagement(latestGroup);
    downloadExcelButton.disabled = true;
    if (latestGroup.order_count === 0) {
      throw new Error("目前還沒有使用者訂單，請有人完成送單後再下載。");
    }

    const response = await fetch(`${managementApiPath(currentGroup.public_code, "management.xlsx")}?download=${Date.now()}`, {
      headers: await managementHeaders(),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error("Excel 表格下載失敗，請稍後再試一次。");
    }
    if (Number(response.headers.get("X-Order-Count")) !== latestGroup.order_count) {
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
    link.download = `${currentGroup.restaurant_name}-${currentGroup.public_code}-團購訂單.xlsx`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    actionStatus.textContent = "Excel 表格已下載，內含餐點彙整與個人明細。";
    actionStatus.dataset.state = "success";
  } catch (error) {
    actionStatus.textContent = error.message;
    actionStatus.dataset.state = "error";
  } finally {
    downloadExcelButton.disabled = !currentGroup || currentGroup.order_count === 0;
  }
});

loadManagement();
