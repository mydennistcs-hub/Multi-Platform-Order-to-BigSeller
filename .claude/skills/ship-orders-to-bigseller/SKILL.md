---
name: ship-orders-to-bigseller
description: 用 Claude in Chrome 處理 mo店+／Coupang（格魯維爾、丹尼書）的新訂單：先查 BigSeller 和 Data 避免重複，再出貨、下載物流單／出貨明細 PDF、匯出訂單報表，用 converter.py 產生 BigSeller 匯入 Excel（全部放進本專案 Data\），最後經使用者同意後上傳匯入 BigSeller 並讀回核對。使用者說「有新訂單請安排出貨」「幫我做匯入檔」「mo店+／酷澎有新單」「匯入 BigSeller」時使用。OpenMall 尚未支援。
---

# 平台訂單出貨 → BigSeller 匯入檔

本 skill 只寫流程與規則，**不含任何客戶資料**。細節規則以專案 `CLAUDE.md`、`使用說明.md` 為準，兩者衝突時以 CLAUDE.md 為準。

## 0. 不可違反的規則

- **會改變平台狀態的按鈕，按之前一定先問使用者**（列出訂單編號、品項、物流方式、出貨地址），等明確同意才按：
  - mo店+：「可出貨」→「確認提交」（訂單變成已印單，無法復原）。
  - Coupang Wing：「確認訂單」、「安排出貨」→「提交」（無法復原）。
  - BigSeller 匯入：可以由 Claude 上傳檔案，但**按「确定」前一定先停下來問**（2026-11-18 使用者同意列為固定流程，見第 6 步）。
  - BigSeller 打單、出庫：不代做，由使用者自己處理。
- 重新列印、匯出報表、搜尋、讀取頁面是唯讀，可直接做。
- 遇到登入頁或驗證碼，請使用者自己完成，不輸入帳密。
- 出貨地一律是 **桃園市中壢區南園二路381巷18號8樓**；畫面上不是這個地址就停下來問。
- `Data\` 有客戶個資：不 commit、不外傳。下載資料夾的原檔複製進 Data 後，移到資源回收筒（不永久刪除）。
- 回覆用繁體中文，最終回覆依全域格式：需求摘要 → 結論 → 細節 → 變更的檔案 → 下一步。

## 1. 選 Chrome 設定檔並核對公司

| 平台／公司 | Chrome 設定檔 | 頁面上要看到 |
|---|---|---|
| mo店+ 格魯維爾 | 0970022250 | 右上角「Superior Choice-000」，統編 94234570 |
| Coupang 格魯維爾 | 0970022250 | Wing 顯示格魯維爾 |
| mo店+ 丹尼書 | 0966324019 | 右上角「Awesome Po-000」，統編 90154390 |
| Coupang 丹尼書 | 0966324019 | Wing 顯示丹尼書 |
| OpenMall | 待補 | 還不知道後台訂單格式，遇到時先問使用者 |

- Claude in Chrome 連線清單只顯示「Browser N」。要指定設定檔時用 `switch_browser`，請使用者在該視窗按 Connect。
- 一定要讀回頁面上的公司名／統編再動手，只看設定檔很容易選錯店。

## 2. 去重（每次動手前必做）

1. **查 Data\**：讀 `Data\import_manual_order_*.xlsx`（模板 `import_manual_order_template_cn.xlsx` 除外）的「订单号」欄，列出已做好匯入檔的訂單編號。
2. **查 BigSeller**（0970 的 BigSeller，`https://www.bigseller.com/web/order/index.htm?status=all`）：在「全部订单」用訂單編號批次搜尋（逗號分隔）。頁面一開始可能空白或一直轉圈：先開 `https://www.bigseller.com/web/index.htm`（會轉到首頁），再回訂單頁等約 10 秒。已匯入的單可能不在「待處理」，而是在「待打单」等其他分頁，所以要用全部订单搜尋。
3. 平台上的新單扣掉上面兩者，剩下的才處理。
   - 已出貨、BigSeller 沒有、Data 也沒有匯入檔的單：只補做匯入檔，不再出貨。
   - Data 有匯入檔、BigSeller 沒有：提醒使用者匯入，不重做。
4. 把去重結果列給使用者看，再進入出貨步驟。

## 3. mo店+ 出貨

後台：`https://3p.momo.com.tw/FrameServlet.do` → 訂單 → E001訂單管理。

1. 「訂單出貨」計數區點超取或第三方的「未印單」，列出訂單。
2. 每張單：「操作」→「可出貨」→ 勾選全部品項 →（先問使用者）→「確認提交」。
3. 出貨成功視窗依序按「列印標籤」「列印明細」，第三方（新竹貨運）另有「列印出貨總表」。第三方視窗的出貨／回收地址要是 18 號 8 樓。
4. 漏下載的檔案：到「配送中」用訂單編號搜尋 →「操作 → 重新列印」補，不會改狀態。
5. 匯出報表：「配送中」→「匯出報表」。
   - 搜尋欄清空會匯出全部配送中的單；converter 只挑「已印單／已印單待寄件」的列。
   - 如果裡面有之前已匯入、但仍是已印單的單，會重複轉出。這時改用訂單編號搜尋，只匯出這次的單。
6. 後台自動產生的檔名是 `LogisticsLabel_/LogisticsDetail_/LogisticsData_/OrderExport_TP0001949_{yyyyMMddHHmmss}`，看不出平台和物流。PDF 複製進 Data 時要改名（見第 5 步第 1 點），OrderExport 報表維持原名。
7. 收件人真名：明細 PDF 是遮罩名時，用「重新列印 → 列印明細」再下載一次確認，不要直接當成查不到。

## 4. Coupang 出貨（Wing）

後台：`https://wing.coupang.com/tenants/sfl-portal/delivery/management`。

1. 「我的訂單」→「訂單確認」勾選 →（先問使用者）→「確認訂單」。
2. 「配送準備」→「安排出貨」，核對取貨地址是 18 號 8 樓 →（先問使用者）→「提交」。
   - 宅配一律新竹物流（HCT）。7-11 的退貨門市沿用後台預設，不改。
3. 寄件單：
   - 宅配（新竹）：「列印寄件單」只把 PDF 載進頁面，不會存檔，要從頁面另存。PDF 在頁面的 `iframe[src^="blob:"]` 裡：用 JS `fetch` 該 blob，確認開頭是 `%PDF-` 後用 `<a download>` 存成下面的檔名。
   - ⚠️ 按過「列印寄件單」後，頁面常會卡住，之後的點擊都沒反應（2026-11-22 實測）。每印完一張就重新載入頁面，再印下一張或做其他操作。
   - 7-11：寄件單開在空白新分頁，另存成 HTML 後用 `api_sync/qt_html_pdf.py` 轉 A4 PDF。
   - 檔名：`{yyyyMMdd}_{HHMMSS}_{統編}_coupang_{物流}.pdf`。
4. DeliveryList：在「配送指示」按「下載Excel」，下載檔名是 `DeliveryList(yyyy-MM-dd)_(0).xlsx`，複製進 Data 時改成 `DeliveryList_{yyyyMMddHHmmss}_{公司}.xlsx`。
   - ⚠️ 剛用 JS 存過寄件單或列印過的頁面，按「下載Excel」常常沒反應、什麼都沒下載（2026-11-22 實測）。重新載入頁面、回到「配送指示」再按一次，就能正常下載。按完要到下載資料夾確認檔案真的有出現。
   - 重新載入後還是下載不了，才讀頁面內容在本機重建。
5. 7-11 運單號：Excel 只有前 8 碼，完整 12 碼在寄件單「交貨便服務代碼」。converter 讀得到寄件單時會自動補齊，轉完要讀回確認。
6. Surfshark 固定 IP 有連上時，也可以改用 API 主控台（`啟動API主控台.bat`）走 ①②③。

## 5. 產生 BigSeller 匯入檔

1. 下載的檔案從 `C:\Users\FG\Downloads` 複製到 `Data\`，確認複製成功後，把下載資料夾的原檔移到資源回收筒：
   `[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(path,'OnlyErrorDialogs','SendToRecycleBin')`
   - **PDF 檔名要看得出平台和物流**（2026-11-21 使用者要求）。複製進 Data 時直接用新檔名：
     - mo店+：`{yyyyMMdd}_{HHMMSS}_{統編}_mo店+_{物流}_{標籤|明細|出貨總表}.pdf`。日期時間沿用後台檔名上的時間戳。物流寫 `7-11`、`全家` 或 `新竹`（第三方物流）。
       例：`LogisticsLabel_TP0001949_20261121143015.pdf` → `20261121_143015_94234570_mo店+_7-11_標籤.pdf`。
     - Coupang：`{yyyyMMdd}_{HHMMSS}_{統編}_coupang_{物流}.pdf`（第 4 步的現行格式，不變）。
   - 比對雜湊要拿 Downloads 原檔和 Data 新檔名那份比。
   - 只套用新下載的檔案，Data 裡 2026-11-21 以前的舊檔不改名（使用者決定）。
   - converter 讀的是 PDF 內容，不看檔名，改名不影響轉檔。
2. 複製 `Data\import_manual_order_template_cn.xlsx` 成輸出檔：`import_manual_order_{yyyyMMdd}_{公司}{平台}[_補充].xlsx`，例如 `import_manual_order_20261117_格魯維爾mo店+.xlsx`。**模板本身不可修改。**
3. 執行（`PYTHONIOENCODING=utf-8`，用專案 `.venv`）：
   ```
   .venv/Scripts/python.exe -X utf8 -c "import converter; converter.convert_orders(<mo店+ OrderExport 或 ''>, <輸出檔>, [<PDF...>], '<統編>', print, lambda *a: None, coupang_path=<DeliveryList 或 ''>, company='<格魯維爾|丹尼書>')"
   ```
   - 簽名是 `convert_orders(mo_path, template_path, pdf_paths, password, log, progress, coupang_path="", company=...)`。
   - `template_path` 會被直接寫入，所以要傳複製出來的輸出檔，不能傳模板本身。
   - 密碼就是該公司的統編。
4. 讀回輸出檔逐欄核對：订单号、店铺（`mo店+`／`酷澎 coupang`）、收件人、地址（超取寫「店號 超取 XX門市」）、物流名称／运单号、店铺SKU（後綴 `-mo{統編}`／`-cou{統編}`）、单价、数量、优惠。
5. 「优惠」：
   - mo店+：`售價×數量 −（訂單進帳金額 − |(預估)手續費_調整金額|）`，v0.26 自動計算。log 出現 `[警告]` 才手動改。
   - Coupang：`round(售價×數量×14.5%) + 2`，v0.25 自動計算。
   - 同一張單有多個 SKU 時，每一列都是整張單的优惠總額，不是分攤後的金額（v0.27，2026-11-23）。BigSeller 只讀同一訂單第一列的优惠，所以匯入後的訂單金額應等於整張單售價合計 − 优惠總額。
6. 收件人姓名、地址：從各來源取最完整的版本，全部都遮罩時才用「王Ｏ明」格式。
   - Coupang 新竹寄件單 PDF 是圖片型，converter 讀不到，要直接看 PDF。地址通常比 DeliveryList 完整（例如「******東勢街30號1樓」對「***** ******1樓」），讀到更完整的就手動寫回輸出檔。

## 6. 匯入 BigSeller（2026-11-18 起固定流程）

在 0970 的 BigSeller 操作：

1. 用第 2 步的方式再搜尋一次這批訂單號，確認是「暂无数据」，不重複匯入。
2. 訂單頁右上「导入」→「导入手工订单」。選單用座標點常會收起來，改用 `find` 找到「导入手工订单」的元素參考再點。
3. 視窗裡的檔案輸入框是隱藏的：用 `find` 找 file-input 的參考，再用 `file_upload` 上傳 Data 裡的匯入檔。**不要點上傳區塊**，那會打開看不到的 Windows 選檔視窗。
4. 「导入订单时同步新增客户」維持預設勾選，除非使用者另有交代。
5. **停下來問使用者**：列出檔名、訂單號、筆數，同意後才按「确定」。
6. 結果視窗看「操作成功／操作失敗」筆數，失敗要把原因原文回報給使用者。
7. 關掉結果視窗，用訂單號搜尋讀回：店鋪、SKU、單價×數量、訂單金額（＝單價×數量−优惠）、收件人、物流／運單號、狀態。
   - 匯入後狀態是「待处理」屬正常流程，使用者會自己點「安排訂單」往下走（2026-11-22 使用者說明）。照實列出即可，不要說成庫存不足或異常。

## 7. 回報

- 每張單列出：訂單編號、收件人、SKU×數量、优惠、物流／運單號、寄件期限。
- 變更的檔案：Data\ 新增了哪些檔案，下載資料夾哪些原檔移到了資源回收筒。
- 下一步：
  - 寄件期限：mo 超取通常是出貨後隔天，Coupang 7-11 以寄件單上的期限為準。
  - 還沒匯入 BigSeller 的話，問使用者要不要照第 6 步匯入。
  - 已匯入的話，提醒使用者在 BigSeller 打單、出庫。
