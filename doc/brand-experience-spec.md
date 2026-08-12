# 品牌視覺與互動體驗規格

最後更新：2026-08-11

## 1. 品牌目標

網站應呈現舒服、高級、放鬆、安靜、自然且容易使用的感受。首頁可以有探索感，進入上傳、點餐與管理任務後則逐步收斂，功能速度與清楚度永遠優先。

參考方向只限設計語言：

- Chloe Yan：空間感、可探索構圖、柔和游標與物件回應。
- Fidlerówna：editorial 編排、字體層級、留白及 quiet luxury。

不得複製參考網站的圖片、插畫、文字、品牌、場景或版面。

## 2. 共用 Design System

先建立全站共用 CSS Variables：

- 色彩：暖米白背景、象牙 surface、深色文字、低飽和自然綠、少量陶土暖色。
- 字級：display、heading、title、body、caption 與英文小標。
- 間距：小至大型 spacing scale。
- 圓角、框線、陰影、容器寬度與層級。
- 動畫：`--motion-fast`、`--motion-normal`、`--motion-slow`、`--ease-standard`。
- 響應式斷點與安全頁面 padding。

共用元件至少包含：

- button、input、select、textarea。
- surface、card、badge。
- nav、modal、toast。
- loading、empty state、error state。
- focus ring 與 disabled 狀態。

## 3. 色彩基礎

起始方向如下，實作時需以對比測試微調：

```css
--color-bg: #f2efe7;
--color-surface: #faf8f2;
--color-text: #20211d;
--color-muted: #6f716a;
--color-line: #d8d3c7;
--color-accent: #5f6f5a;
--color-warm: #9a5f48;
```

避免紫色 AI gradient、霓虹、glassmorphism、大量 blur、發光框、科技網格與機器人視覺。

## 4. 首頁資訊架構

1. 第一屏：品牌名稱、主標「一張菜單，讓大家一起點。」、副標、建立團購 Primary CTA、加入團購 Secondary CTA，以及不搶主操作的登入入口。
2. 流程區：01 上傳菜單、02 確認品項、03 分享團購、04 自動彙整；以數字、線條與文字形成連續節奏，不做四張傳統 SaaS 卡片。
3. 店家入口：「已經有常用菜單？」與固定菜單功能。
4. 帳號價值：未登入顯示跨裝置找回說明；登入後顯示我的團購與最近訂單摘要。

主要操作永遠可直接辨識，不藏在裝飾或 hover 裡。

## 5. 首頁互動

- 抽象 MENU、ORDER、SHARE、菜單、小票、游標及人數元素可形成輕量空間構圖。
- 滑鼠移動只造成非常小的 `transform` 位移。
- CTA 可使用輕微 magnetic response，但不能逃離點擊區或延遲導覽。
- 文字與 section 使用短暫 reveal／staggered entrance。
- 有機背景形狀可緩慢移動，不能遮住資訊或造成大量重繪。
- 不做 scroll hijacking、假 loading、長頁面轉場或只能桌面操作的互動。

## 6. 內頁互動強度

| 頁面 | 建議強度 | 原則 |
| --- | --- | --- |
| 首頁 | 7／10 | 可探索、有空間感，但主入口明確。 |
| 建立／上傳 | 3／10 | 明確進度與狀態回饋，裝飾收斂。 |
| 團購／店家點餐 | 2／10 | 分類、品項、規格、價格、數量與備註優先。 |
| 管理頁 | 1／10 | 安靜、資訊密度清楚，不使用干擾性動畫。 |

## 7. 點餐與購物車

- 同一 base item 只顯示一次，variants 仍保留獨立價格、數量與備註。
- Selected 狀態使用柔和 surface、細框與低飽和 accent，不使用鮮豔底色。
- 購物車採小票式排版，以字體與間距呈現層級，不堆疊大量 card。
- 手機上的增減按鈕與送單按鈕必須容易觸控，文字不得截斷。

## 8. 管理頁

- Header 優先呈現團購／店家名稱、狀態、人數、餐點數與總金額。
- People、Items、Export 使用清楚分區與 typography，減少厚重框線。
- 關閉團購等危險操作清楚可見但避免大片刺眼紅色。
- Excel 與複製功能保持直接，不因動畫延遲。

## 9. 登入介面

- 未登入時右上使用次要「登入」入口。
- 點擊後才顯示「Continue with Google」及跨裝置找回說明。
- 不使用「加入會員」、「立即註冊」或強迫登入文案。
- 登入後顯示簡潔名稱選單：我的團購、我的訂單、我的菜單（若實作）、登出。

## 10. Mobile 與降級

至少驗證 375、390、430、768 像素及桌面。

- 手機取消游標跟隨與 hover-only 互動。
- 裝飾元素減量、縮小或隱藏，但不得移除功能資訊。
- 使用 tap、soft press 與 scroll reveal 取代 hover。
- 不得水平溢出、遮住菜單、縮小觸控區或讓固定購物車蓋住品項。

## 11. 動畫與效能

- 120～180ms：按鈕、輸入與 hover。
- 250～400ms：卡片、modal、toast、內容 reveal。
- 600～900ms：首頁少量 ambient motion。
- 優先 CSS `transform` 與 `opacity`；必要時才使用單一 `requestAnimationFrame` 迴圈。
- 不加入 Three.js、WebGL、GSAP 或大型動畫函式庫。
- 避免大量 DOM、陰影、blur、巨大圖片、未壓縮影片及阻擋導覽的動畫。

## 12. Accessibility

- 所有操作支援鍵盤與明確 `:focus-visible`。
- 表單保留 label、錯誤關聯與必要 ARIA。
- 文字及控制項通過足夠對比。
- 互動不只靠顏色或 hover 表達。
- 支援 `prefers-reduced-motion`，停用非必要位移與 ambient motion。
- 觸控目標維持可操作尺寸。

## 13. 驗收範圍

- 首頁、菜單上傳、AI loading、菜單確認、建立／加入團購、點餐、個人訂單、我的團購、我的訂單、團購管理、店家公開頁及店家後台。
- 每頁驗證 loading、empty、error、長文字及多 variants。
- Gemini、crop、團購碼、分享、QR Code、Excel、PostgreSQL 與 Render 原有功能不得被改版破壞。
- 正式 Production 不作為開發測試機；完成本機程式、migration 與測試後，必須先向使用者說明部署步驟並停止等待批准。
