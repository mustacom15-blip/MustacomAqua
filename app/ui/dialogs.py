from __future__ import annotations
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDateEdit,QDialog,QDialogButtonBox,QDoubleSpinBox,QFileDialog,
    QFormLayout,QHBoxLayout,QLineEdit,QPlainTextEdit,QPushButton,QScrollArea,QSpinBox,QVBoxLayout,QWidget)


class FormDialog(QDialog):
    """Validated reusable form. Field types: line,password,text,int,float,date,combo,check,file."""
    def __init__(self,parent,title: str,fields: list[dict],width=620):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(width,650)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        outer=QVBoxLayout(self)
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        content=QWidget(); self.form=QFormLayout(content); self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scroll.setWidget(content); outer.addWidget(scroll)
        self.controls={}; self.definitions={f["name"]:f for f in fields}
        for f in fields:
            control=self._control(f)
            self.controls[f["name"]]=control
            self.form.addRow(f["label"]+(" *" if f.get("required") else ""),control)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("حفظ")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _control(self,f):
        value=f.get("value")
        kind=f.get("type","line")
        if kind=="text":
            w=QPlainTextEdit(str(value or "")); w.setMaximumHeight(100); return w
        if kind in ("int","float"):
            w=QDoubleSpinBox() if kind=="float" else QSpinBox()
            w.setRange(f.get("min",0),f.get("max",999999999))
            if kind=="float": w.setDecimals(f.get("decimals",3)); w.setSingleStep(f.get("step",1)); w.setGroupSeparatorShown(False)
            w.setValue(value or 0); return w
        if kind=="date":
            w=QDateEdit(); w.setCalendarPopup(True); w.setDisplayFormat("yyyy-MM-dd")
            try: d=QDate.fromString(str(value or date.today().isoformat()),"yyyy-MM-dd")
            except Exception: d=QDate.currentDate()
            w.setDate(d if d.isValid() else QDate.currentDate()); return w
        if kind=="combo":
            w=QComboBox()
            for option in f.get("options",[]):
                if isinstance(option,(tuple,list)): w.addItem(str(option[1]),option[0])
                else: w.addItem(str(option),option)
            if value is not None:
                idx=w.findData(value)
                if idx>=0:w.setCurrentIndex(idx)
            return w
        if kind=="check":
            w=QCheckBox(f.get("text","")); w.setChecked(bool(value)); return w
        if kind=="file":
            container=QWidget(); h=QHBoxLayout(container); h.setContentsMargins(0,0,0,0)
            edit=QLineEdit(str(value or "")); edit.setPlaceholderText("اختر ملفاً…")
            browse=QPushButton("استعراض")
            def choose():
                filename,_=QFileDialog.getOpenFileName(self,"اختيار ملف",str(Path.home()),f.get("filter","كل الملفات (*)"))
                if filename:edit.setText(filename)
            browse.clicked.connect(choose); h.addWidget(edit); h.addWidget(browse)
            container.value_edit=edit; return container
        w=QLineEdit(str(value or ""))
        if kind=="password":w.setEchoMode(QLineEdit.EchoMode.Password)
        if f.get("placeholder"):w.setPlaceholderText(f["placeholder"])
        return w

    def _accept(self):
        for name,f in self.definitions.items():
            if f.get("required") and not self._value(name).strip() if isinstance(self._value(name),str) else False:
                from .widgets import error
                error(self,f"الحقل «{f['label']}» مطلوب."); return
        self.accept()

    def _value(self,name):
        w=self.controls[name]; kind=self.definitions[name].get("type","line")
        if kind=="text":return w.toPlainText().strip()
        if kind in ("int","float"):return w.value()
        if kind=="date":return w.date().toString("yyyy-MM-dd")
        if kind=="combo":return w.currentData()
        if kind=="check":return w.isChecked()
        if kind=="file":return w.value_edit.text().strip()
        return w.text().strip()

    def values(self)->dict[str,Any]:return {name:self._value(name) for name in self.controls}


class ViewDialog(QDialog):
    def __init__(self,parent,title: str,html: str):
        super().__init__(parent);self.setWindowTitle(title);self.resize(900,700)
        from PySide6.QtWidgets import QTextBrowser
        layout=QVBoxLayout(self);browser=QTextBrowser();browser.setHtml(html);layout.addWidget(browser)
        close=QPushButton("إغلاق");close.clicked.connect(self.accept);layout.addWidget(close)
