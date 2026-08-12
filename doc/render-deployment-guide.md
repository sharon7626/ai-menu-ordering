# GitHub 與 Render 部署指南

最後更新：2026-08-11。

本文件保留 Render 的固定設定說明；第二版發布前的實際操作順序、備份、migration 與回復方式，請以 [新版 Production 部署前清單](production-deployment-checklist.md) 為準。

## 1. 部署架構

- 原始碼：Private GitHub Repository `ai-menu-ordering`。
- 網站：Render Web Service，Runtime 使用 Python。
- 本機資料庫：SQLite。
- 正式資料庫：與 Web Service 相同區域的 Render PostgreSQL。
- AI：Gemini Developer API，只由 FastAPI 後端呼叫。
- 不使用 Docker，也不建立獨立 Static Site；HTML、CSS、JavaScript 由同一個 FastAPI 服務提供。

## 2. Web Service 設定

| Render 欄位 | 設定值 |
| --- | --- |
| Repository | Private `ai-menu-ordering` |
| Branch | `main` |
| Root Directory | 留空，因為 `requirements.txt` 與 `backend/` 都在 Repository 根目錄 |
| Runtime／Language | Python 3 |
| Python 版本 | `.python-version` 指定的 3.12 系列 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'` |
| Health Check Path | `/` |

`--proxy-headers` 讓 FastAPI 使用 Render 傳入的原始 HTTPS scheme；因此店家 QR Code 會依實際 `onrender.com` 網域產生 HTTPS 公開網址。`$PORT` 由 Render 自動提供，不需要自行設定。

## 3. Environment Variables

| 變數名稱 | 是否必要 | 應填內容 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 必要 | 使用者自己的 Gemini Developer API Key；只能在 Render 後台設定，不得貼入對話或 Repository。 |
| `DATABASE_URL` | 必要 | 同區域 Render PostgreSQL 的 Internal Database URL；不得使用 External URL，也不得提交至 Git。 |
| `GEMINI_MODEL` | 選填 | 模型名稱；未設定時後端使用 `gemini-3.6-flash`。若設定，也維持目前相同模型。 |
| `FIREBASE_PROJECT_ID` | 帳號功能必要 | Firebase Web App 與 Service Account 所屬的 Project ID。 |
| `FIREBASE_WEB_API_KEY` | 帳號功能必要 | Firebase Web App 設定值；不是 Gemini API Key。 |
| `FIREBASE_AUTH_DOMAIN` | 帳號功能必要 | Firebase Web App 的 Auth Domain。 |
| `FIREBASE_APP_ID` | 帳號功能必要 | Firebase Web App 的 App ID。 |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | 帳號功能必要、機密 | 完整 Service Account JSON，僅存於 Render，不建立或提交金鑰檔。 |

`PORT` 由 Render 自動設定。`.env.example` 只保留空白 Key 與安全的本機 SQLite 範例。

## 4. PostgreSQL 建立原則

1. 在 Render Dashboard 選擇 **New → Postgres**。
2. 名稱可使用 `ai-menu-ordering-db`。
3. 資料庫與使用者名稱可保留 Render 建議值。
4. Region 必須與稍後的 Web Service 相同。
5. 測試或短期展示可選 Free，但免費 PostgreSQL 建立 30 天後會到期，不能視為永久正式資料庫。
6. 建立完成後，在資料庫頁面取得 **Internal Database URL**，直接指定給 Web Service 的 `DATABASE_URL`，不要複製到程式或聊天。

後端 lifespan 會在每次啟動時安全地確認資料表與索引存在。第一次部署是從正式空資料庫開始且不搬本機 `app.db`；後續版本更新必須沿用既有正式 PostgreSQL，先備份，再由可重複執行的 migration 新增所需資料表、欄位與索引，不得改連新空資料庫。

## 5. Private GitHub Repository 原則

建立新 Repository 時：

- Visibility 選 **Private**。
- Repository name 使用 `ai-menu-ordering`。
- 不勾選新增 README、`.gitignore` 或 License，避免與本機既有檔案衝突。
- 第一次 commit 應包含原始碼、前端、測試、文件、`.env.example`、`.gitignore`、`.python-version` 與 `requirements.txt`。
- 不得包含 `.env`、`*.db`、API Key、正式 `DATABASE_URL`、管理 Token、cache 或虛擬環境。
- 建議第一次 commit message：`Prepare AI menu ordering app for deployment`。

任何 commit 或 push 都必須先取得使用者批准。

## 6. 第一次正式部署驗收

部署成功後不能只看 Render 的綠色狀態，必須實際完成：

1. 公開首頁、CSS 與 JavaScript 正常。
2. 上傳一張真實 JPG、PNG 或一頁式 PDF 菜單。
3. Gemini 成功回傳分類、品項與價格。
4. 建立團購並保存參與者連結與統籌管理連結。
5. 使用另一個瀏覽器或無痕模式建立至少兩張參與者訂單。
6. 統籌頁的個人明細、餐點彙整、總額及 Excel 正確。
7. 建立店家固定菜單，固定公開網址正常。
8. QR Code 解出的網址是目前 Render HTTPS 公開網址，且不含管理 Token。
9. 建立至少兩張店家顧客訂單，店家後台與 Excel 正確。
10. 在 Render PostgreSQL 確認資料表已有團購、店家與訂單資料。
11. 手動重新部署或重新啟動 Web Service 後，重新開啟既有團購與店家網址，確認資料仍存在。

## 7. 已知免費方案限制

- Render Free Web Service 閒置時可能休眠，第一次開啟會較慢。
- Render Free PostgreSQL 容量為 1 GB，且建立 30 天後到期；適合競賽、短期展示與部署驗證，不適合永久營運。
- Gemini 免費層仍受 RPM、TPM 與每日額度限制；網站部署不會消除免費層限制。
- 若需要超過 30 天保存正式資料，必須在到期前另行決定是否升級資料庫或匯出資料；本次不會自行選擇付費方案。
