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
