const UPLOAD_URL = "/api/menu-uploads";
const GROUPS_URL = "/api/groups";
const STORES_URL = "/api/stores";
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ALLOWED_TYPES = new Map([
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".png", "image/png"],
  [".pdf", "application/pdf"],
]);

const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#menu-file");
const fileSummary = document.querySelector("#file-summary");
const fileName = document.querySelector("#file-name");
const fileSize = document.querySelector("#file-size");
const menuPreviewPanel = document.querySelector("#menu-preview-panel");
const menuPreviewCanvas = document.querySelector("#menu-preview-canvas");
const pdfPreview = document.querySelector("#pdf-preview");
const cropHelp = document.querySelector("#crop-help");
const startCropButton = document.querySelector("#start-crop");
const cropActions = document.querySelector("#crop-actions");
const applyCropButton = document.querySelector("#apply-crop");
const cancelCropButton = document.querySelector("#cancel-crop");
const resetCropButton = document.querySelector("#reset-crop");
const uploadButton = document.querySelector("#upload-button");
const uploadStatus = document.querySelector("#upload-status");
const recognitionResult = document.querySelector("#recognition-result");
const recognitionContent = document.querySelector("#recognition-content");
const recognitionWarnings = document.querySelector("#recognition-warnings");
const reviewForm = document.querySelector("#review-form");
const confirmButton = document.querySelector("#confirm-button");
const storeButton = document.querySelector("#store-button");
const reviewStatus = document.querySelector("#review-status");
const groupCreated = document.querySelector("#group-created");
const groupCode = document.querySelector("#group-code");
const participantLink = document.querySelector("#participant-link");
const managementLink = document.querySelector("#management-link");
const openParticipantLink = document.querySelector("#open-participant-link");
const openManagementLink = document.querySelector("#open-management-link");
const copyGroupCode = document.querySelector("#copy-group-code");
const copyCodeStatus = document.querySelector("#copy-code-status");
const storeCreated = document.querySelector("#store-created");
const storePublicLink = document.querySelector("#store-public-link");
const storeManagementLink = document.querySelector("#store-management-link");
const storeUpdateLink = document.querySelector("#store-update-link");
const scopeDescription = document.querySelector("#scope-description");
const requestedMode = new URLSearchParams(window.location.search).get("mode");
let isUploading = false;
let isSavingMenu = false;
let latestRecognition = null;
let confirmedRecognition = null;
let previewObjectUrl = "";
let previewImage = null;
let cropSelection = null;
let cropStart = null;
let croppedUploadFile = null;
let appliedCrop = null;
let isSelectingCrop = false;

function getStoreUpdateContext() {
  const match = window.location.pathname.match(/^\/stores\/([a-z]{8})\/menu-update$/);
  if (!match) {
    return null;
  }
  return {
    publicSlug: match[1],
    token: new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "",
  };
}

const storeUpdateContext = getStoreUpdateContext();
if (storeUpdateContext) {
  document.querySelector(".eyebrow").textContent = "店家管理";
  document.querySelector("h1").textContent = "更新固定菜單";
  confirmButton.hidden = true;
  storeButton.textContent = "確認並更新固定菜單";
  scopeDescription.textContent = "重新上傳並確認後，只會更新這家店目前的固定菜單；固定網址與既有訂單內容不會改變。";
} else {
  if (requestedMode === "group") {
    document.querySelector(".eyebrow").textContent = "一般團購｜主揪建立團購";
    document.querySelector("h1").textContent = "建立新團購";
    document.querySelector(".header-inner > p:last-child").textContent = "上傳這次要訂的菜單，AI 會自動讀取菜名與價格。";
    document.title = "建立團購｜AI 菜單點餐系統";
    storeButton.hidden = true;
    scopeDescription.textContent = "主揪上傳並確認菜單後，系統會產生參與連結與 6 碼代碼。一起點餐的人只要開啟連結或在首頁輸入代碼，不需要重新上傳菜單。";
  } else if (requestedMode === "store") {
    document.querySelector(".eyebrow").textContent = "店家模式";
    document.querySelector("h1").textContent = "建立店家固定菜單";
    document.title = "建立店家菜單｜AI 菜單點餐系統";
    confirmButton.hidden = true;
    scopeDescription.textContent = "確認菜單後會建立店家固定網址、QR Code 與私密管理連結，供店家長期使用。";
  }
}

function showStatus(message, state) {
  uploadStatus.textContent = message;
  uploadStatus.dataset.state = state;
  uploadStatus.hidden = false;
}

function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getExtension(filename) {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

function validateSelectedFile(file) {
  if (!file) {
    return "請選擇一個菜單檔案。";
  }
  if (file.size === 0) {
    return "這個檔案是空的，請重新選擇菜單檔案。";
  }

  const extension = getExtension(file.name);
  if (!ALLOWED_TYPES.has(extension)) {
    return "檔案格式不支援，請上傳 JPG、PNG 或一頁式 PDF。";
  }
  if (file.type !== ALLOWED_TYPES.get(extension)) {
    return "檔案內容與副檔名不一致，請重新匯出後再上傳。";
  }
  if (file.size > MAX_FILE_SIZE) {
    return "檔案超過 10 MB，請縮小檔案後再試一次。";
  }
  return "";
}

function clearPreviewObjectUrl() {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = "";
  }
}

function canvasPoint(event) {
  const bounds = menuPreviewCanvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(menuPreviewCanvas.width, (event.clientX - bounds.left) * menuPreviewCanvas.width / bounds.width)),
    y: Math.max(0, Math.min(menuPreviewCanvas.height, (event.clientY - bounds.top) * menuPreviewCanvas.height / bounds.height)),
  };
}

function normalizedSelection(start, end) {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

function setCanvasForSource(source) {
  const longestWidth = 1200;
  const scale = Math.min(1, longestWidth / source.width);
  menuPreviewCanvas.width = Math.max(1, Math.round(source.width * scale));
  menuPreviewCanvas.height = Math.max(1, Math.round(source.height * scale));
}

function drawPreview() {
  if (!previewImage) return;
  const context = menuPreviewCanvas.getContext("2d");
  context.clearRect(0, 0, menuPreviewCanvas.width, menuPreviewCanvas.height);
  if (appliedCrop && !isSelectingCrop) {
    context.drawImage(
      previewImage,
      appliedCrop.x,
      appliedCrop.y,
      appliedCrop.width,
      appliedCrop.height,
      0,
      0,
      menuPreviewCanvas.width,
      menuPreviewCanvas.height,
    );
    return;
  }
  context.drawImage(previewImage, 0, 0, menuPreviewCanvas.width, menuPreviewCanvas.height);
  if (cropSelection && isSelectingCrop) {
    context.fillStyle = "rgba(20, 25, 22, 0.5)";
    context.fillRect(0, 0, menuPreviewCanvas.width, menuPreviewCanvas.height);
    context.save();
    context.beginPath();
    context.rect(cropSelection.x, cropSelection.y, cropSelection.width, cropSelection.height);
    context.clip();
    context.drawImage(previewImage, 0, 0, menuPreviewCanvas.width, menuPreviewCanvas.height);
    context.restore();
    context.strokeStyle = "#ff9f0a";
    context.lineWidth = Math.max(2, menuPreviewCanvas.width / 400);
    context.strokeRect(cropSelection.x, cropSelection.y, cropSelection.width, cropSelection.height);
  }
}

function showImagePreview(file) {
  previewObjectUrl = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => {
    previewImage = image;
    appliedCrop = null;
    setCanvasForSource(image);
    drawPreview();
    menuPreviewCanvas.hidden = false;
    pdfPreview.hidden = true;
    startCropButton.hidden = false;
    cropHelp.textContent = "確認圖片清楚後即可辨識；也可以框選只想交給 AI 辨識的區域。";
  };
  image.onerror = () => showStatus("圖片預覽失敗，請重新選擇檔案。", "error");
  image.src = previewObjectUrl;
}

function showPdfPreview(file) {
  previewObjectUrl = URL.createObjectURL(file);
  previewImage = null;
  menuPreviewCanvas.hidden = true;
  pdfPreview.data = previewObjectUrl;
  pdfPreview.hidden = false;
  startCropButton.hidden = true;
  cropHelp.textContent = "PDF 可以在這裡預覽；第一版裁切辨識範圍只支援 JPG 與 PNG。";
}

function resetPreview(file) {
  clearPreviewObjectUrl();
  previewImage = null;
  cropSelection = null;
  cropStart = null;
  croppedUploadFile = null;
  appliedCrop = null;
  isSelectingCrop = false;
  menuPreviewCanvas.classList.remove("is-cropping");
  cropActions.hidden = true;
  resetCropButton.hidden = true;
  pdfPreview.removeAttribute("data");
  menuPreviewPanel.hidden = !file;
  if (!file) return;
  if (file.type === "application/pdf") {
    showPdfPreview(file);
  } else {
    showImagePreview(file);
  }
}

function updateSelection() {
  const file = fileInput.files[0];
  const errorMessage = validateSelectedFile(file);

  fileSummary.hidden = !file;
  if (file) {
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
  }
  resetPreview(errorMessage ? null : file);

  uploadButton.disabled = isUploading || Boolean(errorMessage);
  if (errorMessage && file) {
    showStatus(errorMessage, "error");
  } else {
    uploadStatus.hidden = true;
  }
  recognitionResult.hidden = true;
  recognitionContent.replaceChildren();
  recognitionWarnings.replaceChildren();
  reviewStatus.hidden = true;
  groupCreated.hidden = true;
  storeCreated.hidden = true;
  latestRecognition = null;
  confirmedRecognition = null;
}

menuPreviewCanvas.addEventListener("pointerdown", (event) => {
  if (!isSelectingCrop) return;
  cropStart = canvasPoint(event);
  cropSelection = { x: cropStart.x, y: cropStart.y, width: 0, height: 0 };
  menuPreviewCanvas.setPointerCapture(event.pointerId);
  applyCropButton.disabled = true;
  drawPreview();
});

menuPreviewCanvas.addEventListener("pointermove", (event) => {
  if (!isSelectingCrop || !cropStart || !menuPreviewCanvas.hasPointerCapture(event.pointerId)) return;
  cropSelection = normalizedSelection(cropStart, canvasPoint(event));
  applyCropButton.disabled = cropSelection.width < 20 || cropSelection.height < 20;
  drawPreview();
});

menuPreviewCanvas.addEventListener("pointerup", (event) => {
  if (!isSelectingCrop || !cropStart) return;
  cropSelection = normalizedSelection(cropStart, canvasPoint(event));
  cropStart = null;
  applyCropButton.disabled = cropSelection.width < 20 || cropSelection.height < 20;
  drawPreview();
});

startCropButton.addEventListener("click", () => {
  if (!previewImage) return;
  appliedCrop = null;
  croppedUploadFile = null;
  isSelectingCrop = true;
  cropSelection = null;
  setCanvasForSource(previewImage);
  menuPreviewCanvas.classList.add("is-cropping");
  cropActions.hidden = false;
  resetCropButton.hidden = true;
  applyCropButton.disabled = true;
  cropHelp.textContent = "請在圖片上按住並拖曳，框住這次要辨識的菜單區域。";
  drawPreview();
});

cancelCropButton.addEventListener("click", () => {
  isSelectingCrop = false;
  cropSelection = null;
  menuPreviewCanvas.classList.remove("is-cropping");
  cropActions.hidden = true;
  cropHelp.textContent = "已取消框選，AI 會辨識整張圖片。";
  drawPreview();
});

applyCropButton.addEventListener("click", () => {
  if (!previewImage || !cropSelection || applyCropButton.disabled) return;
  const scaleX = previewImage.naturalWidth / menuPreviewCanvas.width;
  const scaleY = previewImage.naturalHeight / menuPreviewCanvas.height;
  const sourceCrop = {
    x: Math.round(cropSelection.x * scaleX),
    y: Math.round(cropSelection.y * scaleY),
    width: Math.max(1, Math.round(cropSelection.width * scaleX)),
    height: Math.max(1, Math.round(cropSelection.height * scaleY)),
  };
  const longestSide = 2200;
  const outputScale = Math.min(1, longestSide / Math.max(sourceCrop.width, sourceCrop.height));
  const output = document.createElement("canvas");
  output.width = Math.max(1, Math.round(sourceCrop.width * outputScale));
  output.height = Math.max(1, Math.round(sourceCrop.height * outputScale));
  const outputContext = output.getContext("2d");
  outputContext.fillStyle = "#fff";
  outputContext.fillRect(0, 0, output.width, output.height);
  outputContext.drawImage(
    previewImage,
    sourceCrop.x,
    sourceCrop.y,
    sourceCrop.width,
    sourceCrop.height,
    0,
    0,
    output.width,
    output.height,
  );
  output.toBlob((blob) => {
    if (!blob) {
      showStatus("無法套用選取範圍，請重新框選。", "error");
      return;
    }
    croppedUploadFile = new File([blob], "menu-selected-area.jpg", { type: "image/jpeg" });
    appliedCrop = sourceCrop;
    isSelectingCrop = false;
    cropSelection = null;
    menuPreviewCanvas.classList.remove("is-cropping");
    cropActions.hidden = true;
    resetCropButton.hidden = false;
    setCanvasForSource({ width: sourceCrop.width, height: sourceCrop.height });
    cropHelp.textContent = "已套用框選範圍，AI 只會辨識目前顯示的區域。";
    drawPreview();
  }, "image/jpeg", 0.94);
});

resetCropButton.addEventListener("click", () => {
  croppedUploadFile = null;
  appliedCrop = null;
  cropSelection = null;
  isSelectingCrop = false;
  resetCropButton.hidden = true;
  setCanvasForSource(previewImage);
  cropHelp.textContent = "已還原整張圖片，AI 會辨識完整菜單。";
  drawPreview();
});

function createReviewField({ labelText, value, type = "text", fieldName }) {
  const wrapper = document.createElement("div");
  wrapper.className = "review-field";

  const inputId = `review-${fieldName}`;
  const label = document.createElement("label");
  label.htmlFor = inputId;
  label.textContent = labelText;

  const input = document.createElement("input");
  input.id = inputId;
  input.name = fieldName;
  input.type = type;
  input.value = value ?? "";
  input.required = true;
  input.setAttribute("aria-invalid", "false");
  if (type === "number") {
    input.min = "0";
    input.step = "1";
    input.inputMode = "numeric";
  }

  const error = document.createElement("p");
  error.className = "field-error";
  error.id = `${inputId}-error`;
  error.hidden = true;
  input.setAttribute("aria-describedby", error.id);

  wrapper.append(label, input, error);
  return { wrapper, input, error };
}

function showFieldError(field, message) {
  field.input.setAttribute("aria-invalid", "true");
  field.error.textContent = message;
  field.error.hidden = false;
}

function clearFieldError(field) {
  field.input.setAttribute("aria-invalid", "false");
  field.error.textContent = "";
  field.error.hidden = true;
}

function readRequiredName(field, labelText) {
  const value = field.input.value.trim();
  clearFieldError(field);
  if (!value) {
    showFieldError(field, `請填寫${labelText}。`);
    return null;
  }
  return value;
}

function readRequiredPrice(field) {
  const rawValue = field.input.value.trim();
  const value = Number(rawValue);
  clearFieldError(field);
  if (!rawValue || !Number.isInteger(value) || value < 0) {
    showFieldError(field, "價格必須是大於或等於 0 的整數。");
    return null;
  }
  return value;
}

function createGroupFilters(result) {
  const panel = document.createElement("section");
  panel.className = "group-filter-panel";
  panel.innerHTML = `
    <div class="group-filter-heading">
      <div>
        <strong>快速篩選提供品項</strong>
        <p>設定條件後按「只保留篩選結果」，未符合的品項會自動取消。</p>
      </div>
      <span id="visible-item-count"></span>
    </div>
    <div class="group-filter-fields">
      <label>搜尋品項<input type="search" data-filter="keyword" placeholder="例如：紅茶"></label>
      <label>菜單分類<select data-filter="category"><option value="">全部分類</option></select></label>
      <label>最高價格<input type="number" data-filter="max-price" min="0" step="1" inputmode="numeric" placeholder="不限"></label>
    </div>
    <div class="group-filter-actions">
      <button type="button" class="primary-filter-action" data-filter-action="keep">只保留篩選結果</button>
      <button type="button" data-filter-action="select-all">全部勾選</button>
      <button type="button" data-filter-action="clear-all">全部取消</button>
      <button type="button" data-filter-action="reset">顯示全部</button>
    </div>
  `;
  const categorySelect = panel.querySelector('[data-filter="category"]');
  result.categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = category.name;
    option.textContent = category.name;
    categorySelect.append(option);
  });
  return panel;
}

function setupGroupFilters(panel) {
  const keywordInput = panel.querySelector('[data-filter="keyword"]');
  const categorySelect = panel.querySelector('[data-filter="category"]');
  const maxPriceInput = panel.querySelector('[data-filter="max-price"]');
  const visibleCount = panel.querySelector("#visible-item-count");

  function matchingRows() {
    const keyword = keywordInput.value.trim().toLocaleLowerCase("zh-TW");
    const categoryName = categorySelect.value;
    const maximum = maxPriceInput.value === "" ? null : Number(maxPriceInput.value);
    const rows = [...recognitionContent.querySelectorAll(".group-select-item")];
    rows.forEach((row) => {
      const matches = (!keyword || row.dataset.itemName.toLocaleLowerCase("zh-TW").includes(keyword))
        && (!categoryName || row.dataset.categoryName === categoryName)
        && (maximum === null || Number(row.dataset.price) <= maximum);
      row.hidden = !matches;
    });
    recognitionContent.querySelectorAll(".recognized-category").forEach((section) => {
      section.hidden = !section.querySelector(".group-select-item:not([hidden])");
    });
    const matches = rows.filter((row) => !row.hidden);
    const selectedCount = rows.filter((row) => row.querySelector('[data-role="include-item"]')?.checked).length;
    visibleCount.textContent = `顯示 ${matches.length} 項｜已選 ${selectedCount} 項`;
    recognitionContent.querySelectorAll(".group-variant-group").forEach((group) => {
      group.hidden = !group.querySelector(".group-select-item:not([hidden])");
    });
    return matches;
  }

  function applyActiveFiltersToSelection() {
    const matches = matchingRows();
    const hasFilter = keywordInput.value.trim() || categorySelect.value || maxPriceInput.value !== "";
    if (hasFilter) {
      recognitionContent.querySelectorAll(".group-select-item").forEach((row) => {
        row.querySelector('[data-role="include-item"]').checked = matches.includes(row);
      });
      matchingRows();
      reviewForm.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  panel.addEventListener("input", applyActiveFiltersToSelection);
  panel.addEventListener("change", applyActiveFiltersToSelection);
  panel.addEventListener("click", (event) => {
    const action = event.target.dataset.filterAction;
    if (!action) return;
    if (action === "reset") {
      keywordInput.value = "";
      categorySelect.value = "";
      maxPriceInput.value = "";
      matchingRows();
      return;
    }
    const rows = [...recognitionContent.querySelectorAll(".group-select-item")];
    const matches = matchingRows();
    if (action === "keep") {
      rows.forEach((row) => {
        row.querySelector('[data-role="include-item"]').checked = matches.includes(row);
      });
    } else if (action === "select-all") {
      rows.forEach((row) => { row.querySelector('[data-role="include-item"]').checked = true; });
    } else if (action === "clear-all") {
      rows.forEach((row) => { row.querySelector('[data-role="include-item"]').checked = false; });
    }
    matchingRows();
    reviewForm.dispatchEvent(new Event("input", { bubbles: true }));
  });
  matchingRows();
}

function syncStoreReviewToRecognition() {
  if (!latestRecognition) return;
  const restaurantInput = recognitionContent.querySelector(
    '[data-role="restaurant-field"] input',
  );
  const categories = [...recognitionContent.querySelectorAll(".recognized-category")].map(
    (section) => ({
      name: section.querySelector('[data-role="category-field"] input').value,
      items: [...section.querySelectorAll(".recognized-item")].map((row) => {
        const rawPrice = row.querySelector('[data-role="item-price-field"] input').value.trim();
        return {
          name: row.querySelector('[data-role="item-name-field"] input').value,
          description: row.dataset.description ?? "",
          price: rawPrice === "" ? null : Number(rawPrice),
        };
      }),
    }),
  );
  latestRecognition = {
    ...latestRecognition,
    restaurant_name: restaurantInput.value,
    categories,
  };
}

function renderRecognition(result) {
  latestRecognition = result;
  confirmedRecognition = null;
  recognitionContent.replaceChildren();
  recognitionWarnings.replaceChildren();
  reviewStatus.hidden = true;
  groupCreated.hidden = true;
  storeCreated.hidden = true;

  const filterPanel = requestedMode === "group" ? createGroupFilters(result) : null;
  if (filterPanel) {
    recognitionContent.append(filterPanel);
  }

  const restaurantField = createReviewField({
    labelText: "餐廳名稱",
    value: result.restaurant_name,
    fieldName: "restaurant-name",
  });
  restaurantField.wrapper.dataset.role = "restaurant-field";
  const hasRecognizedRestaurantName = Boolean(result.restaurant_name?.trim());
  if (requestedMode === "group" && hasRecognizedRestaurantName) {
    restaurantField.input.readOnly = true;
    restaurantField.wrapper.classList.add("locked-review-field");
  }
  if (!hasRecognizedRestaurantName) {
    restaurantField.input.placeholder = "請輸入餐廳名稱";
    const restaurantHelp = document.createElement("p");
    restaurantHelp.className = "field-help";
    restaurantHelp.textContent = "菜單未辨識到店名，請自行輸入一個方便辨識的名稱。";
    restaurantField.wrapper.append(restaurantHelp);
  }
  recognitionContent.append(restaurantField.wrapper);

  const isStoreReview = requestedMode === "store" || Boolean(storeUpdateContext);
  result.categories.forEach((category, categoryIndex) => {
    const categorySection = document.createElement("section");
    categorySection.className = "recognized-category";
    categorySection.dataset.categoryIndex = String(categoryIndex);

    const categoryField = createReviewField({
      labelText: "分類名稱",
      value: category.name,
      fieldName: `category-${categoryIndex}-name`,
    });
    categoryField.wrapper.dataset.role = "category-field";
    if (requestedMode === "group") {
      categoryField.input.readOnly = true;
      categoryField.wrapper.classList.add("locked-review-field");
    }
    categorySection.append(categoryField.wrapper);
    if (isStoreReview) {
      const categoryActions = document.createElement("div");
      categoryActions.className = "store-edit-actions category-edit-actions";
      const deleteCategory = document.createElement("button");
      deleteCategory.type = "button";
      deleteCategory.className = "danger-edit-button";
      deleteCategory.textContent = "刪除這個分類";
      deleteCategory.addEventListener("click", () => {
        syncStoreReviewToRecognition();
        latestRecognition.categories.splice(categoryIndex, 1);
        renderRecognition(latestRecognition);
      });
      categoryActions.append(deleteCategory);
      categorySection.append(categoryActions);
    }

    const itemList = document.createElement("div");
    itemList.className = "recognized-items";
    if (requestedMode === "group") {
      const header = document.createElement("div");
      header.className = "group-item-header";
      header.innerHTML = "<span>提供</span><span>品項名稱</span><span>規格與價格</span>";
      itemList.append(header);
    }

    const renderedRows = [];
    category.items.forEach((item, itemIndex) => {
      const itemRow = document.createElement("div");
      itemRow.className = "recognized-item";
      itemRow.dataset.itemIndex = String(itemIndex);
      itemRow.dataset.description = item.description;
      itemRow.dataset.itemName = item.name;
      itemRow.dataset.categoryName = category.name;
      itemRow.dataset.price = String(item.price ?? "");

      const nameField = createReviewField({
        labelText: "品項名稱",
        value: item.name,
        fieldName: `category-${categoryIndex}-item-${itemIndex}-name`,
      });
      nameField.wrapper.dataset.role = "item-name-field";

      const priceField = createReviewField({
        labelText: "價格（NT$）",
        value: item.price,
        type: "number",
        fieldName: `category-${categoryIndex}-item-${itemIndex}-price`,
      });
      priceField.wrapper.dataset.role = "item-price-field";

      if (requestedMode === "group") {
        itemRow.classList.add("group-select-item");
        nameField.input.readOnly = true;
        priceField.input.readOnly = true;
        nameField.wrapper.classList.add("locked-review-field");
        priceField.wrapper.classList.add("locked-review-field");

        const includeLabel = document.createElement("label");
        includeLabel.className = "include-item-control";
        const includeInput = document.createElement("input");
        includeInput.type = "checkbox";
        includeInput.checked = true;
        includeInput.dataset.role = "include-item";
        const includeText = document.createElement("span");
        includeText.className = "visually-hidden";
        includeText.textContent = "提供團購";
        includeLabel.append(includeInput, includeText);
        itemRow.append(includeLabel);
      }

      itemRow.append(nameField.wrapper, priceField.wrapper);
      if (isStoreReview) {
        const deleteItem = document.createElement("button");
        deleteItem.type = "button";
        deleteItem.className = "danger-edit-button item-delete-button";
        deleteItem.textContent = "刪除";
        deleteItem.setAttribute("aria-label", `刪除 ${item.name || "這個品項"}`);
        deleteItem.addEventListener("click", () => {
          syncStoreReviewToRecognition();
          latestRecognition.categories[categoryIndex].items.splice(itemIndex, 1);
          renderRecognition(latestRecognition);
        });
        itemRow.append(deleteItem);
      }
      renderedRows.push({ item, itemRow, nameField, priceField });
    });

    if (requestedMode === "group") {
      MenuVariants.groupItems(renderedRows, (entry) => entry.item.name).forEach((itemGroup) => {
        if (itemGroup.type === "item") {
          itemList.append(itemGroup.item.itemRow);
          return;
        }
        const group = document.createElement("div");
        group.className = "group-variant-group";
        const baseName = document.createElement("strong");
        baseName.className = "group-variant-name";
        baseName.textContent = itemGroup.baseName;
        const options = document.createElement("div");
        options.className = "group-variant-options";
        itemGroup.variants.forEach(({ item: member, variant }) => {
          member.nameField.wrapper.hidden = true;
          member.itemRow.classList.add("group-variant-option");
          const sizeLabel = document.createElement("strong");
          sizeLabel.className = "group-size-label";
          sizeLabel.textContent = variant.variantName;
          const includeLabel = member.itemRow.querySelector(".include-item-control");
          includeLabel.after(sizeLabel);
          options.append(member.itemRow);
        });
        group.append(baseName, options);
        itemList.append(group);
      });
    } else if (isStoreReview) {
      MenuVariants.groupItems(renderedRows, (entry) => entry.item.name).forEach((itemGroup) => {
        if (itemGroup.type === "item") {
          itemGroup.item.itemRow.classList.add("store-single-item");
          itemList.append(itemGroup.item.itemRow);
          return;
        }
        const group = document.createElement("div");
        group.className = "store-variant-group";
        const baseField = createReviewField({
          labelText: "品項名稱",
          value: itemGroup.baseName,
          fieldName: `category-${categoryIndex}-variant-${itemList.children.length}`,
        });
        baseField.wrapper.dataset.role = "variant-base-field";
        group.append(baseField.wrapper);
        const variants = document.createElement("div");
        variants.className = "store-variant-prices";
        itemGroup.variants.forEach(({ item: member, variant }) => {
          member.nameField.wrapper.hidden = true;
          member.itemRow.classList.add("store-variant-item");
          const sizeLabel = document.createElement("strong");
          sizeLabel.textContent = variant.variantName;
          member.priceField.wrapper.querySelector("label").textContent = `${variant.variantName} 價格`;
          member.itemRow.prepend(sizeLabel);
          variants.append(member.itemRow);
        });
        baseField.input.addEventListener("input", () => {
          itemGroup.variants.forEach(({ item: member, variant }) => {
            member.nameField.input.value = `${baseField.input.value.trim()}（${variant.variantName}）`;
          });
        });
        group.append(variants);
        itemList.append(group);
      });
    } else {
      renderedRows.forEach(({ itemRow }) => itemList.append(itemRow));
    }
    categorySection.append(itemList);
    if (isStoreReview) {
      const addItem = document.createElement("button");
      addItem.type = "button";
      addItem.className = "store-add-button";
      addItem.textContent = "＋ 新增品項";
      addItem.addEventListener("click", () => {
        syncStoreReviewToRecognition();
        latestRecognition.categories[categoryIndex].items.push({
          name: "新品項",
          description: "",
          price: 0,
        });
        renderRecognition(latestRecognition);
      });
      categorySection.append(addItem);
    }
    recognitionContent.append(categorySection);
  });

  if (isStoreReview) {
    const addCategory = document.createElement("button");
    addCategory.type = "button";
    addCategory.className = "store-add-button add-category-button";
    addCategory.textContent = "＋ 新增菜單分類";
    addCategory.addEventListener("click", () => {
      syncStoreReviewToRecognition();
      latestRecognition.categories.push({
        name: "新分類",
        items: [{ name: "新品項", description: "", price: 0 }],
      });
      renderRecognition(latestRecognition);
    });
    recognitionContent.append(addCategory);
  }

  if (filterPanel) {
    setupGroupFilters(filterPanel);
  }

  if (result.warnings.length > 0) {
    const warnings = document.createElement("ul");
    warnings.className = "recognition-warnings";
    result.warnings.forEach((warning) => {
      const warningItem = document.createElement("li");
      warningItem.textContent = warning;
      warnings.append(warningItem);
    });
    recognitionWarnings.append(warnings);
  }

  recognitionResult.hidden = false;
}

function collectReviewedRecognition() {
  if (!latestRecognition) {
    return null;
  }

  const restaurantWrapper = recognitionContent.querySelector('[data-role="restaurant-field"]');
  const restaurantField = {
    input: restaurantWrapper.querySelector("input"),
    error: restaurantWrapper.querySelector(".field-error"),
  };
  const restaurantName = readRequiredName(restaurantField, "餐廳名稱");
  let isValid = restaurantName !== null;

  const categories = latestRecognition.categories.map((category, categoryIndex) => {
    const categorySection = recognitionContent.querySelector(
      `[data-category-index="${categoryIndex}"]`,
    );
    const categoryWrapper = categorySection.querySelector('[data-role="category-field"]');
    const categoryField = {
      input: categoryWrapper.querySelector("input"),
      error: categoryWrapper.querySelector(".field-error"),
    };
    const categoryName = readRequiredName(categoryField, "分類名稱");
    isValid = categoryName !== null && isValid;

    categorySection.querySelectorAll('[data-role="variant-base-field"]').forEach((wrapper) => {
      const field = { input: wrapper.querySelector("input"), error: wrapper.querySelector(".field-error") };
      isValid = readRequiredName(field, "品項名稱") !== null && isValid;
    });

    const itemRows = [...categorySection.querySelectorAll(".recognized-item")];
    const items = itemRows.flatMap((itemRow) => {
      const itemIndex = Number(itemRow.dataset.itemIndex);
      const includeInput = itemRow.querySelector('[data-role="include-item"]');
      if (includeInput && !includeInput.checked) {
        return [];
      }
      const nameWrapper = itemRow.querySelector('[data-role="item-name-field"]');
      const priceWrapper = itemRow.querySelector('[data-role="item-price-field"]');
      const nameField = {
        input: nameWrapper.querySelector("input"),
        error: nameWrapper.querySelector(".field-error"),
      };
      const priceField = {
        input: priceWrapper.querySelector("input"),
        error: priceWrapper.querySelector(".field-error"),
      };
      const itemName = readRequiredName(nameField, "品項名稱");
      const itemPrice = readRequiredPrice(priceField);
      isValid = itemName !== null && itemPrice !== null && isValid;

      return [{
        name: itemName,
        description: category.items[itemIndex].description,
        price: itemPrice,
      }];
    });

    return { name: categoryName, items };
  }).filter((category) => category.items.length > 0);

  if (requestedMode === "group" && categories.length === 0) {
    reviewStatus.textContent = "請至少勾選一個要提供給大家點餐的品項。";
    reviewStatus.dataset.state = "error";
    reviewStatus.hidden = false;
    return null;
  }

  if (requestedMode !== "group" && categories.length === 0) {
    reviewStatus.textContent = "店家菜單至少需要一個分類及一個品項。";
    reviewStatus.dataset.state = "error";
    reviewStatus.hidden = false;
    return null;
  }

  if (!isValid) {
    return null;
  }

  return {
    restaurant_name: restaurantName,
    categories,
  };
}

reviewForm.addEventListener("input", () => {
  confirmedRecognition = null;
  reviewStatus.hidden = true;
  groupCreated.hidden = true;
  storeCreated.hidden = true;
});

reviewForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSavingMenu) {
    return;
  }
  confirmedRecognition = collectReviewedRecognition();

  if (!confirmedRecognition) {
    if (reviewStatus.hidden) {
      const restaurantInput = recognitionContent.querySelector(
        '[data-role="restaurant-field"] input',
      );
      const isRestaurantNameMissing = !restaurantInput?.value.trim();
      reviewStatus.textContent = isRestaurantNameMissing
        ? "菜單沒有可辨識的餐廳名稱，請先手動輸入名稱。"
        : requestedMode === "group"
          ? "AI 尚未辨識完整的菜名或價格。團購價格不能手動修改，請重新上傳較清楚的菜單。"
          : "尚有欄位需要修正，請依紅色提示完成後再確認。";
      reviewStatus.dataset.state = "error";
      reviewStatus.hidden = false;
    }
    recognitionContent.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }

  const action = storeUpdateContext
    ? "store-update"
    : event.submitter?.dataset.action ?? "group";
  isSavingMenu = true;
  confirmButton.disabled = true;
  storeButton.disabled = true;
  const isGroupAction = action === "group";
  const isStoreUpdate = action === "store-update";
  reviewStatus.textContent = isGroupAction
    ? "正在建立團購菜單，請稍候。"
    : isStoreUpdate
      ? "正在更新店家固定菜單，請稍候。"
      : "正在建立店家固定菜單，請稍候。";
  reviewStatus.dataset.state = "loading";
  reviewStatus.hidden = false;
  groupCreated.hidden = true;
  storeCreated.hidden = true;

  let requestUrl = GROUPS_URL;
  let requestMethod = "POST";
  const headers = { "Content-Type": "application/json" };
  if (action === "store") {
    requestUrl = STORES_URL;
  } else if (isStoreUpdate) {
    requestUrl = `/api/stores/${storeUpdateContext.publicSlug}/menu`;
    requestMethod = "PUT";
    headers.Authorization = `Bearer ${storeUpdateContext.token}`;
  }

  try {
    const response = await fetch(requestUrl, {
      method: requestMethod,
      headers,
      body: JSON.stringify(confirmedRecognition),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      const message =
        typeof detail === "string"
          ? detail
          : "菜單儲存失敗，請確認內容後再試一次。";
      throw new Error(message);
    }

    if (isGroupAction) {
      const participantUrl = new URL(result.participant_url, window.location.origin);
      const managementUrl = new URL(result.management_url, window.location.origin);
      groupCode.textContent = result.public_code;
      participantLink.href = participantUrl.href;
      participantLink.textContent = participantUrl.href;
      managementLink.href = managementUrl.href;
      managementLink.textContent = managementUrl.href;
      openParticipantLink.href = participantUrl.href;
      openManagementLink.href = managementUrl.href;
      groupCreated.hidden = false;
      reviewStatus.textContent = `${result.restaurant_name} 的團購菜單已建立，共 ${result.category_count} 個分類、${result.item_count} 個品項。`;
    } else {
      const publicUrl = new URL(result.public_url, window.location.origin);
      const publicSlug = result.public_slug;
      const token = isStoreUpdate
        ? storeUpdateContext.token
        : new URL(result.management_url, window.location.origin).hash.slice("#token=".length);
      const managementUrl = new URL(
        `/stores/${publicSlug}/manage#token=${token}`,
        window.location.origin,
      );
      const updateUrl = new URL(
        `/stores/${publicSlug}/menu-update#token=${token}`,
        window.location.origin,
      );
      storePublicLink.href = publicUrl.href;
      storePublicLink.textContent = publicUrl.href;
      storeManagementLink.href = managementUrl.href;
      storeManagementLink.textContent = managementUrl.href;
      storeUpdateLink.href = updateUrl.href;
      storeUpdateLink.textContent = updateUrl.href;
      storeCreated.hidden = false;
      reviewStatus.textContent = isStoreUpdate
        ? `${result.restaurant_name} 的固定菜單已更新為第 ${result.version} 版，公開網址維持不變。`
        : `${result.restaurant_name} 的固定菜單已建立。`;
    }
    reviewStatus.dataset.state = "success";
  } catch (error) {
    confirmedRecognition = null;
    reviewStatus.textContent = error.message || "菜單儲存失敗，請稍後再試一次。";
    reviewStatus.dataset.state = "error";
  } finally {
    isSavingMenu = false;
    confirmButton.disabled = false;
    storeButton.disabled = false;
    confirmButton.textContent = "確認並建立團購";
    storeButton.textContent = storeUpdateContext
      ? "確認並更新固定菜單"
      : "確認並建立店家固定菜單";
  }
});

fileInput.addEventListener("change", updateSelection);

copyGroupCode.addEventListener("click", async () => {
  const code = groupCode.textContent.trim();
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code);
    copyCodeStatus.textContent = `團購代碼 ${code} 已複製，可以貼給一起點餐的人。`;
  } catch (error) {
    copyCodeStatus.textContent = `請手動複製團購代碼：${code}`;
  }
  copyCodeStatus.hidden = false;
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isUploading) {
    return;
  }

  const file = fileInput.files[0];
  const errorMessage = validateSelectedFile(file);
  if (errorMessage) {
    showStatus(errorMessage, "error");
    return;
  }

  isUploading = true;
  uploadButton.disabled = true;
  uploadButton.textContent = "AI 辨識中…";
  showStatus("檔案檢查與 AI 辨識中，請稍候。", "loading");
  recognitionResult.hidden = true;

  const fileForRecognition = croppedUploadFile ?? file;
  const formData = new FormData();
  formData.append("file", fileForRecognition);

  try {
    const response = await fetch(UPLOAD_URL, {
      method: "POST",
      body: formData,
    });
    const result = await response.json();

    if (!response.ok) {
      const detail = result.detail;
      const message =
        typeof detail?.message === "string"
          ? detail.message
          : "檔案上傳暫時失敗，請稍後再試一次。";
      throw new Error(message);
    }

    renderRecognition(result.recognition);
    showStatus(
      croppedUploadFile
        ? `${file.name} 的框選區域辨識完成，請確認下方結果。`
        : `${result.file.name} 辨識完成，請確認並修正下方結果。`,
      "success",
    );
  } catch (error) {
    showStatus(error.message || "檔案上傳暫時失敗，請稍後再試一次。", "error");
  } finally {
    isUploading = false;
    uploadButton.textContent = "上傳並辨識";
    uploadButton.disabled = Boolean(validateSelectedFile(fileInput.files[0]));
  }
});

updateSelection();
