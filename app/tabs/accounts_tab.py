# -*- coding: utf-8 -*-
"""Вкладка "Аккаунты" - таблица аккаунтов с кнопками управления."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
)
from PySide6.QtCore import Qt


class AccountsTab(QWidget):
    """Вкладка "Аккаунты" с таблицей и кнопками управления."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Создание интерфейса вкладки Аккаунты."""
        layout = QVBoxLayout(self)

        # Кнопки управления аккаунтами
        buttons_layout = QHBoxLayout()

        self.add_btn = QPushButton("➕ Добавить")
        self.add_btn.clicked.connect(self.add_account)
        buttons_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ Изменить")
        self.edit_btn.clicked.connect(self.edit_account)
        buttons_layout.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("🗑️ Удалить")
        self.delete_btn.clicked.connect(self.delete_account)
        buttons_layout.addWidget(self.delete_btn)

        self.import_btn = QPushButton("📥 Импорт…")
        self.import_btn.clicked.connect(self.import_accounts)
        buttons_layout.addWidget(self.import_btn)

        buttons_layout.addStretch()

        self.refresh_btn = QPushButton("🔄 Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons_layout.addWidget(self.refresh_btn)

        layout.addLayout(buttons_layout)

        # Кнопки авторизации и браузера
        auth_layout = QHBoxLayout()

        self.login_btn = QPushButton("🔐 Войти")
        self.login_btn.clicked.connect(self.login_account)
        auth_layout.addWidget(self.login_btn)

        self.auto_login_btn = QPushButton("🤖 Автологин")
        self.auto_login_btn.clicked.connect(self.auto_login)
        auth_layout.addWidget(self.auto_login_btn)

        self.login_all_btn = QPushButton("🔐 Войти во все")
        self.login_all_btn.clicked.connect(self.login_all)
        auth_layout.addWidget(self.login_all_btn)

        self.proxy_manager_btn = QPushButton("🎭 Прокси-менеджер")
        self.proxy_manager_btn.clicked.connect(self.open_proxy_manager)
        auth_layout.addWidget(self.proxy_manager_btn)

        layout.addLayout(auth_layout)

        # Кнопки управления браузером
        browser_layout = QHBoxLayout()

        self.open_browsers_btn = QPushButton("🌐 Открыть браузеры")
        self.open_browsers_btn.clicked.connect(self.open_browsers)
        browser_layout.addWidget(self.open_browsers_btn)

        self.browser_status_btn = QPushButton("⚙️ Состояние")
        self.browser_status_btn.clicked.connect(self.browser_status)
        browser_layout.addWidget(self.browser_status_btn)

        self.refresh_browsers_btn = QPushButton("🔄 Обновить")
        self.refresh_browsers_btn.clicked.connect(self.refresh_browsers)
        browser_layout.addWidget(self.refresh_browsers_btn)

        self.close_browsers_btn = QPushButton("❌ Закрыть")
        self.close_browsers_btn.clicked.connect(self.close_browsers)
        browser_layout.addWidget(self.close_browsers_btn)

        layout.addLayout(browser_layout)

        # Таблица аккаунтов
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Аккаунт",
            "Статус",
            "Авторизация",
            "Профиль",
            "Прокси",
            "Заметки",
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        self.table.itemDoubleClicked.connect(self.edit_account)

        layout.addWidget(self.table)

        # Заглушка данных для демонстрации
        self.load_demo_data()

    def load_demo_data(self):
        """Загрузка демо-данных для демонстрации интерфейса."""
        demo_accounts = [
            ["dsmirnov", "Готов", "Не заполнен", "C:/Yandex/profiles/dsmirnov", "77.73.1.1:8080", "Основной аккаунт"],
            ["kuznepetya", "Готов", "Не заполнен", "C:/Yandex/profiles/kuznepetya", "77.73.1.2:8080", "Второй аккаунт"],
            ["ivanov", "Ошибка", "Не заполнен", "C:/Yandex/profiles/ivanov", "77.73.1.3:8080", "Тестовый"],
        ]

        self.table.setRowCount(len(demo_accounts))
        for row, account in enumerate(demo_accounts):
            for col, value in enumerate(account):
                item = QTableWidgetItem(value)
                if col in (0, 1, 2, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

    def add_account(self):
        """Добавить новый аккаунт."""
        print("Добавление нового аккаунта")
        QMessageBox.information(self, "Аккаунты", "Функция добавления аккаунта (заглушка)")

    def edit_account(self):
        """Изменить выбранный аккаунт."""
        print("Изменение аккаунта")
        QMessageBox.information(self, "Аккаунты", "Функция изменения аккаунта (заглушка)")

    def delete_account(self):
        """Удалить выбранный аккаунт."""
        print("Удаление аккаунта")
        QMessageBox.information(self, "Аккаунты", "Функция удаления аккаунта (заглушка)")

    def import_accounts(self):
        """Импорт аккаунтов."""
        print("Импорт аккаунтов")
        QMessageBox.information(self, "Аккаунты", "Функция импорта аккаунтов (заглушка)")

    def refresh(self):
        """Обновить список аккаунтов."""
        print("Обновление списка аккаунтов")
        QMessageBox.information(self, "Аккаунты", "Функция обновления списка (заглушка)")

    def login_account(self):
        """Войти в выбранный аккаунт."""
        print("Вход в аккаунт")
        QMessageBox.information(self, "Аккаунты", "Функция входа в аккаунт (заглушка)")

    def auto_login(self):
        """Автоматический вход."""
        print("Автоматический вход")
        QMessageBox.information(self, "Аккаунты", "Функция автологина (заглушка)")

    def login_all(self):
        """Войти во все аккаунты."""
        print("Вход во все аккаунты")
        QMessageBox.information(self, "Аккаунты", "Функция входа во все аккаунты (заглушка)")

    def open_proxy_manager(self):
        """Открыть прокси-менеджер."""
        print("Открытие прокси-менеджера")
        QMessageBox.information(self, "Аккаунты", "Функция прокси-менеджера (заглушка)")

    def open_browsers(self):
        """Открыть браузеры."""
        print("Открытие браузеров")
        QMessageBox.information(self, "Аккаунты", "Функция открытия браузеров (заглушка)")

    def browser_status(self):
        """Показать состояние браузера."""
        print("Состояние браузера")
        QMessageBox.information(self, "Аккаунты", "Функция состояния браузера (заглушка)")

    def refresh_browsers(self):
        """Обновить браузеры."""
        print("Обновление браузеров")
        QMessageBox.information(self, "Аккаунты", "Функция обновления браузеров (заглушка)")

    def close_browsers(self):
        """Закрыть браузеры."""
        print("Закрытие браузеров")
        QMessageBox.information(self, "Аккаунты", "Функция закрытия браузеров (заглушка)")