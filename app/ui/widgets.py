from __future__ import annotations
from datetime import date
from typing import Any

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog, QCompleter)

from ..reports import STATUS_AR
from ..services import AppError


def info(parent, text: str):
    QMessageBox.information(parent,"تم بنجاح",text)


def error(parent, exc: Exception | str):
    QMessageBox.critical(parent,"تعذر تنفيذ العملية",str(exc))


def confirm(parent, text: str, dangerous: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("تأكيد العملية")
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if dangerous else QMessageBox.Icon.Question)
    yes = box.addButton("تأكيد",QMessageBox.ButtonRole.AcceptRole)
    box.addButton("رجوع",QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() == yes


def ask_reason(parent, title="سبب العملية") -> str | None:
    text,ok = QInputDialog.getMultiLineText(parent,title,"السبب (إلزامي ويحفظ في سجل التدقيق):")
    return text.strip() if ok else None


def run_action(parent, callback, success: str | None = None, refresh=None):
    try:
        result = callback()
        if success: info(parent,success)
        if refresh: refresh()
        return result
    except (AppError,ValueError) as exc:
        error(parent,exc)
    except Exception as exc:
        import sqlite3
        if isinstance(exc,sqlite3.IntegrityError):
            message=str(exc)
            if "UNIQUE" in message: error(parent,"هذا الرقم أو السجل موجود مسبقاً. تحقق من عدم التكرار.")
            elif "FOREIGN KEY" in message: error(parent,"لا يمكن تنفيذ العملية لوجود سجلات مرتبطة محمية.")
            else: error(parent,"رفضت قاعدة البيانات العملية لحماية سلامة السجلات: "+message)
            return None
        error(parent,f"حدث خطأ غير متوقع: {exc}")
    return None


class Page(QWidget):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18,14,18,14)
        self.layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        self.layout.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("PageSubtitle")
            sub.setWordWrap(True)
            self.layout.addWidget(sub)
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(7)
        self.layout.addLayout(self.toolbar)

    def button(self,text: str,callback,primary=False,danger=False) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("primary",primary)
        b.setProperty("danger",danger)
        b.clicked.connect(callback)
        self.toolbar.addWidget(b)
        return b


class Card(QFrame):
    def __init__(self,title: str,value: Any = "0",accent: str = "#176b73"):
        super().__init__()
        self.setObjectName("Card")
        self.setMinimumWidth(145)
        layout = QVBoxLayout(self)
        t = QLabel(title); t.setObjectName("CardTitle")
        self.value = QLabel(str(value)); self.value.setObjectName("CardValue"); self.value.setStyleSheet(f"color:{accent}")
        layout.addWidget(t); layout.addWidget(self.value)

    def set(self,value):
        self.value.setText(str(value))


class SortItem(QTableWidgetItem):
    def __lt__(self,other):
        a,b = self.text(),other.text()
        try:
            return float(a.replace(",","").replace("%","")) < float(b.replace(",","").replace("%",""))
        except ValueError:
            return a.localeAwareCompare(b) < 0


class PagedTable(QWidget):
    rowActivated = Signal(int)

    def __init__(self,page_size=75):
        super().__init__()
        self.page_size = page_size
        self.current_page = 0
        self.rows: list[list[Any]] = []
        self.ids: list[Any] = []
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(4)
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._activated)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        self.prev = QPushButton("السابق"); self.next = QPushButton("التالي")
        self.label = QLabel("لا توجد بيانات")
        self.prev.clicked.connect(lambda:self.set_page(self.current_page-1)); self.next.clicked.connect(lambda:self.set_page(self.current_page+1))
        controls.addWidget(self.prev); controls.addWidget(self.next); controls.addWidget(self.label); controls.addStretch()
        layout.addLayout(controls)

    def set_data(self,headers: list[str],rows: list[list[Any]],ids: list[Any] | None = None):
        self.table.setSortingEnabled(False)
        self.headers,self.rows,self.ids = headers,rows,ids or []
        self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(headers)
        self.current_page = 0
        self._fill()
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def _fill(self):
        start = self.current_page*self.page_size
        chunk = self.rows[start:start+self.page_size]
        self.table.setRowCount(len(chunk))
        for r,row in enumerate(chunk):
            for c,value in enumerate(row):
                item = SortItem("" if value is None else str(value))
                if self.ids and c==0: item.setData(Qt.ItemDataRole.UserRole,self.ids[start+r])
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r,c,item)
        pages = max(1,(len(self.rows)+self.page_size-1)//self.page_size)
        self.label.setText(f"صفحة {self.current_page+1} من {pages} — {len(self.rows)} سجل")
        self.prev.setEnabled(self.current_page>0); self.next.setEnabled(self.current_page<pages-1)

    def set_page(self,page):
        if page<0 or page*self.page_size>=len(self.rows): return
        self.table.setSortingEnabled(False); self.current_page=page; self._fill(); self.table.setSortingEnabled(True)

    def selected_id(self):
        row = self.table.currentRow()
        if row<0: return None
        item = self.table.item(row,0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _activated(self,row,col):
        rid = self.selected_id()
        if rid is not None: self.rowActivated.emit(int(rid))


def member_combo(db,include_empty=True,active_only=False) -> QComboBox:
    combo = QComboBox(); combo.setEditable(True); combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    if include_empty: combo.addItem("— اختر العضو —",None)
    where = "WHERE archived=0"+(" AND status='active'" if active_only else "")
    for r in db.query(f"SELECT id,number,full_name,phone FROM members {where} ORDER BY number"):
        combo.addItem(f"{r['number']} — {r['full_name']} — {r['phone'] or ''}",r["id"])
    combo.setCurrentIndex(0)
    return combo


def area_combo(db,include_empty=True) -> QComboBox:
    combo = QComboBox()
    if include_empty: combo.addItem("كل المناطق",None)
    for r in db.query("SELECT id,name FROM areas WHERE active=1 ORDER BY name"): combo.addItem(r["name"],r["id"])
    return combo


def account_combo(db,include_empty=True,account_type=None) -> QComboBox:
    combo=QComboBox()
    if include_empty: combo.addItem("— اختر الحساب —",None)
    sql="SELECT id,name,type FROM accounts WHERE active=1"; params=()
    if account_type: sql+=" AND type=?"; params=(account_type,)
    for r in db.query(sql+" ORDER BY type,name",params): combo.addItem(f"{r['name']} ({'صندوق' if r['type']=='cash' else 'بنك'})",r["id"])
    return combo


def iso_today(): return date.today().isoformat()
def current_period(db=None):
    today=date.today()
    if db is not None:
        row=db.one("SELECT value FROM settings WHERE key='billing_frequency'")
        frequency=row[0] if row else "monthly"
        if frequency=="bimonthly":return f"{today.year}-B{(today.month+1)//2}"
        if frequency=="custom":return today.strftime("%Y-%m")  # editable in every period filter
    return today.strftime("%Y-%m")
