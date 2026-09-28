"""Phase 1（converter.py）功能移植進 Phase 2 主控台的「訂單轉換」分頁。

直接 `import converter` 重用 converter.convert_orders()——那是純邏輯函式（只吃
log(msg)/progress(value) 兩個 callback，不碰任何 GUI 元件），2026-08-05 起讓 Phase 2 這支
PySide6 App 也能用同一份轉換邏輯，不重寫、不複製一份，兩邊才不會邏輯分岔（見 CLAUDE.md
「Phase 1 / Phase 2」段落：不要因為做 Phase 2 就去動 converter.py 的邏輯——這裡只是重用，
沒有動它）。UI 部分因為 Tkinter 視窗無法內嵌進 PySide6 分頁，另外用 PySide6 元件重畫一份，
畫面配置比照原本 converter.py 的 `class App`（檔案選擇 / 密碼 / 進度 / 日誌）。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import converter


class ConverterPanel(QWidget):
    """mo店+ / Coupang 手動下載 Excel/PDF → BigSeller 模板 轉換工具。"""

    # 背景執行緒（見 _on_start 裡的 threading.Thread）不能直接碰 Qt 元件，改用訊號把 log/progress
    # 丟回主執行緒——訊號的 emit() 本身可以安全跨執行緒呼叫，連到的 slot 會自動排到接收端（主執行緒）
    # 的事件迴圈執行，這點跟原本 tkinter 版用 `root.after(0, ...)` 做的事一樣。
    _log_signal = Signal(str)
    _progress_signal = Signal(float)
    _finished_signal = Signal(bool, str)  # success, error_message

    def __init__(self):
        super().__init__()
        self._pdf_files: list[str] = []

        layout = QVBoxLayout(self)

        title = QLabel("多平台訂單 → BigSeller 訂單格式轉換工具")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        file_group = QGroupBox("文件選擇")
        file_layout = QVBoxLayout(file_group)
        self.mo_edit = self._add_file_row(
            file_layout, "mo店+ 訂單 Excel：", self._browse_mo,
            tooltip="mo店+ 後台匯出的官方格式 Excel，或本 App「mo店+ → 訂單」查詢頁匯出的 Excel"
                    "（欄位已對齊官方格式，兩種都可以直接用）。",
        )
        self.coupang_edit = self._add_file_row(
            file_layout, "Coupang 訂單 Excel：", self._browse_coupang,
            tooltip="⚠️ 必須是 Coupang Wing 後台手動下載的「DeliveryList」Excel，"
                    "不是本 App「Coupang → 訂單」查詢頁的匯出檔（兩者欄位格式不同）。",
        )
        self.template_edit = self._add_file_row(file_layout, "BigSeller 模板 Excel：", self._browse_template)

        pdf_row = QHBoxLayout()
        pdf_row.addWidget(QLabel("PDF 文件（可多選）："))
        self.pdf_label = QLabel("（尚未選擇）")
        self.pdf_label.setStyleSheet("color: #666;")
        pdf_row.addWidget(self.pdf_label, stretch=1)
        pdf_browse_btn = QPushButton("選擇 PDF")
        pdf_browse_btn.clicked.connect(self._browse_pdf)
        pdf_row.addWidget(pdf_browse_btn)
        pdf_clear_btn = QPushButton("清除")
        pdf_clear_btn.clicked.connect(self._clear_pdf)
        pdf_row.addWidget(pdf_clear_btn)
        file_layout.addLayout(pdf_row)
        layout.addWidget(file_group)

        pw_group = QGroupBox("PDF / Excel 解密密碼（若無加密請留空）")
        pw_layout = QHBoxLayout(pw_group)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setFixedWidth(220)
        pw_layout.addWidget(self.password_edit)
        show_pw_check = QCheckBox("顯示密碼")
        show_pw_check.toggled.connect(
            lambda checked: self.password_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        pw_layout.addWidget(show_pw_check)
        pw_layout.addStretch(1)
        layout.addWidget(pw_group)

        btn_row = QHBoxLayout()
        self.start_button = QPushButton("▶  開始轉換")
        self.start_button.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_button)
        clear_log_btn = QPushButton("清除日誌")
        clear_log_btn.clicked.connect(self._clear_log)
        btn_row.addWidget(clear_log_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        progress_group = QGroupBox("執行進度")
        progress_layout = QVBoxLayout(progress_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)
        self.progress_label = QLabel("就緒，等待開始...")
        progress_layout.addWidget(self.progress_label)
        layout.addWidget(progress_group)

        log_group = QGroupBox("執行日誌")
        log_layout = QVBoxLayout(log_group)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        self.log_edit.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_edit)
        layout.addWidget(log_group, stretch=1)

        self._log_signal.connect(self._append_log)
        self._progress_signal.connect(self._set_progress)
        self._finished_signal.connect(self._on_finished)

    # ── 版面小工具 ──────────────────────────────────────────────────────────

    def _add_file_row(
        self, parent_layout: QVBoxLayout, label_text: str, browse_slot, tooltip: str = ""
    ) -> QLineEdit:
        row = QHBoxLayout()
        label = QLabel(label_text)
        if tooltip:
            label.setToolTip(tooltip)
        row.addWidget(label)
        edit = QLineEdit()
        if tooltip:
            edit.setToolTip(tooltip)
        row.addWidget(edit, stretch=1)
        btn = QPushButton("瀏覽…")
        btn.clicked.connect(browse_slot)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return edit

    # ── 瀏覽 ────────────────────────────────────────────────────────────────

    def _browse_mo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 mo店+ 訂單 Excel", "", "Excel (*.xlsx *.xls);;所有文件 (*.*)"
        )
        if path:
            self.mo_edit.setText(path)

    def _browse_coupang(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 Coupang 訂單 Excel", "", "Excel (*.xlsx);;所有文件 (*.*)"
        )
        if path:
            self.coupang_edit.setText(path)

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 BigSeller 模板 Excel（轉換後將直接覆蓋此檔）", "",
            "Excel (*.xlsx *.xls);;所有文件 (*.*)",
        )
        if path:
            self.template_edit.setText(path)

    def _browse_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇裝箱明細 / 運單 PDF（可多選）", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        for p in paths:
            if p not in self._pdf_files:
                self._pdf_files.append(p)
        self._refresh_pdf_label()

    def _clear_pdf(self):
        self._pdf_files.clear()
        self._refresh_pdf_label()

    def _refresh_pdf_label(self):
        if self._pdf_files:
            self.pdf_label.setText(f"已選 {len(self._pdf_files)} 個 PDF 文件")
            self.pdf_label.setStyleSheet("color: #000;")
        else:
            self.pdf_label.setText("（尚未選擇）")
            self.pdf_label.setStyleSheet("color: #666;")

    # ── 日誌／進度 ──────────────────────────────────────────────────────────

    def _clear_log(self):
        self.log_edit.clear()

    def _append_log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{ts}]  {message}")

    def _set_progress(self, value: float):
        self.progress_bar.setValue(int(value))
        self.progress_label.setText(f"進度：{value:.0f}%")

    # ── 執行 ────────────────────────────────────────────────────────────────

    def _on_start(self):
        mo_path = self.mo_edit.text().strip()
        coupang_path = self.coupang_edit.text().strip()
        template_path = self.template_edit.text().strip()

        if not mo_path and not coupang_path:
            QMessageBox.warning(self, "提示", "請至少選擇 mo店+ 或 Coupang 訂單 Excel！")
            return
        if not template_path:
            QMessageBox.warning(self, "提示", "請先選擇 BigSeller 模板 Excel！")
            return
        for p in (mo_path, coupang_path, template_path):
            if p and not os.path.exists(p):
                QMessageBox.critical(self, "錯誤", f"找不到文件：\n{p}")
                return

        password = self.password_edit.text()
        pdf_paths = list(self._pdf_files)

        self.start_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self._append_log("=" * 60)
        self._append_log("開始轉換...")
        self._append_log(f"  mo店+   : {os.path.basename(mo_path) if mo_path else '（未選）'}")
        self._append_log(f"  Coupang : {os.path.basename(coupang_path) if coupang_path else '（未選）'}")
        self._append_log(f"  模板    : {os.path.basename(template_path)}")
        self._append_log(f"  PDF 數  : {len(pdf_paths)} 個")
        self._append_log(f"  密碼    : {'已設定' if password else '（無）'}")
        self._append_log("─" * 60)

        def _run():
            try:
                converter.convert_orders(
                    mo_path, template_path, pdf_paths, password,
                    self._log_signal.emit, self._progress_signal.emit, coupang_path,
                )
            except Exception as exc:  # noqa: BLE001 — 顯示給使用者看，不分類處理
                self._log_signal.emit(f"✗ 轉換失敗：{exc}")
                self._progress_signal.emit(0)
                self._finished_signal.emit(False, str(exc))
            else:
                self._finished_signal.emit(True, "")

        threading.Thread(target=_run, daemon=True).start()

    def _on_finished(self, success: bool, error_message: str):
        self.start_button.setEnabled(True)
        if not success:
            QMessageBox.critical(self, "轉換失敗", error_message)
