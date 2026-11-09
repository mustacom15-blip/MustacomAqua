from __future__ import annotations
import shutil
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox,QComboBox,QFileDialog,QFormLayout,QGroupBox,QHBoxLayout,QLabel,QLineEdit,
    QPushButton,QSpinBox,QTabWidget,QVBoxLayout,QWidget)

from ..database import now
from ..paths import data_dir,resource_dir
from ..services import AppError
from .dialogs import FormDialog
from .widgets import Page,PagedTable,error,info,run_action


class SettingsPage(Page):
    def __init__(self,context):
        super().__init__("إعدادات الجمعية والتطبيق","بيانات الجمعية مستقلة تماماً عن بيانات المطور. شعار الجمعية اختياري ويمكن استبداله هنا.")
        self.context=context;self.db=context.db;self.user=context.user;self.s=self.db.one  # convenience
        self.settings={r["key"]:r["value"] or "" for r in self.db.query("SELECT * FROM settings")}
        self.tabs=QTabWidget();self.layout.addWidget(self.tabs);self.controls={}
        self._association_tab();self._billing_tab();self._areas_tab();self._system_tab()
        self.button("حفظ الإعدادات",self.save,True);self.toolbar.addStretch()

    def _line(self,form,key,label,password=False):
        w=QLineEdit(self.settings.get(key,""));w.setEchoMode(QLineEdit.EchoMode.Password if password else QLineEdit.EchoMode.Normal);self.controls[key]=w;form.addRow(label,w);return w

    def _association_tab(self):
        tab=QWidget();form=QFormLayout(tab)
        for key,label in (("association_name","اسم الجمعية *"),("association_phone","هاتف الجمعية"),("association_email","بريد الجمعية"),("association_address","عنوان الجمعية")):self._line(form,key,label)
        logo=QWidget();h=QHBoxLayout(logo);h.setContentsMargins(0,0,0,0);self.controls["association_logo"]=QLineEdit(self.settings.get("association_logo",""));choose=QPushButton("اختيار/استبدال الشعار");clear=QPushButton("إزالة")
        def choose_logo():
            filename,_=QFileDialog.getOpenFileName(self,"شعار الجمعية",str(Path.home()),"صور (*.png *.jpg *.jpeg)")
            if filename:self.controls["association_logo"].setText(filename)
        choose.clicked.connect(choose_logo);clear.clicked.connect(lambda:self.controls["association_logo"].setText(""));h.addWidget(self.controls["association_logo"]);h.addWidget(choose);h.addWidget(clear);form.addRow("شعار الجمعية",logo)
        form.addRow("شعار المطور الثابت",QLabel("MUSTACOM SERVICES — يظهر في «حول» وتذييل الوثائق كمطور فقط، وليس كشعار للجمعية."))
        self.tabs.addTab(tab,"الجمعية")

    def _billing_tab(self):
        tab=QWidget();form=QFormLayout(tab)
        self._line(form,"currency","العملة (MAD)")
        freq=QComboBox();[freq.addItem(label,key) for key,label in (("monthly","شهري"),("bimonthly","كل شهرين"),("custom","فترة مخصصة"))];freq.setCurrentIndex(max(0,freq.findData(self.settings.get("billing_frequency"))));self.controls["billing_frequency"]=freq;form.addRow("دورية الفوترة",freq)
        for key,label in (("financial_year","السنة المالية"),("invoice_prefix","بادئة الفاتورة"),("receipt_prefix","بادئة السند"),("next_invoice","الرقم التالي للفاتورة"),("next_receipt","الرقم التالي للسند"),("payment_due_days","أيام استحقاق الفاتورة"),("high_consumption_factor","معامل الاستهلاك المرتفع"),("zero_reading_alert_count","عدد القراءات الصفرية للتنبيه")):self._line(form,key,label)
        self.tax=QCheckBox("تفعيل الضريبة (معطلة افتراضياً)");self.tax.setChecked(self.settings.get("tax_enabled")=="1");form.addRow(self.tax)
        self._line(form,"tax_rate","نسبة الضريبة % (لا تفعل إلا بإعداد قانوني)")
        self.late=QCheckBox("تطبيق رسم التأخير المحدد في التعرفة عند وجود دين متأخر");self.late.setChecked(self.settings.get("apply_late_fee")=="1");form.addRow(self.late)
        self.tabs.addTab(tab,"الفوترة والترقيم")

    def _areas_tab(self):
        tab=QWidget();layout=QVBoxLayout(tab);tools=QHBoxLayout();layout.addLayout(tools)
        for text,fn in (("+ منطقة",self.add_area),("تعديل/تعطيل",self.edit_area)):
            b=QPushButton(text);b.clicked.connect(fn);tools.addWidget(b)
        tools.addStretch();self.areas=PagedTable(100);layout.addWidget(self.areas);self.refresh_areas();self.tabs.addTab(tab,"المناطق")

    def _system_tab(self):
        tab=QWidget();form=QFormLayout(tab)
        for key,label in (("export_folder","مجلد التصدير المفضل"),("backup_folder","مجلد النسخ الاحتياطي"),("backup_time","وقت النسخ اليومي HH:MM"),("backup_retention","عدد النسخ المحتفظ بها (0 = لا حذف)")):self._line(form,key,label)
        printers=QComboBox();printers.addItem("الطابعة الافتراضية","")
        try:
            from PySide6.QtPrintSupport import QPrinterInfo
            for p in QPrinterInfo.availablePrinters():printers.addItem(p.printerName(),p.printerName())
        except Exception:pass
        idx=printers.findData(self.settings.get("printer_name"));printers.setCurrentIndex(max(0,idx));self.controls["printer_name"]=printers;form.addRow("الطابعة",printers)
        form.addRow("قاعدة البيانات",QLabel(str(self.db.path)))
        form.addRow("اللغة",QLabel("العربية RTL. الواجهة الفرنسية الاختيارية غير مضمنة في هذا الإصدار."))
        self.tabs.addTab(tab,"النظام")

    def refresh_areas(self):
        rows=self.db.query("SELECT a.*,(SELECT COUNT(*) FROM members WHERE area_id=a.id) members FROM areas a ORDER BY name")
        self.areas.set_data(["المنطقة","نشطة","عدد الأعضاء"],[[r["name"],"نعم" if r["active"] else "لا",r["members"]] for r in rows],[r["id"] for r in rows])

    def add_area(self):
        d=FormDialog(self,"منطقة جديدة",[{"name":"name","label":"اسم المنطقة","required":True}],400)
        if d.exec():
            try:
                with self.db.transaction() as c:c.execute("INSERT INTO areas(name) VALUES(?)",(d.values()["name"],))
                self.refresh_areas()
            except Exception as exc:error(self,exc)

    def edit_area(self):
        aid=self.areas.selected_id()
        if not aid:return error(self,"اختر منطقة.")
        a=self.db.one("SELECT * FROM areas WHERE id=?",(aid,));d=FormDialog(self,"تعديل منطقة",[{"name":"name","label":"الاسم","required":True,"value":a["name"]},{"name":"active","label":"نشطة","type":"check","value":a["active"]}],400)
        if d.exec():
            v=d.values()
            with self.db.transaction() as c:c.execute("UPDATE areas SET name=?,active=? WHERE id=?",(v["name"],v["active"],aid))
            self.refresh_areas()

    def save(self):
        try:
            values={key:(w.currentData() if isinstance(w,QComboBox) else w.text()) for key,w in self.controls.items()}
            if not values["association_name"].strip():raise AppError("اسم الجمعية مطلوب.")
            for key in ("next_invoice","next_receipt","backup_retention","payment_due_days"):
                if int(values.get(key) or 0)<0:raise AppError("قيم الترقيم والاحتفاظ يجب أن تكون صحيحة موجبة.")
            logo=values.get("association_logo","")
            if logo and Path(logo).is_file() and Path(logo).parent!=data_dir():
                ext=Path(logo).suffix.lower();target=data_dir()/("association_logo"+ext);shutil.copy2(logo,target);values["association_logo"]=str(target)
            values["tax_enabled"]="1" if self.tax.isChecked() else "0";values["apply_late_fee"]="1" if self.late.isChecked() else "0"
            with self.db.transaction() as conn:
                before={r["key"]:r["value"] for r in conn.execute("SELECT * FROM settings")}
                for key,value in values.items():conn.execute("UPDATE settings SET value=? WHERE key=?",(str(value or ""),key))
                from ..services import BaseService
                BaseService.audit(conn,self.user,"تعديل إعدادات","settings",None,before,values)
            from ..printing import PrintManager
            PrintManager.printer_name=values.get("printer_name","");PrintManager.export_folder=values.get("export_folder","")
            info(self,"تم حفظ الإعدادات.");self.settings.update(values)
        except Exception as exc:error(self,exc)
