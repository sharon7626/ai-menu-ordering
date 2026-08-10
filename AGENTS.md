# 專案協作規範

本文件適用於專案根目錄及其所有子目錄。所有開發代理與協作者皆必須遵守以下規範。

## 機密資訊安全規範

- 禁止將 API Key、密碼、Token、Cookie、Session Secret 或正式資料庫連線字串寫入程式碼。
- 禁止將 API Key、密碼、Token、Cookie、Session Secret 或正式資料庫連線字串提交至 Git。
- 所有機密資料必須透過環境變數讀取。
- `.env.example` 只能放變數名稱與安全的示範值，不得包含任何真實機密資料或正式資料庫連線字串。
- 不得要求使用者貼出完整 API Key 或密碼。
- AI API Key（包含 Gemini API Key）只能由後端使用，不得出現在 HTML、前端 JavaScript、瀏覽器畫面或前端打包檔案。
- 部署至 Render 時，機密資料必須設定在 Render 的 Environment Variables，不得寫入 Repository。
- 不得建立或提交真正的 `.env`；本機需要機密設定時，應由使用者自行建立受 `.gitignore` 排除的 `.env`。
