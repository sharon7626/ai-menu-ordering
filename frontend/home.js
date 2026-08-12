const CODE_PATTERN = /^[A-HJ-NP-Z2-9]{6}$/;
const quickJoinForm = document.querySelector("#quick-join-form");
const quickGroupCode = document.querySelector("#quick-group-code");
const quickJoinStatus = document.querySelector("#quick-join-status");
const quickJoinDialog = document.querySelector("#quick-join-dialog");

quickJoinForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const code = quickGroupCode.value.trim().toUpperCase();
  quickGroupCode.value = code;
  if (!CODE_PATTERN.test(code)) {
    quickJoinStatus.textContent = "請確認代碼是正確的 6 碼英數字。";
    quickJoinStatus.hidden = false;
    quickGroupCode.focus();
    return;
  }
  window.location.assign(`/groups/${code}`);
});

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const finePointer = window.matchMedia("(pointer: fine)");

if (!reducedMotion.matches && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach((element) => observer.observe(element));
} else {
  document.querySelectorAll(".reveal").forEach((element) => element.classList.add("is-visible"));
}

const flowTabs = [...document.querySelectorAll("[data-flow-step]")];
const flowPanels = [...document.querySelectorAll("[data-flow-panel]")];

function selectFlowStep(step) {
  flowTabs.forEach((tab) => {
    const selected = tab.dataset.flowStep === step;
    tab.classList.toggle("is-active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  flowPanels.forEach((panel) => {
    const selected = panel.dataset.flowPanel === step;
    panel.hidden = !selected;
    panel.classList.toggle("is-active", selected);
  });
  const copyButton = document.querySelector("[data-demo-copy]");
  if (copyButton) copyButton.textContent = "複製分享連結";
}

flowTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectFlowStep(tab.dataset.flowStep));
  tab.addEventListener("focus", () => selectFlowStep(tab.dataset.flowStep));
  if (finePointer.matches) {
    tab.addEventListener("pointerenter", () => selectFlowStep(tab.dataset.flowStep));
  }
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let nextIndex = index;
    if (["ArrowDown", "ArrowRight"].includes(event.key)) nextIndex = (index + 1) % flowTabs.length;
    if (["ArrowUp", "ArrowLeft"].includes(event.key)) nextIndex = (index - 1 + flowTabs.length) % flowTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = flowTabs.length - 1;
    flowTabs[nextIndex].focus();
  });
});

document.querySelectorAll("[data-parallax-root], [data-spatial-root]").forEach((spatialRoot) => {
  if (!finePointer.matches || reducedMotion.matches) return;
  let frameId = 0;
  spatialRoot.addEventListener("pointermove", (event) => {
    cancelAnimationFrame(frameId);
    frameId = requestAnimationFrame(() => {
      const bounds = spatialRoot.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - 0.5;
      const y = (event.clientY - bounds.top) / bounds.height - 0.5;
      spatialRoot.querySelectorAll("[data-depth]").forEach((element) => {
        const depth = Number(element.dataset.depth);
        element.style.setProperty("--ambient-x", `${x * depth * 12}px`);
        element.style.setProperty("--ambient-y", `${y * depth * 12}px`);
      });
    });
  });
  spatialRoot.addEventListener("pointerleave", () => {
    spatialRoot.querySelectorAll("[data-depth]").forEach((element) => {
      element.style.removeProperty("--ambient-x");
      element.style.removeProperty("--ambient-y");
    });
  });
});

if (finePointer.matches && !reducedMotion.matches) {
  document.querySelectorAll("[data-magnetic]").forEach((button) => {
    button.addEventListener("pointermove", (event) => {
      const bounds = button.getBoundingClientRect();
      const x = event.clientX - bounds.left - bounds.width / 2;
      const y = event.clientY - bounds.top - bounds.height / 2;
      button.style.setProperty("--magnetic-x", `${x * 0.035}px`);
      button.style.setProperty("--magnetic-y", `${y * 0.035}px`);
    });
    button.addEventListener("pointerleave", () => {
      button.style.removeProperty("--magnetic-x");
      button.style.removeProperty("--magnetic-y");
    });
  });
}

document.querySelectorAll("[data-open-auth]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector("#auth-open-button")?.click());
});

document.querySelectorAll("[data-open-join]").forEach((button) => {
  button.addEventListener("click", () => {
    quickJoinStatus.hidden = true;
    quickJoinDialog?.showModal();
    requestAnimationFrame(() => quickGroupCode?.focus());
  });
});

document.querySelector("[data-demo-copy]")?.addEventListener("click", (event) => {
  event.currentTarget.textContent = "已複製示範連結 ✓";
});
