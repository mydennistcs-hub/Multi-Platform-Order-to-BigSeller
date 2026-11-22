# CLAUDE.md

本檔案給 Claude Code 在此專案工作時參考，語言固定使用**繁體中文**。
**無論是本檔案內容、程式註解，還是與使用者的所有對話回覆，一律使用繁體中文，不要用英文或簡體中文。**

## 專案目標

`Multi-Platform Order to BigSeller` 是一個 Windows 桌面小工具（tkinter GUI，打包成單一 .exe），
把賣家從各平台後台**手動下載**的訂單 Excel／PDF，轉換成可直接匯入 **BigSeller ERP** 的訂單格式。

目前支援來源：
- **mo店+**（momo 店家平台）：訂單 Excel + 裝箱明細／運單 PDF（用來補齊完整姓名、地址、物流單號）
- **Coupang**：DeliveryList Excel + 7-11 交貨便運單 PDF（可抽取文字時才能補全運單號）

兩個平台的資料會正規化後合併寫入同一份 BigSeller 模板 Excel，依「平台＋訂單號＋SKU」去重合併數量
（**不要求單價相同**：2026-08-06 起改為若合併前各筆單價不同，以「加總金額÷加總數量」算出加權
平均單價寫入合併後那一列，見下方 `開發記錄.md` 對應版本記錄）。

**Phase 1 / Phase 2**：`converter.py`（手動下載 Excel/PDF 轉檔）是 **Phase 1**，已完成穩定使用中。
**Phase 2**（2026-07-29 起動工，見下方 `api_sync/ + app.py` 章節）是直接用 momo/Coupang 官方 API
取代手動下載，最終目標一樣是把訂單資料同步進 BigSeller 做進銷存，只是資料來源從人工匯出 Excel
換成即時 API 呼叫。兩個 Phase 是兩支獨立的 App，共用同一個 repo，Phase 1 在 Phase 2 完全成熟前
仍是主要生產工具，不要因為在做 Phase 2 就去動 `converter.py` 的邏輯。

**BigSeller 現行店鋪暱稱（2026-09-28 起）**：mo店+ 固定寫入 `mo店+`，Coupang 固定寫入
`酷澎 coupang`。這兩個字串由 `converter.py` 的 `MO_STORE` / `COUPANG_STORE` 控制，必須跟
BigSeller 目前啟用的店鋪暱稱完全一致；倉庫名稱與 SKU 後綴未隨本次店鋪改名變更。

**兩家公司只差 SKU 後綴（2026-11-12 使用者確認，v0.24）**：格魯維爾（94234570）與丹尼書（90154390）
的 mo店+／Coupang 店鋪暱稱、發貨倉庫都相同，只有後綴不同（`-mo{統編}`、`-cou{統編}`）。GUI 由使用者
選公司（`converter.COMPANIES`），mo店+ 匯出檔的「統編」欄會用來核對；Coupang 檔案沒有賣家統編，無法自動核對。
**不要再把後綴寫死成單一統編**。

**mo店+ 收件人真名從後台「重新列印 → 列印明細」取（2026-11-12 實測）**：BigSeller 的收件人姓名有真名就填真名，
全部來源都遮罩才用「廖Ｏ鳳」格式（使用者 2026-11-11 規則）。實測 E001訂單管理 → 訂單列「操作」→「重新列印」→
「列印明細」下載的裝箱明細 PDF（以統編解密）印的是完整姓名，671545、628118、615016 三單重印都是真名，
訂單狀態維持「已印單待寄件」，不影響出單。標籤 PDF、訂單列表、後台詳情的姓名都是遮罩的。同一天另外放進 Data
的兩份明細卻是遮罩的（例如「廖Ｏ鳳」），來源不明，可能是 API 重印或其他管道，**還沒查證**。所以只要明細上是遮罩名，
就先到後台重印一次明細確認，不要直接當成查不到真名。`converter.py` 本來就會優先用 PDF 上的姓名，
匯入時選這份重印的明細就能自動帶入真名。

**專案 skill `ship-orders-to-bigseller`（2026-11-17 新增）**：
- 用途：把 mo店+／Coupang「先去重，再出貨、下載 PDF，最後做 BigSeller 匯入檔」的完整流程整理成 skill。
- 位置：`.claude/skills/ship-orders-to-bigseller/SKILL.md`。`.gitignore` 只放行 `.claude/skills/`，所以 skill 有進版控。
- 流程有變動時，這份 CLAUDE.md 和 skill 要一起改。
- 待補：OpenMall 尚未支援。
- **2026-11-18 起匯入 BigSeller 也納入固定流程**（使用者同意）：
  - Claude 在 0970 的 BigSeller 用「导入 → 导入手工订单」，以 `file_upload` 上傳 Data 的匯入檔。
  - **按「确定」前一定先問使用者**，匯入後用訂單號搜尋讀回核對。
  - 打單、出庫仍由使用者自己做。
  - 第一次實測：丹尼書 Coupang 128104346233721，成功 1 筆，BigSeller 單號 BSKXBR026526。
  - 操作細節見 skill 第 6 步。
- **2026-11-21 起下載的 PDF 檔名要看得出平台和物流**（使用者要求）：
  - mo店+ 的 PDF 複製進 Data 時改成 `{yyyyMMdd}_{HHMMSS}_{統編}_mo店+_{物流}_{標籤|明細|出貨總表}.pdf`，比照 Coupang 的 `{yyyyMMdd}_{HHMMSS}_{統編}_coupang_{物流}.pdf`。
  - 舊檔不改名。
  - converter 讀的是 PDF 內容，不依賴檔名（2026-11-21 查過 `converter.py`）。
  - 規則見 skill 第 5 步第 1 點。

**mo店+ 出單到 BigSeller Excel 的標準流程（2026-11-12 實際跑過 4 張格魯維爾訂單）**：
1. 用 Chrome 開 mo店+ 後台，先看右上角帳號名稱確認公司（格魯維爾＝Superior Choice-000，丹尼書＝Awesome Po-000）。
2. E001訂單管理 →「未出貨」逐張按「操作 → 可出貨」→ 勾選全部品項 →「確認提交」。⚠️ 這一步會把訂單改成「已印單」，
   無法復原，**執行前一定要先問使用者**。
3. 出貨成功的視窗裡依序按「列印標籤」「列印明細」「列印出貨總表」（7-11 只有前兩個）。漏下載的檔案到「配送中」
   用訂單編號搜尋 →「操作 → 重新列印」補，不會改變訂單狀態。
4. 在「配送中」分頁把訂單編號搜尋欄清空後按「匯出報表」。搜尋欄沒清空的話只會匯出那一張單。轉檔程式只會挑
   「已印單／已印單待寄件」的訂單，其他已寄出的單混在報表裡也沒關係。
5. 把 PDF 和報表複製到 `Data\`，複製一份 BigSeller 模板當輸出檔，用 `converter.convert_orders(..., company=...)`
   或 GUI 轉檔。
6. 讀回確認「优惠」。v0.26（2026-11-15）起程式會依下方公式自動計算，log 有 `[警告]` 才需要手動改。

**「优惠」直接用匯出報表算，不用逐張點後台詳情頁（2026-11-12 驗證）**：
後台 E001「匯出報表」的 `.xls`（以統編解密）就有 `訂單進帳金額` 和 `(預估)手續費_調整金額` 兩欄，等於訂單詳情頁的
「預估訂單入帳金額」和「預估手續費」。⚠️ 實際欄名是「進帳」不是「入帳」（2026-11-15 讀檔確認），程式兩種都認。公式是：

`优惠 ＝ 商品售價 × 數量 −（訂單進帳金額 − |(預估)手續費_調整金額|）`

- 這兩欄是**訂單層級**的金額，同一張訂單的每個品項列都重複出現同一個數字，只能算一次，不能逐列加總。
- 驗證依據：用這個公式算 671545（蔥油醬 149 元）得到 13、628118 得到 10，跟 2026-11-11 在後台詳情頁逐張確認的數字一樣。
- 同一張單多個 SKU 時，依各 SKU 小計（單價×數量）比例分攤，尾差放最後一列。同一 SKU 被轉檔程式合併成一列時，
  整張單的优惠就寫在那一列。
- `converter.py` v0.26（2026-11-15）起已自動依上面公式計算 mo店+ 优惠（`_mo_order_discounts()`），轉完不用再改。
  Coupang 已在 v0.25（2026-11-15）改成 round(訂單金額×14.5%)＋每張單 2 元，也不用再改。
- ⚠️ 只適用後台「匯出報表」的檔案。舊的 API 匯出 `.xlsx` 沒有進帳欄，程式會退回舊的 23.5% 並印 `[警告]`，
  遇到這種情況要回後台詳情頁查再手動改。
- 2026-11-12 實例：66111200712521＝219−(284−84)＝19；66111200702533（219×4）＝876−(861−128)＝143；
  66111200702043＝149−(214−78)＝13；66111200698923＝599−(629−129)＝99。

## 核心程式

- `converter.py`：全部邏輯都在這支檔案（GUI + Excel/PDF 解析 + 欄位對應 + 合併輸出）。
  - `MO` / `COUPANG` / `BS`：各來源欄位的 1-based 欄號對照表（僅供備援，實際定位靠表頭）。
  - `MO_HEADERS` / `COUPANG_HEADERS` / `BS_HEADERS`：以**第一列表頭文字**動態定位欄位，
    因為 BigSeller / mo店+ 模板常常插欄改版（詳見 `開發記錄.md` v0.23）。
  - PDF 解析（`pdfplumber` + `pypdf`）：從裝箱明細 / 運單 PDF 補齊收件人姓名、地址、完整物流單號。
  - `msoffcrypto`：處理 mo店+ PDF / Excel、BigSeller 模板 Excel 的密碼保護（同一組密碼）。
- 詳細欄位對應、PDF 配對優先順序、篩選規則、加密流程 → 一律以 **`使用說明.md`** 為準，不要在這裡重複。
- 版本演進與每次修改的原因 → 一律以 **`開發記錄.md`** 為準（每次改動都要在此補一筆版本記錄）。

## api_sync/ + app.py：momo/Coupang API 整合主控台（第二個 App，開發中）

跟 `converter.py`（手動 Excel/PDF 匯入流程）是**兩個獨立的 App**，共用同一個 repo。這個是
2026-07-29 開始動工的新方向：直接用 momo/Coupang 官方 API 取代手動下載 Excel，並且要同時管理
**兩家公司 × 多平台**的帳戶（格魯維爾 統編94234570、丹尼書 統編90154390，兩家目前都各自在
momo店+ 和 Coupang 開店，未來可能加 Shopify 等其他平台）。

- **UI 框架**：PySide6（使用者已確認選擇；理由見對話紀錄——多帳戶、多平台、幾十項功能的管理主控台，
  tkinter 的多層導覽/表格能力不夠用，PySide6 的 QTableView/QTreeWidget/QTabWidget 撐得住，且 LGPL
  商用免費）。
- **多帳戶設定**：`accounts.json`（已加入 `.gitignore`，複製 `accounts.example.json` 建立）。每筆帳戶
  = 一家公司在一個平台的一個店鋪，欄位包含 `id`（英文代號，格魯維爾＝`Growell`、丹尼書＝`DennisSu`，
  各平台再接後綴如 `Growell_momo`）、`company`、`tax_id`、`platform`、`credentials`、`expected_ip`
  （這個帳戶登記在該平台白名單的固定 IP，供 App 內建的「IP 檢查」分頁比對用）。
- **`api_sync/` 套件結構**：
  - `models.py` — `Account` / `OrderItem` / `NormalizedOrder`（跨平台共用的正規化訂單結構，未來要拿
    來寫回 BigSeller Excel）。
  - `accounts.py` — 讀取 `accounts.json`，依 id/platform/company 查詢帳戶。
  - `config.py` — `CoupangConfig` / `MomoConfig`，可從 `.env`（單帳戶測試用）或
    `Account.credentials`（多帳戶 App 用，`from_account()`）建立。
  - `coupang_client.py` / `momo_client.py` — 已驗證可用的 API 用戶端（見下方「已知的 API 眉角」）。
  - `ip_check.py` — 查目前對外 IP（`ipinfo.io`），供「IP 檢查」分頁用。
  - `ui/registry.py` — momo/Coupang/Shopify API 功能清單，method/path 逐字核對
    `doc_ref/mo店+ API 串接的資料/20241007001.pdf` 與
    `doc_ref/coupang API 串接的資料/coupang_open_api_tw_agent_pack.md` 填的，不是憑印象猜的。
    Shopify 因為是 GraphQL（只有一個 endpoint，功能靠 query/mutation 名稱區分，不是不同 REST
    path），細節見下方 `doc_ref/：Shopify API 串接參考資料` 一節。Coupang 原本有多支功能重疊的
    query API（訂單：分鐘制／按天／依訂單號；商品：清單分頁／依ID／依SKU），已合併成 `cp_order_query`
    /`cp_product_query` 兩個統一入口（見下）；`implemented=True` 代表 `ui/handlers.py` 有真的呼叫邏輯，
    其餘仍是 UI 佔位。`merged_into=<另一個 key>` 代表這支已經是對方頁面內建的一個動作，**功能樹不會
    再單獨列出它**（見下方「功能合併」）；保留在清單裡是刻意的，它同時也是 API 盤點文件。
  - `ui/query_panel.py` — `QueryPanel` + `QUERY_SPECS`：訂單／商品查詢專用的豐富表單元件（日期
    區間、狀態下拉、訂單編號、關鍵字、SKU、**查詢上限**，依 `QueryPanelSpec` 動態顯示/隱藏），四個統一入口
    （`momo_order_query`/`momo_goods_query`/`cp_order_query`/`cp_product_query`）共用同一個元件。
  - `ui/handlers.py` — `RUN_HANDLERS`：`ApiFunction.key` → 實際執行函式，統一簽名
    `(account, date_from=, date_to=, status=, order_no=, keyword=, sku=, limit=) -> (columns, rows)`
    （多餘的關鍵字參數各 handler 用不到就忽略）。Coupang 訂單/商品查詢已處理 `nextToken` 自動翻頁
    （單一狀態最多翻 20 頁，避免資料量異常大時卡死）。
  - `ui/excel_export.py` — 查詢結果表格一鍵匯出 `.xlsx`（openpyxl）。momo/Coupang 訂單匯出固定把
    平台官方格式放在第一張工作表（`converter.py` 只讀這張），第二張 `API原始欄位` 保留查詢回應
    的完整攤平欄位，避免為了相容官方模板而把 API 已回傳、但官方格式暫無可靠對應的資料丟掉。
  - `qt_html_pdf.py` — **寄件單 HTML → PDF 的正式做法（2026-08-23 起）**：用 QtWebEngine
    （Chromium）渲染再等比例貼到 A4。取代原本的 xhtml2pdf，細節與踩過的坑見下方專章。
  - `label_utils.py` — 寄件單/標籤的檔案處理共用工具：`save_base64`、`download_url_to_file`、
    `html_to_pdf`（xhtml2pdf，⚠️已不用於 Coupang 寄件單，見 `qt_html_pdf.py`）、
    `extract_seven_eleven_service_code`（從 7-11 寄件單 HTML 撈完整 12 碼交貨便服務代碼，
    API 只回傳前 8 碼）、`save_label_content`（自動判斷輸入是
    URL 還是 base64）、`try_decrypt_office_bytes`（best-effort，momo 重印標籤 `printDetail` 文件說
    要用統編解密，但沒說是哪種加密格式，先試 Office(CFB/OOXML) 再試 PDF 密碼保護，都不是就原樣回傳）。
  - `ui/label_handlers.py` — 出貨確認/取得寄件單的執行邏輯：`momo_run_label_action`（呼叫
    momo_client 對應方法、把 `printLabel`/`printDetail`/`printAll` 存成檔案）、
    `coupang_run_arrange_shipment`、`coupang_run_download_invoice`（HTML 用 QtWebEngine 轉 PDF，
    順便補齊 7-11 完整運單號，回傳 `(path, note, full_invoice_number)`）。
  - `ui/label_panel.py` — 出貨確認/取得寄件單的 UI 表單：`MomoLabelPanel`（依 `MOMO_LABEL_SPECS`
    切換欄位，會異動訂單狀態的動作跳確認視窗）、`CoupangLabelPanel`（安排出貨→取得運單號→下載寄件單
    兩步驟，安排出貨那步也會跳確認視窗）。
  - `ui/main_window.py` — 主視窗：momo／Coupang／Shopify／IP檢查 分頁。每個平台分頁：帳戶下拉選單 +
    功能樹 + `QStackedWidget`，裡面兩種分頁：一般 API 用 `FunctionDetailPanel` 顯示佔位資訊；訂單相關
    （查詢＋確認＋出貨）則用 `order_workbench`——一個垂直 `QSplitter`，上半是 `QueryPanel`（查詢表單+
    結果表格），下半是 `MomoLabelPanel`／`CoupangLabelPanel`（momo/Coupang 分頁才有），**查詢、確認、
    出貨全部同一頁就能完成**（2026-07-31 改版，見下方「訂單查詢／出貨同頁」）。商品查詢等跟出貨無關的
    樹狀項目點擊時只是把下半部 `setVisible(False)`（`QSplitter` 會自動收合成單一面板），不需要另外
    拆頁面；Shopify 目前沒有出貨流程，`order_workbench` 就是 `QueryPanel` 本身。
  - `app_paths.py` — `app_dir()`：判斷 `accounts.json`/`.env` 該去哪裡找。**重要**：不能單純用
    `Path(__file__).parent`，因為打包成 .exe 後 `__file__` 指向 PyInstaller 的暫存解壓縮資料夾，
    要用 `sys.frozen` 判斷、改抓 `sys.executable` 所在目錄，否則打包後的 .exe 永遠讀不到使用者放在
    exe 旁邊的設定檔（`accounts.py`/`config.py` 都已經改用這支）。
- **已實作、可直接執行的功能**（其餘都還是佔位）：
  - momo 訂單查詢（含依訂單號查、狀態篩選）、商品查詢（含依 goodsCode 查）。
  - Coupang 訂單查詢（統一入口，含依 orderId 查、狀態篩選、自動翻頁）、商品查詢（統一入口，含關鍵字/SKU
    查、自動翻頁）。
  - momo 第三方物流／7-11／全家**出貨確認**（⚠️會將訂單標記為已出貨，UI 會跳確認視窗）與**重印標籤**
    （唯讀、不異動狀態，可放心重複執行）。
  - Coupang **訂單狀態變更為準備中**（`acknowledgement`，ACCEPT→INSTRUCT，⚠️會異動訂單狀態）→
    **安排直接整合的快遞出貨**（`arrangeShipment`，INSTRUCT→DEPARTURE，⚠️會異動訂單狀態）→
    **下載寄件單**（`downloadInvoices`，唯讀）。三步驟依序整合在同一個 `CoupangLabelPanel`
    裡（①②③按鈕），前兩步都會跳確認視窗。**訂單剛下單時是 ACCEPT 狀態，`arrangeShipment` 只接受
    INSTRUCT 狀態的訂單，所以①一定要先做過，這是 Wing 後台「確認訂單」按鈕做的事**，一開始沒做這步
    會導致②失敗，這是使用者實測直接卡住的地方，不要漏掉。

  訂單查詢結果欄位已補齊收件地址、金額/優惠、下單或處理時間（momo:
  `receiverAddress`/`orderAmount`/`lastProcDate`；Coupang:
  `receiver.addr1+addr2`/`orderedAt`/`salesPrice`/`discountPrice`/`orderPrice`/`externalVendorSkuCode`，
  momo 沒有等同 Coupang `discountPrice` 的欄位，文件裡沒有就沒有，不要編）。Coupang 訂單查詢結果也補了
  `shipmentBoxId`（欄名「合併配送號碼」，`handlers.SHIPMENT_BOX_ID_COLUMN` 常數）——這是
  `acknowledge_orders`/`arrange_shipment`/`download_invoices` 都需要的參數，原本漏掉導致使用者查完
  訂單後找不到這個號碼、還得跑去 Wing 網頁後台找。

  **API 訂單匯出完整度（2026-09-28 更新）**：
  - momo 官方格式現在另外填入 API 可直接取得的「訂單金額依品項」，並把同一訂單所有品項（含運費
    假品項）的 `orderAmount` 加總為「訂單金額加總」。結算日、優惠券、平台手續費、付款方式等
    OrderQuery 沒有回傳的後台欄位仍留空，不編造資料。
  - Coupang 官方格式已跟新版 35 欄 DeliveryList 對齊（末欄新增「統一編號」），並補上 API 已回傳且
    語意可確認的分箱狀態、預計發貨日期、商品/選項名稱、顯示產品 ID、銷售價格、運費類型、運費、
    安心碼、郵遞區號與配送訊息等欄位。配送渠道、條碼、酷澎發票金額與統一編號等無可靠直接對應者
    仍留空；原始 `taxReceiptInfo` 等資料會留在第二張 `API原始欄位`，供人工核對。
  - 匯出第一張工作表仍維持 converter 所需的官方表頭與純數字價格，因此既有「查詢 → 匯出 → 訂單
    轉換 → BigSeller」流程不變。第二張只供核對，不參與轉換。

  momo 商品查詢原本 `queryMethod` 固定用 `"SaleType"`（只問上下架狀態），庫存/原廠編號/規格全部是
  null；已改成 `"All"`，並改為展開 `listGoodsdt`（每個 SKU 一列），補上單品編號/原廠編號/規格/庫存量/
  售價/市價。**momo 這支 API 的「規格」只有一個合併欄位（`goodsdtInfo`），不像新增商品 API 那樣分
  規格1/規格2兩欄**，這是 momo 查詢端點本身的限制，不是我們少做。

  **訂單查詢／出貨同頁 + 完整欄位 + 匯出檔名前綴**（2026-07-31 改版，使用者反饋原本「右鍵選單跳轉」
  不夠直覺，且查詢結果欄位太少）：

  - **同一頁完成查詢→確認→出貨**：momo、Coupang 都改成 `order_workbench`（見上方 `main_window.py`
    說明）。結果表格改成整列選取（`QAbstractItemView.SelectRows`），**點一下（不用右鍵）任一列**就
    透過 `QueryPanel.row_activated` signal 直接帶入下半部出貨/標籤面板（`main_window._on_row_activated`
    統一處理，取代舊版右鍵選單裡的「跳轉並自動帶入」——右鍵選單現在只保留「複製訂單編號/合併配送
    號碼」）。左側樹狀清單裡任何 momo 出貨/重印標籤項目、或 Coupang 的①②③項目，點擊後一律導向同一個
    `order_workbench`，只是切換下半部的動作類型／可見度，不會清掉已經查到的結果。
  - **momo 下半部可自由切換動作類型**：`MomoLabelPanel` 新增內建「動作類型」`QComboBox`（6 種：
    7-11/全家/第三方物流 各自的出貨確認＋重印標籤），取代舊版「外部指定死一種 spec」的設計。切換動作
    類型（`set_action(fn_key)` → `_apply_spec()`）只改欄位顯示規則，**不清空**已輸入的訂單編號/品項
    流水號，這樣使用者發現系統猜錯物流商時可以直接在下拉選單換一種重試，不用重新輸入。帳戶切換時改呼叫
    `reset_fields()` 整個清空（因為換帳戶後舊訂單編號沒有意義）。
  - **自動猜物流方式**：用「物流商」欄位（momo `item.deliveryCompany`，實測即使未出貨也已經是
    「7-11店到店」/「全家店到店」這種可讀字串，不是文件寫的出貨後才有值的宅配公司代碼；Coupang
    `deliveryCompanyName` 自由格式字串）關鍵字比對（`label_panel.guess_momo_label_keys` /
    `guess_courier_code`）自動選對動作類型／`courier_combo`。**momo 猜不到 7-11/全家時（`matched=False`）
    會在提示區塊加橘色警告文字，明確告知可能是宅配訂單（本商店未開通宅配，本 App 無法用 API 確認出貨），
    不會靜默選錯還讓使用者以為選對了**——這是刻意跟 Coupang 那邊「物流公司選錯會導致 `Invoice is
    empty`，面板預設停在第一個選項『嘉里』」的舊踩坑教訓做出的差異化設計，Coupang 猜不到時一樣不會
    亂選，維持原本選中的選項讓使用者自行確認。
  - momo 品項狀態文字含「已出貨/配送中/已送達/出貨完成」等關鍵字時，自動改猜「重印標籤」而不是「出貨
    確認」（對已出貨訂單重複執行出貨確認會失敗）。Coupang 訂單狀態對照 `label_panel._STATUS_HINTS`
    顯示提示（例如 `DEPARTURE`/`DELIVERING` 代表已安排過出貨，直接下載寄件單即可，不用再點①②）。
  - **同一張訂單多個品項列自動合併流水號**：momo 常見商品+運費拆成兩個品項列，`QueryPanel.
    _on_selection_changed` 選取任一列時，會自動把**同一張訂單（同「訂單編號」）在目前查詢結果裡的所有
    品項流水號**合併成逗號分隔字串（`row_data["_combined_order_seq"]`）一起帶給下半部，不用使用者自己
    回頭比對是哪幾個流水號屬於同一張訂單。
  - **匯出 Excel 檔名前綴**：`QueryPanel._default_export_filename()` 從固定字串「查詢結果.xlsx」改成
    `{日期時間}_{平台}_{帳戶公司}_{功能名稱}.xlsx`（例如 `20260731_223015_momo_格魯維爾_訂單查詢.xlsx`），
    靠 `QueryPanel.set_context(platform, account_label_fn)`（`main_window.PlatformPanel` 建構時呼叫一次）
    取得平台/帳戶資訊，使用者存檔對話框仍可自行改檔名，這只是預設值。
  - **訂單查詢欄位不再篩選，API 回傳的任何屬性都會顯示**（範圍限定訂單查詢，商品查詢維持原本精選欄位
    不動）：`handlers._flatten()` 把巢狀 dict 攤平成單層（金額物件如 Coupang 的
    `salesPrice`/`discountPrice`/`orderPrice` 視為一個值轉成可讀字串，不繼續攤平成三欄），
    `handlers._columns_with_extras()` 算出「常用欄位固定在前＋其餘欄位依所有列聯集、第一次出現順序」
    的最終欄位清單（不同筆訂單有的欄位有、有的沒有時也不會漏掉）。momo 用
    `MOMO_ORDER_FIELD_LABELS`（已核對 `doc_ref/mo店+ API 串接的資料/20241007001.pdf` 第54-55頁官方
    欄位說明表，涵蓋全部約30個欄位）翻譯成中文欄名；Coupang 因為 doc_ref 是工程摘要不是官方逐欄位全文，
    只翻譯目前已知欄位（`COUPANG_ORDER_FIELD_LABELS`），**沒對照到的 key 一律直接用原始 API key 當
    欄名**，兩邊都保證「以後平台新增欄位也不會被程式碼漏掉」，不用等我們手動更新對照表才看得到。
    既有的欄位常數（`MOMO_ORDER_SEQ_COLUMN`/`SHIPMENT_BOX_ID_COLUMN` 等）維持不變，翻譯表裡這幾個 key
    的中文名稱刻意對齊這些常數值，右鍵/自動帶入邏輯不受影響。
- **已知的 API 眉角（寫程式前務必留意，都是實測踩出來的，不在官方文件字面上）**：
  - **momo 對外 IP 沒有生效／被擋時，`OrderQuery` 會回 HTTP 200 但 body 帶 `errorMessage:"Unauthorized"`**
    （不是 401/403），程式邏輯要檢查 body 裡的 `errorMessage`，不能只看 HTTP 狀態碼。
  - momo 的請求如果 `User-Agent` 看起來像通用腳本（例如 `python-requests` 預設值），閘道會直接回
    **空白 HTML 的 HTTP 406**（不是 momo App 邏輯層的錯誤），`momo_client.py` 已經固定帶瀏覽器風格
    User-Agent 解決。
  - momo `OrderQuery` 的 `storeDeliveryType` 文件標示非必填，但實測 `deliveryType=All` 時仍會被驗證
    「不可為 null」，`momo_client.py` 已預設帶 `"All"`。
  - **momo `GoodsQueryByMethod`（商品查詢）在對外 IP 不對時，觀察到是回傳「成功但 0 筆」，不是明確報
    錯**——這點還沒完全查清楚原因（可能是這支 API 的 IP 檢查邏輯跟訂單查詢不同，也可能是查詢條件本
    身有問題），等帳戶用正確固定 IP 執行後要重新確認這支查回來的資料是不是真的、完整的。
  - Coupang 對外 IP 不對時，`ordersheets` / 商品清單查詢都會回 HTTP 200、body 帶
    `{"code":..., "message":"Your ip address ... is not allowed..."}`，同樣要看 body 不能只看
    HTTP 狀態碼判斷成功與否。
  - Coupang 訂單查詢的巢狀結構：`data[]` 每筆訂單有 `receiver{name, addr1, addr2, postCode, safeNumber}`
    （收件人在**訂單層級**，不是品項層級）跟 `orderItems[]`（每項有 `salesPrice` 這種
    `{currencyCode, units, nanos}` 金額物件，不是單純數字）。
  - **momo 官方文件對 `printLabel` 欄位拼法前後不一致**：JSON 範例寫 `printLabel`，同一頁的欄位說明表
    卻寫 `printLable`（少一個字母），`label_handlers.py` 對兩種拼法都做防呆查找（`_first()`），不能只
    信其中一種。
  - **momo 的 `success` 欄位型態不穩定**：訂單查詢等大多數 API 回 boolean（`true`/`false`），但實測
    711超商重印標籤失敗時看到的是**字串** `"false"`——用 `if not data.get("success")` 判斷會誤判成功
    （非空字串永遠是 truthy），`label_handlers.py` 的 `_is_falsy_momo_flag()` 對 bool 和字串都做正確
    判斷。寫任何新的 momo 呼叫邏輯前，要留意這個坑。
  - momo 重印標籤的 `printDetail` 欄位文件提到「字串流(收到檔案，請用統編解密)」，但**沒說是哪種加密
    格式**，目前是 best-effort 嘗試（先 Office 加密格式，再 PDF 密碼保護），**還沒有真實資料驗證過這
    段解密邏輯對不對**，等實際跑出重印標籤結果後要重新確認。
  - **Coupang `arrangeShipment` 成功／失敗的回應格式不一樣，且成功格式跟原本推測的不同（已用
    真實資料修正，2026-08-05）**：HTTP 非 200（例如 IP 不在白名單）時是一般的
    `{"code":..., "message":...}` 標準錯誤格式。HTTP 200 成功時，**`shipmentBoxId` 當 key 包起來的
    物件是包在 `data` 這層底下**，即 `{"code":200,"message":"OK","data":{"<shipmentBoxId>":
    {"success":true,"invoiceNumber":...,"errorKey":"200","errorMessage":null,...}}}`——原本
    `label_handlers.coupang_run_arrange_shipment()` 以為成功時最外層就直接是 `{shipmentBoxId:{...}}`
    （沒有 `data` 包裝），是照 doc_ref 摘要文件推測寫的，實際跑出真實成功回應才發現外層其實還是有
    `code`/`message`/`data` 包一層，導致 `data.get(str(shipment_box_id))` 在最外層找不到 key、
    誤判成「無法解析回應內容」而顯示執行失敗——**但那次呼叫在 Coupang 那邊其實已經成功**（`success:
    true`、拿到了 `invoiceNumber`），使用者會因為 App 顯示失敗而不知道訂單其實已經安排出貨、
    誤以為要重試，若真的重試會因訂單已經不是 INSTRUCT 狀態而導致第二次呼叫失敗。已修正成優先讀
    `data["data"][str(shipment_box_id)]`，找不到才退回最外層當防呆。**不能對失敗回應也去抓
    `shipmentBoxId` 這個 key**（曾經因為這樣把 `message` 字串誤當成結果物件，讀 `.get()` 直接炸掉）。
    修好後用同一筆真實訂單（orderId `<已遮蔽>`／shipmentBoxId `<已遮蔽>`／
    invoiceNumber `1837958054`）補做③下載寄件單，成功存出 PDF，確認①②③全流程在 App 上真的能
    走完一次，不只是回應解析不報錯而已。
  - **Coupang `downloadInvoices` 的 7 天限制已確認語意**：官方原文是「訂單還在『付款完成』狀態、尚未
    安排出貨時查不到；運送完成 7 天後也會過期查不到」——不是「要等 7 天才能下載」，是「安排出貨後就能
    馬上下載，但運送完成後只有 7 天寬限期」。之前 Coupang 摘要文件裡標記的那個⚠️已經解開了。
  - **Coupang `ordersheets/acknowledgement` 的 `code` 欄位是字串 `"200"`**，不是 `ordersheets` 查詢
    那種數字 `200`——又是同一家公司不同 API 之間欄位型態不一致的例子，`coupang_run_acknowledge()`
    統一轉字串比對。回應結構也不一樣：外層 `data.responseList[]` 裡每筆才有真正的 `succeed` 布林值，
    外層 `code`/`message` 只代表這次 HTTP 請求本身有沒有成功送達。
  - 打包 PySide6 App 時，`xhtml2pdf`（HTML 轉 PDF）依賴的 `reportlab` 有些子模組（例如
    `reportlab.graphics.barcode.code128`）是動態載入，PyInstaller 靜態掃描抓不到，沒加
    `--collect-all reportlab` 會在使用者端跳 `ModuleNotFoundError`（`打包API主控台.bat` 已修正）。
  - **`xhtml2pdf` 兩家超商的寄件單都轉壞（✅2026-08-23 已改用 QtWebEngine 解決，見下方專章）**：
    7-11 直接噴 reportlab 內部錯誤（`PmlTable ... flowable given negative availWidth ...`）轉不出來；
    全家「轉得出來」但成品是壞的——標籤圖被附上 `/Mask [0 0 0 0 0 0]` colour-key 遮罩，純黑像素
    整片被挖成透明，只剩灰色邊緣，使用者看到的就是「模糊」。兩者的共同原因是這兩份 HTML 都是設計給
    瀏覽器直接列印的實體標籤版面，超出 xhtml2pdf 有限的 CSS2.1／圖片處理能力。**現在的做法是
    `api_sync/qt_html_pdf.py`（QtWebEngine＝Chromium，跟使用者手動在後台列印是同一個引擎）**，
    當初這裡列為「若之後要徹底解決」的方向之一，實測可行且已採用；`weasyprint` 那條路（Windows 要
    另外裝 GTK3 runtime）不需要了。

## momo 訂單匯出 Excel 改用官方格式 + 下載密碼 UI + 標籤檔名比照後台（2026-08-02）

使用者提供一份實際從 mo店+ 後台下載的加密 `OrderExport_TP0001949_20260802143315.xls`
（用 `msoffcrypto` + 帳戶統編解密、`xlrd` 讀出來確認為 79 欄，逐字記在
`api_sync/ui/handlers.py: MOMO_OFFICIAL_ORDER_COLUMNS`），要求 App 匯出的訂單 Excel 改成同一份
表頭／欄位順序，並且下載的寄件單 PDF 檔名也要跟後台下載的一致。

- **Excel 欄位對照**：`handlers.MOMO_OFFICIAL_ORDER_FIELD_MAP`（官方欄名 → `momo_order_query()`
  產生的 row dict key）只放「確定對應」的欄位；官方後台匯出比 `OrderQuery` API 回應多出很多結算/
  財務明細欄位（各式優惠券、手續費、調整金額、鑑賞期/結算日等），這些 API 完全沒有回傳，對不上的
  欄位維持空白，**不拿其他欄位的數字去湊**（跟本檔案其餘「文件裡沒有就沒有，不要編」的原則一致）。
  「統編」「公司名稱」兩欄比較特殊：不是從 API 回應取（那兩個概念相近的 API 欄位
  `corpSIdno`/`corpName` 語意其實是「發票開立統編／發票開立公司」，實測樣本裡是空的，因為賣家是
  momo 代開發票），而是直接從 `accounts.json` 的帳戶設定（`tax_id`/`company`）填入，見
  `handlers.build_momo_official_row()`。`export_momo_order_excel()`（`ui/excel_export.py`）用這份
  對照表輸出，`query_panel._on_export()` 判斷 `fn_key == "momo_order_query"` 時改呼叫這支，其餘查詢
  （商品查詢、Coupang、Shopify）維持原本「常用欄位＋聯集其餘欄位」的通用匯出。
  已用假資料驗證匯出檔表頭與官方檔案表頭**逐字相同**（79 欄）。

- **店鋪代碼推導（`TP0001949`）**：這個代碼同時出現在官方 Excel 檔名與寄件單 PDF 檔名裡，是
  「TP + 7 碼店鋪代碼 + 8 碼商品序號」固定格式商品編號（例：`TP00019490000024`）的前 9 碼——
  比對過 `開發記錄.md` v0.23 提到的另一個檔名 `OrderExport_TP0001949_20260629215344.xls`
  確認同一店鋪這組代碼是固定的。`handlers.momo_store_code_from_goods_no()` 用正規表示式
  `^TP\d{7}` 從任一筆訂單品項的「商品編號」反推，不需要使用者手動設定。查詢結果表格裡點一列
  時（`main_window._on_row_activated`）會把反推出的代碼存進 `MomoLabelPanel._store_code`，
  執行出貨確認/重印標籤時帶給 `label_handlers.momo_run_label_action`。**手動輸入訂單編號（沒有
  點查詢結果列）時沒有這個值**，`_momo_label_base_path()` 會退回舊版命名
  （`{訂單編號}_{流水號}_{標籤/明細/出貨總表}`），不影響功能，只是檔名跟後台不一致。

- **標籤檔名比照後台**：有店鋪代碼時，`_momo_label_base_path()` 存成
  `Logistics{Label/Detail/Data}_{店鋪代碼}_{yyyyMMddHHMMss}.副檔名`——跟使用者截圖的後台下載檔名
  格式一致（第三方物流/新竹貨運一張訂單 3 個檔案 Data+Detail+Label；7-11/全家 2 個檔案
  Detail+Label，這裡不強制檔案數量，就是原本的 `printAll`/`printDetail`/`printLabel` 各自有值才存）。

- **「解除下載文件的密碼」UI**：mo店+ 分頁「帳戶／公司」下拉選單旁新增密碼輸入框＋checkbox
  （`main_window.PlatformPanel`，只有 `platform == "momo"` 才會建立這兩個元件，Coupang/Shopify
  分頁沒有）。密碼欄預設值＝目前帳戶的統編（`_sync_decrypt_password()`），切換帳戶下拉選單會
  跟著聯動更新（`_on_account_changed` 呼叫同一支函式）；使用者也可以自行改成別的密碼。checkbox
  預設打勾，勾選時執行出貨確認/重印標籤存檔會把密碼欄目前的值傳給
  `momo_run_label_action(tax_id_for_decrypt=...)`，套用到**三種檔案**（標籤/明細/出貨總表）都嘗試
  best-effort 解密，不是像舊版那樣只套用在 `明細`(`printDetail`) 一種——`save_label_content()`
  的解密邏輯本來就是 best-effort（格式不符或內容沒加密時原樣寫檔，不會中斷流程），套用到全部檔案
  沒有額外風險。checkbox 沒勾就完全不嘗試解密（`tax_id_for_decrypt=None`）。

- **帳戶下拉選單寬度**：原本 `account_combo` 用 `stretch=1` 撐滿整列，新增的密碼欄位/checkbox
  沒地方放。改用 `main_window._fit_combo_to_contents()`（比照 `query_panel.py` 裡
  `status_combo.view().setMinimumWidth()` 已經用過的 `QFontMetrics.horizontalAdvance()` 抓最長
  選項文字寬度＋40px 邊距的做法）算出剛好顯示文字的寬度，`account_row` 改成不用 stretch 撐滿、
  改在整列最後面加 `addStretch(1)`。這支函式所有平台分頁（momo/Coupang/Shopify）都會呼叫，不是只
  有 momo。

### 追記（2026-08-02 稍晚）：匯出的 Excel 餵給 converter.py 篩出 0 筆，補上「訂單狀態」欄

使用者實測把新版匯出的 `OrderExport_TP0001949_....xlsx` 丟給 Phase 1 的
`dist/Multi-Platform-Order-to-BigSeller.exe`（`converter.py`）轉檔，結果「轉換失敗：沒有可處理的
訂單」。原因：`converter.py` 第 577 行用 `str(_cell(r, mo_cols["status"])).strip() in ("已印單",
"已印單待寄件")` 篩選待處理訂單行，但上面新加的 79 欄對照表裡「訂單狀態」故意留空（`OrderQuery`
API 回應本身沒有這個訂單層級欄位，只有品項層級的 `itemStatus`），篩選結果永遠 0 筆。

修法：`momo_order_query()` 查詢時如果指定了非「全部(All)」的狀態篩選（例如使用者截圖裡選的
「已印單(Printed)」），API 保證回來的每一筆都符合這個狀態，所以可以把篩選條件反推填回每一列的
「訂單狀態」欄（`handlers.MOMO_ORDER_STATUS_COLUMN`）——這不是編造資料，是從查詢條件合法推回的。
注意這裡**不能用** `status_labels.translate()`（會回傳「已印單（Printed）」帶括號原碼的格式），
要直接查 `status_labels.MOMO_ORDER_STATUS` 拿純中文字串，才能跟 `converter.py` 的精確字串比對
對上。查「全部」時無法反推（回來的訂單可能各種狀態都有），維持空白——所以**用這個匯出檔銜接
converter.py 時，查詢狀態一定要指定成「已印單」，不能選「全部」**。

### 追記（2026-08-06）：出貨確認成功後查詢表格沒跟著變，直接匯出又踩到同一個 0 筆的坑

使用者實測走「查詢（狀態=未出貨(未印單)）→ 選列 → 執行第三方物流出貨確認（成功，拿到 PDF 標籤）
→ 直接按上半部『匯出 Excel』」，結果匯出的檔案「訂單狀態」欄還是「未出貨(未印單)」，餵給
`converter.py` 又是同一句「沒有可處理的訂單」——使用者自己抓到根因並提議：**是不是應該在拿到
物流單 PDF 後，聯動更新上半部查詢表格的狀態？**

確認過程式碼：查詢表格是查詢當下的靜態快照，`訂單狀態`欄是查詢時依篩選條件反推寫死進每一列
資料的（見上一節），出貨確認的處理邏輯（`main_window._on_momo_label_run_requested`）原本完全沒
碰查詢表格，只更新下半部面板顯示結果，兩邊沒有任何連動。

修法（採用使用者選的「本地樂觀更新＋提示可重新查詢核對」方案，不是改成強制即時重查）：
- `handlers.MOMO_ORDER_STATUS_PRINTED`：`status_labels.MOMO_ORDER_STATUS["Printed"]`（＝「已印單」）
  的具名常數，語意是「出貨確認＝momo 後台印單動作，成功後訂單狀態應該從『未出貨(未印單)』變成
  『已印單』」——跟上一節「反推查詢篩選條件填回狀態欄」是同一種「從已知業務語意推斷，不是編造」
  的做法，不是新原則。
- `query_panel.QueryPanel.mark_momo_order_status(order_no, seqs, new_status_cn)`（新增）：在目前
  查詢結果表格裡找同一張訂單（有給 `seqs` 就只限那幾個品項流水號）的列，把「訂單狀態」欄**原地**
  改成新值。因為 `show_table()` 存進第 0 欄 `UserRole` 的 dict 物件跟 `self._last_rows` 是同一個
  參照，直接改這個 dict 就會同步反映在匯出邏輯（`_rows_in_display_order`），不用另外同步。同時把
  該儲存格文字改橘色＋加 tooltip「本地推測更新，並非即時查詢結果，建議重新查詢核對」，不讓使用者
  誤以為這是從 API 即時讀回來的真實狀態。
- `main_window._on_momo_label_run_requested`：出貨確認（`spec.needs_confirm=True`，即第三方物流／
  7-11／全家三種出貨確認，不含重印標籤）呼叫成功、且回傳訊息沒有任何一筆帶「失敗」字樣時，才呼叫
  `mark_momo_order_status()`；有任何品項失敗就不更新，避免把失敗的品項誤標成已印單。成功更新後在
  下半部結果訊息追加一行提示，讓使用者知道上面的表格已經跟著變了、可以直接匯出。
- **這是本地推斷值，不是重新打 API 確認的即時狀態**——使用者選這個方案時已經確認可以接受這個
  取捨（比對「不做本地更新，逼使用者出貨確認完要記得回頭重新查詢再匯出」與「兩者都做」兩個選項後
  選的），如果日後這個推斷跟實際 momo 後台狀態對不上（例如 momo 出貨確認後不是進到「已印單」而是
  直接跳到其他狀態），要重新檢視這個假設。

### 追記（2026-08-13）：本地樂觀更新沒有真的反映到匯出的 Excel——PySide6 UserRole 存的是值不是參照

使用者實測回報：出貨確認成功後，上半部查詢結果表格的「訂單狀態」欄位確實變成「已印單」（畫面顯示
正確），但緊接著按「匯出 Excel」，存出來的檔案裡「訂單狀態」欄卻還是舊的「未出貨(未印單)」。這會
逼使用者多繞一圈：回頭用「狀態＝已印單」重新查詢才能匯出正確狀態，但這樣查詢範圍會擴大成整個日期
區間內所有已印單訂單，跟其他早就轉換成功進 BigSeller 的舊訂單混在一起，還要自己手動挑出剛剛才出貨
確認的那幾筆。

**根因**：`QueryPanel.mark_momo_order_status()`（`ui/query_panel.py`）原本是
`row_data = item0.data(Qt.ItemDataRole.UserRole)` 拿到 dict 後直接原地修改
`row_data[MOMO_ORDER_STATUS_COLUMN] = ...`，以為這樣就會同步反映到 `_rows_in_display_order()`
（匯出用）之後再讀一次 `.data(UserRole)` 拿到的結果——這個假設在 PySide6 底下是錯的。實測驗證過：
`QTableWidgetItem.setData(role, 某個 Python dict)` 存進去的是**該次呼叫當下的一份複製**，之後每次
呼叫 `.data(role)` 都各自回傳**新的一份複製**，不是原本那個 dict 物件的參照——直接改「讀出來的那份
複製」不會寫回 Qt 內部儲存。所以畫面上看到「已印單」，只是因為 `mark_momo_order_status()` 裡另外
呼叫了 `status_item.setText()` 直接改了那一格的顯示文字（純視覺），底層真正被匯出邏輯讀取的 UserRole
資料完全沒有被改到，匯出時讀到的還是查詢當下存進去的原始值。

**修法**：`mark_momo_order_status()` 改完 `row_data` 之後，多呼叫一次
`item0.setData(Qt.ItemDataRole.UserRole, row_data)` 把改完的 dict**明確寫回**該儲存格，之後不管是
`_on_selection_changed()` 還是 `_rows_in_display_order()`（匯出用）再讀 `.data(UserRole)`，才會拿到
更新後的版本。已用一支獨立的 PySide6 小腳本驗證：不寫回會讀到舊值，寫回後讀到新值，確認是這裡的
問題、也確認修法有效。

**這個坑的通則**：本專案任何地方如果要「拿 `.data(UserRole)` 出來的 dict 直接原地修改、指望之後
再讀會反映最新值」，都要記得補呼叫 `setData()` 寫回，不能只改拿到的那份複製就以為結束——目前排查
過 `ui/query_panel.py` 內其餘兩處 `.data(Qt.ItemDataRole.UserRole)`（`_on_selection_changed`／
`_rows_in_display_order`）都只有讀取、沒有原地修改後期待持久化，暫時沒有同樣的問題，但日後新增
類似「本地樂觀更新表格資料」的功能時要留意這個陷阱。

## Coupang 超商寄件單改用 QtWebEngine 轉 PDF ＋ 7-11 運單號補齊後 4 碼（2026-08-23）

使用者實測回報三個問題，全部出在「③下載寄件單」這條路上，這一輪一次修完。

### 問題 1：7-11 寄件單轉不出 PDF（只留下 0 byte 的空殼 ＋ 一份 HTML）

`xhtml2pdf` 轉 7-11 交貨便服務單會噴 reportlab 內部錯誤（`PmlTable ... negative
availWidth`），這在 CLAUDE.md 早就記過，原本的處理是 best-effort 退回存 `.html`。
但 `pisa.CreatePDF` 是先開檔再寫入，失敗時**會留下一個 0 byte 的 `.pdf`**，使用者資料夾
裡因此多一個點開是空的假檔案（`doc_ref/coupang API 串接取得的運單問題/` 裡那份就是）。

### 問題 2：全家寄件單「模糊」——不是解析度不夠，是黑色被挖成透明

一開始看起來像圖片畫質差，實際拆開 PDF 才發現**圖片本身是清楚的**：API 版與後台手動下載版
內嵌的都是同一張 2615×4271 的標籤圖，逐塊比對條碼、文字完全同級。壞的是嵌入方式——
xhtml2pdf（透過 reportlab）在那張圖上加了 `/Mask [0 0 0 0 0 0]`，這是 PDF 的
**colour-key 遮罩**，語意是「RGB 等於純黑的像素一律視為透明」。於是條碼、黑底白字、粗框線
這些真正是純黑的部分整片被挖掉，只剩抗鋸齒的灰色邊緣，看起來就是「模糊」。

**判斷這種問題時不能只把圖抽出來看**（抽出來的圖是好的，會誤判成沒問題），要實際把 PDF
渲染成點陣圖跟正常版本並排比對，才看得出來。

### 解法：改用 QtWebEngine（Chromium）渲染，`api_sync/qt_html_pdf.py`

使用者原本的手動流程就是「在後台用瀏覽器把 HTML 列印成 PDF」，那就直接用同一個渲染引擎，
而不是繼續在 xhtml2pdf 有限的 CSS2.1 能力上硬凹。PySide6 本來就內建 QtWebEngine，不用加購
或新增外部相依（`weasyprint` 那條路需要 Windows 額外裝 GTK3 runtime，不採用）。

`render_html_to_pdf(html, out_path)` 的兩段式做法：
1. **先用「A4 寬 × 1200mm 超長頁面」渲染一次**，讓標籤不會在自然尺寸下剛好跨頁被切成兩半
   ——使用者原本手動流程最麻煩的一點就是「全家的會跑到第 2 頁，要在列印裡自訂只印第 2 頁」。
2. **再用 PyMuPDF 量出實際有內容的範圍（ink bbox），等比例放大貼到一張 A4**，靠左上角、
   留 10mm 邊界。等比例＝不變形；靠左上＝跟後台下載的檔案一樣好裁切。`show_pdf_page` 貼上去
   時向量內容仍然是向量，放大不會糊。空白頁（HTML 結尾 `page-break-after` 產生的那一頁）直接
   略過，不會輸出一堆空白紙。

實測結果（7-11 那份真實 HTML）：1 頁 A4、內容 190×276mm、兩張 QR 圖正確、文字是向量。
跟使用者從後台手動下載的那份長得一樣，只是略大一點（後台那份是使用者自己在列印對話框縮放
到 2 倍，我們是自動放大到填滿 A4 可列印範圍，效果等價但不用每次手動調）。

**⚠️ 三個實作上一定要注意的點（都是實測踩出來的）**：
- **`LocalContentCanAccessRemoteUrls` 一定要開**。HTML 是寫成暫存檔再用 `file://` 載入的
  （`setHtml()` 有約 2MB 內容上限，全家那種內嵌大圖的 HTML 會超過），而 QtWebEngine 預設會把
  本機檔案當成「本機內容」**擋掉所有遠端資源**。7-11 那份 HTML 的排版 CSS
  （`epayment.7-11.com.tw/.../C2CQrCodePrint.css`）與兩張 QR 圖都是絕對 https 網址，被擋掉的
  結果是「QR 變破圖、字級回到瀏覽器預設值撐爆表格」——畫面看起來像版面壞掉，其實是資源沒載到。
- **`PrintElementBackgrounds` 要開**，Chromium 列印預設可能略過背景色/背景圖，全家標籤有
  黑底白字的區塊。
- **QtWebEngine 相關的 import 一律放在函式內部**，不要拉到模組層級：一方面避免拖慢 App 啟動，
  一方面 `app.py` 對「PySide6 要在 xhtml2pdf 之後 import」有嚴格順序要求（見對應章節）。
  實測在 App 已經跑起來、`QApplication` 已存在的情況下才第一次載入 QtWebEngine 完全正常，
  跟使用者按下「③下載寄件單」的時序一致。

另有一道保險：渲染後如果偵測到內容右緣貼齊畫布右緣（代表被裁掉），會自動改用 630mm 寬的
畫布重畫一次再縮到 A4。目前兩種寄件單都不會觸發，是給「哪天平台把標籤 HTML 改成固定大尺寸」
用的。已用「圖片沒指定寬度、原始像素 1654px 寬」與「圖片 width:100%」兩種情境驗證過都能完整
輸出、不被裁切。

**打包設定連帶要改**（`Multi-Platform-API-Console.spec`／`build_api_console.py`）：
`PySide6.QtWebEngineCore`（連帶 `QtWebChannel`／`QtQml`／`QtQuick`／`QtPositioning`）
**不能再放在 excludes**，`PyMuPDF` 要加進 REQUIREMENTS。代價是打包體積會明顯變大
（QtWebEngine 約 130MB＋資源檔），這是為了功能正確性刻意付出的成本，**不要為了縮小體積把它
加回 excludes**。日常自用建議還是用 `啟動API主控台.bat` 直接跑原始碼，不受打包體積影響。

`label_utils.html_to_pdf()`（xhtml2pdf 版）保留但**已不用於 Coupang 寄件單**，docstring 有註明
原因；`xhtml2pdf` 的模組層級 import 也維持不動，因為 `app.py` 的匯入順序依賴它。

### 舊檔補救：`repair_invoice_pdf.py`

已經存下來的舊版全家 PDF 不用重新去 Coupang 下載——把 `/Mask` 拿掉就能**無損還原**
（圖片本體本來就是好的）。用法：

```
python repair_invoice_pdf.py <pdf檔或資料夾> [...]
```

原檔不覆蓋，修好的另存成 `原檔名_修復版.pdf`；沒有 colour-key 遮罩的檔案會回報「不需修復」
不動它，0 byte 的空殼檔會略過。只認 `/Mask` 是**陣列**的情況（陣列＝colour-key 遮罩；
是 stream 時代表正常的點陣遮罩圖，不能刪）。

### 問題 3：7-11 運單號在匯出的 Excel 裡永遠少 4 碼

Coupang `arrangeShipment` 回的 `invoiceNumber` **只有前 8 碼**（例 `E8966792`），但 7-11 與
Wing 後台 DeliveryList 匯出的「寄件單號」是**完整 12 碼**（`E89667925349`）。

比對使用者的真實訂單確認：少的那 4 碼**在 API 任何欄位都拿不到**，只出現在寄件單 HTML 的
`ctl00_Bill1_lblC2BPinCode`（畫面上的「交貨便服務代碼」）。同一份 HTML 裡的 QR 內容
`E89667927000001`、物流條碼 `89B001E896679246` 都**不含**那 4 碼，不要以為可以從它們湊出來。

所以只能在下載寄件單時順手撈：
- `label_utils.extract_seven_eleven_service_code(html)` 解析（主要靠固定的 ASP.NET 欄位 id，
  另有一組用中文標籤的備援 regex）。
- `label_handlers._full_invoice_number_from_html()` 驗證後才採用：**只對 `TWL_711` 生效**，
  而且完整碼必須「以 API 給的運單號開頭、而且比它長」。對不上就回空字串**不補**——寧可少填
  也不要把錯的號碼寫進匯出的 Excel（跟本檔案其餘「文件裡沒有就沒有，不要編」同一個原則）。
- `query_panel.mark_coupang_invoice_number()` 把查詢結果表格裡對應那張訂單的「運單號」欄
  原地改成完整 12 碼，標藍色＋tooltip 說明來源，使用者不用重新查詢就能直接匯出正確的 Excel
  （跟 momo 出貨確認後補「訂單狀態」是同一個做法）。**注意這裡一樣要 `setData()` 寫回
  UserRole**，只改讀出來的那份 dict 複製不會反映到匯出——2026-08-13 momo 那次踩過的坑。
- 原始的 API 運單號另存進 `_api_invoice_number`（底線開頭的 key 不會變成表格欄位、不會被匯出）。
  之後再點同一列時，下半部面板帶入的是**這組 API 原始號碼**，不是補齊後的 12 碼——③下載寄件單
  要帶的是 Coupang 當初配發的那組，帶 12 碼可能會失敗。

### ✅ 已用真實 API 驗證通過（2026-08-23 14:16）

改完當下因為開發機沒連 VPN（Coupang API 需要 Surfshark 固定 IP），只能拿使用者提供的真實下載
結果檔案離線重跑邏輯。使用者隨後接上固定 IP 實際走完①②③，三項產出都正確：

| 產出 | 結果 |
|---|---|
| `Data/20260823_141621_94234570_coupang_7-11.pdf` | 1 頁 A4、內容 190×276mm、2 張 QR 完整、文字是向量可選取（完整服務代碼已遮蔽） |
| `Data/20260823_141607_94234570_coupang_全家.pdf` | 1 頁 A4、黑色實心不再被挖空、條碼清楚 |
| `Data/DeliveryList_20260823141720.xlsx` | 7-11 那筆「寄件單號」已補成完整 12 碼，全家那筆維持原值（實際號碼已遮蔽） |

**已知但不是 bug**：全家那份的標籤只佔 A4 左上約 80×136mm，比 7-11 那份小。原因是 Coupang 給的
全家標籤是**一整張圖**，圖裡本來就含大片裁切留白，`_ink_bbox()` 量到的是整張圖而不是標籤本體，
等比例放大的幅度因此有限。實際尺寸接近全家 10×15cm 貼紙、可正常使用。日後若使用者要求放大，
方向是針對「整頁只有一張圖」的情況改成偵測圖內非白區域再裁切，**不要去調 `LABEL_FIT_*` 常數**
（那會連帶把 7-11 那份也改掉，而 7-11 目前的尺寸使用者已經確認可用）。

## 開發慣例

- 搬機與原始碼開發環境：使用 Python 3.13 建立本機 `.venv`，再用其 Python 執行
  `-m pip install -r requirements.txt`。此清單涵蓋 Phase 1 + Phase 2 執行相依，PySide6 固定為
  6.11.1；`.venv/` 已忽略，不可跨 PC 複製。兩支日常啟動 `.bat` 優先使用
  `.venv\Scripts\python.exe`，缺環境時才用 PATH 中的 Python；缺套件時依共同清單安裝。
  編輯器、測試與直接啟動也須選同一個解譯器，詳細指令見 `使用說明.md`。
- 修改 `converter.py` 後，**同步更新** `開發記錄.md`（新版本號 + 問題/修正說明）與必要時的 `使用說明.md`。
- 欄位定位優先用表頭字串比對（`*_HEADERS`），不要假設固定欄號，因為上游模板會插欄。
- PDF/Excel 解密採 best-effort：單一檔案解密失敗不應中斷整體流程，只記錄 `[警告]`／`[錯誤]`。
- `Data/` 資料夾為賣家實際訂單資料（已於 `.gitignore` 排除，含個資，不可提交、不可外流）。
- 打包（Phase 1／`converter.py`）：**2026-08-02 修過同一個「.bat 含中文會解析錯位」的坑，見下方
  「Phase 1 打包」專章**。現在是 `打包成exe.bat`（純 ASCII 薄殼）→ `build_converter_exe.py`
  （所有邏輯與中文訊息）→ `Multi-Platform-Order-to-BigSeller.spec`（PyInstaller 設定），
  產生單一 .exe。日常自用改推薦 `執行轉換工具.bat` 直接跑原始碼，不打包。
- 打包（Phase 2／`app.py`）：**2026-08-01 整個重做，見下方「Phase 2 打包」專章**。
  現在是 `打包API主控台.bat`（純 ASCII 薄殼）→ `build_api_console.py`（所有邏輯與中文訊息）
  → `Multi-Platform-API-Console.spec`（所有 PyInstaller 設定），產出改為 onedir 資料夾
  `dist/Multi-Platform-API-Console/`。日常自用改推薦 `啟動API主控台.bat` 直接跑原始碼，不打包。

## Phase 1 打包：`打包成exe.bat` / `build_converter_exe.py` / `.spec`

2026-08-02 修的，症狀跟下面「Phase 2 打包」的坑 1 一模一樣，只是這次是在**另一台電腦**上炸的：
使用者把整個專案搬到另一台電腦執行 `打包成exe.bat`，畫面噴出「'el' 不是內部或外部命令」「'♦' 不是
內部或外部命令」「'陝?..' 不是內部或外部命令」這種把中文訊息／路徑腰斬後半段當成指令執行的錯誤
（另一支日常用的 `執行轉換工具.bat` 也是同一個問題，同一天一起修）。

原本這兩支 `.bat` 都是 `chcp 65001` + 直接寫中文 `echo`／`pyinstaller ... ^` 續行的舊版寫法。
根本原因跟下面 Phase 2 坑 1 完全一樣（cmd.exe 用位元組定位檔案指標、再用當下字碼頁解碼，中文字
一多偏移量就跑掉）——**這裡再度印證了那個坑不是巧合，是 `chcp 65001` 在 cmd.exe 批次檔解析器裡
天生就不可靠**，只是這次是換了一台字碼頁設定不同的電腦才炸出來，證明「在原本那台電腦上測試正常」
不代表沒有這個坑，只是主控台字碼頁剛好對而已。

修法完全比照 Phase 2：`打包成exe.bat`／`執行轉換工具.bat` 都改成純 ASCII 薄殼（不加 `chcp`、
不用 `^` 續行、訊息一律英文），中文訊息與建置邏輯搬進 `build_converter_exe.py`
（`打包成exe.bat` 呼叫）。`Multi-Platform-Order-to-BigSeller.spec`（原本就存在但 `.bat` 沒有引用
它、是直接把 PyInstaller 參數塞在指令列裡的舊寫法）現在真正被 `build_converter_exe.py` 拿來用
（`pyinstaller --noconfirm --clean <spec>`），設定內容跟舊版指令列參數一致
（hiddenimports：openpyxl/xlrd/pdfplumber/pypdf/msoffcrypto；collect_all：pdfplumber/pdfminer；
單一 .exe＋視窗模式無主控台）。

## Phase 2 打包：`打包API主控台.bat` / `build_api_console.py` / `.spec`

2026-08-01 重做。舊版是「.bat 裡塞一長串 `pyinstaller --onefile --collect-all PySide6 ^ ...`」，
連續踩了四個坑，每一個都會讓打包**看起來在跑但實際沒產出**，全部記在這裡避免重蹈覆轍。

**現在的結構（三層，職責分離）**

| 檔案 | 職責 |
|---|---|
| `啟動API主控台.bat` | **日常自用的首選**：不打包，直接 `python app.py`。0 秒建置、秒開、改完程式立刻生效。 |
| `打包API主控台.bat` | 純 ASCII 薄殼，只負責找到 python 並呼叫 `build_api_console.py`。 |
| `build_api_console.py` | 裝套件→驗證匯入→呼叫 PyInstaller→複製範本→回報大小。所有中文訊息在這裡。 |
| `Multi-Platform-API-Console.spec` | 所有 PyInstaller 設定（excludes、onedir/onefile 開關）。 |

**坑 1：.bat 含中文會被 cmd.exe 解析錯位（這是舊版打包失敗的直接原因）**

cmd.exe 讀批次檔是「用**位元組**定位檔案指標，再用**當下字碼頁**把位元組換算成字元」，
兩種中文編碼各有各的死法：
- **UTF-8 + `chcp 65001`**：每個中文字 3 bytes 都讓指標算錯，偏移一路累積，讀到後面幾行
  就從行中間切開。實際症狀是畫面噴 `'--hidden-import' 不是內部或外部命令`、
  `'-API-Console.exe' 不是內部或外部命令`——參數甚至 echo 訊息的尾巴被當成指令執行。
  `^` 續行會放大這個問題。
- **Big5/cp950**：Big5 第二個位元組範圍 0x40-0x7E 含 `|`(0x7C)、`\`(0x5C)、`^`(0x5E)、
  `` ` ``(0x60)。只要主控台字碼頁不是 950，cmd 會把中文字的第二個位元組當成管線符號直接把該行
  切成兩段，**連 `rem` 註解行都會被當指令執行**（實測過）。

  → 結論：**.bat 一律只寫純 ASCII，不要加 `chcp`，不要用 `^` 續行**。中文訊息放 Python
  （Python 在 Windows 走 WriteConsoleW，不受字碼頁影響）。長參數放 `.spec`。
  改這兩支 .bat 前請先確認自己沒有加回任何非 ASCII 字元。

**坑 2：`--collect-all PySide6` 是體積與耗時的元兇**

`app.py` 只用到 QtCore/QtGui/QtWidgets，但 `collect_all` 會無差別把整包 Qt（磁碟上 634MB）
塞進去：QtWebEngine、Qt3D、QtQuick/QML、QtCharts、QtMultimedia、QtPdf、全部翻譯檔……
PyInstaller 6.x 內建的 PySide6 hook 本來就會依實際 import 只收需要的，加 `collect_all`
等於把它的判斷關掉。已改成不用 collect_all + `.spec` 裡明確列 excludes。
`reportlab` 的 `collect_all` **必須保留**（`reportlab.graphics.barcode.code128` 是動態載入）。

**坑 3：`--onefile` 讓使用者以為「程式很慢」**

onefile 每次啟動都要把整包解壓到 `%TEMP%` 才跑得起來，開啟要等數十秒。已改成 onedir，
啟動幾乎秒開。要單一檔案帶去別台電腦時，把 `.spec` 最上面的 `ONEFILE` 改 `True` 即可。
`--clean` 也已移除（它強制每次全量重建），只有換 Python/套件版本時才需要手動加。

**坑 4：PC-cillin 雲端版會把剛建好的 exe 直接刪掉**

使用者這台機器的防毒是 **PC-cillin 雲端版（趨勢科技）**，Windows Defender 因此顯示停用。
實測：PyInstaller 建置完成當下 exe 存在，**10 秒內就被刪除**（`dist/` 只剩 `_internal/`），
過程沒有任何提示視窗。這會讓人誤以為「打包沒完成」。而且 COLLECT 階段要複製 1100+ 個檔案，
每個都被即時掃描，這是打包耗時的一大部分。
→ 處理方式：請使用者在 PC-cillin 加入「例外/排除資料夾」，把整個專案目錄
（至少 `build/` 與 `dist/`）排除。這件事**只能由使用者自己在防毒介面操作**。

**已知數據（2026-08-01 實測，這台機器）**：舊 onefile 279MB → 新 onedir 159MB；
全新建置約 160 秒、增量約 138 秒（含防毒掃描）。

## 查詢上限（`limit`）：原本的「每頁筆數」是壞的，不要改回去

**症狀**：使用者在 Shopify 商品查詢把「每頁筆數」設成 50，結果仍然回 492 筆；三個平台都一樣。

**原因**：舊參數叫 `page_size`，但它只被拿去當「每次 API 呼叫的批次大小」
（momo `maxPerPage`／Coupang `maxPerPage`／Shopify GraphQL `first`），而每個 handler 接著都會用
`nextToken`／游標**自動翻頁把資料全部抓完**（最多 `_MAX_PAGES_PER_STATUS`＝20 頁）。
所以不管填 10 還是 250，最後表格筆數完全一樣，這個欄位形同虛設。

**現在的作法**（2026-08-01）：拆成兩件事。
- 對外（UI）：`limit` ＝ 真正的結果上限，達到就停止翻頁。UI 標示「查詢上限（筆）」，
  `QSpinBox` 範圍 0–100000，**0 顯示為「不限」**（送給 handler 時轉成 `None`）。
- 對內（API）：批次大小由 `handlers._batch_size(limit, api_max, default)` 自己算
  （能一次抓完就不要分兩次，但不能超過該 API 單頁上限：Shopify 250／Coupang 50／momo 最小 100），
  使用者不需要也不應該管這個技術細節。

**中斷點一律在「記錄邊界」**（訂單／商品），不是列邊界——因為一張訂單會展開成多列品項、一個商品會
展開成多列 SKU，從中間切斷會產生看起來像資料遺失的半截訂單。所以實際回傳**可能略多於** `limit`。
`QueryPanel.show_table` 用 `len(rows) >= limit` 判斷要不要顯示橘色提示
「已達查詢上限 X，可能還有更多資料未取回」，這個「略多」的行為是刻意的，改動 handler 時要一併確認
那邊的提示邏輯。相關函式：`handlers._reached()`、`_batch_size()`、
`_coupang_orders_to_rows(..., remaining=)`。

預設值（`QUERY_SPECS` 的 `default_limit`）：訂單類 500、商品類 1000
（商品會依 variant 展開，Shopify 實測 492 列，設太小反而常常被截斷）。

## UI 功能合併：`merged_into` 與「訂單」頁

2026-08-01 依使用者要求做的整併（原話：「一開始是要求各 API 功能都先佔位無功能，現在開始可以慢慢把
類似的功能漸漸合併起來」）。

- momo／Coupang 的樹狀項目「訂單查詢」都改名為 **「訂單」**——因為那一頁本來就不只查詢，
  是「查詢＋確認＋出貨＋取標籤」一次做完。
- 下列項目加上 `merged_into`，**功能樹不再單獨列出**，它們已經是「訂單」頁下半部內建的動作：
  - momo（6 項→`momo_order_query`）：7-11／全家／第三方物流的**出貨確認**與**重印標籤**，
    全部收在 `MomoLabelPanel` 的「動作類型」下拉選單。
  - Coupang（3 項→`cp_order_query`）：`cp_order_acknowledgement`／`cp_arrange_shipment`／
    `cp_download_invoices`，就是 `CoupangLabelPanel` 的①②③按鈕。
- 功能樹標題會顯示「共 N 項，另 M 項已合併」，數字只計實際顯示的項目，免得跟畫面對不起來。
- 分頁標題用 **「mo店+」不是「momo店+」**：momo 是集團品牌，賣家後台的正式名稱是「mo店+」，
  意義不同（使用者指正）。內部代號仍是 `"momo"`（對應 `accounts.json` 的 `platform`、匯出檔名），
  畫面文字走 `PlatformPanel(display_name=...)`，**兩者不要混用**。

## 狀態一律顯示繁體中文：`ui/status_labels.py`

2026-08-01 加。**下拉選單顯示中文、送給 API 的仍是英文代碼**，兩者不可混用——
`QueryPanel._on_run()` 取的是 `status_combo.currentData()`（代碼）**不是** `currentText()`（中文），
改到這段時要特別注意，取錯會變成把中文字串送去查詢、永遠 0 筆。

顯示格式固定「中文（原碼）」（例如「配送結束（DoneDelivery）」）。保留原碼是刻意的：
排查問題、對照官方文件、跟平台客服溝通時都需要那組英文。

**譯名來源分級**（改之前先確認你要動的是哪一種）：
1. **momo ＝ 官方文件原文**，逐字取自 `doc_ref/mo店+ API 串接的資料/20241007001.pdf`
   第 54 頁（orderStatus）與第 18 頁（saleStatus）。例如 `NotShipped` 官方就是寫
   「未出貨(未印單)」、`DoneDelivery` 是「配送結束」不是「配送完成」——**不要改成看起來比較順的
   講法**，這樣才跟賣家在 mo店+ 後台看到的一致。
2. **Coupang ＝ 本專案既有講法**（與 `label_panel._STATUS_HINTS`、上面的出貨三步驟表一致），
   doc_ref 是工程摘要沒有官方逐欄位中文，語意正確但用詞不保證跟 Wing 後台逐字相同。
3. **Shopify ＝ 繁中後台常見用語**（有效／已封存／草稿），⚠️尚未跟實際後台畫面逐字核對。

**中文化的連鎖影響**：Coupang 結果的「狀態」欄變成中文顯示字串後，出貨面板就不能再從那一欄
反推狀態碼。所以 `_coupang_orders_to_rows()` 會另外塞一個隱藏欄位
`handlers.COUPANG_RAW_STATUS_KEY`（＝`"_raw_status"`）保留原碼，`main_window._on_row_activated()`
用它去比對 `_STATUS_HINTS`。**底線開頭的 key 一律被 `_columns_with_extras()` 排除、不會變成表格欄位**，
日後要加類似的內部欄位請比照用底線開頭。

## Coupang 寄件單檔名改成 `{日期}_{時間}_{統編}_coupang_{物流}`（2026-08-05）

`coupang_run_download_invoice()`（`label_handlers.py`）原本存檔名稱是
`{shipmentBoxId}_{invoiceNumber}.pdf`（純數字，跟訂單本身有唯一對應但看不出日期／公司／物流商）。
使用者原本手動整理這個共用資料夾（`我的雲端硬碟/電商事業/寄件單/酷澎`）時是用
`{日期}_coupang_{物流}_{序號}.pdf` 這種格式，序號純粹是同一天下載多筆時手動累加用來避免撞名。
現在格魯維爾／丹尼書兩家公司都在用同一個 App、同一個資料夾下載，原本的命名沒有統編分不出是哪家
公司，序號也不夠精確（同一天同一物流商可能有好幾筆）。

改成 `_coupang_invoice_base_path()`：`{yyyyMMdd}_{HHMMSS}_{統編}_coupang_{物流}.pdf`，精確到秒
的時間戳記取代原本手動編號，物流商中文名稱（`_COUPANG_COURIER_FILE_NAMES`）沿用
`label_panel.COUPANG_COURIERS` 的顯示文字（去掉「（宅配）／（超商）」後綴），跟 UI 下拉選單一致，
不另外維護一份對照表。⚠️ 這個命名不再包含 `shipmentBoxId`/`invoiceNumber`，如果同一秒內下載
同一家公司、同一物流商的兩筆寄件單會撞名互相覆蓋——實務上是使用者手動一筆一筆點下載，機率極低，
是使用者確認過可以接受的取捨，不需要額外加防撞名邏輯。
只影響**新下載**的檔案；資料夾裡舊檔案的命名不受影響，維持原樣——這是**問過使用者的明確決定**
（曾詢問要不要把 `20260610`~`20260730` 那批舊檔案批次改名成新格式，使用者選擇不用，因為舊檔案
沒有精確下載時間可回填，且早期都是格魯維爾單一公司的訂單，重新命名的價值不高，維持現狀即可）。

## momo「原廠編號」搜尋：訂單是 API 篩選、商品是本地過濾

兩支 API 的能力不一樣，**不要看到訂單能查就以為商品也能直接丟給 API**：

| | 支援方式 | 依據 |
|---|---|---|
| 訂單（`OrderQuery`） | **API 原生**，request body 帶 `entpGoodsNo`，官方註明「支援模糊查詢」 | PDF 第 54 頁請求欄位表 |
| 商品（`GoodsQueryByMethod`） | **本地過濾**（抓回來再比對） | PDF 第 16-17 頁：request body 只有 `queryMethod`/`saleStatus`/`pageIndex`/`maxPerPage`/`applyDate`/`listGoods`，`entpGoodsNo` 只出現在**回應**的 `listGoodsdt` 裡 |

- 訂單那支順帶一提：同一張表裡 `goodsNo`／`goodsName`／`customerName` 也都支援模糊查詢，
  日後要加篩選條件可以比照 `momo_client.query_orders(entp_goods_no=...)` 的寫法。
- 商品的本地過濾做成**不分大小寫的包含比對**（模仿 API 的模糊查詢行為），且 `limit` 套用在
  **過濾後**的列數，避免使用者填了原廠編號卻因為前幾頁剛好都不符合而回 0 筆。
  另外，沒有子品項（`listGoodsdt` 為空）的商品在有指定原廠編號時會被略過——那一列根本沒有
  原廠編號可比對，列出來等於沒篩選。

## 查詢表單永遠貼齊上方（不要再把結果表格 setVisible(False)）

**症狀**：查詢 0 筆時整張表單往下飄到畫面中央，上下都是大片空白（使用者截圖）。

**原因**：舊版在沒資料時對結果表格 `setVisible(False)`。Qt 版面配置會**直接忽略隱藏的元件**，
連同它的 `stretch=1` 一起消失，於是多出來的垂直空間沒有元件認領，被平均分配給上面那些
QLabel／QHBoxLayout，表單就被推到中間。

**修法**：表格改成「永遠可見、沒資料時只是空的」（`clear_results()`／`show_error()` 只清內容不隱藏），
`stretch=1` 永遠有元件認領；再加上表單區塊 `QSizePolicy.Fixed`、表格 `Expanding` 當保險。
實測標題與「執行查詢」按鈕的 y 座標在 0 筆／3 筆／500 筆／錯誤四種狀態下完全不變。
**日後不要為了「沒資料時比較乾淨」把 setVisible(False) 加回去。**

## 表格排序：選取／匯出不能用「視覺列號」索引 `_last_rows`

2026-08-01 加。`QueryPanel.result_table` 開了 `setSortingEnabled(True)`（點表頭排序，涵蓋使用者
要的日期時間欄位；純數字欄位如金額/數量是字典序排序，不是數值排序，"129" 會排在 "9" 前面，
目前沒有特別處理，這是已知限制不是 bug）。

**排序後畫面上第幾列 ≠ `self._last_rows[該列]`**——這是開排序前就要處理好的陷阱，舊版
`_on_selection_changed` 靠 `self._last_rows[row]` 拿選取列的資料，一旦使用者排序過，視覺列號
跟原始查詢順序就對不上，會把 A 訂單的資料當成 B 訂單帶進下半部出貨面板。

修法：`show_table()` 建表格時，把每一列的原始 dict 整包存進**第 0 欄** `QTableWidgetItem` 的
`setData(Qt.ItemDataRole.UserRole, row)`。之後不管排成什麼順序，Qt 排序只是重新排列「列」本身
（含它附掛的 data），所以永遠可以從畫面上任一列正確讀回對應的原始資料，不用管視覺順序跟查詢
順序是否一致：
- `_on_selection_changed()` 改讀 `item(row, 0).data(UserRole)`，不再用 `self._last_rows[row]`。
- `_on_export()` 改用新增的 `_rows_in_display_order()`（逐列讀 UserRole 重組），匯出結果會跟著
  使用者排序後的畫面順序，而不是原始查詢順序——這是刻意的，使用者排序後匯出，理應预期看到的
  順序就是匯出檔案的順序。
- `_on_result_context_menu()` 不受影響：它本來就是直接讀 `result_table.item(r, col).text()`
  （畫面顯示值），不是索引 `_last_rows`，天生排序安全。

`show_table()` 填資料期間會先 `setSortingEnabled(False)` 再 `True`——插入資料時每呼叫一次
`setItem` 都可能觸發即時重新排序，資料量大時很慢，也可能讓填到一半的列被排到奇怪位置。

## 狀態下拉選單的下拉選單寬度

`QComboBox` 展開的下拉選單（`view()`）預設寬度＝collapsed 狀態時 combo 本身的顯示寬度，
選項文字比它長就會被截斷看不全（使用者截圖：「未出貨(未印單)」被切掉）。`QComboBox` 本身沒有
「依最長選項自動加寬 popup」的內建選項，`configure()` 裡狀態下拉填完選項後，用
`QFontMetrics.horizontalAdvance()` 算出最長選項文字寬度，`+40`（捲軸與內距）後設給
`status_combo.view().setMinimumWidth(...)`。每次 `configure()` 都會重算，所以不同查詢頁的
狀態選項不一樣長也沒關係。

## 商品原廠編號 vs 廠商商品編號：官方 PDF 裡兩處欄位翻譯彼此矛盾，已修正

`entpGoodsNo` 這個 API 欄位，momo 官方 PDF **請求欄位表**（第 54 頁）跟**訂單回應欄位表**
（第 55 頁）都寫「商品原廠編號」，但 `MOMO_ORDER_FIELD_LABELS`（`handlers.py`）舊版把它翻成
「廠商商品編號」——這是先前抄錄時的錯字/混淆，不是官方原文，2026-08-01 依使用者指正核對原文後
修正，訂單結果欄位、商品查詢結果欄位、兩邊輸入框標籤現在統一都是「商品原廠編號」。
`status_labels.py` docstring 提到的「momo 譯名逐字取自官方 PDF」這個原則不變，只是這一項先前
真的抄錯了，這次是對照原文修正，不是「改成比較順的講法」。

## momo「商品查詢」的 API 回應不含國際條碼

已查證：`internationalNo`（國際條碼）只出現在**新增商品**（第 22-24 頁 `skuParamList` 附近）與
**編輯已上架商品資料**（第 28-30 頁）這兩支**寫入** API 的請求欄位裡，是賣家上架時要填的東西。
**商品查詢 `GoodsQueryByMethod`（第 16-18 頁）的回應完全沒有這個欄位**——跟「商品原廠編號」
不同，這個不是查詢端限制可以繞過的，官方就是沒提供，查詢不到不是我們少做。

## Coupang 出貨三步驟到底是什麼（使用者問過，容易搞混）

| 樹狀/按鈕 | 官方 API | 做什麼 | 會不會異動狀態 |
|---|---|---|---|
| ①確認訂單（訂單狀態變更為準備中） | `PATCH .../ordersheets/acknowledgement` | ACCEPT → INSTRUCT。**就是 Wing 後台「確認訂單」按鈕做的事** | ⚠️會，不可復原 |
| ②安排出貨並取得運單號（安排直接整合的快遞出貨［僅台灣］） | `POST .../directIntegration/arrangeShipment` | INSTRUCT → DEPARTURE，**Coupang 當場配發 `invoiceNumber`（運單號）** | ⚠️會，不可復原 |
| ③下載寄件單（下載直接整合物流發票［僅台灣］） | `POST .../directIntegration/downloadInvoices` | 回傳**可列印的檔案本體**（嘉里/新竹＝PDF，全家/7-11＝HTML） | 否，唯讀可重複執行 |

所以「安排直接…」「下載直接…」確實就是使用者猜的那兩件事（取運單號＋取寄件單），
只是官方中文譯名寫得很難懂（「物流發票」其實是寄件單/託運單，不是財務發票）。
**訂單剛成立是 ACCEPT，②只接受 INSTRUCT，所以①一定要先做**——這是實測直接卡住過的地方。

### 退貨地／發貨地代碼：改成按「選擇…」跳對話框，不要再叫使用者硬填

②`arrangeShipment` 依物流類型要帶不同代碼：超商（`TWL_711`/`TWL_FM`）要 `returnCenterCode`，
宅配（`TWL_HCT` 新竹／`TWL_KERRY` 嘉里）要 `outboundShippingPlaceCode`（＝要物流來哪個地址收件）。
這些是 Coupang 內部代碼，賣家背不起來，原本 UI 只給一個空白輸入框，等於整個流程卡在這一步。

現在：欄位右邊有「選擇…」按鈕 → `CoupangLabelPanel.pick_return_center_requested` /
`pick_outbound_place_requested` 訊號 → `main_window._pick_place()` 呼叫
`label_handlers.coupang_fetch_return_centers()` / `coupang_fetch_outbound_places()` 抓清單 →
`QInputDialog.getItem` 跳選單 → 選完填回欄位。按②時若該填的代碼還空著，會**自動觸發**這個對話框，
不會只丟一句錯誤就停住。

- 用戶端方法：`CoupangClient.query_return_shipping_centers()`（`GET .../v5/vendors/{vendorId}/
  returnShippingCenters`）、`query_outbound_shipping_places()`（`GET .../marketplace_openapi/apis/
  api/v2/vendor/shipping-place/outbound`，**注意這支 path 不含 vendorId**）。路徑取自
  `doc_ref/coupang API 串接的資料/coupang_open_api_tw_agent_pack.md` 第 228/230 行與端點總表。
- `_raise_if_coupang_error()`：Coupang 失敗時是 HTTP 200＋body 帶 `{code, message}`（例如 IP 不在
  白名單），沒有這道檢查的話 `_first_list` 只會回空陣列，UI 就顯示「查不到任何發貨地，請先去 Wing
  建立」——**把「IP 沒過」誤導成「資料沒建」，使用者會白跑一趟後台**。新增類似的清單查詢時要記得比照。

### 追記（2026-08-05）：`query_outbound_shipping_places` pageSize 超過官方上限，錯誤被 `_first_list` 吞成「查不到任何發貨地」

使用者實測：Wing 後台①確認訂單／②安排出貨都能透過 App 正確執行（訂單狀態
ACCEPT→INSTRUCT 有跟著變），但 App 選「發貨地代碼」時一律顯示「這個帳戶查不到任何發貨地。
請先到 Coupang Wing 後台建立，再回來重試。」——但 Wing 後台「安排出貨」對話框裡明明看得到
這張訂單的取貨地址（桃園市中壢區…）。①能成功代表 HMAC 簽章／accessKey/secretKey／IP 白名單
都沒問題，範圍縮小到「查發貨地清單」這支 API 呼叫本身。

用 WebFetch 核對官方文件（`query-a-shipping-location` / `query-a-list-of-return-locations`）
才發現：**兩支的 `pageSize` 官方上限都是 50**，但 `coupang_client.py` 原本兩支的預設值都是
`page_size: int = 100`——超過上限。`query_outbound_shipping_places` 屬於 `marketplace_openapi`
家族（跟訂單那組 `openapi` 家族不同），參數驗證失敗時的錯誤回應格式不保證是
`_raise_if_coupang_error()` 認得的 `{code, message}`；加上原本程式碼是 `resp.json()` 直接解析、
完全沒看 HTTP 狀態碼，只要錯誤回應格式對不上，就會被下面的 `_first_list()` 直接吞成空清單，
使用者端看到的就是「帳戶沒建發貨地」這種具誤導性的訊息，而不是「請求本身被拒絕」。

修法：
1. `coupang_client.py`：`query_return_shipping_centers()` / `query_outbound_shipping_places()`
   預設 `page_size` 改成 50，並用 `min(page_size, 50)` 強制夾住，不管呼叫端傳什麼值都不會超過
   官方上限。
2. `label_handlers.py` 新增 `_parse_coupang_json(resp, action)`：**先看 HTTP 狀態碼**，非 200
   一律連原始回應內容（或解析失敗時的原始文字）一起拋成例外，不會流進 `_first_list` 被當成
   「查詢成功但 0 筆」。`coupang_fetch_return_centers()` / `coupang_fetch_outbound_places()`
   都先過這一關，再過原本 `_raise_if_coupang_error()`（處理 HTTP 200 但 body 帶錯誤的情況）。
   兩層合起來才能涵蓋 Coupang 兩種不同的報錯方式（HTTP 狀態碼 vs. body 內 code/message）。

**已用真實資料驗證修好**：使用者重開 App 後點「選擇…」，成功跳出清單並選到
「杜忠興｜桃園市 中壢區 南園二路381巷18號8樓｜22927403」，回填 `outboundShippingPlaceCode`
後順利執行完②安排出貨、③下載寄件單。至此 `query_outbound_shipping_places()` 的成功回應欄位
（`content`／`outboundShippingPlaceCode`／`shippingPlaceName`／`placeAddresses`）等同**已用真實
資料核對過**，上面「退貨地／發貨地代碼」小節原本標記的「⚠️回應欄位還沒有真實資料驗證過」已解除
（`query_return_shipping_centers()` 那支超商用的仍未實測，維持觀察）。

## ⚠️ `app.py` 的匯入順序不能動：PySide6 必須在 xhtml2pdf 之後

`app.py` 最上面那段 `import xhtml2pdf.pisa` **一定要留在 `from PySide6...` 之前**，
不是可有可無的裝飾，動了 App 會直接開不起來（打包成 exe 也一樣）。

原因（2026-08-01 實測 PySide6 6.11.1 + six 1.x）：shiboken6 會註冊一個 import hook
（`shibokensupport.feature.feature_imported`），對之後每個新匯入的模組呼叫 `inspect.getsource()`。
six 是用 `_SixMetaPathImporter` 憑空造出 `six.moves.*` 假模組，這些假模組沒有 `_path` 屬性，
`inspect` 走到最後會噴：

```
AttributeError: '_SixMetaPathImporter' object has no attribute '_path'
```

本專案的匯入鏈必踩：`main_window → label_handlers → label_utils → xhtml2pdf → html5lib → six.moves`。

- `import PySide6.QtWidgets` 之後再 `import xhtml2pdf.pisa` → **crash**
- `import xhtml2pdf.pisa` 之後再 `import PySide6.QtWidgets` → 正常

**只寫 `import six.moves` 不夠**：`six.moves.*` 是被存取時才即時造出來的，html5lib 稍後那句
`from six.moves import http_client, urllib` 仍會現場產生新模組並觸發 hook。必須把真正的使用者
（xhtml2pdf → html5lib）整條鏈先載入完。反正 `label_utils` 本來就在模組層級 import xhtml2pdf，
提前並不增加啟動成本。

`shibokensupport` 是編進 `Shiboken.pyd` 的凍結模組，**沒有官方開關可以關掉這個 hook**，
不要浪費時間去找。同理，任何新的進入點（新寫的測試腳本、新的 `__main__`）若會匯入
`api_sync.ui.*`，都要比照 `app.py` 先載入 xhtml2pdf。

## doc_ref/：momo店+ Vendor API 規格書（未來自動化方向的參考資料）

`doc_ref/mo店+ API 串接的資料/` 內是 momo 官方提供的兩份 API 文件（供評估「是否能用 API 串接取代手動下載 Excel/PDF」）：

- `<已遮蔽>.pdf`：**訂單狀態主動推播**（momo → 店家 webhook）。
  店家提供一個 URL，momo 在訂單成立/退貨/取消時會 POST `{"method","orderNo","message"}`，
  Header 帶 `Authorization: Bearer <廠商TOKEN>`。可用來做「新單即時通知」，取代排程輪詢。
- `20241007001.pdf`：**momo店+後台管理系統 - 廠商 API 規格書**（v0.11.3，78 頁），
  涵蓋商品相關（21 支 API：上下架、變價、庫存、查詢、新增/編輯商品、圖檔等）與
  **訂單相關（10 支 API，重點如下）**：

  | API | 用途 |
  |---|---|
  | `POST /VendorApi/OrderQuery` | 查訂單。可用 `listOrderNo` 精準查（14 或 18 碼含流水號），或用日期區間（`queryDateType`: 訂單日/出貨日/回收日/最晚出貨日/廠商退貨日，最大 30 天）＋ `deliveryType`/`orderStatus` 篩選。回傳完整訂單品項、收件人姓名/地址（**未出貨的宅配單才會顯示明碼，其餘遮罩**）、物流公司/單號、發票資訊等。這支可直接取代「手動從後台匯出 Excel」。 |
  | `POST /VendorApi/OrderShippingStatusConfirmHomeDelivery` | 宅配出貨確認：把**店家自己已取得**的物流公司＋運單號回填給 momo（momo 不產生宅配標籤，運單仍要向宅配業者自行取得）。 |
  | `POST /VendorApi/OrderShippingStatusConfirmThirdPartyDelivery` | 第三方物流出貨確認：momo **會產生並回傳標籤**（`printLabel`/`printDetail`/`printAll`，即寄件單／出貨明細／出貨總表的下載位址或 base64），可視為「取得寄件單」的主要管道之一。 |
  | `POST /VendorApi/OrderShippingStatusConfirmSevenStoreDelivery` | 7-11 超商出貨確認（`delyGb`: 21 倉到店／22 店到店）。同樣回傳 `printLable`/`printDetail`（base64）**寄件單**。 |
  | `POST /VendorApi/OrderShippingStatusConfirmFamilyStoreDelivery` | 全家超商出貨確認（`delyGb`: 29 常溫店到店／27 常溫倉到店／24 冷凍店到店／23 冷凍倉到店）。同樣回傳寄件單 base64。 |
  | `POST /VendorApi/OrderShippingSevenStorePrintLabel` / `OrderShippingThirdPartyPrintLabel` / `OrderShippingFamilyStorePrintLabel` | 各配送方式的**重印標籤**（已出貨過但要補印寄件單時用）。 |
  | `POST /VendorApi/OrderRecover` | 商品回收（退貨）確認。 |
  | `POST /VendorApi/OrderChangeAddr` | 同意/拒絕買家申請的更改地址。 |

  **認證方式／申請流程**：
  1. 登入 momo店+ 後台，`商店 → 權限管理 → A103 API串接IP位址管理` → 點「新增IP」開啟申請表單。
  2. 填寫表單並送出，欄位如下：
     - API串接聯絡人資料：聯絡人（必填）、**聯絡人信箱（必填，TOKEN 會寄到這裡）**、是否為委外系統開發商（必填，是/否）。
     - 若「委外系統開發商」選是，需另填委外系統商資料：公司名稱（必填）、聯絡人（必填）、聯絡電話、聯絡信箱（必填）。
     - 固定IP位址：至少 1 組，可加到多組（表單註記單一商店最多申請 10 個 IP）；**今日申請、2 小時後生效**。
  3. momo 審核通過後，會把 JWT 格式的 TOKEN 寄到申請表單填的「聯絡人信箱」。
  4. 之後每支 API 請求的 Header 都要帶 `Authorization: Bearer <TOKEN>`。
  5. **發送 API 請求的主機對外 IP，必須是申請時登記的 IP 之一**，否則系統會拒絕；若要用排程主機/雲端伺服器呼叫，需先確認其固定對外 IP 再拿去申請。
  6. TOKEN 遺失或外流要立刻回後台刪除並重新申請一組。
  7. 若使用 Callback URL 接收 webhook（見上方 `20240909001.pdf`），momo 會用同一組 TOKEN 回傳資料，比對 TOKEN 是否相同即可驗證來源可信。

  **結論／可行性判斷**：
  - 「自動取得訂單資訊」完全可行 → 用 `OrderQuery` 取代目前手動匯出 Excel 的步驟。
  - 「取得寄件單／出貨標籤」：**超商取貨（7-11／全家）與第三方物流**可行，momo 會直接回傳可列印的標籤（等同現在流程中依賴 PDF 補全運單號的部分可以省略，因為出貨當下就能拿到完整單號＋標籤）。
  - **宅配**單則不同：momo 這支 API 只接受店家「回填」自己已經產生的物流單號，**不會**幫忧產生宅配標籤，宅配的寄件單仍須向宅配業者（黑貓/新竹貨運/大榮…）另外串接或人工取得。
  - 若要做這個方向的整合，建議獨立於現有 `converter.py`（Excel/PDF 匯入流程）新增一個 API 用戶端模組，
    先做 `OrderQuery` 取代 Excel 匯入，出貨確認/標籤取得可視超商/第三方物流訂單比例決定優先度；
    宅配部分仍需搭配現有 PDF 解析或另外串接宅配業者 API。
  - 尚未實作：目前 `converter.py` 完全未使用這兩份文件的 API，仍是 Excel/PDF 手動匯入流程。此節只作為未來開發依據，動工前應向 momo 後台確認目前是否已申請到 TOKEN／IP 權限。

  **目前進度（2026-07-28）**：使用者準備中，尚未動工寫 API 程式，兩件事都完成前先維持手動流程（用 `dist/Multi-Platform-Order-to-BigSeller.exe`）：
  1. 購買 Surfshark VPN「Dedicated IP」加購（~NT$121.33/月），並把執行此工具的電腦上的 Surfshark App 設成開機自動啟動＋自動連線到該固定 IP。
  2. 到 momo店+ 後台用該固定 IP 送出 A103 API 申請，等待審核並收到 TOKEN。
  兩者皆到位後，下一步才是寫 momo API 用戶端模組（先做 `OrderQuery`），並在呼叫 API 前先檢查本機目前對外 IP 是否等於申請登記的固定 IP。

  **重要限制**：使用者的 mo店+ 商店**只開通「超商」與「第三方物流」兩種配送方式，未開通宅配**。所以動工時可以完全略過 `OrderShippingStatusConfirmHomeDelivery`（宅配出貨確認，且該支本來就不會產生標籤，要另外對接宅配業者），優先做 `OrderShippingStatusConfirmSevenStoreDelivery` / `OrderShippingStatusConfirmFamilyStoreDelivery`（若有用全家）/ `OrderShippingStatusConfirmThirdPartyDelivery` 三支即可涵蓋出貨與取得寄件單。

## doc_ref/coupang API 串接的資料/coupang_open_api_tw_agent_pack.md：Coupang Open API 台灣串接開發包（未來自動化方向的參考資料）

使用者請 AI Agent 從 `developers.coupang.com/zh-TW` 抓取整理（2026-07-29，325 頁來源，繁中入口目前 48 個端點）。與 momo 那份不同，**這份是工程摘要，不是官方全文**，動工前務必回查文件內附的 Source 連結核對完整 request/response（已用 WebFetch 抽查驗證下列重點，其餘欄位仍以官方頁面為準）。

- **認證機制與 momo 不同**：不是單純 Bearer Token，而是 `accessKey` + `secretKey` 做 **HMAC-SHA256** 簽章（`Authorization: CEA algorithm=HmacSHA256, access-key=..., signed-date=..., signature=...`），且必須先在 Wing（`wing.coupang.com`）完成商業身份驗證才能申請金鑰。所有請求必須帶 `X-MARKET: TW`。
- **申請流程**：Wing → 帳號選單 →「其他商家資訊」→ Open API Key「發行」→ 選「自建開發」→ 填公司名稱、URL、**最多 10 組固定 IP**（可用 `findip.kr` 查目前 IP）→ 發行後取得 `vendorId`/`accessKey`/`secretKey`。金鑰有效期 **180 天**，到期前 14 天可重新發行；串接資訊每週最多改 10 次；**沒有獨立測試環境**，所有呼叫都打正式訂單資料。
  - IP 白名單這邊可以跟 momo 共用同一組 Surfshark 專用 IP 去申請，不用為 Coupang 另外多買一組固定 IP。
- **速率限制**：2026-03 起基準調整為 **5 req/s**（未特別設定的帳號），對這個規模的自動化綽綽有餘。

## doc_ref/shopify API 串接的資料/：Shopify Admin API 串接參考資料（未來自動化方向的參考資料，2026-07-31 動工）

`shopify_api_agent_guide.md`（AI Agent 實作指南）+ `shopify_api_official_sources.md`（官方來源索引，含已下載的
原始 HTML 存在 `shopify_api_source_html/`）。核實日期 2026-07-31，API 版本 `2026-07`（目前 latest stable）。
跟 momo/Coupang 都不同的地方：**Shopify Admin API 是 GraphQL**，只有一個 endpoint
（`POST https://{store}.myshopify.com/admin/api/2026-07/graphql.json`，Header `X-Shopify-Access-Token`），
不同功能靠 GraphQL query/mutation 名稱區分，不是不同的 REST path——所以 `ui/registry.py` 的
`SHOPIFY_FUNCTIONS` 每一項 method/path 都長一樣，真正的區分資訊在 description 裡標的 query/mutation 名稱。

- **目前進度**：`ui/registry.py` 已建立 `SHOPIFY_FUNCTIONS`（14 項，涵蓋訂單/商品庫存/出貨物流/Webhook/批次
  作業五大類），`main_window.py` 已加上「Shopify」分頁（順序：momo店+ → Coupang → **Shopify** → IP檢查，
  IP檢查維持在最右邊）。**商品查詢（`shopify_products_query`）已是真正可執行的功能**（`implemented=True`），
  其餘 13 項仍是 UI 佔位。商品查詢用 `ui/handlers.py: shopify_products_query`，GraphQL `products` query +
  游標分頁（每頁最多 250 筆，最多翻 20 頁），可用 SKU 精準查（`sku:`）、狀態篩選
  （ACTIVE/ARCHIVED/DRAFT）、關鍵字（比對標題等欄位），每個商品的 variants 展開成一列一個 SKU（跟 momo
  商品查詢展開 `listGoodsdt` 的做法一致）。**已用 `awesome_po_shopify` 真實帳戶實測成功**：抓到 185 筆
  真實商品/SKU 資料，中文欄位正確。底層連線這部分已經打通、已實測成功：
  - `api_sync/shopify_client.py`（新增）：`ShopifyClient`，`graphql()` 通用方法 + `shop_info()` smoke test。
  - `api_sync/config.py`：新增 `ShopifyConfig`（`store_domain`/`access_token`/`api_version`，
    `from_account()` 讀 `account.credentials`）。
  - `models.py` 的 `Account` 新增 `oauth_client_id`/`oauth_client_secret` 兩個欄位（跟 `credentials` 分開放，
    原因見下方「串接前置作業」最後一點）。
  - `test_shopify_api.py`（新增，根目錄）：連通性測試腳本，`python test_shopify_api.py <account_id>`，
    跑 `query { shop { name } }`，**已實測 HTTP 200 成功**。
  - `shopify_oauth_helper.py`（新增，根目錄）：一次性 OAuth 授權碼流程工具，細節見下方「串接前置作業」。
  - `shopify-app-config/`（新增，已加入 `.gitignore`，內含 `shopify.app.toml` 是用 Shopify CLI
    `app config link` 連結到使用者 Dev Dashboard 上「Awesome Po API」這個 App 產生的本機專案，用來改
    `application_url`/`redirect_urls` 設定並 `app deploy` 重新部署，不是這個 repo 本身的程式碼）。
  - `accounts.example.json` 已改成單一 `your_store_shopify` 範例（**不是**像 momo/Coupang 那樣一家公司一筆
    ——使用者說明 Shopify 這邊沒有依公司分店鋪，只有一個線上購物網站「Awesome Po」，`tax_id` 就填
    `"none"`）。`credentials: {store_domain, access_token}` 是日常呼叫 API 用的；`oauth_client_id`/
    `oauth_client_secret` 是帳戶頂層欄位，只有要重新換 token 時才用得到。
- **串接前置作業（2026-07-31 已實測走完全部申請流程，`awesome_po_shopify` 帳戶已可正常呼叫 API）**：
  1. **決定串接方式**：格魯維爾/丹尼書是自己經營自己的 Shopify 店，不是要給別人裝的公開 App，理論上不需要走
     Partner Dashboard／完整 OAuth／上架審核那一套。但實測發現使用者店鋪後台已經是新版 **Dev Dashboard**
     介面，跟 CLAUDE.md 原本寫的「舊版後台建立自訂應用程式，安裝後直接顯示一組固定 `shpat_...` token」完全
     不是同一套流程，而且**最終確認唯一可行的路徑就是走完整 OAuth 授權碼流程**，記錄一下實測過程避免以後
     走冤枉路：
     - Dev Dashboard／店鋪後台「應用程式」清單裡的 App 詳細頁**兩邊都沒有任何直接顯示 Admin API access
       token 的欄位**（截圖實測過，只有動態/權限/隱私權/App記錄，沒有憑證頁）。舊版店鋪後台
       `/admin/settings/apps/development`（Develop apps，會秒生成 token 的那個）在這間店已經不存在／
       被導去別的地方，這條捷徑走不通。
     - 「設定→憑證」頁看到的「用戶端ID(Client ID)」+「用戶端密碼(Client Secret)」才是對的東西——這是
       OAuth 授權碼流程要用的 App 憑證（momo/Coupang 文件講的「做法 B」）。同一頁的「App 自動化權杖」
       **實測會被拒絕（HTTP 401 Invalid API key or access token）**——它是給 Shopify CLI 在 CI/CD
       環境登入用的，不是給呼叫 Admin API 用，畫面上「僅限用於 CI/CD 工作流程」那行說明是認真的，不要被
       「長期有效的 token」這種表面描述誤導去用它呼叫 API。
     - 走 OAuth 授權碼流程時，Shopify 會驗證 `redirect_uri` 的 host 必須跟 App 設定的 `application_url`
       一致，否則直接報 `invalid_request: The redirect_uri and application url must have matching
       hosts`。這個 App 是用 Dev Dashboard／`shopify.app.toml` 管理的（版本化部署，Dev Dashboard 網頁上的
       「版本」頁是唯讀快照，不能直接編輯），預設 `application_url = "https://example.com"`、
       `redirect_urls = []`，要改的話：
       1. 本機裝 Node.js（`node`/`npm` 需已安裝），在一個空資料夾跑
          `npx @shopify/cli@latest app config link`（互動式，選組織→選「連到現有 App」→選對應 App 名稱），
          會產生 `shopify.app.toml` 並連結到該 App。
       2. 手動編輯 `shopify.app.toml`：`application_url` 改成 `http://localhost:8765`，
          `[auth] redirect_urls` 改成 `[ "http://localhost:8765/callback" ]`（port 只要跟後面換 token
          的程式一致即可，不一定要 8765）。
       3. 跑 `npx @shopify/cli@latest app deploy` 部署新版本（互動式，確認發布）。
       4. `shopify app config link` / `app deploy` 這兩個指令**都需要真正的互動式終端機**（瀏覽器登入＋
          方向鍵選單），在沒有 TTY 的環境（例如背景執行的 shell）會卡住沒有任何輸出，要請使用者自己在
          自己的終端機視窗跑，不能用背景指令硬跑。
     - `application_url`/`redirect_urls` 設對之後，用 `shopify_oauth_helper.py`（新增，見下方）跑完整
       Authorization Code Grant：本機開一個 `http.server` 監聽 `localhost:8765/callback`，印出授權網址、
       `webbrowser.open()` 自動開瀏覽器 → 使用者登入按同意 → Shopify 導回 localhost 帶著 `code` →
       程式用 `client_id`+`client_secret`+`code` 向 `POST https://{store}.myshopify.com/admin/oauth/
       access_token` 換 `access_token` → 直接寫回 `accounts.json` 該帳戶的 `credentials.access_token`
       （不印在畫面上）。**已實測成功**：換到的 token 呼叫 `query { shop { name } }` 回 HTTP 200，正確拿到
       店名「Awesome Po」。
     - **這組 token 沒有 `expires_in`/`refresh_token`**（`shopify_oauth_helper.py` 有印出這個判斷），符合
       Shopify 傳統文件「offline access token 不會過期」的說法，**不需要**額外做 token 自動更新邏輯
       （中途曾經有其他 AI 助理建議「token 需要程式化自動更新」，實測證明這個說法不準確，不要照做）。
     - `accounts.json` 的 shopify 帳戶欄位結構：`oauth_client_id`/`oauth_client_secret` 是跟 `credentials`
       同層的**帳戶頂層欄位**（`models.py` 的 `Account.oauth_client_id`/`oauth_client_secret`），不是塞進
       `credentials` 裡——因為 `credentials` 是「日常呼叫 API 要用的東西」，`Account.has_credentials` 會檢查
       裡面每個欄位都填了才准呼叫，Client ID/Secret 只有要重新走一次 OAuth 換 token 時才用得到，混在一起會
       導致 token 明明已經拿到手，程式卻誤判成「憑證沒填齊」。
     - 這整段（新版 Dev Dashboard 介面、Client ID/Secret 才是對的、App 自動化權杖行不通、OAuth
       redirect_uri/application_url 要用 CLI 改設定檔重新部署）完全不在已下載的 doc_ref 文件裡，是這次
       使用者實際操作後台＋反覆試錯才摸清楚的，之後若 Shopify 後台介面再變動，要以實際測試結果為準，不要
       照這裡的文字死記。
  2. **依用途勾選 Admin API scopes**（最小權限原則，`shopify_api_agent_guide.md` 認證章節有列）：
     - 訂單查詢（近60天）：`read_orders`
     - 訂單完整歷史：`read_orders` + `read_all_orders`（⚠️需另外在 Partner Dashboard 申請並核准，可能牽涉
       受保護顧客資料(protected customer data)合規設定，建議提早準備）
     - 商品/庫存查詢：`read_products`、`read_inventory`、`read_locations`
     - 商品寫入/上架：另加 `write_products`、`write_inventory`
     - 出貨與寄件單：`read_orders`、`write_orders`、`read_merchant_managed_fulfillment_orders`、
       `write_merchant_managed_fulfillment_orders`、`read_shipping`、`write_shipping`
  3. **IP 白名單**：跟 momo/Coupang 不同，**確認 Shopify Admin API 不需要固定 IP 白名單**——不只是文件判斷，
     整個 OAuth 換 token 流程＋`test_shopify_api.py` 實測都是在一台一般開發機上做的（對外 IP 與
     momo/Coupang 白名單的 Surfshark 固定 IP 均已遮蔽），全程呼叫都
     正常成功，Dev Dashboard 裡也完全沒有任何「登記 IP」的設定項。所以 Shopify 這邊可以在任何機器上開發/
     排程，不需要依賴那台固定 IP 機器（`accounts.example.json` 的 shopify 項目 `expected_ip` 維持 `null`）。
  4. **每家公司/店鋪各自一組**：格魯維爾、丹尼書如果各自有自己的 `xxx.myshopify.com` 網域，要各自建立一次
     自訂應用程式、各自拿一組 access token，對應 `accounts.json` 裡各自一筆 shopify 帳戶（跟現有 momo/Coupang
     每家公司各自一組憑證的模式一致）。
  5. **API 版本策略**：程式裡要寫死 `2026-07`（目前 latest stable），不要用 `"latest"` 字串，因為 Shopify
     每季發布新版本，官方建議每季重新檢查一次 changelog 再決定要不要升版。
  6. **Rate limit 認知**：Standard 方案 100 points/秒，單一 GraphQL query cost 不可超過 1000 points；大量資料
     （首次匯入全部商品/大量歷史訂單）要用 Bulk Operation，不要用深度分頁硬查。
  7. **Webhook 是後續才需要考慮的事**：`shopify_api_agent_guide.md` 建議正式架構是「GraphQL 查詢 + Webhooks +
     定期 reconciliation」，但 Webhook 需要一個外部可連到的 HTTPS endpoint，跟現在這支單機桌面 App 的架構不同
     （沒有常駐伺服器）。先做「主動查詢」（訂單/商品 query，不需要 webhook）即可涵蓋目前 momo/Coupang 那樣的
     使用模式；等未來真的需要近即時同步，才需要另外考慮要不要架一台有固定網域/HTTPS 的伺服器。
- **與 momo/Coupang 的關鍵差異，動工時要留意**：
  - GraphQL 錯誤處理跟 REST 不一樣：要同時檢查回應最外層的 `errors`（GraphQL 層級錯誤，例如語法/權限錯誤）
    跟每個 mutation 自己回傳的 `userErrors`（業務邏輯錯誤，例如某欄位值不合法），兩層都要判斷，不能只看
    HTTP 狀態碼（這點跟 momo「HTTP 200 但 body 帶 errorMessage」的坑本質類似，只是換了個資料結構）。
  - `productSet` mutation 是 full-state upsert：沒列在 list 欄位（例如 variants 清單）裡的既有項目可能被視為
    要刪除，動工前必須先確認要用它做「整批覆蓋」還是改用 `productVariantsBulkUpdate` 做「局部更新」。
  - `FulfillmentOrder` 由 Shopify 訂單建立後自動產生，**不可手動建立**，串接出貨流程要先讀
    `order.fulfillmentOrders`，再看 `supportedActions` 決定能執行哪些動作，不是憑空組一個新的。
  - `shippingLabelPurchase`（2026-07 新增）是直接跟 Shopify Shipping buy 標籤、會實際扣款，需要
    `write_orders` + 對應 fulfillment order write scope + 使用者 `buy_shipping_labels` 權限 + 店鋪已接受
    Shopify Shipping 條款，且 **FedEx 不支援**，不是所有店都能用，串接前要先確認使用者的店有沒有開通
    Shopify Shipping。

- **訂單查詢**（已用 WebFetch 核對過官方頁面欄位）：`GET /v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets`，可用分鐘制／按天分頁／`orderId`／`shipmentBoxId` 四種方式查。回傳欄位足以取代目前手動下載的 DeliveryList Excel：
  - 收件人：`name`、`addr1`/`addr2`、`postCode`、`safeNumber`（隱碼安全號碼）
  - 商品：`vendorItemId`、`vendorItemName`、`externalVendorSkuCode`（賣家自訂SKU）、`sellerProductName`
  - 金額數量：`salesPrice`、`shippingCount`、`orderPrice`
  - 物流：`deliveryCompanyName`、`invoiceNumber`、`shipmentType`（`THIRD_PARTY`=自出貨／`CGF`／`CGF_LITE`）
  - 狀態：`status`（`ACCEPT`/`INSTRUCT`/`DEPARTURE`/`DELIVERING`/`FINAL_DELIVERY`/`NONE_TRACKING`）
  - ⚠️ **`CGF`/`CGF LITE`（Coupang 倉配送）訂單不會出現在 Open API 查詢結果**，要用這條路徑前，先確認使用者的 Coupang 商品是否有啟用 Coupang 倉配送；若有，那部分訂單仍須去 Wing 後台人工看。

- **取得寄件單（印單）**：台灣專屬、需兩支 API 接力，且**已確認涵蓋使用者實際在用的物流商（新竹物流、全家、7-11）**：
  1. `POST /v2/providers/openapi/apis/api/v1/vendors/{vendorId}/orders/directIntegration/arrangeShipment`：把訂單從「商品準備中 INSTRUCT」轉成「待寄出 DEPARTURE」，帶 `shipmentBoxId` + `deliveryCompanyCode`。台灣僅支援 4 家：
     | 代碼 | 物流商 | 類型 |
     |---|---|---|
     | `TWL_KERRY` | 嘉里 | 宅配 |
     | `TWL_HCT` | 新竹物流 | 宅配 |
     | `TWL_FM` | 全家 | 超商 |
     | `TWL_711` | 7-11 | 超商 |
     超商類要帶 `returnCenterCode`，宅配類要帶 `outboundShippingPlaceCode`。**回應只回 `invoiceNumber`（運單號），不含可列印檔案**——運單號是 Coupang／物流商當下配發，不是賣家自己先跟物流商申請再回填（這點跟 momo 宅配流程「賣家自己拿單號回填」相反，屬於 Coupang 台灣特有的模式）。
  2. `POST /v2/providers/openapi/apis/api/v1/vendors/{vendorId}/orders/directIntegration/downloadInvoices`：帶 `deliveryCompanyCode` + `invoicePrintDtoList`（`shipmentBoxId`+`invoiceNumber` 清單），才會回傳**真正可列印的寄件單檔案**——嘉里／新竹物流回 **PDF**，全家／7-11 回 **HTML**，直接是檔案本體（非 base64／非下載連結）。
     - ⚠️ 官方頁面提到下載時間窗限制（自動摘要為「付款完成狀態且運送完成七天之後／七天內」，語意不確定是「完成後才能下載」還是「完成後 7 天內須下載」，動工前務必直接開這支 Source 連結核對原文，不要照本節字面直接假設）。
  - 「物流公司代碼」參考頁（`api/logistics/courier-code`）列的是韓國／國際物流商清單，**不含**台灣 4 碼；台灣專用代碼只寫在上述兩支 TW-only API 頁面裡。

- **結論／可行性判斷**：使用者需求（自動取得訂單資訊回填 BigSeller Excel、取得印單列印）**可行**，且台灣直接整合物流剛好覆蓋使用者實際用到的 7-11、全家、新竹物流。認證比 momo 複雜（要自己刻 HMAC 簽章邏輯），但兩邊 IP 白名單可共用同一組固定 IP。動工前一定要對這份摘要文件裡標記「⚠️」的兩處（CGF 篩選、downloadInvoices 時間窗）用官方原文再次確認。
