const MENU_URL = "/data/menu.json";
const ORDER_URL = "/api/orders";

const restaurantName = document.querySelector("#restaurant-name");
const menuStatus = document.querySelector("#menu-status");
const menuContent = document.querySelector("#menu-content");
const cartEmpty = document.querySelector("#cart-empty");
const cartItems = document.querySelector("#cart-items");
const cartTotal = document.querySelector("#cart-total");
const orderForm = document.querySelector("#order-form");
const customerName = document.querySelector("#customer-name");
const submitOrderButton = document.querySelector("#submit-order");
const orderStatus = document.querySelector("#order-status");
const itemQuantities = new Map();
const menuItemsById = new Map();
let loadedMenu = null;
let isSubmitting = false;

function formatPrice(amount) {
  return `NT$ ${amount.toLocaleString("zh-TW")}`;
}

function showStatus(message, state) {
  menuStatus.replaceChildren();
  menuStatus.dataset.state = state;
  menuStatus.textContent = message;
  menuStatus.hidden = false;
}

function getSelectedItems() {
  return Array.from(itemQuantities.entries())
    .filter(([, quantity]) => quantity > 0)
    .map(([itemId, quantity]) => ({
      item: menuItemsById.get(itemId),
      quantity,
    }))
    .filter(({ item }) => item);
}

function updateSubmitButton(selectedItemCount = getSelectedItems().length) {
  submitOrderButton.disabled = isSubmitting || selectedItemCount === 0;
  submitOrderButton.textContent = isSubmitting ? "訂單送出中…" : "送出訂單";
}

function showOrderStatus(message, state) {
  orderStatus.textContent = message;
  orderStatus.dataset.state = state;
  orderStatus.hidden = false;
}

function renderCart() {
  const selectedItems = getSelectedItems();

  cartItems.replaceChildren();
  cartEmpty.hidden = selectedItems.length > 0;

  let total = 0;
  const fragment = document.createDocumentFragment();

  selectedItems.forEach(({ item, quantity }) => {
    const subtotal = item.price * quantity;
    total += subtotal;

    const listItem = document.createElement("li");
    listItem.className = "cart-item";

    const heading = document.createElement("div");
    heading.className = "cart-item-heading";

    const name = document.createElement("span");
    name.className = "cart-item-name";
    name.textContent = item.name;

    const subtotalText = document.createElement("span");
    subtotalText.className = "cart-item-subtotal";
    subtotalText.textContent = formatPrice(subtotal);

    const details = document.createElement("div");
    details.className = "cart-item-details";

    const unitPrice = document.createElement("span");
    unitPrice.textContent = `單價 ${formatPrice(item.price)}`;

    const quantityText = document.createElement("span");
    quantityText.textContent = `數量 ${quantity}`;

    heading.append(name, subtotalText);
    details.append(unitPrice, quantityText);
    listItem.append(heading, details);
    fragment.append(listItem);
  });

  cartItems.append(fragment);
  cartTotal.textContent = formatPrice(total);
  updateSubmitButton(selectedItems.length);
}

function createQuantityControl(item) {
  const control = document.createElement("div");
  control.className = "quantity-control";
  control.setAttribute("aria-label", `${item.name} 數量調整`);

  const label = document.createElement("span");
  label.className = "quantity-label";
  label.textContent = "數量";

  const decreaseButton = document.createElement("button");
  decreaseButton.type = "button";
  decreaseButton.className = "quantity-button";
  decreaseButton.setAttribute("aria-label", `減少 ${item.name} 數量`);
  decreaseButton.textContent = "−";

  const quantityValue = document.createElement("output");
  quantityValue.className = "quantity-value";
  quantityValue.setAttribute("aria-live", "polite");

  const increaseButton = document.createElement("button");
  increaseButton.type = "button";
  increaseButton.className = "quantity-button";
  increaseButton.setAttribute("aria-label", `增加 ${item.name} 數量`);
  increaseButton.textContent = "+";

  function updateQuantity(nextQuantity) {
    const quantity = Math.max(0, nextQuantity);
    itemQuantities.set(item.id, quantity);
    quantityValue.value = quantity;
    quantityValue.textContent = quantity;
    decreaseButton.disabled = quantity === 0;
    renderCart();
  }

  decreaseButton.addEventListener("click", () => {
    updateQuantity((itemQuantities.get(item.id) ?? 0) - 1);
  });

  increaseButton.addEventListener("click", () => {
    updateQuantity((itemQuantities.get(item.id) ?? 0) + 1);
  });

  updateQuantity(itemQuantities.get(item.id) ?? 0);
  control.append(label, decreaseButton, quantityValue, increaseButton);

  return control;
}

function createMenuItem(item) {
  const article = document.createElement("article");
  article.className = "menu-item";
  menuItemsById.set(item.id, item);

  if (item.available === false) {
    article.classList.add("is-unavailable");
  }

  const name = document.createElement("h3");
  name.className = "item-name";
  name.textContent = item.name;

  const price = document.createElement("p");
  price.className = "item-price";
  price.textContent = formatPrice(item.price);

  const description = document.createElement("p");
  description.className = "item-description";
  description.textContent = item.description || "暫無餐點說明";

  article.append(name, price, description);

  if (item.available === false) {
    const availability = document.createElement("span");
    availability.className = "availability";
    availability.textContent = "暫停供應";
    article.append(availability);
  } else {
    article.append(createQuantityControl(item));
  }

  return article;
}

function renderMenu(menu) {
  const categories = Array.isArray(menu.categories) ? menu.categories : [];
  const visibleCategories = categories.filter(
    (category) => Array.isArray(category.items) && category.items.length > 0,
  );

  restaurantName.textContent = menu.restaurant?.name || "餐廳菜單";
  document.title = `線上菜單｜${restaurantName.textContent}`;
  loadedMenu = menu;
  itemQuantities.clear();
  menuItemsById.clear();
  renderCart();
  menuContent.replaceChildren();

  if (visibleCategories.length === 0) {
    showStatus("目前沒有可顯示的餐點", "empty");
    return;
  }

  const fragment = document.createDocumentFragment();

  visibleCategories.forEach((category) => {
    const section = document.createElement("section");
    section.className = "category-section";
    section.setAttribute("aria-labelledby", `category-${category.id}`);

    const heading = document.createElement("h2");
    heading.id = `category-${category.id}`;
    heading.className = "category-heading";
    heading.textContent = category.name;

    const itemGrid = document.createElement("div");
    itemGrid.className = "item-grid";
    category.items.forEach((item) => itemGrid.append(createMenuItem(item)));

    section.append(heading, itemGrid);
    fragment.append(section);
  });

  menuContent.append(fragment);
  menuStatus.hidden = true;
}

function createOrderPayload(name) {
  const items = getSelectedItems().map(({ item, quantity }) => ({
    item_id: item.id,
    item_name: item.name,
    unit_price: item.price,
    quantity,
    subtotal: item.price * quantity,
  }));

  return {
    customer_name: name,
    items,
    total_amount: items.reduce((sum, item) => sum + item.subtotal, 0),
  };
}

orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (isSubmitting) {
    return;
  }

  const name = customerName.value.trim();
  const selectedItems = getSelectedItems();

  if (!name) {
    showOrderStatus("請先輸入取餐姓名。", "error");
    customerName.focus();
    return;
  }

  if (selectedItems.length === 0) {
    showOrderStatus("請先選擇至少一項餐點。", "error");
    return;
  }

  isSubmitting = true;
  updateSubmitButton(selectedItems.length);
  showOrderStatus("訂單送出中，請稍候。", "loading");

  try {
    const response = await fetch(ORDER_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(createOrderPayload(name)),
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string" ? result.detail : `HTTP ${response.status}`,
      );
    }

    customerName.value = "";
    if (loadedMenu) {
      renderMenu(loadedMenu);
    }
    showOrderStatus(`訂單已送出，訂單編號 ${result.order_id}。`, "success");
  } catch (error) {
    console.error("訂單送出失敗：", error);
    showOrderStatus("訂單暫時無法送出，請稍後再試。", "error");
  } finally {
    isSubmitting = false;
    updateSubmitButton();
  }
});

async function loadMenu() {
  try {
    const response = await fetch(MENU_URL);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const menu = await response.json();
    renderMenu(menu);
  } catch (error) {
    console.error("菜單載入失敗：", error);
    showStatus("菜單暫時無法載入，請確認伺服器已啟動後再重新整理頁面。", "error");
  }
}

loadMenu();
