"""
Popup panel for Add button actions (like Frequency button popup)
Shows a dropdown menu panel below the button
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt


class AddActionsPopup(QWidget):
    """Popup panel with action buttons for adding phrases"""
    
    def __init__(self, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.parent_tab = parent
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Action buttons
        btn1 = QPushButton("Добавить фразы...")
        btn1.setObjectName("popupButton")
        btn1.clicked.connect(lambda: self._action(parent.on_add_phrases_dialog))
        
        btn2 = QPushButton("Загрузить из файла...")
        btn2.setObjectName("popupButton")
        btn2.clicked.connect(lambda: self._action(parent.on_load_from_file))
        
        btn3 = QPushButton("Импорт из буфера")
        btn3.setObjectName("popupButton")
        btn3.clicked.connect(lambda: self._action(parent.on_import_from_clipboard))
        
        btn4 = QPushButton("Очистить таблицу")
        btn4.setObjectName("popupButton")
        btn4.clicked.connect(lambda: self._action(parent.on_clear_table))
        
        layout.addWidget(btn1)
        layout.addWidget(btn2)
        layout.addWidget(btn3)
        layout.addWidget(btn4)
        
        # Styling
        self.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QPushButton#popupButton {
                text-align: left;
                padding: 8px 16px;
                border: none;
                background: white;
            }
            QPushButton#popupButton:hover {
                background: #f0f0f0;
            }
        """)
        
        self.setMinimumWidth(200)
    
    def _action(self, handler):
        """Execute action and close popup"""
        self.close()
        if callable(handler):
            handler()
