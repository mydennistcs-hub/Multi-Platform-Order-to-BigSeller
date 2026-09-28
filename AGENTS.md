# Multi-Platform-Order-to-BigSeller 專案規則

本檔適用於此 repository 全部檔案；若子資料夾另有更近的 `AGENTS.md`，以較近規則優先。溝通、文件與程式註解預設使用繁體中文。

## 開工前必讀

1. 先讀 `CLAUDE.md` 的專案架構與 API 眉角。
2. 讀 `開發記錄.md` 最近一筆與「待辦 / 已知限制」。
3. 涉及轉檔操作時再讀 `使用說明.md`，並確認 `git status --short`，不可覆蓋既有未提交修改。
4. `Data/`、`.env`、`accounts.json` 含訂單個資或憑證，只可在本機必要範圍內讀取；不可提交、外傳或在回覆中揭露姓名、電話、地址、訂單號、金鑰與 token。

## App 與資料流

- 日常 GUI 由 `啟動API主控台.bat` 啟動，實際執行 `python app.py`；改原始碼後不用重新打包即可生效。
- `converter.py` 是 mo店+ / Coupang Excel、PDF 轉 BigSeller 模板的共用核心；PySide6 的「訂單轉換」分頁直接呼叫 `convert_orders()`。
- `api_sync/ui/handlers.py` 負責 API 回應攤平與官方格式欄位映射；`api_sync/ui/excel_export.py` 負責輸出 Excel；`api_sync/ui/query_panel.py` 負責 GUI 匯出流程。
- BigSeller 模板以第 1 列表頭定位欄位，第 5 列起才是資料。不可依固定欄號假設模板永遠不插欄。
- API 訂單匯出第一張工作表必須維持平台官方格式，讓 `converter.py` 可直接讀取；額外完整資料可放後續工作表，不可改變第一張工作表的表頭語意。

## 現行固定值與相容性

- BigSeller 店鋪名稱必須精確使用：mo店+ 為 `mo店+`，Coupang 為 `酷澎 coupang`。
- 倉庫名稱維持 `樸翔初耘18號8樓 mo店+倉庫` 與 `樸翔初耘18號8樓 Coupang倉庫`，除非使用者明確確認 BigSeller 倉庫也已更名。
- SKU 後綴維持 `-mo94234570` 與 `-cou94234570`；平台費率維持目前程式定義，變更前要有新的業務依據。
- 只把可由官方 API 欄位直接確認或可靠計算的值映射到官方匯出欄位。語意不確定的欄位留空並在 `API原始欄位` 保留來源，不可拿相近數字湊欄位。
- momo API 匯出要保留 converter 需要的純中文訂單狀態、純數字商品售價與表頭；Coupang 的 `選項價格` 必須是純數字，不可寫成 `599 TWD`。
- 7-11 完整運單號可能只能從寄件單補齊；不可用推測值補後四碼。

## Excel、訂單與 API 安全

- `Data/` 原始 Excel/PDF 一律唯讀分析。需要解密或跑轉換時，先複製到暫存資料夾，因為現有解密流程可能移除密碼並覆蓋輸入檔。
- BigSeller 模板是覆寫式產出；驗證時使用暫存副本。不要把客戶資料寫進測試 fixture 或 Git。
- 沒有固定 IP / VPN 時不得把 API 未能實測說成已驗證。清楚區分：靜態檢查、離線模擬、真實平台 API、BigSeller 實際上傳。
- 查詢結果達到 UI 上限時可能還有未取回資料；不可把截斷結果描述成完整訂單集。
- 對外 API、出貨確認、安排出貨與下載標籤的狀態異動邊界，以 `CLAUDE.md` 為準；不得為測試執行會改變平台訂單狀態的操作。

## 修改與驗證

- 做最小、內聚的修改；先維持 Phase 1 手動匯入與 Phase 2 API 主控台兩條路都可用。
- 改 `converter.py`、API 欄位映射或 Excel 匯出後，至少執行：

  ```powershell
  python -m compileall converter.py api_sync
  python -m unittest discover -s tests -v
  ```

- 轉檔核心變更要再用 `Data/` 參考檔的暫存副本做離線全鏈路驗證：來源可讀、模板前 4 列保留、資料由第 5 列開始、BigSeller 必填欄位非空、店鋪名稱正確、輸出可重新開啟。
- UI 變更不能只報 compile/test；需以 `QT_QPA_PLATFORM=offscreen` 建立 `MainWindow`，必要時再做實際畫面檢查。不得在沒有固定 IP 時呼叫真實平台 API。
- 完成實質功能變更後更新 `開發記錄.md`；使用者操作、固定值或已知限制改變時同步更新 `使用說明.md` 與 `CLAUDE.md`。
- 除非使用者明確要求，不要重新打包 `dist/`；原始碼驗證與打包 EXE 驗證必須分開回報。

## 批次檔與打包

- `.bat` 必須維持純 ASCII，不要加入中文、`chcp 65001` 或 `^` 續行；中文訊息與複雜邏輯放 Python。
- Phase 2 打包流程是 `打包API主控台.bat` → `build_api_console.py` → `Multi-Platform-API-Console.spec`。
- QtWebEngine / PyMuPDF 是 Coupang 寄件單正確轉 PDF 所需，不可為縮小體積任意移除。

最後更新：2026-09-28（Asia/Taipei）。
