# 新版 Production 部署前清單

最後更新：2026-08-11。

這份文件用來把目前已在本機完成的帳號、品牌與封存功能安全發布到既有 Render 正式網站。清單完成不代表新版已上線；目前不得因閱讀或勾選本文件而自行 commit、push、migration 或 deploy。

## 1. 目前狀態

- 正式網站：`https://ai-menu-ordering.onrender.com`
- GitHub：Private Repository `sharon7626/ai-menu-ordering`，正式分支為 `main`
- 正式服務：Render Web Service + Render PostgreSQL
- 目前正式網站仍是舊版穩定版本；本機第二版尚未 commit、push 或部署。
- 本機第二版已完成 128 項自動測試、前端 JavaScript 語法、Python 編譯與機密字串檢查。
- 新版 migration 只新增資料表、可為空欄位與索引，不刪除既有團購、訂單、菜單或 Token 資料。

## 2. 整體安全順序

一次只進行一段，上一段確認成功後才進入下一段：

1. [x] 備份正式 PostgreSQL，確認可以取得備份或匯出檔。
2. [x] 檢查 Render PostgreSQL 的到期日與狀態。
3. [x] 從 Metrics／Info 核對正式資料庫的剩餘容量。
4. [x] 在 Render 補齊 Firebase Environment Variables，不重新建立資料庫。
5. [x] 最後一次檢查 Git 變更、測試及機密資訊。
6. [ ] 取得使用者明確批准後才 commit 與 push。
7. [ ] 觀察 Render build、startup 與 migration log。
8. [ ] 先驗證舊資料仍存在，再驗證 Firebase 帳號功能。
9. [ ] 完成訪客、團購、店家、Gemini、Excel、QR Code 與手機回歸。
10. [ ] 驗收完成後才宣布新版正式上線。

任何一步失敗時停止，不要反覆部署，也不要刪除或重建正式資料庫。

## 3. 步驟一：正式資料庫備份

這一步必須在 push 前完成，且由使用者在 Render 操作。

1. [x] 開啟目前 Web Service 使用的 PostgreSQL，確認狀態為 Available。
2. [ ] 確認 Web Service 的 `DATABASE_URL` 仍連向這一個資料庫，不要貼出或傳送連線字串。
3. [x] 查看資料庫頁面的 Recovery／備份功能與方案限制。
4. [x] Free 方案不能使用 Render Recovery／Export；已使用 `scripts/backup_postgresql.py` 將全部正式資料表匯出到 Repository 以外的位置。
5. [x] 記錄備份時間、資料庫名稱及當時正式版本 commit；記錄中不含密碼或完整連線字串。
6. [x] 確認免費 PostgreSQL 的到期日。免費資料庫不適合永久保存；若即將到期，先處理資料保存，不要直接部署新版。

備份完成的判定：有可復原的備份／匯出檔，而且知道它保存在哪裡。只有畫面顯示 Available 不等於已備份。

目前正式資料庫已確認會在 **2026-09-09** 到期並由 Render 刪除。即使本次部署成功，也必須在到期前另行搬移資料庫或建立新的免費 PostgreSQL；ZIP 備份只是資料保全，不會讓到期後的網站自動繼續運作。

2026-08-12 已完成本次部署前備份：資料庫 `ai-menu-ordering-db`、正式版本 `ba9d17e`，ZIP 位於使用者桌面的 `ai-menu-ordering-backups`（Repository 外）。工具建立後及獨立重讀驗證皆通過，共 6 張資料表、26 筆資料列；文件不記錄 ZIP 內資料、密碼或連線字串。

同日已從 Render Metrics 確認 Disk Usage 上限為 1 GB，目前曲線明顯低於 20%（約 5%），本次只新增少量資料表、可空欄位與索引，容量不是本次 migration 的阻擋；真正限制仍是 2026-09-09 的免費資料庫到期日。

免費本機匯出工具的使用方式：

1. 在 Render 資料庫右上角 **Connect** 取得 External Database URL，但不要貼到對話或任何專案檔案。
2. 在自己的 PowerShell 以安全輸入方式暫存連線網址，再執行工具；備份目的地必須在 Repository 外。
3. 工具以唯讀連線匯出所有 public 資料表，建立 CSV + manifest ZIP，並重新讀取 ZIP 核對每張表筆數。
4. 執行後立即移除 PowerShell 中的暫存變數；ZIP 含姓名、訂單與 Token 雜湊，不得提交 Git 或公開分享。

## 4. 步驟二：Firebase Console 檢查

以下項目目前已在本機設定並通過真實 Google 登入，部署前仍要逐項核對：

1. [x] Firebase 專案為 `ai-menu-ordering` 使用的同一個專案。
2. [x] Authentication 的 Google 登入方式為啟用。
3. [x] Web App 已註冊，且 Web App 與 Service Account 屬於同一個 Firebase Project。
4. [x] Authorized Domains 包含 `ai-menu-ordering.onrender.com`；只填網域，不含 `https://`、路徑或結尾斜線。
5. [x] `localhost` 與 `127.0.0.1` 可保留供本機測試。
6. [x] Service Account credential 已由既有安全 JSON 提供，未將內容提交至 Repository 或對話。

Firebase Web 設定會提供登入初始化所需的公開識別資訊；Service Account JSON 則是後端私密憑證，兩者不可混用。

## 5. 步驟三：Render Environment Variables

在既有 Web Service 的 Environment 頁面逐項確認。只核對名稱與來源，不要把值貼到文件、GitHub 或對話中。

| 變數名稱 | 必要性 | 值的來源與規則 |
| --- | --- | --- |
| `DATABASE_URL` | 必要 | 既有 Render PostgreSQL 的 Internal Database URL；不要改用 External URL，也不要換成新空資料庫。 |
| `GEMINI_API_KEY` | 必要 | Gemini Developer API Key；只供後端使用。 |
| `GEMINI_MODEL` | 選填 | 未設定時使用 `gemini-3.6-flash`；若保留此變數也使用相同模型。 |
| `FIREBASE_PROJECT_ID` | 帳號功能必要 | Firebase 專案設定中的 Project ID。 |
| `FIREBASE_WEB_API_KEY` | 帳號功能必要 | Firebase Web App 設定值，不是 Gemini Key。 |
| `FIREBASE_AUTH_DOMAIN` | 帳號功能必要 | Firebase Web App 的 Auth Domain。 |
| `FIREBASE_APP_ID` | 帳號功能必要 | Firebase Web App 的 App ID。 |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | 帳號功能必要、機密 | 完整 Service Account JSON 以單一 Render Secret／Environment Variable 保存，不建立 Repository 內的 JSON 檔。 |

檢查規則：

- [x] 變數名稱大小寫完全一致。
- [x] Web App 各欄位只填設定值，Service Account JSON 以完整 JSON 貼入。
- [x] Web App 與 Service Account 均取自同一個 `ai-menu-ordering` Firebase Project。
- [ ] `PORT` 由 Render 自動提供，不自行新增。
- [x] Repository 中沒有真正的 `.env`、Service Account JSON、正式 `DATABASE_URL` 或任何真實 Key／Token。
- [x] 設定儲存後 Render 重新建置目前舊版程式並恢復 Live；尚未 push 新版，因此尚未執行新版 migration。

2026-08-12 已在正式 Web Service 保留原 `DATABASE_URL` 與 `GEMINI_API_KEY`，並新增五個 Firebase 變數；實際值未出現在文件或對話。儲存後 Render build 成功並顯示 Live。

## 6. 步驟四：PostgreSQL migration 內容

FastAPI 啟動時會呼叫 `initialize_database()`。PostgreSQL migration 在同一個 transaction 內執行；失敗時 rollback，服務不會假裝啟動成功。

新版預期加入：

- `app_users`：保存最小 Firebase 使用者資料。
- `user_saved_menus`：保存登入者確認過的菜單快照。
- `group_sessions.owner_user_id`：可為 `NULL`，不猜測舊團購擁有者。
- `group_sessions.archived_at`：可為 `NULL`，只做可恢復封存。
- `orders.user_id`：可為 `NULL`，不依取餐姓名猜測帳號。
- `orders.archived_at`：可為 `NULL`，不刪除訂單。
- 帳號查詢所需索引；全部使用 `CREATE ... IF NOT EXISTS` 或 `ADD COLUMN IF NOT EXISTS`。

Migration 前後規則：

1. [ ] 不手動執行未經審核的 SQL。
2. [ ] 不清空、不重新建立、不更換正式 PostgreSQL。
3. [ ] 先完成備份，再讓新版服務第一次啟動。
4. [ ] Render log 應看到應用程式正常啟動；不得出現 schema、permission、connection 或 transaction error。
5. [ ] 舊團購、舊店家、舊訂單與 Excel 仍能讀取。
6. [ ] 舊資料的帳號欄位維持 `NULL` 是正確行為；只有持有既有私密 Token 才能安全 Claim。
7. [ ] 重啟服務一次，確認 migration 可重複執行且資料沒有重複或遺失。

## 7. 步驟五：GitHub 與 Render 發布行為

發布前由 Codex 執行唯讀檢查並向使用者回報；commit、push 必須再次取得使用者明確批准。

1. [x] 檢視全部變更，確認沒有其他專案或無關檔案。
2. [x] 確認 `.env`、`*.db`、金鑰檔、cache 與虛擬環境被 `.gitignore` 排除。
3. [x] 執行完整測試、JavaScript 語法、Python 編譯與機密掃描。
4. [ ] 使用者確認變更範圍後才 commit。
5. [ ] 使用者確認正式發布後才 push 到 `main`。

如果 Render 的 Auto-Deploy 已啟用，push 到 `main` 後會自動 build 與部署，因此「push」就是會影響正式網站的發布動作，不是單純備份到 GitHub。若 Auto-Deploy 關閉，則 push 後還要由使用者在 Render 按 Manual Deploy。

Render 設定應維持：

| 欄位 | 設定 |
| --- | --- |
| Repository | `sharon7626/ai-menu-ordering` |
| Branch | `main` |
| Root Directory | 留空 |
| Runtime | Python 3 |
| Python | `.python-version` 指定 `3.12` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'` |
| Health Check Path | `/` |

## 8. 步驟六：部署當下觀察

1. [ ] Render build 完成，依賴安裝沒有 error。
2. [ ] Startup log 顯示 Uvicorn 啟動完成，沒有資料庫 migration 或 Firebase 初始化錯誤。
3. [ ] Render 顯示 Live 後，以無痕視窗開啟正式首頁。
4. [ ] 首頁載入、CSS、JavaScript 與主要連結正常，瀏覽器 console 沒有錯誤。
5. [ ] 先開啟一筆部署前已存在的團購、訂單或店家網址，確認舊資料仍在。
6. [ ] 只有上述項目通過後才開始建立新版測試資料。

## 9. 步驟七：正式網站驗收順序

請使用小量測試資料依序驗收，不要一開始大量上傳或建立訂單。

### A. 不登入也能用

1. [ ] 無痕視窗可建立團購、取得代碼、公開連結與 QR Code。
2. [ ] 另一個無痕視窗可加入團購並送單。
3. [ ] 團購管理能看到個人明細、餐點彙整與總金額。
4. [ ] 團購 Excel 可下載且三個工作表都有正確資料。
5. [ ] 店家固定菜單、顧客 QR 點餐、店家後台與 Excel 正常。

### B. Google 帳號

1. [ ] 正式首頁可開啟 Google 登入，沒有空白 popup 或 unauthorized domain。
2. [ ] 登入後重新整理仍保持登入狀態，登出也正常。
3. [ ] 登入建立的團購出現在「我的團購」，公開連結與 QR Code 可找回。
4. [ ] 登入送出的團購／店家訂單，不論填什麼取餐姓名，都出現在「我的訂單」。
5. [ ] 「我的菜單」可用既有菜單再開團，且不重新呼叫 Gemini。
6. [ ] 團購與訂單可封存、查看已封存及恢復，原始資料沒有刪除。
7. [ ] 使用第二個 Google 帳號確認看不到第一個帳號的私人資料。

### C. Gemini、手機與保存性

1. [ ] 上傳一張代表性 JPG／PNG 或一頁式 PDF，Gemini 能回傳菜名與價格。
2. [ ] 同品項不同規格同列顯示，規格仍可各自選數量與備註。
3. [ ] 若免費 Gemini 出現 429，從 Render 安全 log 判斷額度類型；不要因此更換模型或貼出 Key。
4. [ ] 手機檢查首頁、上傳、點餐、購物車、管理與我的頁面，沒有水平溢出或按鈕遮擋。
5. [ ] 在 Render 重新啟動 Web Service，再確認既有團購、訂單、菜單與帳號清單仍存在。

## 10. 失敗時如何處理

- Build 失敗：不要修改資料庫；先閱讀第一個實際 error，再決定是否修正程式。
- Migration 失敗：停止新版發布，保留正式資料庫與備份；不要反覆 restart，也不要手動刪表或刪欄位。
- Google 登入失敗：先檢查 Render 變數名稱、Firebase Project 是否一致，以及 Authorized Domains；不要重新產生 Key 當作第一個解法。
- 首頁可用但舊資料消失：立即檢查 `DATABASE_URL` 是否誤連新資料庫；不要在錯誤資料庫繼續建立資料。
- 功能回歸失敗：使用 Render 的上一個成功 deploy／commit 回復應用程式版本；資料庫只在有明確證據與備份時才考慮還原。
- 免費服務喚醒慢：先等待服務完成喚醒並查看 log；不要把冷啟動誤判為資料遺失。

## 11. 誰負責哪些操作

需要使用者本人操作或確認：

- Render PostgreSQL 備份／匯出、到期日與方案限制。
- Firebase Console 與 Render Environment Variables 的真實值。
- 批准 commit、push，以及是否讓 Render 正式部署。
- 正式 Google 帳號與手機端人工驗收。

Codex 可在取得批准後協助：

- 再次檢查 Git 變更、機密與完整測試。
- 建立清楚的 commit 並 push。
- 依 Render log 協助判斷 build、migration 或登入錯誤。
- 按本文件逐項陪同正式驗收並記錄結果。

## 12. 下一個決策點

本文件完成後先停止。下一次只有在使用者確認已完成正式資料庫備份，並明確批准 commit 與 push 時，才進行新版發布；在那之前 Production 應維持現況。
