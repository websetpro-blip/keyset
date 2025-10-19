from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from PySide6 import QtCore, QtWidgets

from ..services.proxy_manager import Proxy, ProxyManager


class ProxyEditorDialog(QtWidgets.QDialog):
    """Диалог для добавления или редактирования прокси."""

    def __init__(self, proxy: Optional[Proxy] = None, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Прокси")
        self._proxy = proxy
        self._result: Optional[Proxy] = None

        self.edit_label = QtWidgets.QLineEdit()
        self.combo_type = QtWidgets.QComboBox()
        self.combo_type.addItems(["http", "https", "socks5"])
        self.edit_server = QtWidgets.QLineEdit()
        self.edit_username = QtWidgets.QLineEdit()
        self.edit_password = QtWidgets.QLineEdit()
        self.edit_password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.edit_geo = QtWidgets.QLineEdit()
        self.check_sticky = QtWidgets.QCheckBox("Закреплять IP (sticky)")
        self.spin_max = QtWidgets.QSpinBox()
        self.spin_max.setRange(0, 999)
        self.check_enabled = QtWidgets.QCheckBox("Прокси активен")
        self.edit_notes = QtWidgets.QPlainTextEdit()
        self.edit_notes.setMaximumBlockCount(6)

        form = QtWidgets.QFormLayout()
        form.addRow("Метка", self.edit_label)
        form.addRow("Тип", self.combo_type)
        form.addRow("Сервер (host:port)", self.edit_server)
        form.addRow("Логин", self.edit_username)
        form.addRow("Пароль", self.edit_password)
        form.addRow("Гео (RU/KZ/...)", self.edit_geo)
        form.addRow("Макс. соединений", self.spin_max)
        form.addRow(self.check_sticky)
        form.addRow(self.check_enabled)
        form.addRow("Заметки", self.edit_notes)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if proxy:
            self._populate(proxy)

    def _populate(self, proxy: Proxy) -> None:
        self.edit_label.setText(proxy.label)
        self.combo_type.setCurrentText(proxy.type)
        self.edit_server.setText(proxy.server.split("://", 1)[-1])
        self.edit_username.setText(proxy.username or "")
        self.edit_password.setText(proxy.password or "")
        self.edit_geo.setText(proxy.geo or "")
        self.check_sticky.setChecked(proxy.sticky)
        self.spin_max.setValue(proxy.max_concurrent if proxy.max_concurrent is not None else 0)
        self.check_enabled.setChecked(proxy.enabled)
        self.edit_notes.setPlainText(proxy.notes or "")

    def accept(self) -> None:
        server = self.edit_server.text().strip()
        if not server:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите адрес прокси.")
            self.edit_server.setFocus()
            return

        proxy_id = self._proxy.id if self._proxy else uuid.uuid4().hex
        proxy = Proxy(
            id=proxy_id,
            label=self.edit_label.text().strip() or proxy_id,
            type=self.combo_type.currentText(),
            server=server,
            username=self.edit_username.text().strip() or None,
            password=self.edit_password.text().strip() or None,
            geo=self.edit_geo.text().strip() or None,
            sticky=self.check_sticky.isChecked(),
            max_concurrent=int(self.spin_max.value()),
            enabled=self.check_enabled.isChecked(),
            notes=self.edit_notes.toPlainText().strip(),
            last_check=self._proxy.last_check if self._proxy else None,
            last_ip=self._proxy.last_ip if self._proxy else None,
        )
        self._result = proxy
        super().accept()

    def proxy(self) -> Optional[Proxy]:
        return self._result


class ProxyManagerDialog(QtWidgets.QDialog):
    """Базовый менеджер прокси."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Proxy Manager")
        self.resize(900, 520)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.manager = ProxyManager.instance()
        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Метка",
                "Тип",
                "Сервер",
                "Логин",
                "Гео",
                "Sticky",
                "Макс.",
                "Активен",
                "Последний IP / Проверка",
            ]
        )

        self.button_add = QtWidgets.QPushButton("Добавить")
        self.button_edit = QtWidgets.QPushButton("Изменить")
        self.button_delete = QtWidgets.QPushButton("Удалить")
        self.button_test = QtWidgets.QPushButton("Проверить IP")
        self.button_refresh = QtWidgets.QPushButton("Обновить")
        self.button_close = QtWidgets.QPushButton("Закрыть")

        self.button_add.clicked.connect(self.add_proxy)
        self.button_edit.clicked.connect(self.edit_selected)
        self.button_delete.clicked.connect(self.delete_selected)
        self.button_test.clicked.connect(self.test_selected)
        self.button_refresh.clicked.connect(self.reload)
        self.button_close.clicked.connect(self.close)

        buttons_layout = QtWidgets.QHBoxLayout()
        for widget in (self.button_add, self.button_edit, self.button_delete, self.button_test, self.button_refresh):
            buttons_layout.addWidget(widget)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.button_close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons_layout)

        self.reload()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        proxies = self.manager.list(include_disabled=True)
        self.table.setRowCount(len(proxies))
        for row, proxy in enumerate(proxies):
            self._populate_row(row, proxy)
        self.table.resizeColumnsToContents()

    def _populate_row(self, row: int, proxy: Proxy) -> None:
        def item(text: str, alignment: QtCore.Qt.AlignmentFlag = QtCore.Qt.AlignmentFlag.AlignLeft) -> QtWidgets.QTableWidgetItem:
            cell = QtWidgets.QTableWidgetItem(text)
            cell.setData(QtCore.Qt.ItemDataRole.UserRole, proxy.id)
            cell.setTextAlignment(alignment | QtCore.Qt.AlignmentFlag.AlignVCenter)
            return cell

        host_port = proxy.server.split("://", 1)[-1]
        last_seen = ""
        if proxy.last_ip:
            last_seen = proxy.last_ip
            if proxy.last_check:
                dt = datetime.fromtimestamp(proxy.last_check)
                last_seen += f" ({dt.strftime('%Y-%m-%d %H:%M:%S')})"

        values = [
            item(proxy.id),
            item(proxy.label),
            item(proxy.type.upper(), QtCore.Qt.AlignmentFlag.AlignCenter),
            item(host_port),
            item(proxy.username or "", QtCore.Qt.AlignmentFlag.AlignCenter),
            item(proxy.geo or "", QtCore.Qt.AlignmentFlag.AlignCenter),
            item("Да" if proxy.sticky else "Нет", QtCore.Qt.AlignmentFlag.AlignCenter),
            item(str(proxy.max_concurrent), QtCore.Qt.AlignmentFlag.AlignCenter),
            item("Да" if proxy.enabled else "Нет", QtCore.Qt.AlignmentFlag.AlignCenter),
            item(last_seen),
        ]

        for column, cell in enumerate(values):
            self.table.setItem(row, column, cell)

    def _current_proxy(self) -> Optional[Proxy]:
        row = self.table.currentRow()
        if row < 0:
            return None
        cell = self.table.item(row, 0)
        if not cell:
            return None
        proxy_id = cell.data(QtCore.Qt.ItemDataRole.UserRole)
        return self.manager.get(proxy_id)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #
    def add_proxy(self) -> None:
        dialog = ProxyEditorDialog(parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            proxy = dialog.proxy()
            if proxy:
                self.manager.upsert(proxy)
                self.reload()
                self._select_proxy(proxy.id)

    def edit_selected(self) -> None:
        proxy = self._current_proxy()
        if not proxy:
            QtWidgets.QMessageBox.information(self, "Proxy Manager", "Выберите прокси для редактирования.")
            return
        dialog = ProxyEditorDialog(proxy, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = dialog.proxy()
            if updated:
                self.manager.upsert(updated)
                self.reload()
                self._select_proxy(updated.id)

    def delete_selected(self) -> None:
        proxy = self._current_proxy()
        if not proxy:
            QtWidgets.QMessageBox.information(self, "Proxy Manager", "Выберите прокси для удаления.")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Удаление прокси",
            f"Удалить прокси «{proxy.label}»?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if confirm == QtWidgets.QMessageBox.StandardButton.Yes:
            self.manager.delete(proxy.id)
            self.reload()

    def test_selected(self) -> None:
        proxy = self._current_proxy()
        if not proxy:
            QtWidgets.QMessageBox.information(self, "Proxy Manager", "Выберите прокси для проверки.")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            result = self.manager.test_proxy(proxy)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if result.get("ok"):
            QtWidgets.QMessageBox.information(
                self,
                "Результат проверки",
                f"✅ Прокси работает\n\nIP: {result.get('ip', '')}\nЗадержка: {result.get('latency_ms', '—')} мс",
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Результат проверки",
                f"❌ Прокси не ответил.\n\nПричина: {result.get('error', '')}",
            )
        self.reload()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _select_proxy(self, proxy_id: str) -> None:
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell and cell.data(QtCore.Qt.ItemDataRole.UserRole) == proxy_id:
                self.table.selectRow(row)
                self.table.scrollToItem(cell, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
                break


__all__ = ["ProxyManagerDialog"]
