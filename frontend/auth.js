const FIREBASE_SDK_VERSION = "12.16.0";
const FIREBASE_APP_URL = `https://www.gstatic.com/firebasejs/${FIREBASE_SDK_VERSION}/firebase-app.js`;
const FIREBASE_AUTH_URL = `https://www.gstatic.com/firebasejs/${FIREBASE_SDK_VERSION}/firebase-auth.js`;

const authNav = document.querySelector("#auth-nav");
const openButton = document.querySelector("#auth-open-button");
const userMenu = document.querySelector("#auth-user-menu");
const userName = document.querySelector("#auth-user-name");
const signOutButton = document.querySelector("#auth-sign-out-button");
const dialog = document.querySelector("#auth-dialog");
const googleButton = document.querySelector("#auth-google-button");
const status = document.querySelector("#auth-status");

let firebaseAuth = null;
let firebaseAuthSdk = null;
let verifiedUser = null;
const listeners = new Set();

function showStatus(message) {
  if (!status) return;
  status.textContent = message;
  status.hidden = !message;
}

function updateUi(user) {
  verifiedUser = user;
  if (openButton) openButton.hidden = Boolean(user);
  if (userMenu) userMenu.hidden = !user;
  if (userName) userName.textContent = user?.display_name || user?.email || "已登入";
  for (const listener of listeners) {
    listener(user);
  }
}

async function verifyWithBackend(firebaseUser) {
  const idToken = await firebaseUser.getIdToken();
  const response = await fetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${idToken}` },
  });
  if (!response.ok) {
    throw new Error("後端無法確認登入身分");
  }
  return response.json();
}

function shouldUseRedirect() {
  return window.matchMedia("(max-width: 760px)").matches;
}

async function signIn() {
  if (!firebaseAuth || !firebaseAuthSdk) return;
  if (googleButton) googleButton.disabled = true;
  showStatus("正在開啟 Google 登入…");
  const provider = new firebaseAuthSdk.GoogleAuthProvider();
  try {
    if (shouldUseRedirect()) {
      await firebaseAuthSdk.signInWithRedirect(firebaseAuth, provider);
      return;
    }
    await firebaseAuthSdk.signInWithPopup(firebaseAuth, provider);
  } catch (error) {
    showStatus("登入沒有完成，請再試一次。");
  } finally {
    if (googleButton) googleButton.disabled = false;
  }
}

async function signOut() {
  if (!firebaseAuth || !firebaseAuthSdk) return;
  await firebaseAuthSdk.signOut(firebaseAuth);
  updateUi(null);
}

async function initializeAuthentication() {
  try {
    const configResponse = await fetch("/api/auth/config", { cache: "no-store" });
    if (!configResponse.ok) return;
    const config = await configResponse.json();
    if (!config.enabled) return;

    const [firebaseAppSdk, loadedAuthSdk] = await Promise.all([
      import(FIREBASE_APP_URL),
      import(FIREBASE_AUTH_URL),
    ]);
    firebaseAuthSdk = loadedAuthSdk;
    const firebaseApp = firebaseAppSdk.initializeApp({
      apiKey: config.api_key,
      authDomain: config.auth_domain,
      projectId: config.project_id,
      appId: config.app_id,
    });
    firebaseAuth = loadedAuthSdk.getAuth(firebaseApp);
    await loadedAuthSdk.setPersistence(
      firebaseAuth,
      loadedAuthSdk.browserLocalPersistence,
    );
    if (authNav) authNav.hidden = false;

    await loadedAuthSdk.getRedirectResult(firebaseAuth);
    loadedAuthSdk.onAuthStateChanged(firebaseAuth, async (firebaseUser) => {
      if (!firebaseUser) {
        updateUi(null);
        return;
      }
      try {
        const backendUser = await verifyWithBackend(firebaseUser);
        updateUi(backendUser);
        showStatus("");
        if (dialog?.open) dialog.close();
      } catch (error) {
        await loadedAuthSdk.signOut(firebaseAuth);
        updateUi(null);
        showStatus("登入驗證失敗，請稍後再試。");
      }
    });
  } catch (error) {
    if (authNav) authNav.hidden = true;
  }
}

openButton?.addEventListener("click", () => {
  showStatus("");
  dialog.showModal();
});
googleButton?.addEventListener("click", signIn);
signOutButton?.addEventListener("click", signOut);

const ready = initializeAuthentication();

window.AppAuth = {
  ready,
  getCurrentUser: () => verifiedUser,
  getIdToken: async () => firebaseAuth?.currentUser?.getIdToken() || null,
  async getAuthorizationHeaders() {
    await ready;
    const token = await firebaseAuth?.currentUser?.getIdToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  },
  onChange(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  signIn,
  signOut,
};
