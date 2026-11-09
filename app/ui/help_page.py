from __future__ import annotations
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices,QPixmap
from PySide6.QtWidgets import QHBoxLayout,QLabel,QPushButton,QTextBrowser

from ..paths import data_dir,resource_dir
from ..printing import PrintManager
from .widgets import Page


class HelpPage(Page):
    def __init__(self,context):
        super().__init__("دليل الاستخدام ومعلومات التطبيق","إعداد أول مرة، سير العمل اليومي، النسخ الاحتياطي، والصلاحيات.")
        self.context=context
        self.browser=QTextBrowser();self.layout.addWidget(self.browser)
        help_path=resource_dir()/"help"/"guide_ar.html"
        if help_path.exists():self.html=help_path.read_text(encoding="utf-8")
        else:self.html="<h1>MUSTACOM AQUA GESTION PRO</h1><p>راجع ملف README_AR.md.</p>"
        self.browser.setHtml(self.html)
        self.button("طباعة الدليل",lambda:PrintManager.preview(self,self.html,"دليل الاستخدام"));self.button("فتح مجلد البيانات",lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))));self.toolbar.addStretch()
        about=QLabel("الإصدار 1.0.0 — يعمل دون إنترنت بعد التثبيت\nالمطور: MUSTACOM SERVICES\nالهاتف: 0708785153 — البريد: contact@mustacom.com\nالعربية RTL • SQLite • Windows 10/11")
        about.setWordWrap(True);self.layout.addWidget(about)
        logo=QLabel();logo.setAlignment(Qt.AlignmentFlag.AlignCenter);pix=QPixmap(str(resource_dir()/"assets"/"mustacom_logo.png"))
        if not pix.isNull():logo.setPixmap(pix.scaledToWidth(300,Qt.TransformationMode.SmoothTransformation));self.layout.addWidget(logo)
