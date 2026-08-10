---
name: guided-mvp-development
description: Guide beginner-friendly MVP development in the ai-menu-ordering repository by reading project documents, selecting the next unblocked Todo, implementing exactly one independently testable task, verifying it, and updating project memory. Use when Codex is asked to continue, implement, or guide the next development step in this project.
---

# 引導式 MVP 開發

協助初學者在 `ai-menu-ordering` 專案中，依既有文件與 Todo 一次完成一個可獨立驗收的小任務。

## 1. 開始前檢查

1. 確認目前工作資料夾名稱是 `ai-menu-ordering`；若不是，立即停止且不得修改任何檔案。
2. 依序完整閱讀：
   - `AGENTS.md`
   - `doc/requirements.md`
   - `doc/project-memory.md`
   - `doc/todo.md`
   - 與本次任務相關的規格文件
3. 檢查現有檔案與 Git 工作目錄狀態，保留使用者既有修改，不覆蓋無關內容。
4. 找出 `doc/todo.md` 中下一個未完成、相依任務已完成且沒有阻擋的任務。若使用者指定的工作與此任務不同，先說明差異並停止等待確認，不得自行改做其他項目。

## 2. 執行前回報

在修改任何檔案前，以繁體中文簡短回報：

- 本次唯一目標。
- 為什麼現在做這一步。
- 預計修改哪些檔案。
- 如何確認完成。
- 本次明確不做什麼。

首次出現技術名詞時，用一句白話說明。操作步驟保持單一路徑，不一次提供過多分支方案。

## 3. 執行範圍

一次只執行一個可獨立測試、可明確驗收的小任務。採用最小必要變更，遵守已確認需求、技術選型、資料規格與安全規範。

未經使用者明確批准，不得：

- 擴大產品範圍或增加未確認功能。
- 增加新技術或框架。
- 安裝套件。
- 建立未批准的 API 或資料表。
- 串接 AI API。
- 部署。
- 執行 Git commit 或 push。
- 修改其他專案。

遇到需求衝突、必要決策尚未確認、資料可能遺失或工作會超出唯一目標時，停止並以白話說明阻擋原因。

## 4. 完成與驗收

修改完成後依序執行：

1. 執行與本次變更相稱的最小必要測試，不安裝未批准工具。
2. 記錄實際執行的測試指令與完整結果，不得只說「應該可以」。
3. 說明使用者如何在自己的電腦親自測試。
4. 只有在驗收通過後，才將 `doc/todo.md` 中對應的唯一任務標記為 Done；不得修改其他任務狀態。
5. 更新 `doc/project-memory.md` 的「目前進度」，只加入已驗證完成的事實，並保留既有重要決策。
6. 列出本次建立或修改的檔案。
7. 說明是否有錯誤、風險、阻擋或待確認事項。
8. 停止工作，等待使用者批准下一步。

## 5. 回覆規則

- 全程使用繁體中文。
- 對初學者使用白話、短句與明確結果。
- 先說明成果或目前狀態，再補充必要技術細節。
- 不把未執行的檢查寫成已通過，也不隱藏錯誤。
