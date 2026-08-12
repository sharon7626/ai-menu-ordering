const statusPanel = document.querySelector("#my-groups-status");
const content = document.querySelector("#my-groups-content");
const list = document.querySelector("#my-groups-list");
const empty = document.querySelector("#my-groups-empty");
const emptyTitle = document.querySelector("#my-groups-empty-title");
const emptyCopy = document.querySelector("#my-groups-empty-copy");
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

function renderGroups(groups) {
  list.replaceChildren();
  empty.hidden = groups.length > 0;
  groups.forEach((group) => {
    const card = document.createElement("article");
    card.className = "my-card";
    const heading = document.createElement("div");
    const name = document.createElement("h2");
    name.textContent = group.restaurant_name;
    const code = document.createElement("p");
    code.textContent = `團購代碼 ${group.public_code}`;
    heading.append(name, code);
    const meta = document.createElement("p");
    meta.textContent = `${group.status === "open" ? "進行中" : "已截止"}・${group.order_count} 張訂單・${formatPrice(group.grand_total)}`;
    const actions = document.createElement("div");
    actions.className = "my-card-actions";
    const managementLink = document.createElement("a");
    managementLink.href = group.management_url;
    managementLink.textContent = "查看團購管理";
    actions.append(managementLink);

    const archiveButton = document.createElement("button");
    archiveButton.type = "button";
    archiveButton.className = "my-secondary-button";
    archiveButton.textContent = showingArchived ? "恢復團購" : "封存團購";
    archiveButton.addEventListener("click", () => updateArchive(group, archiveButton));
    actions.prepend(archiveButton);

    card.append(heading, meta, actions);

    if (group.status === "open") {
      const shareButton = document.createElement("button");
      shareButton.type = "button";
      shareButton.className = "my-secondary-button";
      shareButton.textContent = "分享連結與 QR Code";
      shareButton.setAttribute("aria-expanded", "false");

      const sharePanel = document.createElement("section");
      sharePanel.className = "my-share-panel";
      sharePanel.hidden = true;
      const shareTitle = document.createElement("h3");
      shareTitle.textContent = "參與者點餐入口";
      const publicUrl = new URL(group.public_url, window.location.origin);
      const publicLink = document.createElement("a");
      publicLink.className = "my-public-link";
      publicLink.href = publicUrl.href;
      publicLink.textContent = publicUrl.href;
      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.className = "my-copy-button";
      copyButton.textContent = "複製參與連結";
      const copyStatus = document.createElement("p");
      copyStatus.className = "my-copy-status";
      copyStatus.setAttribute("role", "status");
      const qr = document.createElement("img");
      qr.className = "my-group-qr";
      qr.src = `/api/groups/${encodeURIComponent(group.public_code)}/qr.svg`;
      qr.alt = `${group.restaurant_name}團購參與者 QR Code`;
      sharePanel.append(shareTitle, publicLink, copyButton, copyStatus, qr);

      shareButton.addEventListener("click", () => {
        sharePanel.hidden = !sharePanel.hidden;
        shareButton.setAttribute("aria-expanded", String(!sharePanel.hidden));
        shareButton.textContent = sharePanel.hidden ? "分享連結與 QR Code" : "收起分享資訊";
      });
      copyButton.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(publicUrl.href);
          copyStatus.textContent = "參與連結已複製。";
        } catch (error) {
          copyStatus.textContent = "請長按或使用右鍵複製上方連結。";
        }
      });

      actions.prepend(shareButton);
      card.append(sharePanel);
    }
    list.append(card);
  });
  statusPanel.hidden = true;
  content.hidden = false;
}

async function updateArchive(group, button) {
  button.disabled = true;
  try {
    const headers = await window.AppAuth.getAuthorizationHeaders();
    const action = showingArchived ? "restore" : "archive";
    const response = await fetch(`${group.archive_api_url}/${action}`, {
      method: "POST",
      headers,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "團購狀態暫時無法更新。");
    await loadGroups();
  } catch (error) {
    showError(error.message || "團購狀態暫時無法更新。");
    button.disabled = false;
  }
}

async function loadGroups() {
  try {
    const headers = window.AppAuth?.getAuthorizationHeaders
      ? await window.AppAuth.getAuthorizationHeaders()
      : {};
    if (!headers.Authorization) {
      throw new Error("請先回首頁使用 Google 登入，再查看我的團購。");
    }
    const response = await fetch(`/api/me/groups?archived=${showingArchived}`, {
      headers,
      cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error("我的團購暫時無法讀取，請重新登入後再試。");
    }
    emptyTitle.textContent = showingArchived ? "目前沒有已封存的團購" : "還沒有已保存的團購";
    emptyCopy.textContent = showingArchived
      ? "封存的團購會保留資料，並可隨時恢復。"
      : "登入狀態下建立新團購，之後就能從這裡跨裝置找回。";
    renderGroups(result.groups);
  } catch (error) {
    showError(error.message || "我的團購暫時無法讀取。");
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
    statusPanel.textContent = showingArchived ? "已封存團購載入中" : "團購載入中";
    statusPanel.dataset.state = "loading";
    statusPanel.hidden = false;
    loadGroups();
  });
});

loadGroups();
