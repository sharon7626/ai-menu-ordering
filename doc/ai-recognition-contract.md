# AI 菜單辨識介面契約

最後更新：2026-08-08

## 1. 文件目的

本文件定義上傳檔案通過驗證後，如何交給 AI 辨識，以及 AI 必須回傳的統一資料格式。辨識結果只是「待確認資料」，不得直接覆寫 `data/menu.json`；店家確認與修正屬於後續 Todo。

「結構化輸出」是要求 AI 依固定 JSON 欄位回傳資料，讓後端可以安全檢查，而不是接收格式不固定的文字。

## 2. AI 服務決策

| 項目 | 決策 |
| --- | --- |
| 供應商 | Google Gemini Developer API |
| Python SDK | `google-genai==2.17.0` |
| 預設模型 | `gemini-3.6-flash` |
| 思考層級 | 預設模型使用 `low`，縮短菜單辨識等待時間 |
| 呼叫方式 | 後端使用非同步 `generate_content` |
| 輸出格式 | `application/json` 搭配 JSON Schema |
| 模型環境變數 | `GEMINI_MODEL`，未設定時使用預設模型 |
| Key 環境變數 | `GEMINI_API_KEY` |

選用 `gemini-3.6-flash` 是因為目前官方免費層包含輸入與輸出額度，並支援圖片、PDF 與結構化輸出。免費層有用量限制，Google 也可能調整模型、額度或條款，因此正式部署前必須重新確認。

免費層送出的內容可能被 Google 用來改善產品。本專案現階段只適合上傳公開、非機密的餐廳菜單；不得用它處理含個資、密碼、Token 或其他機密內容。

## 3. 輸入方式

檔案必須先通過 `doc/menu-upload-spec.md` 的格式、大小、內容與 PDF 頁數檢查。

- JPG、JPEG、PNG：以原始 bytes 和正確 MIME type 建立圖片 Part。
- 一頁式 PDF：以原始 bytes 和 `application/pdf` 建立文件 Part。
- 檔案以單次 inline data 傳送，不永久上傳至 Gemini Files API。
- 提示文字和檔案一起送出。
- 後端不把 Base64、完整菜單內容或 API Key 寫入 log。

## 4. 辨識原則

1. 只擷取檔案中實際可見的餐廳名稱、分類、品項名稱、說明與價格。
2. 保留原菜單順序，不得固定成飯類、麵類或任何預設分類。
3. 不得補出原檔沒有的內容。
4. 沒有分類時使用「未分類」。
5. 價格只保留大於或等於 0 的新臺幣整數。
6. 沒有說明時使用空字串。
7. 名稱或價格模糊時使用 `null`，將 `needs_review` 設為 `true`，並在 `warnings` 說明。
8. 必須比對餐點列、點線及價格欄；共用欄名如 M／L、大／小、冷／熱，應依欄位位置配對價格。
9. 同一品項有多個且規格清楚的價格時，拆成可獨立點選的項目，例如「紅茶（M）」與「紅茶（L）」，各自保存原菜單價格，不要求使用者重新輸入。
10. 套餐與單點價格若標示清楚，同樣拆成名稱清楚的獨立項目；不得自行任選一個價格。
11. 只有原圖文字或數字真的無法確認時才使用 `null`，不得只因菜單版面有多欄或多規格就將價格留空。
12. 不得依常識或其他菜單猜測。

## 5. 回傳格式

正式 Schema 位於 `doc/menu-recognition.schema.json`，所有物件都禁止未定義欄位。

| 欄位 | 型別 | 用途 |
| --- | --- | --- |
| `restaurant_name` | string 或 null | 可辨識的餐廳名稱 |
| `categories` | array | 依原菜單順序排列的分類 |
| `category.name` | string 或 null | 分類名稱 |
| `items` | array | 分類內的餐點 |
| `item.name` | string 或 null | 餐點名稱 |
| `item.description` | string | 菜單上實際說明，沒有時為空字串 |
| `item.price` | integer 或 null | 原菜單上的非負整數價格；規格明確時拆成獨立項目，只有真的無法確認時為 null |
| `needs_review` | boolean | 是否需要人工確認 |
| `warnings` | string array | 需要店家修正或注意的繁體中文訊息 |

完整範例：

```json
{
  "restaurant_name": "海風小館",
  "categories": [
    {
      "name": "飲品",
      "items": [
        {
          "name": "古早味紅茶",
          "description": "每日現煮",
          "price": 35
        },
        {
          "name": "冬瓜檸檬",
          "description": "",
          "price": null
        }
      ]
    }
  ],
  "needs_review": true,
  "warnings": [
    "冬瓜檸檬的價格模糊，請人工確認。"
  ]
}
```

## 6. 與正式 menu.json 的關係

AI 回傳不包含正式分類與餐點 ID，也允許部分名稱或價格為 `null`，所以不能直接成為正式菜單。後續流程必須先讓店家人工修正，再產生小寫英文與連字符組成的 ID，最後才寫入統一的 `menu.json` 格式。`available` 初始值預計為 `true`。

餐廳名稱為 `null` 不代表菜單無效，因為原始菜單可能沒有印店名。確認頁必須允許團購主揪或店家手動輸入一個方便辨識的餐廳名稱；名稱仍為空白時不得建立團購或固定菜單。這項人工補填只處理餐廳名稱，不代表團購模式可以修改 AI 辨識出的餐點名稱或價格。

## 7. 錯誤處理

| 錯誤識別碼 | 使用者訊息重點 |
| --- | --- |
| `AI_NOT_CONFIGURED` | 後端沒有有效的 Gemini API Key |
| `AI_RATE_LIMITED` | 短時間請求過多，稍後再試 |
| `AI_QUOTA_EXHAUSTED` | 今日免費額度可能用完，稍後或隔天再試 |
| `AI_SERVICE_UNAVAILABLE` | 網路或 Gemini 暫時無法使用 |
| `AI_REFUSED` | 檔案被安全規則阻擋 |
| `AI_RESPONSE_INCOMPLETE` | AI 回應遭截斷 |
| `AI_OUTPUT_INVALID` | AI 回應不符合 Schema |
| `AI_NO_MENU_FOUND` | 沒有找到任何餐點 |

失敗時不得寫入正式菜單，前端只顯示安全且容易理解的訊息，不顯示供應商原始錯誤、API Key 或內部路徑。後續 Todo 第 18 項會提供人工修正流程，作為免費額度不足或辨識不完整時的實用備援；本任務不先建立該介面。

單次請求維持 60 秒逾時。一般 429 暫時限流、Gemini 5xx、HTTP 逾時、傳輸錯誤或 `OSError` 最多重試 2 次。若 Gemini 的結構化 `RetryInfo.retryDelay` 或 HTTP `Retry-After` 有提供等待時間，優先依供應商資訊等待；沒有時才使用約 1 秒與 2 秒的遞增備援。

每日額度只能由結構化 quota ID 或安全的備援文字明確判定為 `PerDay`／`Daily`；`FreeTier` 只代表額度層級，不能單獨判定每日額度用完，因為每分鐘 RPM／TPM 限制也可能標示為 FreeTier。401／403、明確的每日 quota exhausted、安全拒絕、回應截斷、無效輸出及沒有菜單內容等不可恢復錯誤不重試。

每次呼叫只在後端 console 記錄 attempt（例如 `1/3`）、開始時間、成功或失敗、單次耗時、是否重試、等待秒數及是否為最終結果；失敗時只追加 APIError HTTP code、安全分類後的 quota 類型，或錯誤類型 `TimeoutException`、`TransportError`、`OSError`。不得記錄 API Key、Token、錯誤原文、上傳檔案內容、訂單個資或其他請求資料。

## 8. 官方參考

- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini document understanding](https://ai.google.dev/gemini-api/docs/document-processing)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
