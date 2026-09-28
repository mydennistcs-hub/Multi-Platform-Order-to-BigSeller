"""多帳戶／多平台 API 管理主控台 —— UI 骨架。

大部分功能項目點擊後仍只會顯示「尚未實作」；「訂單」、商品查詢這幾項
（見 registry.py 裡 implemented=True 者）已經接上 api_sync/ 的真實邏輯，
用 query_panel.QueryPanel 顯示完整查詢表單（日期區間/狀態/訂單號/關鍵字/
SKU/查詢上限），點「執行查詢」會實際打 API 並把結果列出來，可匯出 Excel。

功能樹只列出 `merged_into` 為空的項目：momo 各物流的出貨確認/重印標籤、Coupang 的
①確認訂單/②安排出貨/③下載寄件單，都已經是「訂單」頁下半部內建的動作，不再單獨列一項
（registry.py 仍保留它們做為 API 盤點資料）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api_sync.accounts import accounts_by_platform, get_account, load_accounts
from api_sync.ip_check import fetch_current_ip
from api_sync.ui.converter_panel import ConverterPanel
from api_sync.ui.handlers import (
    COUPANG_RAW_STATUS_KEY,
    MOMO_DELIVERY_COMPANY_COLUMN,
    MOMO_ITEM_STATUS_COLUMN,
    MOMO_ORDER_NO_COLUMN,
    MOMO_ORDER_SEQ_COLUMN,
    MOMO_ORDER_STATUS_PRINTED,
    RUN_HANDLERS,
    SHIPMENT_BOX_ID_COLUMN,
    momo_store_code_from_goods_no,
)
from api_sync.ui.label_handlers import (
    coupang_fetch_outbound_places,
    coupang_fetch_return_centers,
    coupang_run_acknowledge,
    coupang_run_arrange_shipment,
    coupang_run_download_invoice,
    momo_run_label_action,
)
from api_sync.ui.label_panel import (
    MOMO_LABEL_SPECS,
    CoupangLabelPanel,
    MomoLabelPanel,
    guess_momo_label_keys,
)
from api_sync.ui.query_panel import QUERY_SPECS, QueryPanel
from api_sync.ui.registry import (
    COUPANG_BASE_URL,
    COUPANG_FUNCTIONS,
    MOMO_BASE_URL,
    MOMO_FUNCTIONS,
    SHOPIFY_BASE_URL,
    SHOPIFY_FUNCTIONS,
    ApiFunction,
)

FUNCTION_ROLE = Qt.ItemDataRole.UserRole

# Coupang「訂單相關」樹狀清單裡，跟出貨/寄件單流程有關、應該導向 CoupangLabelPanel 的項目
# （①確認訂單／②安排出貨／③下載寄件單，見 registry.py 的 cp_order_acknowledgement/
# cp_arrange_shipment/cp_download_invoices）。
_COUPANG_ORDER_WORKFLOW_KEYS = {"cp_order_acknowledgement", "cp_arrange_shipment", "cp_download_invoices"}


def _s(value) -> str:
    return str(value) if value is not None else ""


def _fit_combo_to_contents(combo: QComboBox, extra_padding: int = 40):
    """讓下拉選單收合狀態的寬度依目前選項文字自動調整（剛好show出文字再留一點邊距），不要固定
    stretch=1 硬撐滿整列——原本帳戶下拉搶走一整列寬度，新增的密碼欄位/checkbox 就沒地方放。"""
    metrics = combo.fontMetrics()
    longest = max((metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
    combo.setMinimumWidth(longest + extra_padding)


# 「查詢結果／出貨確認」上下分隔線原本又細又沒有視覺提示，使用者反應「拉不太動」——預設 handle
# 只有幾個像素寬，滑鼠很難剛好點中；加寬＋上色（hover 時變深）讓它好抓好拖。
_ORDER_WORKBENCH_SPLITTER_STYLE = (
    "QSplitter::handle{background:#c7cdd6;}"
    "QSplitter::handle:hover{background:#8a97a8;}"
)


def _wrap_scrollable(widget: QWidget) -> QScrollArea:
    """把下半部（出貨確認／取得寄件單）面板包一層 QScrollArea 再放進 QSplitter。

    原本面板直接放進 QSplitter 時，它的最小高度＝內部欄位（動作類型/訂單編號/儲存資料夾…等
    好幾列）全部排開所需要的高度，導致分隔線能拖曳的範圍很小——使用者往下拖沒多少就撞到這個
    最小高度，看起來像「拉不太動」。包上 QScrollArea 後，面板本身允許被壓縮到遠小於內容高度，
    壓不下的部分改用捲動顯示（不會裁切/重疊），分隔線因此可以大幅往下拖，讓查詢結果拿到更多
    空間、出貨面板收到接近畫面底部。
    """
    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setMinimumHeight(0)
    return scroll


class FunctionDetailPanel(QGroupBox):
    """畫面右側（一般功能）：顯示目前選到的 API 功能詳細資訊 + 佔位執行按鈕。"""

    def __init__(self):
        super().__init__("功能詳細資訊")
        layout = QVBoxLayout(self)

        self.name_label = QLabel("請從左側選擇一個功能")
        self.name_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.name_label.setWordWrap(True)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color: #666;")

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)

        self.run_button = QPushButton("執行")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)

        layout.addWidget(self.name_label)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.desc_label)
        layout.addStretch(1)
        layout.addWidget(self.run_button)

        self._current: ApiFunction | None = None

    def show_function(self, fn: ApiFunction, base_url: str):
        self._current = fn
        self.name_label.setText(fn.name + ("（已停用）" if fn.deprecated else ""))
        self.meta_label.setText(f"{fn.method}  {base_url}{fn.path}")
        self.status_label.setText("狀態：尚未實作")
        self.status_label.setStyleSheet("color: #999;")
        self.desc_label.setText(fn.description or "（此功能暫無額外說明）")
        self.run_button.setEnabled(True)

    def _on_run(self):
        if self._current is not None:
            QMessageBox.information(
                self,
                self._current.name,
                f"「{self._current.name}」尚未串接到 UI，敬請期待。\n\n"
                f"{self._current.method} {self._current.path}",
            )


class PlatformPanel(QWidget):
    """單一平台（momo 或 Coupang）的分頁內容：帳戶選擇 + 功能樹 + 詳細面板／查詢面板。"""

    def __init__(self, platform: str, base_url: str, functions: list[ApiFunction], display_name: str = ""):
        super().__init__()
        self.platform = platform
        self.base_url = base_url
        # platform 是內部代號（accounts.json 的 platform 欄位、匯出檔名都用它，不要動）；
        # display_name 只給畫面上的標題用。例如內部代號 "momo"，畫面顯示「mo店+」——
        # momo 是集團品牌，店家後台的正式名稱是「mo店+」，兩者意義不同（使用者指正）。
        self.display_name = display_name or platform

        layout = QVBoxLayout(self)

        account_row = QHBoxLayout()
        account_row.addWidget(QLabel("帳戶／公司："))
        self.account_combo = QComboBox()
        self._load_accounts()
        # 寬度剛好show出文字再留一點邊距，不要用 stretch=1 撐滿整列——騰出空間給 mo店+ 專用的
        # 「解除下載文件的密碼」欄位（見下方）。
        _fit_combo_to_contents(self.account_combo)
        account_row.addWidget(self.account_combo)

        # 只有 mo店+ 需要：momo 重印標籤等回傳的檔案有時要用統編解密（官方文件寫「請用統編解密」，
        # 沒說是哪種加密格式，label_utils.try_decrypt_office_bytes 是 best-effort）。密碼欄預設帶入
        # 目前帳戶的統編（_sync_decrypt_password，帳戶切換時聯動），使用者也可以自行改成別的密碼；
        # checkbox 控制匯出/下載時要不要嘗試解密，兩者都不影響非加密內容（best-effort 沒偵測到加密
        # 就原樣存檔）。
        self.decrypt_password_edit: QLineEdit | None = None
        self.decrypt_checkbox: QCheckBox | None = None
        if platform == "momo":
            account_row.addWidget(QLabel("解除下載文件的密碼："))
            self.decrypt_password_edit = QLineEdit()
            self.decrypt_password_edit.setFixedWidth(140)
            self.decrypt_password_edit.setToolTip(
                "momo 回傳的重印標籤/明細等檔案有時需要密碼解密（官方文件提到用統編解密），"
                "預設帶入目前帳戶的統編，可自行修改成其他密碼。"
            )
            account_row.addWidget(self.decrypt_password_edit)
            self.decrypt_checkbox = QCheckBox("匯出/下載時，若偵測到密碼就自動解密")
            self.decrypt_checkbox.setChecked(True)
            account_row.addWidget(self.decrypt_checkbox)
            self._sync_decrypt_password()

        account_row.addStretch(1)
        layout.addLayout(account_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree = QTreeWidget()
        # 只計入實際會顯示的項目；已合併進別的頁面的不算，免得數字跟畫面上看到的對不起來。
        shown = sum(1 for fn in functions if not fn.merged_into)
        merged = len(functions) - shown
        header = f"{self.display_name} 功能（共 {shown} 項"
        header += f"，另 {merged} 項已合併）" if merged else "）"
        self.tree.setHeaderLabels([header])
        self._populate_tree(functions)
        self.tree.itemClicked.connect(self._on_item_clicked)
        splitter.addWidget(self.tree)

        self.stack = QStackedWidget()
        self.detail = FunctionDetailPanel()
        self.query_panel = QueryPanel()
        self.query_panel.run_requested.connect(self._on_query_run_requested)
        self.query_panel.row_activated.connect(self._on_row_activated)
        self.query_panel.set_context(platform, self._account_label_for_export, self._current_account)

        # 查詢／確認／出貨合併同一個頁面：momo、Coupang 都是「上半查詢表單+結果表格、下半出貨/標籤
        # 面板」放在同一個垂直 QSplitter 裡，不用再切頁面就能一次完成整個流程。商品查詢等跟出貨無關
        # 的功能，點擊時把下半部隱藏即可（見 _on_item_clicked），不需要另外拆頁面。
        self.momo_label_panel = None
        self.coupang_label_panel = None
        # 出貨/標籤面板實際放進 QSplitter 的是包了 QScrollArea 的外層容器（見 _wrap_scrollable），
        # 不是面板本身——顯示/隱藏下半部時要切外層容器的可見性，否則面板本身 setVisible(False) 只會
        # 讓 QScrollArea 內容變空白，並不會讓 QSplitter 把這塊空間收回去給上半部查詢結果。
        self._momo_label_wrap: QScrollArea | None = None
        self._coupang_label_wrap: QScrollArea | None = None
        if platform == "momo":
            self.momo_label_panel = MomoLabelPanel()
            self.momo_label_panel.run_requested.connect(self._on_momo_label_run_requested)
            self._momo_label_wrap = _wrap_scrollable(self.momo_label_panel)
            self.order_workbench = QSplitter(Qt.Orientation.Vertical)
            self.order_workbench.addWidget(self.query_panel)
            self.order_workbench.addWidget(self._momo_label_wrap)
            self.order_workbench.setStretchFactor(0, 2)
            self.order_workbench.setStretchFactor(1, 1)
            self.order_workbench.setHandleWidth(8)
            self.order_workbench.setStyleSheet(_ORDER_WORKBENCH_SPLITTER_STYLE)
            self.order_workbench.setSizes([520, 180])
        elif platform == "coupang":
            self.coupang_label_panel = CoupangLabelPanel()
            self.coupang_label_panel.pick_return_center_requested.connect(self._on_pick_return_center)
            self.coupang_label_panel.pick_outbound_place_requested.connect(self._on_pick_outbound_place)
            self.coupang_label_panel.acknowledge_requested.connect(self._on_coupang_acknowledge_requested)
            self.coupang_label_panel.arrange_requested.connect(self._on_coupang_arrange_requested)
            self.coupang_label_panel.download_requested.connect(self._on_coupang_download_requested)
            self._coupang_label_wrap = _wrap_scrollable(self.coupang_label_panel)
            self.order_workbench = QSplitter(Qt.Orientation.Vertical)
            self.order_workbench.addWidget(self.query_panel)
            self.order_workbench.addWidget(self._coupang_label_wrap)
            self.order_workbench.setStretchFactor(0, 2)
            self.order_workbench.setStretchFactor(1, 1)
            self.order_workbench.setHandleWidth(8)
            self.order_workbench.setStyleSheet(_ORDER_WORKBENCH_SPLITTER_STYLE)
            self.order_workbench.setSizes([520, 180])
        else:
            # Shopify 目前沒有出貨流程，維持單純查詢面板。
            self.order_workbench = self.query_panel

        self.stack.addWidget(self.detail)
        self.stack.addWidget(self.order_workbench)

        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter, stretch=1)

        self.account_combo.currentIndexChanged.connect(self._on_account_changed)

    def _on_account_changed(self, _index: int):
        # 切換帳戶後，前一個帳戶查出來的結果／已選定的訂單編號都不代表現在選的這個帳戶，清掉避免誤用。
        self.query_panel.clear_results("（已切換帳戶，上面的結果已失效，請重新按「執行查詢」）")
        if self.momo_label_panel is not None:
            self.momo_label_panel.reset_fields()
        if self.coupang_label_panel is not None:
            self.coupang_label_panel.reset()
        self._sync_decrypt_password()

    def _sync_decrypt_password(self):
        """帳戶下拉切換時聯動：「解除下載文件的密碼」預設值跟著新帳戶的統編更新。"""
        if self.decrypt_password_edit is None:
            return
        acc = self._current_account()
        self.decrypt_password_edit.setText(acc.tax_id if acc is not None else "")

    def _account_label_for_export(self) -> str:
        acc = self._current_account()
        return acc.company if acc is not None else self.account_combo.currentText()

    def _load_accounts(self):
        try:
            accounts = accounts_by_platform(self.platform)
        except RuntimeError as e:
            self.account_combo.addItem(f"（尚未設定：{e}）")
            self.account_combo.setEnabled(False)
            return
        if not accounts:
            self.account_combo.addItem("（accounts.json 內沒有這個平台的帳戶）")
            self.account_combo.setEnabled(False)
            return
        for acc in accounts:
            suffix = "" if acc.has_credentials else "（尚未設定憑證）"
            self.account_combo.addItem(f"{acc.company}（統編 {acc.tax_id}）{suffix}", userData=acc.id)

    def _populate_tree(self, functions: list[ApiFunction]):
        category_items: dict[str, QTreeWidgetItem] = {}
        for fn in functions:
            # 已合併到別的功能頁的項目不單獨列出（例如 momo 各物流的出貨確認/重印標籤都收在
            # 「訂單」頁下半部的動作類型下拉，Coupang 的①②③收在「訂單」頁下半部的三個按鈕）。
            # registry 仍保留這些項目做為 API 盤點資料，只是不進功能樹。
            if fn.merged_into:
                continue
            if fn.category not in category_items:
                cat_item = QTreeWidgetItem([fn.category])
                cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(cat_item)
                category_items[fn.category] = cat_item
            label = fn.name + ("（已停用）" if fn.deprecated else "")
            if fn.implemented:
                label = "✅ " + label
            fn_item = QTreeWidgetItem([label])
            fn_item.setData(0, FUNCTION_ROLE, fn)
            category_items[fn.category].addChild(fn_item)
        self.tree.expandAll()

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int):
        fn = item.data(0, FUNCTION_ROLE)
        if fn is None:
            return

        query_spec = QUERY_SPECS.get(fn.key)
        if query_spec is not None:
            # 同一個查詢功能重新點擊（例如切去別的面板又切回來）時不要重新 configure，
            # 否則會清空既有查詢結果，使用者又要重新查一次。
            if self.query_panel.current_fn_key() != fn.key:
                self.query_panel.configure(query_spec, fn.name)
            # 商品查詢跟出貨無關，下半部出貨/標籤面板收起來；訂單查詢才顯示。
            self._set_momo_label_visible(fn.key == "momo_order_query")
            self._set_coupang_label_visible(fn.key == "cp_order_query")
            self.stack.setCurrentWidget(self.order_workbench)
            return

        if self.momo_label_panel is not None and fn.key in MOMO_LABEL_SPECS:
            # 出貨/重印標籤相關項目：查詢表單若還沒查過訂單就順便設成訂單查詢（同樣套用「已經是同一
            # 個 fn_key 就不重設」規則，避免清掉使用者已經查好的結果），下半部切到對應動作類型。
            if self.query_panel.current_fn_key() != "momo_order_query":
                self.query_panel.configure(QUERY_SPECS["momo_order_query"], "訂單")
            self._set_momo_label_visible(True)
            self.momo_label_panel.set_action(fn.key)
            self.stack.setCurrentWidget(self.order_workbench)
            return

        if self.coupang_label_panel is not None and fn.key in _COUPANG_ORDER_WORKFLOW_KEYS:
            if self.query_panel.current_fn_key() != "cp_order_query":
                self.query_panel.configure(QUERY_SPECS["cp_order_query"], "訂單")
            self._set_coupang_label_visible(True)
            self.stack.setCurrentWidget(self.order_workbench)
            return

        self.detail.show_function(fn, self.base_url)
        self.stack.setCurrentWidget(self.detail)

    def _set_momo_label_visible(self, visible: bool):
        """切外層 QScrollArea（見 _wrap_scrollable）的可見性，不是面板本身——這樣隱藏時 QSplitter
        才會把這塊空間收回去給上半部查詢結果，而不是留著一塊空白的捲動區域。"""
        if self._momo_label_wrap is not None:
            self._momo_label_wrap.setVisible(visible)

    def _set_coupang_label_visible(self, visible: bool):
        if self._coupang_label_wrap is not None:
            self._coupang_label_wrap.setVisible(visible)

    def _current_account(self):
        account_id = self.account_combo.currentData()
        if not account_id:
            return None
        try:
            return get_account(account_id)
        except KeyError:
            return None

    def _on_query_run_requested(self, fn_key: str, params: dict):
        handler = RUN_HANDLERS.get(fn_key)
        if handler is None:
            self.query_panel.show_error("此功能尚未串接後端邏輯。")
            return

        account = self._current_account()
        if account is None:
            self.query_panel.show_error("找不到對應帳戶設定，請確認 accounts.json。")
            return
        if not account.has_credentials:
            self.query_panel.show_error(f"「{account.label}」尚未設定完整憑證，無法執行。")
            return

        try:
            columns, rows = handler(account, **params)
        except Exception as e:  # noqa: BLE001 — 顯示給使用者看，不分類處理
            self.query_panel.show_error(f"執行失敗：{e}")
            return

        if not rows:
            self.query_panel.show_error("查詢成功，但沒有符合條件的資料（0 筆）。")
            return
        self.query_panel.show_table(columns, rows)

    def _on_row_activated(self, row_data: dict):
        """使用者在結果表格點一下（整列選取）某一列，直接帶入下半部出貨/標籤面板——查詢跟出貨本來
        就在同一頁，不需要再跳頁。依 row_data 有沒有 Coupang/momo 專屬欄位判斷是哪個平台的結果。"""
        if SHIPMENT_BOX_ID_COLUMN in row_data and self.coupang_label_panel is not None:
            shipment_box_id = _s(row_data.get(SHIPMENT_BOX_ID_COLUMN))
            if not shipment_box_id:
                return
            self._set_coupang_label_visible(True)
            self.coupang_label_panel.prefill(
                shipment_box_id,
                # 「運單號」欄可能已經被 mark_coupang_invoice_number() 補成完整 12 碼（7-11），
                # 但③下載寄件單要帶的是 API 當初配發的那組號碼，所以有原始值就優先用原始值。
                invoice_number=_s(row_data.get("_api_invoice_number") or row_data.get("運單號")),
                delivery_company_name=_s(row_data.get("物流商")),
                # 用未翻譯的原始狀態碼，「狀態」欄現在是「配送中（DELIVERING）」這種中文顯示字串，
                # 拿去比對 label_panel._STATUS_HINTS 會對不上。
                status=_s(row_data.get(COUPANG_RAW_STATUS_KEY)),
            )
        elif MOMO_ORDER_SEQ_COLUMN in row_data and self.momo_label_panel is not None:
            order_no = _s(row_data.get(MOMO_ORDER_NO_COLUMN))
            if not order_no:
                return
            order_seq = _s(row_data.get("_combined_order_seq")) or _s(row_data.get(MOMO_ORDER_SEQ_COLUMN))
            delivery_company = _s(row_data.get(MOMO_DELIVERY_COMPANY_COLUMN))
            item_status = _s(row_data.get(MOMO_ITEM_STATUS_COLUMN))
            # 商品編號固定格式 TP+7碼店代碼+8碼序號，反推店代碼給下載檔名用（見
            # momo_run_label_action 的檔名邏輯，要跟 mo店+ 後台下載的檔名一致：
            # LogisticsLabel_TP0001949_時間戳記.pdf）。查不到（例如手動輸入訂單、非點選列進來）
            # 時維持 None，_on_momo_label_run_requested 那邊會退回舊版命名，不影響功能。
            store_code = momo_store_code_from_goods_no(row_data.get("商品編號"))

            # 品項狀態文字含「已出貨」等關鍵字時代表這張訂單早就出貨過，「出貨確認」對已出貨訂單重複
            # 執行會失敗，這種情況改猜「重印標籤」比較符合使用者實際想做的事。
            already_shipped = any(k in item_status for k in ("已出貨", "配送中", "已送達", "出貨完成"))
            confirm_key, print_key, matched = guess_momo_label_keys(delivery_company)
            fn_key = print_key if already_shipped else confirm_key

            self._set_momo_label_visible(True)
            self.momo_label_panel.set_action(fn_key)
            if not matched:
                note = (
                    "⚠️無法從物流商文字自動判斷是 7-11 或全家，已預設帶到「第三方物流」——"
                    "若這其實是宅配訂單，本 App 目前無法用 API 確認出貨（商店未開通宅配），請改用人工"
                    "流程；若其實是 7-11／全家，請自行從上方「動作類型」下拉選單改選對應項目。"
                )
                item_status = f"{item_status}\n{note}" if item_status else note
            self.momo_label_panel.prefill(
                order_no, order_seq=order_seq, delivery_company=delivery_company, item_status=item_status,
                store_code=store_code,
            )

    def _on_momo_label_run_requested(self, fn_key: str, kwargs: dict):
        spec = MOMO_LABEL_SPECS[fn_key]
        account = self._current_account()
        if account is None:
            self.momo_label_panel.show_error("找不到對應帳戶設定，請確認 accounts.json。")
            return
        if not account.has_credentials:
            self.momo_label_panel.show_error(f"「{account.label}」尚未設定完整憑證，無法執行。")
            return

        # 「解除下載文件的密碼」欄位＋checkbox（見 __init__ account_row）：checkbox 沒勾就不嘗試解密，
        # 勾了就用密碼欄目前的值（預設是帳戶統編，使用者可自行改成別的密碼）。
        password = None
        if self.decrypt_checkbox is not None and self.decrypt_checkbox.isChecked():
            password = self.decrypt_password_edit.text().strip() or None
        store_code = kwargs.pop("store_code", None)
        try:
            saved_files, messages = momo_run_label_action(
                account, spec.client_method, kwargs.pop("folder"),
                tax_id_for_decrypt=password, store_code=store_code, **kwargs,
            )
        except Exception as e:  # noqa: BLE001
            self.momo_label_panel.show_error(f"執行失敗：{e}")
            return
        self.momo_label_panel.show_result(saved_files, messages)

        # 出貨確認（第三方物流/7-11/全家，spec.needs_confirm=True）成功＝momo 後台「印單」動作，
        # 把上半部查詢結果表格裡這張訂單的「訂單狀態」本地樂觀更新為「已印單」，使用者不用重新
        # 查詢就能直接匯出正確狀態的 Excel（見 query_panel.mark_momo_order_status 的說明）。
        # 重印標籤（needs_confirm=False）不異動訂單狀態，不用更新；任一品項訊息帶「失敗」時
        # 也不更新，避免把失敗的品項誤標成已印單。
        if spec.needs_confirm and messages and all("失敗" not in m for m in messages):
            order_list = kwargs.get("order_list") or []
            order_no = order_list[0].get("orderNo") if order_list else None
            seqs = [o.get("orderSeq") for o in order_list if o.get("orderSeq")]
            if order_no:
                updated = self.query_panel.mark_momo_order_status(order_no, seqs, MOMO_ORDER_STATUS_PRINTED)
                if updated:
                    self.momo_label_panel.show_result(
                        saved_files,
                        messages + [
                            "（已將查詢結果表格裡這張訂單的「訂單狀態」本地更新為「已印單」，"
                            "方便直接匯出；如需確認最新狀態請重新查詢核對）"
                        ],
                    )

    def _pick_place(self, fetch_fn, title: str, prompt: str, setter):
        """共用的「抓清單→跳對話框讓使用者選→填回欄位」流程。

        Coupang 安排出貨要帶的 returnCenterCode（超商）/ outboundShippingPlaceCode（宅配，
        例如新竹物流要指定去哪個地址收件）都是賣家背不起來的內部代碼，原本 UI 只給空白輸入框，
        等於整個流程卡在這一步。改成按「選擇…」就即時查 API 列出來給使用者挑。
        """
        account = self._current_account()
        if account is None or not account.has_credentials:
            self.coupang_label_panel.show_error("找不到帳戶或憑證未設定完整，無法查詢清單。")
            return
        try:
            items = fetch_fn(account)
        except Exception as e:  # noqa: BLE001
            self.coupang_label_panel.show_error(f"查詢清單失敗：{e}")
            return
        if not items:
            self.coupang_label_panel.show_error(
                f"這個帳戶查不到任何{title}。請先到 Coupang Wing 後台建立，再回來重試。"
            )
            return

        labels = [label for _code, label in items]
        choice, ok = QInputDialog.getItem(self, title, prompt, labels, 0, False)
        if not ok:
            return
        setter(items[labels.index(choice)][0])
        self.coupang_label_panel.show_acknowledge_result(f"已選擇{title}，可以繼續執行②安排出貨。")

    def _on_pick_return_center(self):
        self._pick_place(
            coupang_fetch_return_centers, "退貨地",
            "請選擇要用的退貨地（超商出貨必填 returnCenterCode）：",
            self.coupang_label_panel.set_return_center_code,
        )

    def _on_pick_outbound_place(self):
        self._pick_place(
            coupang_fetch_outbound_places, "發貨地",
            "請選擇物流要來收件的發貨地（宅配必填 outboundShippingPlaceCode）：",
            self.coupang_label_panel.set_outbound_place_code,
        )

    def _on_coupang_acknowledge_requested(self, kwargs: dict):
        account = self._current_account()
        if account is None:
            self.coupang_label_panel.show_error("找不到對應帳戶設定，請確認 accounts.json。")
            return
        if not account.has_credentials:
            self.coupang_label_panel.show_error(f"「{account.label}」尚未設定完整憑證，無法執行。")
            return
        try:
            message = coupang_run_acknowledge(account, **kwargs)
        except Exception as e:  # noqa: BLE001
            self.coupang_label_panel.show_error(f"執行失敗：{e}")
            return
        self.coupang_label_panel.show_acknowledge_result(f"確認訂單成功：{message}")

    def _on_coupang_arrange_requested(self, kwargs: dict):
        account = self._current_account()
        if account is None:
            self.coupang_label_panel.show_error("找不到對應帳戶設定，請確認 accounts.json。")
            return
        if not account.has_credentials:
            self.coupang_label_panel.show_error(f"「{account.label}」尚未設定完整憑證，無法執行。")
            return
        try:
            result = coupang_run_arrange_shipment(account, **kwargs)
        except Exception as e:  # noqa: BLE001
            self.coupang_label_panel.show_error(f"執行失敗：{e}")
            return
        self.coupang_label_panel.show_arrange_result(
            result.get("invoiceNumber", ""), f"安排出貨成功，運單號：{result.get('invoiceNumber')}"
        )

    def _on_coupang_download_requested(self, kwargs: dict):
        account = self._current_account()
        if account is None:
            self.coupang_label_panel.show_error("找不到對應帳戶設定，請確認 accounts.json。")
            return
        if not account.has_credentials:
            self.coupang_label_panel.show_error(f"「{account.label}」尚未設定完整憑證，無法執行。")
            return
        try:
            path, note, full_invoice_number = coupang_run_download_invoice(account, **kwargs)
        except Exception as e:  # noqa: BLE001
            self.coupang_label_panel.show_error(f"執行失敗：{e}")
            return

        # 7-11：API 給的運單號只有前 8 碼，完整 12 碼只出現在剛下載的寄件單裡，順手補回查詢
        # 結果表格，使用者不用重新查詢就能直接匯出正確運單號的 Excel（跟 momo 出貨確認後補
        # 訂單狀態是同一個做法）。
        extra = ""
        if full_invoice_number:
            extra = f"7-11 完整交貨便服務代碼：{full_invoice_number}（API 只回傳前 8 碼）"
            updated = self.query_panel.mark_coupang_invoice_number(
                kwargs.get("shipment_box_id", ""), full_invoice_number
            )
            extra += (
                "，已同步更新上方查詢結果的「運單號」欄，可直接匯出 Excel。"
                if updated
                else "，但目前查詢結果裡找不到這張訂單，匯出前請重新查詢或自行補上。"
            )
        self.coupang_label_panel.show_download_result(path, note, extra)


class IpCheckPanel(QWidget):
    """檢查目前對外 IP 是否符合各帳戶登記在平台白名單裡的固定 IP。"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.current_ip_label = QLabel("尚未查詢")
        self.current_ip_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        refresh_button = QPushButton("重新查詢目前 IP")
        refresh_button.clicked.connect(self.refresh)
        top_row.addWidget(QLabel("目前對外 IP："))
        top_row.addWidget(self.current_ip_label, stretch=1)
        top_row.addWidget(refresh_button)
        layout.addLayout(top_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["公司", "平台", "帳戶 id", "應登記的固定 IP", "是否相符"])
        layout.addWidget(self.table, stretch=1)

        self._current_ip = None
        self.refresh()

    def refresh(self):
        try:
            info = fetch_current_ip()
        except Exception as e:  # noqa: BLE001
            self.current_ip_label.setText(f"查詢失敗：{e}")
            self._current_ip = None
        else:
            self._current_ip = info.get("ip")
            self.current_ip_label.setText(
                f"{info.get('ip', '?')}（{info.get('city', '?')}, {info.get('country', '?')} - {info.get('org', '?')}）"
            )
        self._reload_table()

    def _reload_table(self):
        try:
            accounts = load_accounts()
        except RuntimeError:
            accounts = []
        self.table.setRowCount(len(accounts))
        for r, acc in enumerate(accounts):
            self.table.setItem(r, 0, QTableWidgetItem(acc.company))
            self.table.setItem(r, 1, QTableWidgetItem(acc.platform))
            self.table.setItem(r, 2, QTableWidgetItem(acc.id))
            self.table.setItem(r, 3, QTableWidgetItem(acc.expected_ip or "（未設定）"))
            if self._current_ip is None or not acc.expected_ip:
                match_text = "？無法比對"
            elif self._current_ip == acc.expected_ip:
                match_text = "✅ 相符"
            else:
                match_text = "❌ 不符，請切換 VPN"
            match_item = QTableWidgetItem(match_text)
            self.table.setItem(r, 4, match_item)
        self.table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multi-Platform API 管理主控台")
        self.resize(1300, 760)

        tabs = QTabWidget()
        # 分頁標題用「mo店+」不是「momo店+」：momo 是集團品牌，賣家後台的正式名稱是「mo店+」，
        # 兩者代表的意義不同（使用者指正）。內部代號仍是 "momo"（對應 accounts.json 的 platform）。
        tabs.addTab(PlatformPanel("momo", MOMO_BASE_URL, MOMO_FUNCTIONS, display_name="mo店+"), "mo店+")
        tabs.addTab(PlatformPanel("coupang", COUPANG_BASE_URL, COUPANG_FUNCTIONS, display_name="Coupang"), "Coupang")
        tabs.addTab(PlatformPanel("shopify", SHOPIFY_BASE_URL, SHOPIFY_FUNCTIONS, display_name="Shopify"), "Shopify")
        # Phase 1（converter.py，原本獨立的 Multi-Platform-Order-to-BigSeller.exe）手動下載
        # Excel/PDF 轉 BigSeller 格式功能，2026-08-05 移植進來當一個分頁，直接重用
        # converter.convert_orders() 這個純邏輯函式（見 converter_panel.py 開頭說明）。
        tabs.addTab(ConverterPanel(), "訂單轉換")
        tabs.addTab(IpCheckPanel(), "IP 檢查")
        self.setCentralWidget(tabs)

        self.statusBar().showMessage(
            "訂單查詢／商品查詢已可實際執行並匯出 Excel，其餘功能仍為 UI 佔位（見 api_sync/ui/registry.py）"
        )
