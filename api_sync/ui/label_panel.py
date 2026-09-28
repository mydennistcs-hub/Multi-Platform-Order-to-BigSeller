"""取得寄件單／出貨確認的 UI 表單。

momo 和 Coupang 的流程形狀不一樣（momo 一次呼叫就回標籤；Coupang 要先安排出貨拿
運單號，再用運單號下載寄件單），所以拆成兩個獨立面板，不硬塞進同一個元件。
"""

import os
from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


@dataclass
class MomoLabelActionSpec:
    fn_key: str
    title: str
    client_method: str
    needs_confirm: bool
    show_dely_gb: bool = False
    dely_gb_options: list = field(default_factory=list)  # [(value, label)]
    show_delivery_note: bool = False


MOMO_LABEL_SPECS: dict[str, MomoLabelActionSpec] = {
    "momo_third_party_delivery_confirm": MomoLabelActionSpec(
        fn_key="momo_third_party_delivery_confirm", title="第三方物流出貨確認",
        client_method="confirm_third_party_delivery", needs_confirm=True, show_delivery_note=True,
    ),
    "momo_seven_store_delivery_confirm": MomoLabelActionSpec(
        fn_key="momo_seven_store_delivery_confirm", title="7-11超商出貨確認",
        client_method="confirm_seven_store_delivery", needs_confirm=True, show_delivery_note=True,
        show_dely_gb=True, dely_gb_options=[("21", "倉到店"), ("22", "店到店")],
    ),
    "momo_family_store_delivery_confirm": MomoLabelActionSpec(
        fn_key="momo_family_store_delivery_confirm", title="全家超商出貨確認",
        client_method="confirm_family_store_delivery", needs_confirm=True, show_delivery_note=True,
        show_dely_gb=True,
        dely_gb_options=[("29", "常溫店到店"), ("27", "常溫倉到店"), ("24", "冷凍店到店"), ("23", "冷凍倉到店")],
    ),
    "momo_third_party_print_label": MomoLabelActionSpec(
        fn_key="momo_third_party_print_label", title="第三方物流重印標籤",
        client_method="reprint_third_party_label", needs_confirm=False,
    ),
    "momo_seven_store_print_label": MomoLabelActionSpec(
        fn_key="momo_seven_store_print_label", title="711超商重印標籤",
        client_method="reprint_seven_store_label", needs_confirm=False,
        show_dely_gb=True, dely_gb_options=[("21", "倉到店"), ("22", "店到店")],
    ),
    "momo_family_store_print_label": MomoLabelActionSpec(
        fn_key="momo_family_store_print_label", title="全家超商重印標籤",
        client_method="reprint_family_store_label", needs_confirm=False,
        dely_gb_options=[("29", "常溫店到店"), ("27", "常溫倉到店"), ("24", "冷凍店到店"), ("23", "冷凍倉到店")],
        show_dely_gb=True,
    ),
}


# momo 訂單查詢回傳的「物流商」是自由格式字串（例："7-11店到店"、"全家店到店"、"新竹貨運"…），
# 不是代號，只能用關鍵字猜對應到哪一種出貨確認 API；猜不到（例如宅配，本商店未開通）就讓使用者自己選，
# 不要亂猜硬選一個。confirm/print_label 各給一組對應 key，方便「出貨確認」與「重印標籤」都能自動跳轉。
_MOMO_DELIVERY_KEYWORDS = [
    (("7-11", "711", "統一"), "momo_seven_store_delivery_confirm", "momo_seven_store_print_label"),
    (("全家", "FAMILY", "FM"), "momo_family_store_delivery_confirm", "momo_family_store_print_label"),
]


def guess_momo_label_keys(delivery_company: str) -> tuple[str, str, bool]:
    """回傳 (出貨確認fn_key, 重印標籤fn_key, 是否為關鍵字辨識出來的). 7-11/全家可辨識；辨識不出來
    （含宅配、空白）時預設落回第三方物流分頁，但 matched=False，呼叫端要清楚提示使用者自行確認
    （本商店只開通超商與第三方物流，未開通宅配，若其實是宅配訂單，本 App 無法用 API 確認出貨）。"""
    if delivery_company:
        upper = delivery_company.upper()
        for keywords, confirm_key, print_key in _MOMO_DELIVERY_KEYWORDS:
            if any(k in delivery_company or k in upper for k in keywords):
                return confirm_key, print_key, True
    return "momo_third_party_delivery_confirm", "momo_third_party_print_label", False


class MomoLabelPanel(QGroupBox):
    run_requested = Signal(str, dict)  # fn_key, kwargs（給 label_handlers.momo_run_label_action）

    def __init__(self):
        super().__init__("出貨確認／取得寄件單")
        layout = QVBoxLayout(self)

        # 動作類型：查詢結果同一頁就要能在 7-11／全家／第三方物流 出貨確認＋各自重印標籤這 6 種之間
        # 自由切換（例如系統猜是第三方物流，但使用者知道其實要走 7-11），不用再靠外部樹狀清單導覽。
        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("動作類型："))
        self.action_combo = QComboBox()
        for key, spec in MOMO_LABEL_SPECS.items():
            self.action_combo.addItem(spec.title, userData=key)
        self.action_combo.currentIndexChanged.connect(self._on_action_combo_changed)
        action_row.addWidget(self.action_combo, stretch=1)
        layout.addLayout(action_row)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.status_hint_label = QLabel("")
        self.status_hint_label.setWordWrap(True)
        self.status_hint_label.setStyleSheet("color: #1a5fb4;")
        self.status_hint_label.setVisible(False)
        layout.addWidget(self.title_label)
        layout.addWidget(self.warning_label)
        layout.addWidget(self.status_hint_label)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("訂單編號："))
        self.order_no_edit = QLineEdit()
        row1.addWidget(self.order_no_edit)
        row1.addWidget(QLabel("品項流水號（可用逗號分隔多個，例：001,002）："))
        self.order_seq_edit = QLineEdit("001")
        row1.addWidget(self.order_seq_edit)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.dely_gb_label = QLabel("超取類型：")
        self.dely_gb_combo = QComboBox()
        self.note_label = QLabel("配送訊息：")
        self.note_edit = QLineEdit("可出貨")
        row2.addWidget(self.dely_gb_label)
        row2.addWidget(self.dely_gb_combo)
        row2.addWidget(self.note_label)
        row2.addWidget(self.note_edit)
        row2.addStretch(1)
        layout.addLayout(row2)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("儲存資料夾："))
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        browse_btn = QPushButton("選擇...")
        browse_btn.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder_edit, stretch=1)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        self.run_button = QPushButton("執行")
        self.run_button.clicked.connect(self._on_run)
        layout.addWidget(self.run_button)

        self.log_label = QLabel("")
        self.log_label.setWordWrap(True)
        layout.addWidget(self.log_label)
        layout.addStretch(1)

        self._spec: MomoLabelActionSpec | None = None
        # 從查詢結果點選列進來時，main_window 會反推店鋪代碼（見 handlers.momo_store_code_from_goods_no）
        # 存在這裡，_on_run 帶給 momo_run_label_action 做跟 mo店+ 後台一致的檔名
        # （LogisticsLabel_TP0001949_時間戳記.pdf）。手動輸入訂單編號時沒有這個值，維持 None，
        # 存檔會退回舊版「訂單編號_品項_標籤」命名，不影響功能。
        self._store_code: str | None = None
        self._apply_spec(MOMO_LABEL_SPECS[self.action_combo.currentData()])

    def _on_action_combo_changed(self, _index: int):
        key = self.action_combo.currentData()
        if key is not None:
            self._apply_spec(MOMO_LABEL_SPECS[key])

    def _apply_spec(self, spec: MomoLabelActionSpec):
        """切換動作類型時只調整欄位顯示規則，**不清空**已輸入的訂單編號/品項流水號——使用者可能只是
        想幫同一張訂單換一種出貨方式重試（例如系統猜錯物流商），清空會很煩人。"""
        self._spec = spec
        self.title_label.setText(spec.title)
        if spec.needs_confirm:
            self.warning_label.setText("⚠️ 此動作會將訂單標記為已出貨，無法復原，請確認訂單資訊正確再執行。")
            self.warning_label.setStyleSheet("color: #b45309; font-weight: bold;")
        else:
            self.warning_label.setText("此動作只是補印標籤，不會異動訂單狀態，可放心重複執行。")
            self.warning_label.setStyleSheet("color: #1a7f37;")

        self.dely_gb_label.setVisible(spec.show_dely_gb)
        self.dely_gb_combo.setVisible(spec.show_dely_gb)
        self.dely_gb_combo.clear()
        for value, label in spec.dely_gb_options:
            self.dely_gb_combo.addItem(f"{label}（{value}）", userData=value)

        self.note_label.setVisible(spec.show_delivery_note)
        self.note_edit.setVisible(spec.show_delivery_note)
        if spec.show_delivery_note and not self.note_edit.text():
            self.note_edit.setText("可出貨")

        self.log_label.setText("")

    def set_action(self, fn_key: str):
        """外部（樹狀清單點擊某個出貨/標籤項目）指定要切到哪種動作類型；不清空欄位。"""
        idx = self.action_combo.findData(fn_key)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)  # 會觸發 _on_action_combo_changed → _apply_spec

    def reset_fields(self):
        """帳戶切換等情境下，舊帳戶查到的訂單編號已經沒有意義，整個清空。"""
        self.order_no_edit.clear()
        self.order_seq_edit.setText("001")
        self.log_label.setText("")
        self.status_hint_label.setVisible(False)
        self._store_code = None

    def clear_log(self, message: str = ""):
        self.log_label.setText(message)

    def prefill(self, order_no: str, order_seq: str = "", delivery_company: str = "", item_status: str = "",
                store_code: str | None = None):
        """從訂單查詢結果右鍵選單跳轉過來時，帶入訂單編號／品項流水號，並顯示物流商/品項狀態提示。"""
        self.order_no_edit.setText(order_no)
        if order_seq:
            self.order_seq_edit.setText(order_seq)
        self.log_label.setText("")
        self._store_code = store_code

        hint_parts = []
        if delivery_company:
            hint_parts.append(f"訂單查詢顯示的物流商：{delivery_company}")
        if item_status:
            hint_parts.append(f"品項狀態：{item_status}")
        self.status_hint_label.setText("　".join(hint_parts))
        self.status_hint_label.setVisible(bool(hint_parts))

    def show_result(self, saved_files: list, messages: list):
        lines = list(messages)
        if saved_files:
            lines.append("")
            lines.append(f"已儲存 {len(saved_files)} 個檔案：")
            lines.extend(saved_files)
        self.log_label.setStyleSheet("color: #1a7f37;")
        self.log_label.setText("\n".join(lines))

    def show_error(self, message: str):
        self.log_label.setStyleSheet("color: #c00;")
        self.log_label.setText(message)

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "選擇儲存資料夾")
        if path:
            self.folder_edit.setText(path)

    def _on_run(self):
        if self._spec is None:
            return
        if not self.folder_edit.text():
            self.show_error("請先選擇儲存資料夾。")
            return
        order_no = self.order_no_edit.text().strip()
        seqs = [s.strip() for s in self.order_seq_edit.text().split(",") if s.strip()]
        if not order_no or not seqs:
            self.show_error("請輸入訂單編號與品項流水號。")
            return

        if self._spec.needs_confirm:
            reply = QMessageBox.question(
                self, "確認執行",
                f"「{self._spec.title}」會將訂單 {order_no} 標記為已出貨，無法復原。\n確定要執行嗎？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        order_list = [{"orderNo": order_no, "orderSeq": seq} for seq in seqs]
        kwargs = {"order_list": order_list, "folder": self.folder_edit.text(), "store_code": self._store_code}
        if self._spec.show_dely_gb:
            kwargs["dely_gb"] = self.dely_gb_combo.currentData()
        if self._spec.show_delivery_note:
            kwargs["delivery_note"] = self.note_edit.text()

        self.clear_log("執行中...")
        self.run_requested.emit(self._spec.fn_key, kwargs)


COUPANG_COURIERS = [
    ("TWL_KERRY", "嘉里（宅配）", "home"),
    ("TWL_HCT", "新竹物流（宅配）", "home"),
    ("TWL_FM", "全家（超商）", "cvs"),
    ("TWL_711", "7-11（超商）", "cvs"),
]

# Coupang 訂單查詢回傳的 deliveryCompanyName 是自由格式的物流商名稱，不是 TWL_XXX 代碼，
# 只能用關鍵字盡量猜對應到哪一家；猜不到就讓使用者自己選，不要亂猜硬選一個。
_COURIER_NAME_KEYWORDS = [
    ("TWL_711", ("7-11", "711", "統一", "SEVEN")),
    ("TWL_FM", ("全家", "FAMILY")),
    ("TWL_KERRY", ("嘉里", "KERRY")),
    ("TWL_HCT", ("新竹", "HCT")),
]


def guess_courier_code(delivery_company_name: str) -> str | None:
    if not delivery_company_name:
        return None
    upper = delivery_company_name.upper()
    for code, keywords in _COURIER_NAME_KEYWORDS:
        if any(k in delivery_company_name or k in upper for k in keywords):
            return code
    return None


_STATUS_HINTS = {
    "ACCEPT": "此訂單狀態是 ACCEPT（訂單確認），請先執行①確認訂單。",
    "INSTRUCT": "此訂單狀態是 INSTRUCT（準備中），可以直接執行②安排出貨（不用再做①）。",
    "DEPARTURE": "此訂單狀態是 DEPARTURE（待寄出），通常已經安排過出貨、運單號已存在，"
                 "直接執行③下載寄件單即可（不用再做①②，重複執行②可能會失敗）。",
    "DELIVERING": "此訂單狀態是 DELIVERING（配送中），已經安排過出貨，直接執行③下載寄件單即可。",
    "FINAL_DELIVERY": "此訂單狀態是 FINAL_DELIVERY（配送完成），只能執行③下載寄件單，"
                       "且官方限制送達完成 7 天後會過期無法下載。",
}


class CoupangLabelPanel(QGroupBox):
    acknowledge_requested = Signal(dict)
    arrange_requested = Signal(dict)
    download_requested = Signal(dict)
    # 使用者按「選擇…」時發出，main_window 去呼叫 API 抓清單、跳對話框讓使用者選，
    # 選完再呼叫本面板的 set_return_center_code / set_outbound_place_code 填回來。
    # 這兩個代碼是 Coupang 內部代碼（例如新竹物流要指定從哪個發貨地收件），賣家背不起來，
    # 原本只給空白輸入框等於卡死在這一步。
    pick_return_center_requested = Signal()
    pick_outbound_place_requested = Signal()

    def __init__(self):
        super().__init__("安排出貨／下載寄件單")
        layout = QVBoxLayout(self)

        warning = QLabel(
            "訂單狀態要依序走：ACCEPT（訂單確認）→ INSTRUCT（準備中）→ DEPARTURE（待寄出）。"
            "⚠️「①確認訂單」「②安排出貨」都會異動訂單狀態、無法復原；「③下載寄件單」單純下載檔案，"
            "可重複執行（官方限制：訂單還沒安排出貨前查不到，運送完成 7 天後也會過期）。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #b45309; font-weight: bold;")
        layout.addWidget(warning)

        self.status_hint_label = QLabel("")
        self.status_hint_label.setWordWrap(True)
        self.status_hint_label.setStyleSheet("color: #1a5fb4;")
        self.status_hint_label.setVisible(False)
        layout.addWidget(self.status_hint_label)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("合併配送號碼(shipmentBoxId)："))
        self.shipment_box_id_edit = QLineEdit()
        row1.addWidget(self.shipment_box_id_edit)
        row1.addWidget(QLabel("物流公司："))
        self.courier_combo = QComboBox()
        for code, label, _kind in COUPANG_COURIERS:
            self.courier_combo.addItem(f"{label}（{code}）", userData=code)
        self.courier_combo.currentIndexChanged.connect(self._on_courier_changed)
        row1.addWidget(self.courier_combo)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.return_center_label = QLabel("退貨地代碼(returnCenterCode)：")
        self.return_center_edit = QLineEdit()
        self.return_center_edit.setPlaceholderText("按右邊「選擇…」從帳戶已建立的退貨地挑一個")
        self.return_center_pick = QPushButton("選擇…")
        self.return_center_pick.clicked.connect(self.pick_return_center_requested.emit)
        self.outbound_place_label = QLabel("發貨地代碼(outboundShippingPlaceCode)：")
        self.outbound_place_edit = QLineEdit()
        self.outbound_place_edit.setPlaceholderText("宅配要指定從哪個發貨地收件，按右邊「選擇…」")
        self.outbound_place_pick = QPushButton("選擇…")
        self.outbound_place_pick.clicked.connect(self.pick_outbound_place_requested.emit)
        row2.addWidget(self.return_center_label)
        row2.addWidget(self.return_center_edit, stretch=1)
        row2.addWidget(self.return_center_pick)
        row2.addWidget(self.outbound_place_label)
        row2.addWidget(self.outbound_place_edit, stretch=1)
        row2.addWidget(self.outbound_place_pick)
        layout.addLayout(row2)

        self.acknowledge_button = QPushButton("① 確認訂單（狀態變更為準備中，ACCEPT→INSTRUCT）")
        self.acknowledge_button.clicked.connect(self._on_acknowledge)
        layout.addWidget(self.acknowledge_button)

        self.arrange_button = QPushButton("② 安排出貨並取得運單號")
        self.arrange_button.clicked.connect(self._on_arrange)
        layout.addWidget(self.arrange_button)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("運單號(invoiceNumber)："))
        self.invoice_number_edit = QLineEdit()
        self.invoice_number_edit.setPlaceholderText("安排出貨成功後會自動帶入，也可以手動輸入已知的運單號")
        row3.addWidget(self.invoice_number_edit, stretch=1)
        layout.addLayout(row3)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("儲存資料夾："))
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        browse_btn = QPushButton("選擇...")
        browse_btn.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder_edit, stretch=1)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        self.download_button = QPushButton("③ 下載寄件單")
        self.download_button.clicked.connect(self._on_download)
        layout.addWidget(self.download_button)

        self.log_label = QLabel("")
        self.log_label.setWordWrap(True)
        layout.addWidget(self.log_label)
        layout.addStretch(1)

        self._on_courier_changed()

    def _on_courier_changed(self):
        kind = COUPANG_COURIERS[self.courier_combo.currentIndex()][2]
        for w in (self.return_center_label, self.return_center_edit, self.return_center_pick):
            w.setVisible(kind == "cvs")
        for w in (self.outbound_place_label, self.outbound_place_edit, self.outbound_place_pick):
            w.setVisible(kind == "home")

    def set_return_center_code(self, code: str):
        self.return_center_edit.setText(code)

    def set_outbound_place_code(self, code: str):
        self.outbound_place_edit.setText(code)

    def reset(self):
        self.shipment_box_id_edit.clear()
        self.return_center_edit.clear()
        self.outbound_place_edit.clear()
        self.invoice_number_edit.clear()
        self.log_label.setText("")
        self.status_hint_label.setVisible(False)

    def prefill(self, shipment_box_id: str, invoice_number: str = "", delivery_company_name: str = "", status: str = ""):
        self.shipment_box_id_edit.setText(shipment_box_id)
        self.invoice_number_edit.setText(invoice_number or "")
        self.log_label.setText("")

        guessed_code = guess_courier_code(delivery_company_name)
        if guessed_code:
            for i, (code, _label, _kind) in enumerate(COUPANG_COURIERS):
                if code == guessed_code:
                    self.courier_combo.setCurrentIndex(i)
                    break

        hint_parts = []
        if delivery_company_name:
            matched = "已自動選取對應物流公司" if guessed_code else "⚠️無法自動判斷對應物流公司代碼，請手動確認選對"
            hint_parts.append(f"訂單查詢顯示的物流商：{delivery_company_name}（{matched}）")
        if status:
            hint_parts.append(_STATUS_HINTS.get(status, f"此訂單狀態是 {status}。"))
        self.status_hint_label.setText("　".join(hint_parts))
        self.status_hint_label.setVisible(bool(hint_parts))

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "選擇儲存資料夾")
        if path:
            self.folder_edit.setText(path)

    def show_error(self, message: str):
        self.log_label.setStyleSheet("color: #c00;")
        self.log_label.setText(message)

    def show_acknowledge_result(self, message: str):
        self.log_label.setStyleSheet("color: #1a7f37;")
        self.log_label.setText(message)

    def show_arrange_result(self, invoice_number: str, message: str):
        self.invoice_number_edit.setText(str(invoice_number))
        self.log_label.setStyleSheet("color: #1a7f37;")
        self.log_label.setText(message)

    def show_download_result(self, path: str, note: str = "", extra: str = ""):
        """extra 給「補齊 7-11 完整運單號」這種附加說明用，不影響成功/警告的顏色判斷。"""
        lines = [f"已儲存：{path}"]
        if extra:
            lines.append(extra)
        if note:
            lines.append(note)
            self.log_label.setStyleSheet("color: #b26a00;")
        else:
            self.log_label.setStyleSheet("color: #1a7f37;")
        self.log_label.setText("\n".join(lines))

    def _on_acknowledge(self):
        shipment_box_id = self.shipment_box_id_edit.text().strip()
        if not shipment_box_id:
            self.show_error("請輸入合併配送號碼(shipmentBoxId)。")
            return

        reply = QMessageBox.question(
            self, "確認執行",
            f"確認訂單會將訂單 {shipment_box_id} 狀態變更為「準備中」，無法復原。\n確定要執行嗎？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.log_label.setText("執行中...")
        self.acknowledge_requested.emit({"shipment_box_id": shipment_box_id})

    def _on_arrange(self):
        shipment_box_id = self.shipment_box_id_edit.text().strip()
        courier = self.courier_combo.currentData()
        if not shipment_box_id:
            self.show_error("請輸入合併配送號碼(shipmentBoxId)。")
            return
        kind = COUPANG_COURIERS[self.courier_combo.currentIndex()][2]
        return_center_code = self.return_center_edit.text().strip() or None
        outbound_place_code = self.outbound_place_edit.text().strip() or None
        if kind == "cvs" and not return_center_code:
            self.show_error(
                "超商（7-11／全家）安排出貨需要退貨地代碼(returnCenterCode)。"
                "請按欄位右邊的「選擇…」，程式會把這個帳戶已建立的退貨地抓回來給你挑。"
            )
            self.pick_return_center_requested.emit()
            return
        if kind == "home" and not outbound_place_code:
            self.show_error(
                "宅配（新竹物流／嘉里）安排出貨需要指定發貨地代碼(outboundShippingPlaceCode)，"
                "也就是要物流來哪個地址收件。請按欄位右邊的「選擇…」，程式會把這個帳戶已建立的"
                "發貨地抓回來給你挑。"
            )
            self.pick_outbound_place_requested.emit()
            return

        reply = QMessageBox.question(
            self, "確認執行",
            f"安排出貨會將訂單 {shipment_box_id} 標記為待寄出並配發運單號，無法復原。\n確定要執行嗎？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.log_label.setText("執行中...")
        self.arrange_requested.emit(
            {
                "shipment_box_id": shipment_box_id,
                "delivery_company_code": courier,
                "return_center_code": return_center_code,
                "outbound_shipping_place_code": outbound_place_code,
            }
        )

    def _on_download(self):
        shipment_box_id = self.shipment_box_id_edit.text().strip()
        invoice_number = self.invoice_number_edit.text().strip()
        courier = self.courier_combo.currentData()
        if not shipment_box_id or not invoice_number:
            self.show_error("請確認合併配送號碼與運單號都已填寫（可先執行①，或手動輸入已知的運單號）。")
            return
        if not self.folder_edit.text():
            self.show_error("請先選擇儲存資料夾。")
            return

        self.log_label.setText("下載中...")
        self.download_requested.emit(
            {
                "shipment_box_id": shipment_box_id,
                "delivery_company_code": courier,
                "invoice_number": invoice_number,
                "folder": self.folder_edit.text(),
            }
        )
