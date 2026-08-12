const restaurantName = document.querySelector("#restaurant-name");
const statusPanel = document.querySelector("#store-status");
const storeContent = document.querySelector("#store-content");
const serviceState = document.querySelector("#service-state");
const menuContent = document.querySelector("#menu-content");
const emptyMenu = document.querySelector("#empty-menu");
const storeQr = document.querySelector("#store-qr");
const publicLink = document.querySelector("#public-link");
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
let currentStore = null;
let isSubmitting = false;

function slugFromPath() {
  const match = window.location.pathname.match(/^\/stores\/([a-z]{8})$/);
  return match ? match[1] : "";
}

function formatPrice(price) {
  return `NT$ ${price.toLocaleString("zh-TW")}`;
}

function showError(message) {
  statusPanel.textContent = message;
  statusPanel.dataset.state = "error";
  statusPanel.hidden = false;
  storeContent.hidden = true;
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
  submitOrder.disabled =
    isSubmitting || !currentStore?.active || selectedItems().length === 0;
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

  decrease.addEventListener("click", () =>
    setQuantity((itemQuantities.get(item.id) ?? 0) - 1),
  );
  increase.addEventListener("click", () =>
    setQuantity((itemQuantities.get(item.id) ?? 0) + 1),
  );
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
  const card = document.createElement("article");
  card.className = "menu-item";
  if (!item.available) card.classList.add("is-unavailable");
  const details = document.createElement("div");
  const name = document.createElement("h3");
  name.textContent = item.name;
  details.append(name);
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
    card.append(details, priceArea, noteField);
    return card;
  }
  card.append(details, priceArea);
  return card;
}

function createVariantMenuItem(baseName, variants, canOrder) {
  const card = document.createElement("article");
  card.className = "menu-item menu-variant-item";
  const heading = document.createElement("h3");
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
  card.append(heading, options);
  return card;
}

function renderStore(store) {
  currentStore = store;
  restaurantName.textContent = store.menu.restaurant.name;
  document.title = `${store.menu.restaurant.name}｜線上點餐`;
  serviceState.textContent = store.active ? "目前開放點餐" : "目前暫停接單";
  serviceState.dataset.state = store.active ? "active" : "inactive";
  menuContent.replaceChildren();
  itemQuantities.clear();
  itemNotes.clear();
  menuItemsById.clear();
  orderStatus.hidden = true;
  customerName.value = "";
  let itemCount = 0;

  store.menu.categories.forEach((category) => {
    if (!category.items.length) return;
    const section = document.createElement("section");
    section.className = "menu-category";
    const heading = document.createElement("h2");
    heading.textContent = category.name;
    const list = document.createElement("div");
    list.className = "menu-items";
    category.items.forEach((item) => {
      itemCount += 1;
      menuItemsById.set(item.id, item);
    });
    MenuVariants.groupItems(category.items).forEach((itemGroup) => {
      if (itemGroup.type === "variants") {
        list.append(createVariantMenuItem(itemGroup.baseName, itemGroup.variants, store.active));
      } else {
        list.append(createRegularMenuItem(itemGroup.item, store.active));
      }
    });
    section.append(heading, list);
    menuContent.append(section);
  });

  emptyMenu.hidden = itemCount > 0;
  cartPanel.hidden = !store.active;
  const fixedUrl = new URL(`/stores/${store.public_slug}`, window.location.origin);
  publicLink.href = fixedUrl.href;
  publicLink.textContent = fixedUrl.href;
  storeQr.src = `/api/stores/${store.public_slug}/qr.svg`;
  renderCart();
  statusPanel.hidden = true;
  storeContent.hidden = false;
}

orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting || !currentStore?.active) return;
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
    const authHeaders = window.AppAuth?.getAuthorizationHeaders
      ? await window.AppAuth.getAuthorizationHeaders()
      : {};
    const response = await fetch(`/api/stores/${currentStore.public_slug}/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
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
      document.createTextNode(
        `訂單已送出！你的訂單編號是 ${result.public_order_number}。 `,
      ),
      orderLink,
    );
    orderStatus.dataset.state = "success";
    orderStatus.hidden = false;
    itemQuantities.forEach((_, itemId) => itemQuantities.set(itemId, 0));
    itemNotes.clear();
    menuContent.querySelectorAll(".quantity-control output").forEach((output) => {
      output.textContent = "0";
    });
    menuContent
      .querySelectorAll(".quantity-control button:first-child")
      .forEach((button) => {
        button.disabled = true;
      });
    menuContent.querySelectorAll(".item-note-field input").forEach((input) => {
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

async function loadStore() {
  const slug = slugFromPath();
  if (!slug) {
    showError("店家網址格式不正確，請確認完整網址。");
    return;
  }
  try {
    const response = await fetch(`/api/stores/${slug}`);
    const result = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "店家菜單暫時無法讀取，請稍後再試。",
      );
    }
    renderStore(result);
  } catch (error) {
    showError(error.message || "店家菜單暫時無法讀取，請稍後再試。");
  }
}

loadStore();
