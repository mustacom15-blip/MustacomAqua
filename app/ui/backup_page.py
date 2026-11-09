from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox,QFileDialog,QFormLayout,QGroupBox,QHBoxLayout,QLabel,QLineEdit,QPushButton,QVBoxLayout,QWidget,QApplication

from ..backup import BackupService
from ..database import now
from ..paths import data_dir
from .widgets import Page,confirm,error,info,run_action


class BackupPage(Page):
    def __init__(self,context):
        super().__init__("النسخ الاحتياطي والاستعادة والنقل","نسخة SQLite متسقة + المرفقات، تشفير AES-256 اختياري، نسخة أمان قبل الاستعادة، ولا حذف تلقائي دون سياسة احتفاظ.")
        self.context=context;self.db=context.db;self.user=context.user;self.service=BackupService(self.db)
        settings={r["key"]:r["value"] or "" for r in self.db.query("SELECT * FROM settings")}
        box=QGroupBox("نسخة فورية");form=QFormLayout(box);self.layout.addWidget(box)
        folder=QWidget();h=QHBoxLayout(folder);h.setContentsMargins(0,0,0,0);self.folder=QLineEdit(settings.get("backup_folder") or str(data_dir()/"backups"));choose=QPushButton("اختيار مجلد")
        choose.clicked.connect(self.choose_folder);h.addWidget(self.folder);h.addWidget(choose);form.addRow("مجلد النسخ",folder)
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password);form.addRow("كلمة مرور (اختياري، 8+)",self.password)
        create=QPushButton("إنشاء نسخة الآن");create.setProperty("primary",True);create.clicked.connect(self.create);form.addRow(create)
        self.latest=QLabel();self.latest.setWordWrap(True);form.addRow("آخر نسخة",self.latest)
        auto=QGroupBox("الجدولة والاحتفاظ");af=QFormLayout(auto);self.layout.addWidget(auto)
        self.auto=QCheckBox("نسخ تلقائي يومي أثناء تشغيل التطبيق (النسخ المجدولة ZIP غير مشفرة)");self.auto.setChecked(settings.get("auto_backup")=="1");af.addRow(self.auto)
        self.time=QLineEdit(settings.get("backup_time","18:00"));af.addRow("الوقت HH:MM",self.time)
        self.retention=QLineEdit(settings.get("backup_retention","0"));af.addRow("عدد النسخ المحتفظ بها (0 = بلا حذف)",self.retention)
        save=QPushButton("حفظ الجدولة");save.clicked.connect(self.save_schedule);af.addRow(save)
        actions=QHBoxLayout();self.layout.addLayout(actions)
        for text,fn in (("استعادة نسخة…",self.restore),("نسخة محمولة لنقل قاعدة البيانات…",self.portable),("فتح مجلد البيانات",self.open_data)):
            b=QPushButton(text);b.clicked.connect(fn);actions.addWidget(b)
        actions.addStretch()
        note=QLabel("النقل إلى حاسوب آخر: ثبّت التطبيق، ثم استورد النسخة من شاشة الاستعادة. لا توجد مزامنة متعددة الحواسيب؛ العمل المتزامن على أكثر من جهاز يتطلب إعداداً خادمياً إضافياً غير مضمن.")
        note.setWordWrap(True);self.layout.addWidget(note);self.layout.addStretch();self.update_latest()
        self.timer=QTimer(self);self.timer.timeout.connect(self.check_schedule);self.timer.start(60_000)

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"مجلد النسخ الاحتياطي",self.folder.text())
        if folder:self.folder.setText(folder)

    def update_latest(self):
        rows=self.db.query("SELECT key,value FROM settings WHERE key IN ('last_backup_at','last_backup_path')");s={r["key"]:r["value"] for r in rows}
        self.latest.setText((s.get("last_backup_at","لم تنشأ نسخة بعد")+"\n"+s.get("last_backup_path","")) )

    def create(self):
        result=run_action(self,lambda:self.service.create(self.user,self.folder.text(),self.password.text()),refresh=self.update_latest)
        if result:
            with self.db.transaction() as c:
                c.execute("INSERT INTO settings(key,value) VALUES('last_backup_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now(),))
                c.execute("INSERT INTO settings(key,value) VALUES('last_backup_path',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(result),))
            self.password.clear();self.update_latest();info(self,"تم إنشاء النسخة وفحص سلامتها:\n"+str(result))

    def save_schedule(self):
        try:
            datetime.strptime(self.time.text(),"%H:%M");retention=int(self.retention.text() or 0)
            if retention<0:raise ValueError
            with self.db.transaction() as c:
                for key,value in (("auto_backup","1" if self.auto.isChecked() else "0"),("backup_time",self.time.text()),("backup_retention",str(retention)),("backup_folder",self.folder.text())):
                    c.execute("UPDATE settings SET value=? WHERE key=?",(value,key))
            info(self,"حفظت الجدولة. يعمل النسخ المجدول عندما يكون التطبيق مفتوحاً.")
        except ValueError:error(self,"تحقق من الوقت HH:MM وعدد النسخ (صفر أو أكثر).")

    def check_schedule(self):
        if not self.auto.isChecked():return
        current=datetime.now();last=self.db.one("SELECT value FROM settings WHERE key='last_auto_backup_date'")
        if current.strftime("%H:%M")>=self.time.text() and (not last or last[0]!=current.date().isoformat()):
            try:
                path=self.service.create(self.user,self.folder.text(),"",True)
                with self.db.transaction() as c:
                    c.execute("INSERT INTO settings(key,value) VALUES('last_auto_backup_date',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(current.date().isoformat(),))
                    c.execute("INSERT INTO settings(key,value) VALUES('last_backup_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now(),))
                    c.execute("INSERT INTO settings(key,value) VALUES('last_backup_path',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(path),))
                self.update_latest()
            except Exception as exc:self.latest.setText("فشل النسخ التلقائي: "+str(exc))

    def restore(self):
        filename,_=QFileDialog.getOpenFileName(self,"اختيار نسخة",self.folder.text(),"نسخ MUSTACOM (*.mustabak *.zip)")
        if not filename:return
        if not confirm(self,"ستستبدل قاعدة البيانات الحالية بمحتوى النسخة. سينشئ التطبيق أولاً نسخة أمان من الوضع الحالي. أغلق النوافذ الأخرى وتأكد من النسخة. هل تتابع؟",True):return
        password=self.password.text()
        result=run_action(self,lambda:(self.service.restore(self.user,filename,password),True)[1])
        if result is not None:
            info(self,"تمت الاستعادة. سيعاد تشغيل التطبيق الآن؛ سجل الدخول من جديد.")
            QApplication.exit(20)

    def portable(self):
        filename,_=QFileDialog.getSaveFileName(self,"نسخة محمولة لقاعدة البيانات",str(Path.home()/"mustacom_aqua_portable.db"),"SQLite (*.db)")
        if filename:
            result=run_action(self,lambda:self.service.portable_copy(self.user,filename))
            if result:info(self,"تم إنشاء النسخة المحمولة. لنقل المرفقات أيضاً استخدم النسخة الاحتياطية الكاملة.\n"+str(result))

    def open_data(self):QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))
