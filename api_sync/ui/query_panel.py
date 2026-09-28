"""訂單查詢／商品查詢專用的豐富查詢表單。

一個 QueryPanel 元件依 QueryPanelSpec 動態顯示/隱藏欄位（日期區間、狀態、
訂單編號、關鍵字、貨號/SKU、每頁筆數），四個已串接的統一入口
（momo 訂單查詢、momo 商品查詢、Coupang 訂單查詢、Coupang 商品查詢）
都共用這一個元件，只是設定不同。
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QDate, Qt, Signal  # noqa: I001
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from api_sync.ui import status_labels
from api_sync.ui.excel_export import export_coupang_order_excel, export_momo_order_excel, export_to_excel
from api_sync.ui.handlers import (
    MOMO_ORDER_NO_COLUMN,
    MOMO_ORDER_SEQ_COLUMN,
    MOMO_ORDER_STATUS_COLUMN,
    SHIPMENT_BOX_ID_COLUMN,
    momo_store_code_from_goods_no,
)


def _safe_filename_part(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s or "").strip() or "?"


@dataclass
class QueryPanelSpec:
    fn_key: str
    show_date_range: bool = False
    show_status: bool = False
    status_options: list = field(default_factory=list)  # 第一個選項留空字串代表「全部」
    show_order_no: bool = False
    order_no_label: str = "訂單編號："
    show_keyword: bool = False
    show_sku: bool = False
    sku_label: str = "商品貨號(SKU)："
    # 狀態下拉的選項：[(顯示中文, API 代碼), ...]，用 status_labels.options() 產生。
    # 顯示中文、送出英文代碼，兩者不可混用（詳見 _on_run 取 currentData 而不是 currentText）。
    status_choices: list = field(default_factory=list)
    show_entp_goods_no: bool = False  # 商品原廠編號（momo entpGoodsNo）搜尋框
    # 狀態下拉的標籤文字。預設「狀態：」；momo 商品查詢改用「上架狀態：」，
    # 對齊結果表格的欄位名稱（也對齊 mo店+ 後台用語），使用者才能一眼看出這個下拉就是
    # 用來篩選「上架狀態」這一欄的（原本共用泛用文字「狀態：」時不容易聯想到）。
    status_label: str = "狀態："
    # 這次查詢最多要抓幾筆（0 = 不限，抓到 API 沒有下一頁為止）。
    # 舊版這個欄位叫 default_page_size、UI 標示「每頁筆數」，但它只被拿去當「每次 API 呼叫的
    # 批次大小」，handlers 接著會自動翻頁把所有頁抓完，所以不管填 10 還是 250，最後表格筆數
    # 都一樣（使用者實測 Shopify 填 50 仍回 492 筆）。現在改成真正會生效的「查詢上限」。
    default_limit: int = 200


class QueryPanel(QGroupBox):
    run_requested = Signal(str, dict)  # fn_key, params
    # 使用者點選（整列選取）結果表格任一列時發出，帶該列完整原始資料（dict，key＝欄名）。
    # momo 訂單查詢結果會多帶一個 "_combined_order_seq"（見 _on_selection_changed，把同一張訂單的
    # 所有品項流水號合併成逗號分隔字串），讓下半部出貨/標籤面板可以直接讀，不用使用者自己動手輸入。
    row_activated = Signal(dict)

    def __init__(self):
        super().__init__("查詢")
        layout = QVBoxLayout(self)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(self.title_label)

        row1 = QHBoxLayout()
        self.date_label_from = QLabel("起始日期：")
        self.date_from_edit = QDateEdit(calendarPopup=True)
        self.date_from_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_label_to = QLabel("結束日期：")
        self.date_to_edit = QDateEdit(calendarPopup=True)
        self.date_to_edit.setDisplayFormat("yyyy-MM-dd")
        self.status_label = QLabel("狀態：")
        self.status_combo = QComboBox()
        for w in (self.date_label_from, self.date_from_edit, self.date_label_to,
                  self.date_to_edit, self.status_label, self.status_combo):
            row1.addWidget(w)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.order_no_label = QLabel("訂單編號：")
        self.order_no_edit = QLineEdit()
        self.order_no_edit.setPlaceholderText("留空 = 依日期區間查詢多筆")
        self.keyword_label = QLabel("商品關鍵字：")
        self.keyword_edit = QLineEdit()
        self.sku_label = QLabel("商品貨號(SKU)：")
        self.sku_edit = QLineEdit()
        self.entp_goods_no_label = QLabel("商品原廠編號：")
        self.entp_goods_no_edit = QLineEdit()
        self.entp_goods_no_edit.setPlaceholderText("支援模糊查詢")
        self.limit_label = QLabel("查詢上限（筆）：")
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 100000)
        self.limit_spin.setSpecialValueText("不限")  # 0 顯示成「不限」
        _limit_tip = (
            "這次查詢最多抓幾筆就停止，設 0（顯示「不限」）代表抓到沒有下一頁為止。\n"
            "為了不把同一張訂單／同一個商品的明細切成兩半，達到上限時會把當前這一筆展開完才停，"
            "所以實際筆數可能略多於設定值。"
        )
        self.limit_label.setToolTip(_limit_tip)
        self.limit_spin.setToolTip(_limit_tip)
        for w in (self.order_no_label, self.order_no_edit, self.keyword_label, self.keyword_edit,
                  self.sku_label, self.sku_edit, self.entp_goods_no_label, self.entp_goods_no_edit,
                  self.limit_label, self.limit_spin):
            row2.addWidget(w)
        row2.addStretch(1)
        layout.addLayout(row2)

        self.run_button = QPushButton("執行查詢")
        self.run_button.clicked.connect(self._on_run)
        layout.addWidget(self.run_button)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c00;")
        layout.addWidget(self.error_label)

        result_row = QHBoxLayout()
        result_row.addWidget(QLabel("查詢結果："))
        result_row.addStretch(1)
        self.export_button = QPushButton("匯出 Excel")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._on_export)
        result_row.addWidget(self.export_button)
        layout.addLayout(result_row)

        self.result_table = QTableWidget()
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # 點欄位標題排序（例如「下單時間」「處理時間」這類日期時間欄位）。ISO 風格字串
        # （yyyy-mm-dd hh:mm:ss，零填補）字典序排序剛好等於時間先後順序，不需要額外解析成
        # datetime 物件；純數字欄位（金額/數量）用字典序會不準確（"129" 排在 "9" 前面），
        # 這是字串排序的已知限制，目前沒有特別處理，使用者若在意可以自行匯出 Excel 後排序。
        self.result_table.setSortingEnabled(True)
        self.result_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.result_table.customContextMenuRequested.connect(self._on_result_context_menu)
        self.result_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.result_table, stretch=1)

        # ---- 讓查詢表單永遠貼齊上方 ----
        # 原本結果表格在沒資料時會被 setVisible(False)。Qt 的版面配置會直接忽略隱藏的元件，
        # 連同它的 stretch=1 一起消失，於是「多出來的垂直空間」變成沒有元件認領，
        # 就被平均分配給上面那些 QLabel／QHBoxLayout，導致整張表單往下飄到畫面中央
        # （使用者截圖：查詢 0 筆時「訂單」標題被推到中間，上下都是大片空白）。
        #
        # 修法：表格改成「永遠可見、沒資料時只是空的」，stretch=1 永遠有元件認領，
        # 表單位置就完全不受查詢結果多寡影響。下面兩行是保險：
        # 表單區塊固定高度，多餘空間一律歸表格。
        for w in (self.title_label, self.run_button, self.error_label):
            w.setSizePolicy(w.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Fixed)
        self.result_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._spec: QueryPanelSpec | None = None
        self._last_columns = None
        self._last_rows = None
        self._requested_limit = None  # 上一次按「執行查詢」時送出的上限，show_table 判斷要不要提示用
        self._platform = ""
        self._account_label_fn = None
        self._account_fn = None

    def current_fn_key(self):
        return self._spec.fn_key if self._spec else None

    def set_context(self, platform: str, account_label_fn=None, account_fn=None):
        """給匯出 Excel 用：platform（例如 "momo"/"coupang"）＋一個能讀「目前選到哪個帳戶顯示文字」
        的 callable（給預設檔名用）＋一個能讀「目前選到哪個帳戶物件」的 callable（給 momo 訂單匯出
        要填「統編」「公司名稱」兩欄用，見 _on_export）。帳戶下拉選單切換時呼叫也會拿到最新值，
        不用每次都重新設定。"""
        self._platform = platform
        self._account_label_fn = account_label_fn
        self._account_fn = account_fn

    def configure(self, spec: QueryPanelSpec, fn_name: str):
        self._spec = spec
        self.title_label.setText(fn_name)

        for w in (self.date_label_from, self.date_from_edit, self.date_label_to, self.date_to_edit):
            w.setVisible(spec.show_date_range)
        if spec.show_date_range:
            today = QDate.currentDate()
            self.date_from_edit.setDate(today.addDays(-7))
            self.date_to_edit.setDate(today)

        self.status_label.setText(spec.status_label)
        self.status_label.setVisible(spec.show_status)
        self.status_combo.setVisible(spec.show_status)
        self.status_combo.clear()
        if spec.show_status:
            # 顯示繁體中文（含原碼），userData 存 API 要的英文代碼；_on_run 取 currentData()。
            for text, code in spec.status_choices:
                self.status_combo.addItem(text, userData=code)
            # QComboBox 的下拉選單預設寬度＝combo 本身收合時的顯示寬度，選項文字比它長就會被截斷
            # 看不全（使用者截圖：「未出貨(未印單)」在下拉選單裡被切掉）。展開的下拉選單是獨立的
            # QAbstractItemView，寬度要另外算最長選項文字需要多寬再設給它。
            metrics = self.status_combo.fontMetrics()
            longest = max((metrics.horizontalAdvance(text) for text, _code in spec.status_choices), default=0)
            self.status_combo.view().setMinimumWidth(longest + 40)  # +40 給捲軸與內距空間

        self.order_no_label.setText(spec.order_no_label)
        self.order_no_label.setVisible(spec.show_order_no)
        self.order_no_edit.setVisible(spec.show_order_no)
        self.order_no_edit.clear()

        self.keyword_label.setVisible(spec.show_keyword)
        self.keyword_edit.setVisible(spec.show_keyword)
        self.keyword_edit.clear()

        self.sku_label.setText(spec.sku_label)
        self.sku_label.setVisible(spec.show_sku)
        self.sku_edit.setVisible(spec.show_sku)
        self.sku_edit.clear()

        self.entp_goods_no_label.setVisible(spec.show_entp_goods_no)
        self.entp_goods_no_edit.setVisible(spec.show_entp_goods_no)
        self.entp_goods_no_edit.clear()

        self.limit_spin.setValue(spec.default_limit)

        self.clear_results()

    def clear_results(self, message: str = ""):
        # 不再 setVisible(False)：隱藏表格會讓版面塌陷、表單飄到畫面中央（見 __init__ 結尾說明）。
        # 沒資料時就讓它留在原位、內容清空即可。
        self.error_label.setText(message)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.export_button.setEnabled(False)
        self._last_columns = None
        self._last_rows = None

    def _on_run(self):
        if self._spec is None:
            return
        params = {}
        if self._spec.show_date_range:
            params["date_from"] = self.date_from_edit.date().toString("yyyy-MM-dd")
            params["date_to"] = self.date_to_edit.date().toString("yyyy-MM-dd")
        if self._spec.show_status:
            # 取 currentData()（英文代碼）而不是 currentText()（中文顯示字串）——
            # 下拉是中文化過的，送 currentText() 給 API 會直接查不到東西。
            params["status"] = self.status_combo.currentData() or None
        if self._spec.show_order_no:
            params["order_no"] = self.order_no_edit.text().strip() or None
        if self._spec.show_keyword:
            params["keyword"] = self.keyword_edit.text().strip() or None
        if self._spec.show_sku:
            params["sku"] = self.sku_edit.text().strip() or None
        if self._spec.show_entp_goods_no:
            params["entp_goods_no"] = self.entp_goods_no_edit.text().strip() or None
        # 0 = 不限，handlers 收到 None 就不做上限判斷
        self._requested_limit = self.limit_spin.value() or None
        params["limit"] = self._requested_limit

        self.error_label.setText("")
        self.run_requested.emit(self._spec.fn_key, params)

    def show_error(self, message: str):
        # 同 clear_results：不隱藏表格，只清空，維持版面穩定。
        self.error_label.setStyleSheet("color: #c00;")
        self.error_label.setText(message)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.export_button.setEnabled(False)
        self._last_columns = None
        self._last_rows = None

    def show_table(self, columns: list[str], rows: list[dict]):
        # 抓到的筆數已達（或超過）使用者設的上限，就明講「可能還有更多」，不要讓人以為這就是全部。
        # handlers 為了不切斷同一張訂單/商品的明細，會把當前這一筆展開完才停，所以是 >= 不是 ==。
        limit = getattr(self, "_requested_limit", None)
        if limit and len(rows) >= limit:
            self.error_label.setText(
                f"共 {len(rows)} 筆（已達查詢上限 {limit}，可能還有更多資料未取回；"
                f"請提高上限、設為 0（不限），或縮小日期區間／加上篩選條件）"
            )
            self.error_label.setStyleSheet("color: #b26a00;")
        else:
            self.error_label.setText(f"共 {len(rows)} 筆")
            self.error_label.setStyleSheet("color: #1a7f37;")
        self._last_columns = columns
        self._last_rows = rows
        # 插入資料期間先關掉排序：setSortingEnabled(True) 時每呼叫一次 setItem 都可能觸發
        # 重新排序，資料量大時很慢，也可能讓「還沒填完的半列」被排到奇怪的位置。填完再打開。
        self.result_table.setSortingEnabled(False)
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)
        self.result_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(columns):
                item = QTableWidgetItem(str(row.get(col, "")))
                if c == 0:
                    # 把這一列的原始資料整包存在第 0 欄，排序安全：使用者點表頭排序後，
                    # QTableWidget 只是重新排列「列」本身（含它存的 data），所以之後不管
                    # 排成什麼順序，都還是能從畫面上任一列正確取回它對應的原始資料——
                    # 不能像舊版那樣用「視覺上第幾列」去索引 self._last_rows[row]，
                    # 排序後兩者的順序會對不起來，選錯資料。見 _on_selection_changed。
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.result_table.setItem(r, c, item)
        self.result_table.setSortingEnabled(True)
        self.result_table.resizeColumnsToContents()
        self.export_button.setEnabled(True)

    def _on_selection_changed(self):
        """點一下（整列選取）結果表格任一列，就直接把該列資料 emit 出去，讓下半部出貨/標籤面板
        自動帶入——不用再靠右鍵選單「跳轉」。"""
        if not self._last_columns or not self._last_rows:
            return
        selected_rows = self.result_table.selectionModel().selectedRows() if self.result_table.selectionModel() else []
        if not selected_rows:
            return
        row = selected_rows[0].row()
        # 讀第 0 欄 item 存的原始資料（見 show_table），不要用視覺列號去索引 self._last_rows——
        # 表格開啟排序後，畫面上第幾列跟 self._last_rows 的原始順序不再相同，索引會取到別筆資料。
        first_item = self.result_table.item(row, 0)
        stored = first_item.data(Qt.ItemDataRole.UserRole) if first_item else None
        if not isinstance(stored, dict):
            return

        row_data = dict(stored)
        if MOMO_ORDER_SEQ_COLUMN in self._last_columns and MOMO_ORDER_NO_COLUMN in self._last_columns:
            # 同一張訂單常常拆成多個品項列（商品＋運費…），出貨確認要一次帶齊同一張訂單的所有品項
            # 流水號，不然使用者還要自己回頭比對哪些流水號屬於同一張訂單。
            order_no = str(row_data.get(MOMO_ORDER_NO_COLUMN, ""))
            all_seqs = []
            for r in self._last_rows:
                if str(r.get(MOMO_ORDER_NO_COLUMN, "")) != order_no:
                    continue
                seq = r.get(MOMO_ORDER_SEQ_COLUMN)
                if seq and seq not in all_seqs:
                    all_seqs.append(seq)
            row_data["_combined_order_seq"] = ",".join(str(s) for s in all_seqs) if all_seqs else row_data.get(
                MOMO_ORDER_SEQ_COLUMN, ""
            )
        self.row_activated.emit(row_data)

    def mark_momo_order_status(self, order_no: str, seqs: list[str] | None, new_status_cn: str) -> int:
        """出貨確認（第三方物流/7-11/全家）成功後，把查詢結果表格裡對應這張訂單（有給 seqs 就只
        限那幾個品項流水號，否則整張訂單）的「訂單狀態」欄本地樂觀更新，不用重新查詢就能直接匯出
        正確狀態的 Excel（見 CLAUDE.md「訂單狀態一定要是已印單，converter.py 才篩得到」那個坑）。

        這是根據「出貨確認＝momo 後台印單動作」的業務語意推斷，不是從 API 即時讀回的真實狀態，
        所以順便把該欄位標橘色＋tooltip，提醒使用者有疑慮時可重新查詢核對。

        row_data 是 show_table() 存進第 0 欄 UserRole 的同一個 dict 物件，直接原地修改就會同步反映在
        self._last_rows／匯出邏輯（_rows_in_display_order），不需要另外同步一份。
        回傳實際更新的列數（0 代表目前查詢結果裡找不到這張訂單，例如手動輸入訂單編號、不是從
        查詢結果點選進來的情況）。
        """
        if not self._last_columns or MOMO_ORDER_STATUS_COLUMN not in self._last_columns:
            return 0
        if MOMO_ORDER_NO_COLUMN not in self._last_columns:
            return 0
        status_col = self._last_columns.index(MOMO_ORDER_STATUS_COLUMN)
        has_seq_col = MOMO_ORDER_SEQ_COLUMN in self._last_columns
        seq_set = {str(s) for s in seqs} if seqs else None
        updated = 0
        for r in range(self.result_table.rowCount()):
            item0 = self.result_table.item(r, 0)
            row_data = item0.data(Qt.ItemDataRole.UserRole) if item0 else None
            if not isinstance(row_data, dict):
                continue
            if str(row_data.get(MOMO_ORDER_NO_COLUMN, "")) != str(order_no):
                continue
            if seq_set is not None and has_seq_col and str(row_data.get(MOMO_ORDER_SEQ_COLUMN, "")) not in seq_set:
                continue
            row_data[MOMO_ORDER_STATUS_COLUMN] = new_status_cn
            # PySide6 的 QTableWidgetItem.setData(UserRole, dict)／.data(UserRole) 是「存值」
            # 不是「存參照」：每次呼叫 .data() 都會回傳一份新複製，直接改上面拿到的 row_data
            # 不會反映回 Qt 內部儲存，一定要呼叫 setData() 明確寫回，之後 _rows_in_display_order()
            # （匯出用）再讀一次 .data() 才讀得到更新後的狀態（2026-08-13 使用者實測踩到：畫面上
            # 顯示已印單，但匯出的 Excel 仍是舊的「未出貨(未印單)」，因為原本只有 setText() 改了
            # 畫面文字，UserRole 底層的 dict 資料沒有真的被改到）。
            item0.setData(Qt.ItemDataRole.UserRole, row_data)
            status_item = self.result_table.item(r, status_col)
            if status_item is not None:
                status_item.setText(new_status_cn)
                status_item.setForeground(QBrush(QColor("#b26a00")))
                status_item.setToolTip("出貨確認成功後本地推測更新，並非即時查詢結果，建議重新查詢核對最新狀態。")
            updated += 1
        return updated

    def mark_coupang_invoice_number(self, shipment_box_id: str, full_invoice_number: str) -> int:
        """下載 7-11 寄件單後，把查詢結果表格裡對應這張訂單的「運單號」欄補成完整 12 碼。

        Coupang API（安排出貨／訂單查詢）給的 `invoiceNumber` 只有前 8 碼（例 E8966792），
        7-11 與 Wing 後台 DeliveryList 認的是完整 12 碼（E89667925349），少的 4 碼只出現在
        寄件單本身。不補的話匯出的 Excel 運單號永遠少 4 碼（使用者實測回報）。

        這裡補的值是從**實際下載到的寄件單**讀出來的，不是推測值，但畢竟不是重新查詢 API 的
        結果（而且重新查詢也只會拿回 8 碼），所以標成藍色＋tooltip 說明來源。

        原始的 API 運單號另外存進 `_api_invoice_number`（底線開頭的 key 不會變成表格欄位，
        也不會被匯出），讓之後再點這一列時，下半部面板仍然帶入 API 認得的那組號碼去重複
        下載寄件單——③下載寄件單要帶的是 API 配發的運單號，帶補齊後的 12 碼可能會失敗。

        回傳實際更新的列數（0 ＝ 目前查詢結果裡找不到這張訂單，例如手動輸入號碼、不是點選列
        進來的情況）。
        """
        if not self._last_columns:
            return 0
        if SHIPMENT_BOX_ID_COLUMN not in self._last_columns or "運單號" not in self._last_columns:
            return 0
        invoice_col = self._last_columns.index("運單號")
        updated = 0
        for r in range(self.result_table.rowCount()):
            item0 = self.result_table.item(r, 0)
            row_data = item0.data(Qt.ItemDataRole.UserRole) if item0 else None
            if not isinstance(row_data, dict):
                continue
            if str(row_data.get(SHIPMENT_BOX_ID_COLUMN, "")) != str(shipment_box_id):
                continue
            row_data.setdefault("_api_invoice_number", str(row_data.get("運單號", "")))
            row_data["運單號"] = full_invoice_number
            # 一定要 setData 寫回：QTableWidgetItem 的 UserRole 存的是值不是參照，只改讀出來
            # 的那份複製，匯出時再讀會拿到舊值（2026-08-13 momo 訂單狀態踩過同一個坑）。
            item0.setData(Qt.ItemDataRole.UserRole, row_data)
            invoice_item = self.result_table.item(r, invoice_col)
            if invoice_item is not None:
                invoice_item.setText(full_invoice_number)
                invoice_item.setForeground(QBrush(QColor("#1a5fb4")))
                invoice_item.setToolTip(
                    "已用下載到的 7-11 寄件單補齊完整 12 碼交貨便服務代碼"
                    "（Coupang API 只回傳前 8 碼）。"
                )
            updated += 1
        return updated

    def _on_result_context_menu(self, pos):
        if not self._last_columns:
            return
        row = self.result_table.rowAt(pos.y())
        if row < 0:
            return

        def cell(col_name, r=row):
            if col_name not in self._last_columns:
                return ""
            item = self.result_table.item(r, self._last_columns.index(col_name))
            return item.text() if item else ""

        if SHIPMENT_BOX_ID_COLUMN in self._last_columns:
            value = cell(SHIPMENT_BOX_ID_COLUMN)
            label = "合併配送號碼"
        elif MOMO_ORDER_NO_COLUMN in self._last_columns:
            value = cell(MOMO_ORDER_NO_COLUMN)
            label = "訂單編號"
        else:
            return
        if not value:
            return

        menu = QMenu(self)
        copy_action = menu.addAction(f"複製{label}（{value}）")
        chosen = menu.exec(self.result_table.viewport().mapToGlobal(pos))
        if chosen == copy_action:
            QApplication.clipboard().setText(value)

    def _momo_store_code_from_results(self) -> str | None:
        """從目前查詢結果任一列的「商品編號」反推店鋪代碼（見 handlers.momo_store_code_from_goods_no），
        給 momo 訂單匯出的預設檔名用。查不到（例如結果剛好都沒有商品編號）時回 None，呼叫端會退回
        通用命名，不影響功能。"""
        for row in self._last_rows or []:
            code = momo_store_code_from_goods_no(row.get("商品編號"))
            if code:
                return code
        return None

    def _default_export_filename(self) -> str:
        if self._spec is not None and self._spec.fn_key == "momo_order_query":
            # mo店+ 訂單匯出的預設檔名比照後台「訂單匯出」的命名格式（OrderExport_店代碼_時間戳記.xls），
            # 使用者才不用每次手動改檔名去對照後台下載的檔案（2026-08-02 使用者要求）。
            store_code = self._momo_store_code_from_results()
            if store_code:
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                return f"OrderExport_{store_code}_{ts}.xlsx"
        if self._spec is not None and self._spec.fn_key == "cp_order_query":
            # Coupang 訂單匯出的預設檔名比照 Wing 後台「DeliveryList」的命名前綴，讓使用者一眼
            # 看出這份是官方格式（可直接餵給「訂單轉換」），跟 momo 那筆是同樣的用意
            # （2026-08-05）。不追求跟 Wing 完全一致的 "(2026-07-30)_(0)" 編號規則——那是瀏覽器
            # 下載去重用的序號，此處用到秒的時間戳記本身就不會撞名，不需要額外加編號邏輯。
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            return f"DeliveryList_{ts}.xlsx"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        platform = _safe_filename_part(self._platform)
        account = _safe_filename_part(self._account_label_fn()) if self._account_label_fn else "?"
        fn_name = _safe_filename_part(self.title_label.text())
        return f"{ts}_{platform}_{account}_{fn_name}.xlsx"

    def _rows_in_display_order(self) -> list[dict]:
        """依目前表格畫面上的順序回傳資料——使用者點過表頭排序後，這個順序會跟原始查詢
        回傳順序不同。從每列第 0 欄存的 UserRole 資料重組，取代 self._last_rows（那是原始
        查詢順序，不會跟著排序變動）。"""
        rows = []
        for r in range(self.result_table.rowCount()):
            item = self.result_table.item(r, 0)
            data = item.data(Qt.ItemDataRole.UserRole) if item else None
            rows.append(data if isinstance(data, dict) else (self._last_rows[r] if r < len(self._last_rows) else {}))
        return rows

    def _on_export(self):
        if not self._last_rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "匯出 Excel", self._default_export_filename(), "Excel (*.xlsx)")
        if not path:
            return
        try:
            # 匯出照畫面目前顯示的順序（含使用者排序過的結果），不是原始查詢順序，
            # 這樣匯出的檔案才會跟使用者在畫面上看到的一致。
            display_rows = self._rows_in_display_order()
            if self._spec is not None and self._spec.fn_key == "momo_order_query":
                # mo店+ 訂單匯出改用跟後台「訂單匯出」相同的官方表頭／欄位順序（2026-08-02 使用者要求）。
                account = self._account_fn() if self._account_fn else None
                export_momo_order_excel(path, display_rows, account=account)
            elif self._spec is not None and self._spec.fn_key == "cp_order_query":
                # Coupang 訂單匯出改用跟 Wing 後台「DeliveryList」相同的官方表頭／欄位順序
                # （2026-08-05 使用者要求，讓查詢結果也能直接餵給「訂單轉換」分頁）。
                export_coupang_order_excel(path, display_rows)
            else:
                export_to_excel(path, self._last_columns, display_rows)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "匯出失敗", str(e))
        else:
            # 文字比照 MomoLabelPanel.show_result 的「已儲存 N 個檔案：」格式，跟下方出貨/標籤面板
            # 的存檔結果訊息風格一致。
            sheet_note = ""
            if self._spec is not None and self._spec.fn_key in ("momo_order_query", "cp_order_query"):
                sheet_note = "\n工作表：官方格式（第一張）、API原始欄位（第二張）"
            QMessageBox.information(self, "匯出完成", f"已儲存 1 個檔案：\n{path}{sheet_note}")


# 狀態下拉選項一律顯示繁體中文（含原碼），送給 API 的仍是英文代碼——對照表與譯名來源分級
# 見 ui/status_labels.py。momo 用 "All" 這個明確代碼表示全部，所以不需要空白項；
# Coupang/Shopify 沒有「全部」代碼，用空白項代表「不指定狀態」（include_blank=True）。
MOMO_ORDER_STATUS_CHOICES = status_labels.options(status_labels.MOMO_ORDER_STATUS)
MOMO_GOODS_STATUS_CHOICES = status_labels.options(status_labels.MOMO_GOODS_STATUS)
COUPANG_ORDER_STATUS_CHOICES = status_labels.options(status_labels.COUPANG_ORDER_STATUS, include_blank=True)
COUPANG_PRODUCT_STATUS_CHOICES = status_labels.options(status_labels.COUPANG_PRODUCT_STATUS)
SHOPIFY_PRODUCT_STATUS_CHOICES = status_labels.options(status_labels.SHOPIFY_PRODUCT_STATUS, include_blank=True)

QUERY_SPECS: dict[str, QueryPanelSpec] = {
    # default_limit：訂單類預設 500（一般查一週訂單不會超過），商品類預設 1000
    # （商品會依 SKU/variant 展開成多列，Shopify 實測 492 列，設太小反而常常被截斷）。
    # 使用者可以直接在畫面上改，設 0 代表不限。
    #
    # show_entp_goods_no：只有 momo 有「商品原廠編號」這個概念。訂單那支是 API 原生支援
    # （OrderQuery 的 entpGoodsNo，官方註明支援模糊查詢），商品那支 API 請求端沒有這個參數，
    # 只在回應裡有，所以是抓回來之後在本地過濾——詳見 handlers.momo_goods_query。
    "momo_order_query": QueryPanelSpec(
        fn_key="momo_order_query", show_date_range=True, show_status=True,
        status_choices=MOMO_ORDER_STATUS_CHOICES, show_order_no=True,
        show_entp_goods_no=True, default_limit=500,
    ),
    "momo_goods_query": QueryPanelSpec(
        fn_key="momo_goods_query", show_status=True, status_choices=MOMO_GOODS_STATUS_CHOICES,
        status_label="上架狀態：",  # 對齊結果表格的「上架狀態」欄名，使用者才看得出這是同一件事
        show_sku=True, sku_label="商品編號(goodsCode)：",
        show_entp_goods_no=True, default_limit=1000,
    ),
    "cp_order_query": QueryPanelSpec(
        fn_key="cp_order_query", show_date_range=True, show_status=True,
        status_choices=COUPANG_ORDER_STATUS_CHOICES, show_order_no=True,
        order_no_label="訂單編號(orderId)：", default_limit=500,
    ),
    "cp_product_query": QueryPanelSpec(
        fn_key="cp_product_query", show_status=True, status_choices=COUPANG_PRODUCT_STATUS_CHOICES,
        show_keyword=True, show_sku=True, sku_label="賣家SKU(externalVendorSkuCode)：",
        default_limit=1000,
    ),
    "shopify_products_query": QueryPanelSpec(
        fn_key="shopify_products_query", show_status=True, status_choices=SHOPIFY_PRODUCT_STATUS_CHOICES,
        show_keyword=True, show_sku=True, sku_label="SKU：", default_limit=1000,
    ),
}
