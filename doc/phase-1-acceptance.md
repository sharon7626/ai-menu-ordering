# 第一階段整合驗收紀錄

驗收日期：2026-08-04

## 1. 驗收範圍

本次依 `doc/requirements.md` 的 AC-01 至 AC-07，完整驗證固定 `menu.json` 點餐底座。測試使用獨立的 `.phase1-acceptance.db`，未讀寫既有 `app.db`，也未設定或使用 AI API Key。

## 2. 測試環境與指令

後端以本機 FastAPI 服務啟動：

```powershell
$env:DATABASE_URL="sqlite:///./.phase1-acceptance.db"
& "C:\Users\sharo\anaconda3\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8012
```

自動測試：

```powershell
& "C:\Users\sharo\anaconda3\python.exe" -m unittest discover -s tests -v
```

另以實際瀏覽器操作顧客點餐頁與 `/admin` 管理後台，並直接查詢測試用 SQLite 資料庫核對寫入結果。

## 3. 驗收結果

| 編號 | 結果 | 實際驗證內容 |
| --- | --- | --- |
| AC-01 | 通過 | 顧客頁正確顯示「島味小館」、2 個分類、6 個餐點、價格與「暫停供應」狀態。 |
| AC-02 | 通過 | 同時選擇滷肉飯 2 份與紅燒牛肉麵 1 份，兩個品項及不同數量皆正確。 |
| AC-03 | 通過 | 購物車顯示滷肉飯小計 NT$ 90、紅燒牛肉麵小計 NT$ 150，總金額為 NT$ 240。 |
| AC-04 | 通過 | 輸入「第一階段驗收」後成功送單，頁面顯示訂單編號 1，並清空姓名與購物車。 |
| AC-05 | 通過 | SQLite 寫入 1 張訂單及 2 筆明細；姓名、單價、數量、小計與總金額 240 均正確。 |
| AC-06 | 通過 | `/admin` 顯示訂單編號 1、顧客姓名、建立時間、總金額及兩筆完整餐點明細。 |
| AC-07 | 通過 | 未設定 AI API Key、未呼叫 AI API，仍可完成菜單顯示、購物車、送單、SQLite 儲存及後台查詢。 |

結論：第一階段 AC-01 至 AC-07 全部通過，固定 `menu.json` 的點餐底座可獨立使用。

## 4. 其他檢查

- `data/menu.json` 可由 Python 內建 `json` 模組讀取，共 2 個分類、6 個餐點。
- `frontend/app.js` 與 `frontend/admin.js` 通過 JavaScript 語法檢查。
- 後端與測試 Python 檔案通過編譯檢查。
- 5 項自動測試全部通過，涵蓋訂單交易、失敗回復及管理查詢。
- 管理後台在實際瀏覽器中沒有水平溢出。

## 5. 已知範圍

- 第一版依已確認需求不包含會員登入，因此簡易管理後台目前沒有登入保護；公開部署前需要重新評估存取保護。
- AI 菜單上傳與辨識屬於第二階段，本次未開始實作。
