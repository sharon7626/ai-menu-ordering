const CODE_PATTERN = /^[A-HJ-NP-Z2-9]{6}$/;

const codeForm = document.querySelector("#code-form");
const codeInput = document.querySelector("#group-code");
const codeStatus = document.querySelector("#code-status");
const menuSection = document.querySelector("#menu-section");
const restaurantName = document.querySelector("#restaurant-name");
const groupLabel = document.querySelector("#group-label");
const groupState = document.querySelector("#group-state");
const menuContent = document.querySelector("#menu-content");
const emptyMenu = document.querySelector("#empty-menu");
const cartPanel = document.querySelector("#cart-panel");
const cartEmpty = document.querySelector("#cart-empty");
const cartItems = document.querySelector("#cart-items");
const cartTotal = document.querySelector("#cart-total");
const orderForm = document.querySelector("#order-form");
const customerName = document.querySelector("#customer-name");
const submitOrder = document.querySelector("#submit-order");
const orderStatus = document.querySelector("#order-status");
const itemQuantities = new Map();
const itemNotes = new Map();
const menuItemsById = new Map();
let currentGroup = null;
let isSubmitting = false;

function showStatus(message, state) {
  codeStatus.textContent = message;
  codeStatus.dataset.state = state;
  codeStatus.hidden = false;
}

function normalizeCode(value) {
  return value.trim().toUpperCase();
}

function codeFromPath() {
  const match = window.location.pathname.match(/^\/groups\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : "";
}

function formatPrice(price) {
  return `NT$ ${price.toLocaleString("zh-TW")}`;
}

function selectedItems() {
  return [...itemQuantities.entries()]
    .filter(([, quantity]) => quantity > 0)
    .map(([itemId, quantity]) => ({
      item: menuItemsById.get(itemId),
      quantity,
      note: itemNotes.get(itemId)?.trim() ?? "",
    }))
    .filter(({ item }) => item);
}

function updateSubmitButton() {
  submitOrder.disabled = isSubmitting || selectedItems().length === 0;
  submitOrder.textContent = isSubmitting ? "訂單送出中…" : "送出訂單";
}

function renderCart() {
  const selections = selectedItems();
  cartItems.replaceChildren();
  cartEmpty.hidden = selections.length > 0;
  let total = 0;

  selections.forEach(({ item, quantity, note }) => {
    const subtotal = item.price * quantity;
    total += subtotal;
    const row = document.createElement("li");
    const details = document.createElement("span");
    details.textContent = note
      ? `${item.name} × ${quantity}｜備註：${note}`
      : `${item.name} × ${quantity}`;
    const amount = document.createElement("strong");
    amount.textContent = formatPrice(subtotal);
    row.append(details, amount);
    cartItems.append(row);
  });

  cartTotal.textContent = formatPrice(total);
  updateSubmitButton();
}

function createQuantityControl(item, noteField) {
  const control = document.createElement("div");
  control.className = "quantity-control";
  control.setAttribute("aria-label", `${item.name} 數量調整`);

  const decrease = document.createElement("button");
  decrease.type = "button";
  decrease.textContent = "−";
  decrease.setAttribute("aria-label", `減少 ${item.name} 數量`);

  const quantity = document.createElement("output");
  quantity.textContent = "0";

  const increase = document.createElement("button");
  increase.type = "button";
  increase.textContent = "+";
  increase.setAttribute("aria-label", `增加 ${item.name} 數量`);

  function setQuantity(value) {
    const nextValue = Math.max(0, value);
    itemQuantities.set(item.id, nextValue);
    quantity.textContent = String(nextValue);
    decrease.disabled = nextValue === 0;
    noteField.hidden = nextValue === 0;
    if (nextValue === 0) {
      const noteInput = noteField.querySelector("input");
      noteInput.value = "";
      itemNotes.delete(item.id);
    }
    renderCart();
  }

  decrease.addEventListener("click", () => setQuantity((itemQuantities.get(item.id) ?? 0) - 1));
  increase.addEventListener("click", () => setQuantity((itemQuantities.get(item.id) ?? 0) + 1));
  setQuantity(0);
  control.append(decrease, quantity, increase);
  return control;
}

function createItemNoteField(item) {
  const field = document.createElement("label");
  field.className = "item-note-field";
  const label = document.createElement("span");
  label.textContent = "餐點備註（選填）";
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 200;
  input.placeholder = "例如：小辣、半糖少冰";
  input.setAttribute("aria-label", `${item.name} 餐點備註`);
  input.addEventListener("input", () => {
    itemNotes.set(item.id, input.value);
    renderCart();
  });
  field.append(label, input);
  return field;
}

function createRegularMenuItem(item, canOrder) {
  const article = document.createElement("article");
  article.className = "menu-item";
  const details = document.createElement("div");
  const itemName = document.createElement("h4");
  itemName.textContent = item.name;
  details.append(itemName);
  if (item.description) {
    const description = document.createElement("p");
    description.textContent = item.description;
    details.append(description);
  }
  const priceArea = document.createElement("div");
  priceArea.className = "price-area";
  const price = document.createElement("strong");
  price.textContent = formatPrice(item.price);
  priceArea.append(price);
  if (!item.available) {
    const unavailable = document.createElement("span");
    unavailable.textContent = "暫停供應";
    priceArea.append(unavailable);
  } else if (canOrder) {
    const noteField = createItemNoteField(item);
    noteField.hidden = true;
    priceArea.append(createQuantityControl(item, noteField));
    article.append(details, priceArea, noteField);
    return article;
  }
  article.append(details, priceArea);
  return article;
}

function createVariantMenuItem(baseName, variants, canOrder) {
  const article = document.createElement("article");
  article.className = "menu-item menu-variant-item";
  const heading = document.createElement("h4");
  heading.className = "menu-variant-name";
  heading.textContent = baseName;
  const options = document.createElement("div");
  options.className = "menu-variant-options";
  variants.forEach(({ item, variant }) => {
    const option = document.createElement("div");
    option.className = "menu-variant-option";
    const summary = document.createElement("div");
    summary.className = "variant-summary";
    const size = document.createElement("strong");
    size.textContent = variant.variantName;
    const price = document.createElement("span");
    price.textContent = formatPrice(item.price);
    summary.append(size, price);
    option.append(summary);
    if (!item.available) {
      const unavailable = document.createElement("span");
      unavailable.className = "variant-unavailable";
      unavailable.textContent = "暫停供應";
      option.append(unavailable);
    } else if (canOrder) {
      const noteField = createItemNoteField(item);
      noteField.hidden = true;
      option.append(createQuantityControl(item, noteField), noteField);
    }
    options.append(option);
  });
  article.append(heading, options);
  return article;
}

function renderMenu(group) {
  currentGroup = group;
  restaurantName.textContent = group.menu.restaurant.name;
  groupLabel.textContent = `團購代碼：${group.public_code}`;
  menuContent.replaceChildren();
  itemQuantities.clear();
  itemNotes.clear();
  menuItemsById.clear();
  orderStatus.hidden = true;
  customerName.value = "";
  emptyMenu.hidden = true;

  if (group.status === "closed") {
    groupState.textContent = "這個團購已截止，目前不能再新增訂單。";
    groupState.dataset.state = "closed";
    groupState.hidden = false;
    cartPanel.hidden = true;
  } else {
    groupState.textContent = "團購進行中";
    groupState.dataset.state = "open";
    groupState.hidden = false;
    cartPanel.hidden = false;
  }

  let itemCount = 0;
  group.menu.categories.forEach((category) => {
    if (!category.items.length) {
      return;
    }
    const categorySection = document.createElement("section");
    categorySection.className = "menu-category";

    const title = document.createElement("h3");
    title.textContent = category.name;
    categorySection.append(title);

    const itemList = document.createElement("div");
    itemList.className = "menu-items";
    category.items.forEach((item) => {
      menuItemsById.set(item.id, item);
      itemCount += 1;
    });
    MenuVariants.groupItems(category.items).forEach((itemGroup) => {
      if (itemGroup.type === "variants") {
        itemList.append(
          createVariantMenuItem(itemGroup.baseName, itemGroup.variants, group.status === "open"),
        );
      } else {
        itemList.append(createRegularMenuItem(itemGroup.item, group.status === "open"));
      }
    });
    categorySection.append(itemList);
    menuContent.append(categorySection);
  });

  emptyMenu.hidden = itemCount > 0;
  renderCart();
  menuSection.hidden = false;
}

orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting || !currentGroup) {
    return;
  }

  const name = customerName.value.trim();
  const selections = selectedItems();
  if (!name) {
    orderStatus.textContent = "請先輸入取餐姓名。";
    orderStatus.dataset.state = "error";
    orderStatus.hidden = false;
    customerName.focus();
    return;
  }
  if (!selections.length) {
    orderStatus.textContent = "請先選擇至少一項餐點。";
    orderStatus.dataset.state = "error";
    orderStatus.hidden = false;
    return;
  }

  isSubmitting = true;
  updateSubmitButton();
  orderStatus.textContent = "訂單送出中，請稍候。";
  orderStatus.dataset.state = "loading";
  orderStatus.hidden = false;
  try {
    const response = await fetch(`/api/groups/${currentGroup.public_code}/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_name: name,
        items: selections.map(({ item, quantity, note }) => ({
          item_id: item.id,
          quantity,
          note,
        })),
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "訂單暫時無法送出，請稍後再試。",
      );
    }

    const orderUrl = new URL(result.order_url, window.location.origin);
    const orderLink = document.createElement("a");
    orderLink.href = orderUrl.href;
    orderLink.textContent = `查看個人訂單 ${result.public_order_number}`;
    orderStatus.replaceChildren(
      document.createTextNode(`訂單已送出！你的訂單編號是 ${result.public_order_number}。 `),
      orderLink,
    );
    orderStatus.dataset.state = "success";
    orderStatus.hidden = false;
    itemQuantities.forEach((_, itemId) => itemQuantities.set(itemId, 0));
    itemNotes.clear();
    menuSection.querySelectorAll(".quantity-control output").forEach((output) => {
      output.textContent = "0";
    });
    menuSection.querySelectorAll(".quantity-control button:first-child").forEach((button) => {
      button.disabled = true;
    });
    menuSection.querySelectorAll(".item-note-field input").forEach((input) => {
      input.value = "";
    });
    renderCart();
  } catch (error) {
    orderStatus.textContent = error.message || "訂單暫時無法送出，請稍後再試。";
    orderStatus.dataset.state = "error";
    orderStatus.hidden = false;
  } finally {
    isSubmitting = false;
    updateSubmitButton();
  }
});

async function loadGroup(code) {
  showStatus("菜單載入中", "loading");
  menuSection.hidden = true;
  try {
    const response = await fetch(`/api/groups/${encodeURIComponent(code)}`);
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "菜單讀取失敗，請稍後再試。",
      );
    }
    renderMenu(result);
    codeStatus.hidden = true;
  } catch (error) {
    showStatus(error.message || "菜單讀取失敗，請稍後再試。", "error");
  }
}

codeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const code = normalizeCode(codeInput.value);
  codeInput.value = code;
  if (!CODE_PATTERN.test(code)) {
    showStatus("請輸入正確的 6 碼團購代碼。", "error");
    codeInput.focus();
    return;
  }
  window.location.assign(`/groups/${code}`);
});

const initialCode = normalizeCode(codeFromPath());
if (initialCode) {
  codeInput.value = initialCode;
  if (CODE_PATTERN.test(initialCode)) {
    loadGroup(initialCode);
  } else {
    showStatus("分享連結中的團購代碼格式不正確。", "error");
  }
}
