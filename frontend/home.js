const CODE_PATTERN = /^[A-HJ-NP-Z2-9]{6}$/;
const quickJoinForm = document.querySelector("#quick-join-form");
const quickGroupCode = document.querySelector("#quick-group-code");
const quickJoinStatus = document.querySelector("#quick-join-status");

quickJoinForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const code = quickGroupCode.value.trim().toUpperCase();
  quickGroupCode.value = code;
  if (!CODE_PATTERN.test(code)) {
    quickJoinStatus.textContent = "請輸入主揪提供的正確 6 碼代碼。";
    quickJoinStatus.hidden = false;
    quickGroupCode.focus();
    return;
  }
  window.location.assign(`/groups/${code}`);
});
