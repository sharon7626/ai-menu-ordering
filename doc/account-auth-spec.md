# 選擇性 Google 登入與安全找回規格

最後更新：2026-08-19

## 1. 目的

Google 登入只增加「保存、找回、跨裝置」能力，不取代訪客流程。未登入使用者仍可建立或加入團購、送出訂單、使用既有管理連結、個人訂單連結及店家固定菜單。

## 2. 驗證架構

1. 前端使用 Firebase Authentication 的 Google Sign-In。
2. Firebase 前端 SDK 取得短效 Firebase ID Token。
3. 前端透過 HTTPS 將 ID Token 放在 `Authorization: Bearer <firebase-id-token>`。
4. FastAPI 使用 Firebase Admin SDK 驗證簽章、期限、issuer 與 audience。
5. 後端只使用驗證結果中的 `uid` 作為身分，並建立或更新本機 `app_users` 紀錄。
6. email 與 display name 只作顯示用途，不可作為授權判斷。

不得保存 Google Access Token、Firebase ID Token 或 refresh token。不得在 log 記錄任何完整 Token。

## 3. 最小資料模型

### `app_users`

| 欄位 | 規則 |
| --- | --- |
| `id` | 內部主鍵，不公開作為授權憑證。 |
| `firebase_uid` | 必填、唯一；只接受後端驗證後的 UID。 |
| `email` | 選填顯示資料，不作為權限依據。 |
| `display_name` | 選填顯示資料。 |
| `created_at` | UTC ISO 8601。 |
| `updated_at` | UTC ISO 8601。 |

### 既有資料表的選填關聯

- `group_sessions.owner_user_id`：可為 `NULL`；登入建立或安全 Claim 後指向 `app_users.id`。
- `orders.user_id`：可為 `NULL`；登入送單或安全 Claim 後指向 `app_users.id`。
- 既有資料維持 `NULL`，不自動猜測擁有者，不依姓名或 email 回填。

需要索引：

- `app_users.firebase_uid` 唯一索引。
- `group_sessions(owner_user_id, created_at)`。
- `orders(user_id, created_at)`。

SQLite 與 PostgreSQL migration 都只能新增資料表、可為 `NULL` 的欄位及索引，不改寫既有訂單或 Token 雜湊。

## 4. 訪客與登入流程

| 情境 | 行為 |
| --- | --- |
| 訪客建立團購 | 完全維持既有建立與 management Token 回傳；`owner_user_id = NULL`。 |
| 登入建立團購 | 建立流程不變，後端另外綁定驗證後的使用者。 |
| 訪客送單 | 保留既有 order view Token 且 `user_id = NULL`；另須擇一提供手機或 Email 作為聯絡身分。這不是登入或授權憑證。 |
| 登入送單 | 後端核價與送單流程不變，另綁定驗證後的使用者。 |
| 登入狀態維持 | 使用 Firebase Web SDK 的瀏覽器登入狀態；登出後前端清除目前登入狀態。 |

登入失敗不得阻止訪客繼續使用原本流程。

訪客聯絡資料只增加送單可追溯性，不可用來登入、Claim、查看私人訂單或取得管理權限；相關權限仍只接受後端驗證的 Firebase 身分及原有私密 Token。本階段沒有手機／Email OTP，故不宣稱已驗證訪客確實持有該聯絡方式。

## 5. 我的團購

- 只查詢 `owner_user_id` 等於目前驗證使用者的團購。
- 顯示餐廳名稱、日期、狀態、團購碼及管理入口。
- 跨裝置管理時以 Firebase 身分確認 owner，不要求重新取得原始 management Token。
- 原本持有 management Token 的管理頁與 API 繼續有效，兩種授權入口並存。
- 公開團購碼永遠不能推導 owner 或管理權限。

## 6. 我的訂單

- 只查詢 `user_id` 等於目前驗證使用者的訂單。
- 顯示所屬團購或店家、日期、金額與查看入口。
- 跨裝置查看以 Firebase 身分確認訂單擁有者。
- 原本持有 order view Token 的個人訂單頁與 API 繼續有效。
- 姓名、公開訂單編號或團購碼不能單獨取得私人訂單。

## 7. 安全 Claim

Claim 是把訪客已建立的資料安全綁定到登入帳號。

### 團購 Claim

必須同時驗證：

1. 有效 Firebase ID Token。
2. 指定團購存在。
3. 使用者提供的原始 management Token 經雜湊後與資料庫值相符。
4. `owner_user_id` 目前為 `NULL`，或已經是同一位使用者。

只知道團購碼不得 Claim；已綁定其他帳號時回傳一般化拒絕訊息。

### 訂單 Claim

必須同時驗證：

1. 有效 Firebase ID Token。
2. 指定訂單存在。
3. 使用者提供的原始 order view Token 經雜湊後與資料庫值相符。
4. `user_id` 目前為 `NULL`，或已經是同一位使用者。

姓名、團購碼與訂單編號不得取代 order view Token。

### Header 分工

- `Authorization` 專供 Firebase ID Token。
- Claim API 使用獨立的 `X-Management-Token` 或 `X-Order-Token` 傳送既有私密 Token。
- 既有只使用 management／order Token 的 API 保持原本行為，避免破壞現有連結。

## 8. 建議 API 邊界

實際路徑可在實作任務確認，但職責必須分離：

- 取得目前登入者資料。
- 取得我的團購清單與單一團購管理資料。
- 取得我的訂單清單與單一私人訂單。
- Claim 訪客團購。
- Claim 訪客訂單。

所有 `/api/me/...` 類型入口都必須先完成 Firebase ID Token 驗證。

## 9. 環境與機密

預計使用的變數名稱由實作任務最終確認，至少包括 Firebase project id，以及前端初始化所需的 Web App 設定。所有正式值放在 Render Environment Variables。

- Firebase Admin credential 不得提交至 Git。
- `.env.example` 只能列變數名稱與安全空值。
- Firebase Web App 設定雖會送至瀏覽器，仍不得把正式專案值硬寫入 Repository。
- Gemini Key、Database URL、Firebase credential 與任何 Token 不得出現在前端原始碼、錯誤畫面或 log。

## 10. 錯誤與隱私

- 缺少或無效 Firebase ID Token：`401`。
- 已登入但不是資料擁有者：`403`。
- Claim Token 無效或資料已屬於他人：使用不洩漏細節的一般化 `403` 或 `409`。
- 回應與 log 不得包含原始 Token、Token 雜湊、Firebase credential、其他帳號 email 或其他人的訂單。
- 訪客手機／Email 只可回傳給通過管理授權的後台及 Excel；公開菜單、公開團購、分享連結與 QR Code 不得包含。

## 11. 本階段不做

- 強制登入。
- Email＋密碼、忘記密碼、SMS 或其他社群登入。
- Google Access Token 保存或呼叫 Google 使用者資料 API。
- 會員等級、付費會員、管理員角色或大頭照上傳。
- 依姓名、email、團購碼或訂單編號自動認領歷史資料。
- 自動把所有舊資料指派給第一個登入者。

## 12. 驗收重點

- 訪客仍可完整使用主要流程，但送單時須提供手機或 Email；不強制建立帳號。
- Firebase Token 必須由後端驗證。
- 帳號 A 無法管理帳號 B 的團購，也無法查看帳號 B 的訂單。
- 正確 Token 可 Claim；錯誤 Token、只有公開代碼或只有姓名不可 Claim。
- 新瀏覽器登入同一帳號可找回已綁定資料。
- SQLite、PostgreSQL、既有 Token、Excel 與歷史訂單皆維持相容。
