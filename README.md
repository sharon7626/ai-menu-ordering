# AI 菜單點餐系統

本專案使用 AI 將 JPG、PNG 或一頁式 PDF 菜單轉成統一資料，讓不同菜單都能使用同一套點餐頁面。系統共用菜單、購物車與訂單核心，並分成兩種使用模式。

## 產品模式

### 一般使用者團購模式（優先開發）

統籌上傳並確認菜單後，系統建立團購代碼與統籌管理連結。參與者使用代碼進入同一份菜單，各自輸入姓名、選擇餐點並取得個人訂單編號。統籌可查看個人明細、依餐點彙整數量與金額，最後複製文字摘要，自行打電話或傳訊息向店家訂購。

### 店家固定菜單模式

店家預先設定自己的固定菜單，顧客透過固定網址或 QR Code 點餐。每位顧客送單後取得個人訂單編號，店家可從後台依編號與姓名查看餐點，辨識每份餐點屬於誰。

兩種模式不會共同覆寫全站唯一菜單：團購使用該次團購的菜單快照，店家模式使用屬於店家的固定菜單。`data/menu.json` 只保留為開發與未串接 AI 時的示範資料。

## 目前已完成

- 統一 `menu.json` 菜單格式與示範菜單。
- HTML、CSS、JavaScript 點餐頁面。
- 品項數量、購物車與總金額。
- 姓名送單、FastAPI API 與 SQLite 儲存。
- 簡易訂單管理後台。
- JPG、PNG、一頁式 PDF 上傳與驗證。
- Gemini 免費層菜單辨識。
- 餐廳名稱、分類、品項名稱與價格的人工修改及確認介面。
- 團購模式與店家固定菜單模式的需求及開發順序。
- 團購資料格式、菜單快照、公開代碼與私密 Token 的安全規格。
- SQLite 團購、菜單快照及訂單關聯資料表。
- 人工確認菜單後建立團購代碼、菜單快照與私密管理連結。
- 團購代碼輸入頁、分享連結與公開團購菜單。
- 團購參與者選餐、購物車、姓名送單與個人訂單編號。
- 以私密個人連結查看自己的團購訂單。
- 以私密統籌連結查看團購全部個人明細。
- 統籌依餐點查看總份數、品項金額與團購總金額。
- 統籌關閉團購並複製可傳給店家的純文字摘要。
- 團購模式 AC-08 至 AC-12 完整整合驗收。
- 店家固定菜單建立、私密更新連結與菜單版本更新。
- 店家固定公開網址、公開菜單頁與不含管理資訊的 QR Code。
- 店家顧客購物車、姓名送單、個人訂單編號與私密個人查看頁。
- 店家私密訂單後台，可依訂單編號與姓名查看該店顧客的餐點及數量。
- 店家模式 AC-13 至 AC-15 與雙模式資料隔離整合驗收。
- 雙模式系統首頁，可分別建立團購、加入團購或建立店家固定菜單；兩種建立流程都能上傳菜單並進行 AI 辨識。
- 團購與店家點餐都可為每個餐點填寫選填備註，並在個人訂單與管理後台顯示。
- AI 辨識確認畫面直接顯示實際分類、菜名與價格，不使用「品項 1、2」作為名稱。
- L／XL、大小份等明確多價格菜單會拆成各自帶有原價的可點項目，不因多價格而要求全部手動輸入。
- 首頁直接分成「主揪上傳建立」、「參與者輸入代碼」及「店家建立固定菜單」，並顯示團購五步驟。
- 團購確認頁鎖定 AI 辨識名稱與價格，主揪只勾選本次提供的餐點。
- 點餐頁採緊湊清單，選取餐點後才展開該品項備註；相同餐點的不同需求會分開彙整。
- 統籌與店家管理頁的個人明細以姓名為標題，不在姓名前加訂單代碼。

主要 MVP 與發布前操作修正已完成，目前進入 GitHub、Render 與 PostgreSQL 發布準備。

## 預定技術

- 前端：HTML、CSS、JavaScript（不使用 React 或 Vite）
- 後端：Python、FastAPI
- 本機資料庫：SQLite
- AI：Google Gemini Developer API 免費層
- 版本管理：Git、GitHub
- 部署：Render
- 正式資料庫：Render PostgreSQL

## 本機啟動

在專案根目錄執行：

```powershell
C:\Users\sharo\anaconda3\python.exe -m uvicorn backend.main:app --reload
```

再開啟 `http://127.0.0.1:8000`。未設定 `DATABASE_URL` 時會使用本機 `app.db`；真正的 `.env`、API Key 與正式資料庫網址不得提交至 Git。

## Render 部署摘要

- Python：3.12 系列，由 `.python-version` 指定。
- Build Command：`pip install -r requirements.txt`
- Start Command：`uvicorn backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'`
- 正式資料庫：同區域 Render PostgreSQL 的 Internal Database URL。
- 必要機密：`GEMINI_API_KEY`、`DATABASE_URL` 與 `FIREBASE_SERVICE_ACCOUNT_JSON` 只能放在 Render Environment Variables；Firebase Web App 設定也由環境變數提供，不寫入 Repository。

完整設定與第一次正式驗收方式請見 [Render 部署指南](doc/render-deployment-guide.md)。
第二版帳號與品牌功能發布前，請依 [Production 部署前清單](doc/production-deployment-checklist.md) 先備份正式資料，再逐步設定及驗收。

## 專案文件

- [需求規格](doc/requirements.md)
- [點餐模式與資料歸屬](doc/ordering-modes-spec.md)
- [團購資料格式與安全規格](doc/group-order-data-spec.md)
- [團購模式整合驗收](doc/group-order-acceptance.md)
- [店家固定菜單資料格式與入口](doc/store-menu-data-spec.md)
- [店家模式與雙模式整合驗收](doc/store-mode-acceptance.md)
- [菜單資料格式](doc/menu-data-spec.md)
- [開發待辦](doc/todo.md)
- [專案記憶](doc/project-memory.md)
- [Render 部署指南](doc/render-deployment-guide.md)
- [Production 部署前清單](doc/production-deployment-checklist.md)

## 第一版不包含

會員登入、多店家帳戶與多分店平台、外送派單、線上付款、電子發票、自動 LINE 或簡訊通知、POS 串接、複雜套餐、固定加料或規格選單與自動加價，以及保證辨識所有手寫或複雜菜單。
