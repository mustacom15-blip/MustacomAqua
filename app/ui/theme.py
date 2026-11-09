from __future__ import annotations
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

STYLE = """
* { font-family: 'Tahoma','Arial'; font-size: 10pt; }
QMainWindow,QDialog,QWidget { background:#f3f6f8; color:#1c2a33; }
QWidget#Sidebar { background:#102f43; }
QWidget#Sidebar QLabel { color:white; background:transparent; }
QLabel#Brand { font-size:16pt; font-weight:bold; color:#f7bd2b; }
QLabel#SubBrand { font-size:8pt; color:#c8d8e2; }
QPushButton { background:#ffffff; border:1px solid #c5d1d7; border-radius:6px; padding:7px 13px; min-height:20px; }
QPushButton:hover { background:#eaf3f5; border-color:#24717a; }
QPushButton:pressed { background:#d9e9ec; }
QPushButton:disabled { color:#95a1a8; background:#e9edef; }
QPushButton[primary="true"] { background:#176b73; color:white; border-color:#176b73; font-weight:bold; }
QPushButton[primary="true"]:hover { background:#10565e; }
QPushButton[danger="true"] { background:#a53b3b; color:white; border-color:#a53b3b; }
QPushButton[nav="true"] { text-align:right; color:#e9f1f5; background:transparent; border:0; padding:10px 14px; font-size:10pt; }
QPushButton[nav="true"]:hover { background:#19465d; }
QPushButton[nav="true"]:checked { background:#f7bd2b; color:#102f43; font-weight:bold; border-right:4px solid white; }
QLineEdit,QComboBox,QDateEdit,QDoubleSpinBox,QSpinBox,QPlainTextEdit,QTextEdit { background:white; border:1px solid #b9c8cf; border-radius:5px; padding:5px; selection-background-color:#24717a; }
QLineEdit:focus,QComboBox:focus,QDateEdit:focus,QDoubleSpinBox:focus,QSpinBox:focus { border:2px solid #24717a; }
QLabel#PageTitle { font-size:20pt; font-weight:bold; color:#123a54; }
QLabel#PageSubtitle { color:#637681; font-size:9pt; }
QFrame#Card { background:white; border:1px solid #dce4e8; border-radius:9px; }
QLabel#CardValue { font-size:19pt; font-weight:bold; color:#176b73; }
QLabel#CardTitle { color:#637681; font-size:9pt; }
QTableWidget,QTableView { background:white; alternate-background-color:#f1f6f8; border:1px solid #d1dce1; border-radius:5px; gridline-color:#e4eaed; }
QHeaderView::section { background:#dfeaed; color:#173d50; padding:7px; border:0; border-left:1px solid #c9d6dc; font-weight:bold; }
QTableWidget::item:selected,QTableView::item:selected { background:#bde0e2; color:#102f43; }
QTabWidget::pane { border:1px solid #cedade; background:white; }
QTabBar::tab { background:#e2eaed; padding:8px 15px; margin-left:2px; }
QTabBar::tab:selected { background:#176b73; color:white; }
QGroupBox { background:white; border:1px solid #d4dfe3; border-radius:7px; margin-top:12px; padding-top:12px; font-weight:bold; }
QGroupBox::title { subcontrol-origin:margin; right:12px; padding:0 5px; color:#176b73; }
QTextBrowser { background:white; border:1px solid #ccd9df; }
QStatusBar { background:#e5ecef; }
QToolTip { background:#102f43; color:white; border:0; padding:5px; }
QScrollBar:vertical { background:#edf2f4; width:12px; } QScrollBar::handle:vertical { background:#9db3bd; border-radius:5px; min-height:25px; }
"""

def apply_theme(app: QApplication):
    app.setFont(QFont("Tahoma",10))
    app.setStyleSheet(STYLE)
