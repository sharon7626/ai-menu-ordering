# 訂單資料與送出 API 規格

## 1. 文件目的

本文件定義第一版點餐系統的訂單 JSON 格式，以及前端將訂單送到 FastAPI 後端時使用的固定入口。統一格式可讓後續的前端送單、SQLite 儲存與管理後台共用相同欄位。

後端驗證成功後，會使用單一資料庫交易將訂單主表與所有餐點明細寫入 SQLite；任一筆寫入失敗時，整張訂單都不會保留。

## 2. API

- 方法：`POST`
- 路徑：`/api/orders`
- 請求格式：`application/json`
- 有效訂單：回傳 HTTP `201 Created`
- 格式或內容無效：回傳 HTTP `422 Unprocessable Entity`

## 3. 請求欄位

### 3.1 訂單

| 欄位 | 型別 | 必填 | 規則 |
| --- | --- | --- | --- |
| `customer_name` | string | 是 | 顧客姓名，去除前後空白後不可為空。 |
| `items` | array | 是 | 訂單餐點陣列，至少包含一筆。 |
| `total_amount` | integer | 是 | 訂單總金額，必須是大於或等於 0 的整數，且等於所有小計加總。 |

### 3.2 訂單餐點

| 欄位 | 型別 | 必填 | 規則 |
| --- | --- | --- | --- |
| `item_id` | string | 是 | 對應菜單餐點識別碼，使用小寫英文與連字符。 |
| `item_name` | string | 是 | 送單當下的餐點名稱，不可為空白。 |
| `unit_price` | integer | 是 | 送單當下的單價，必須是大於或等於 0 的整數。 |
| `quantity` | integer | 是 | 購買數量，必須是大於 0 的整數。 |
| `subtotal` | integer | 是 | 餐點小計，必須等於 `unit_price × quantity`。 |

未列出的額外欄位會被拒絕，避免前後端使用不同版本的訂單格式。

## 4. 完整請求範例

```json
{
  "customer_name": "王小明",
  "items": [
    {
      "item_id": "braised-pork-rice",
      "item_name": "滷肉飯",
      "unit_price": 45,
      "quantity": 2,
      "subtotal": 90
    },
    {
      "item_id": "beef-noodle-soup",
      "item_name": "紅燒牛肉麵",
      "unit_price": 150,
      "quantity": 1,
      "subtotal": 150
    }
  ],
  "total_amount": 240
}
```

## 5. 成功回應範例

後端會補上使用 UTC 時區記錄的 `created_at` 建立時間。

```json
{
  "success": true,
  "message": "訂單已成功儲存",
  "order_id": 1,
  "order": {
    "customer_name": "王小明",
    "items": [
      {
        "item_id": "braised-pork-rice",
        "item_name": "滷肉飯",
        "unit_price": 45,
        "quantity": 2,
        "subtotal": 90
      },
      {
        "item_id": "beef-noodle-soup",
        "item_name": "紅燒牛肉麵",
        "unit_price": 150,
        "quantity": 1,
        "subtotal": 150
      }
    ],
    "total_amount": 240,
    "created_at": "2026-08-04T12:00:00Z"
  }
}
```

## 6. 拒絕條件

以下任一情況會回傳 HTTP `422`：

- 缺少顧客姓名，或姓名只有空白。
- `items` 是空陣列或缺少餐點。
- 數量不是大於 0 的整數。
- 單價、小計或總金額不是非負整數。
- 餐點小計不等於單價乘以數量。
- 訂單總金額不等於所有餐點小計加總。
- 缺少必填欄位，或包含未定義的額外欄位。

## 7. 本階段限制

- 尚未加入會員、付款、套餐或餐點客製選項。

## 7.1 團購與店家訪客身分欄位

團購與店家固定菜單的送單 API 在既有訂單內容外接受以下欄位：

| 欄位 | 型別 | 規則 |
| --- | --- | --- |
| `contact_method` | `"phone"` 或 `"email"` | 未登入訪客必填；登入者不需提供。 |
| `contact_value` | string | 必須和 `contact_method` 成對提供。手機接受 `09xxxxxxxx` 或 `+8869xxxxxxxx`，可含空格、連字號及括號，後端統一保存為 `09xxxxxxxx`；Email 驗證基本格式並轉為小寫。 |

前端是否顯示聯絡欄位只是操作體驗，後端仍會獨立檢查。已通過 Firebase ID Token 驗證的登入者以 Google 帳號作為身分，送單時即使帶入訪客聯絡欄位也不作為授權依據。未登入且缺少、只提供其中一個欄位或格式錯誤時回傳 `422`。

私人團購／店家管理回應每張訂單另提供：

- `identity_method`：`google`、`phone`、`email` 或 `legacy`。
- `identity_value`：Google 帳號顯示資料或訪客聯絡方式；舊訂單可能為 `null`。

以上資料只供通過 management Token 或帳號擁有者授權的私人管理頁與 Excel 使用，不得加入公開菜單、公開團購或 QR Code 回應。這些欄位提供聯絡線索與基本嚇阻，沒有 OTP 驗證，不代表系統已證明訪客確實持有該手機或 Email。

## 7.2 團購與店家送單防濫用

團購與店家固定菜單的送單 API 共用以下基本保護：

- 30 秒內來源、身分、姓名及餐點內容完全相同時，只建立第一張訂單；再次送出回傳 HTTP `409`。
- 同一來源與身分對同一份團購／店家菜單，10 分鐘最多完成 5 次建立或更新送單；第 6 次回傳 HTTP `429`，並提供 `Retry-After` 回應標頭。
- 前端送出 `website` 隱藏誘捕欄位，正常使用者不會看到且欄位必須保持空白；自動程式填入後回傳 HTTP `422`。

後端只在單一服務執行個體的記憶體中保存不可逆雜湊與短期時間戳，不保存原始 IP、手機、Email、姓名或訂單內容。服務重啟會清除限制，且多個服務執行個體不共用紀錄；這是目前免費單機部署的基本防護，不等同於 SMS／Email OTP、CAPTCHA、WAF 或分散式 Rate Limit。

## 7.3 團購重複身分的加購與修改

團購模式會用後端驗證的 Google 使用者 ID，或訪客正規化後的 `contact_method`＋`contact_value`，判斷同一團購內是否已有訂單。第一次建立成功回傳 HTTP `201`，並以 `HttpOnly`、`SameSite=Lax` Cookie 在該瀏覽器保存「訂單編號＋高強度私密 Token」；Cookie 不提供給前端 JavaScript 讀取。

同一身分再次送單但未指定動作時回傳 HTTP `409`：

```json
{
  "detail": {
    "code": "ORDER_ACTION_REQUIRED",
    "message": "這個身分在本團購已有訂單，請選擇加購或修改原訂單。",
    "public_order_number": "ABC234-001"
  }
}
```

前端顯示三個選項：

- `repeat_action: "add"`：保留原明細並加入本次品項；相同品項且相同備註會合併數量，不同備註維持分列。
- `repeat_action: "replace"`：以本次購物車完整取代原明細。
- 取消：不送出第二次請求，原訂單不變。

加購或修改成功回傳 HTTP `200`，`public_order_number` 維持不變並輪替私密 Token。後端會重新依團購菜單快照核價，不採信前端價格。若另一台裝置只有相同手機或 Email、卻沒有第一次送單憑證，回傳 `ORDER_ALREADY_EXISTS`；即使自行傳送 `repeat_action` 也回傳 HTTP `403`。登入使用者則可用後端驗證的同一 Google 帳號跨裝置更新。

此規則只套用團購。店家固定菜單可能每天持續接收同一顧客的新訂單，仍使用第 7.2 節的短時間重複與速率保護，不會永久鎖成一張訂單。

## 8. 管理者訂單查詢 API

- 方法：`GET`
- 路徑：`/api/admin/orders`
- 成功：回傳 HTTP `200 OK`
- 排序：建立時間較新的訂單在前；時間相同時，訂單編號較大的在前。

第一版不包含會員登入或權限管理，因此目前查詢 API 不要求登入。正式對外營運前若新增登入需求，必須另行規劃存取限制。

簡易管理後台可由 `/admin` 開啟；頁面會讀取此 API，並顯示訂單與完整明細。

回應包含 `orders` 陣列；沒有訂單時陣列為空。每張訂單包含：

- `order_id`：資料庫訂單編號。
- `customer_name`：顧客姓名。
- `created_at`：包含時區的建立時間。
- `total_amount`：訂單總金額。
- `items`：完整餐點明細，包含餐點識別碼、名稱、單價、數量與小計。

```json
{
  "orders": [
    {
      "order_id": 2,
      "customer_name": "陳小華",
      "total_amount": 195,
      "created_at": "2026-08-04T13:00:00Z",
      "items": [
        {
          "item_id": "sesame-noodles",
          "item_name": "麻醬麵",
          "unit_price": 65,
          "quantity": 3,
          "subtotal": 195
        }
      ]
    }
  ]
}
```
