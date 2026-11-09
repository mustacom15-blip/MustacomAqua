from __future__ import annotations
from datetime import date

from PySide6.QtCore import Qt,QDate
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDateEdit,QDialog,QDialogButtonBox,QDoubleSpinBox,QFormLayout,QHBoxLayout,
    QLabel,QLineEdit,QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget)

from ..billing import InvoiceService,TariffService
from ..documents import DocumentService
from ..printing import PrintManager
from ..reports import STATUS_AR,money
from ..services import AppError
from .dialogs import FormDialog
from .widgets import Page,PagedTable,area_combo,ask_reason,confirm,current_period,error,info,run_action


class TariffDialog(QDialog):
    def __init__(self,parent,db,record=None):
        super().__init__(parent);self.setWindowTitle("تعرفة وشرائح الاستهلاك");self.resize(700,620)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.name=QLineEdit(record["name"] if record else "");self.start=QDateEdit();self.start.setCalendarPopup(True);self.start.setDisplayFormat("yyyy-MM-dd")
        self.end=QDateEdit();self.end.setCalendarPopup(True);self.end.setDisplayFormat("yyyy-MM-dd");self.has_end=QCheckBox("تاريخ نهاية محدد")
        self.fixed=QDoubleSpinBox();self.fixed.setRange(0,9999999);self.fixed.setDecimals(2)
        self.late=QDoubleSpinBox();self.late.setRange(0,9999999);self.late.setDecimals(2)
        self.active=QCheckBox("نشطة");self.active.setChecked(True)
        if record:
            self.start.setDate(QDate.fromString(record["start_date"],"yyyy-MM-dd"))
            self.fixed.setValue(record["fixed_fee"]);self.late.setValue(record["late_fee"]);self.active.setChecked(bool(record["active"]))
            if record["end_date"]:self.has_end.setChecked(True);self.end.setDate(QDate.fromString(record["end_date"],"yyyy-MM-dd"))
        else:self.start.setDate(QDate.currentDate());self.end.setDate(QDate.currentDate())
        form.addRow("اسم التعرفة",self.name);form.addRow("تاريخ البداية",self.start);form.addRow(self.has_end,self.end);form.addRow("رسوم ثابتة",self.fixed);form.addRow("رسم تأخير اختياري",self.late);form.addRow(self.active)
        layout.addWidget(QLabel("شرائح تصاعدية متصلة تبدأ من صفر. اترك النهاية فارغة/صفراً في الشريحة الأخيرة المفتوحة."))
        self.tiers=QTableWidget(0,3);self.tiers.setHorizontalHeaderLabels(["من م³","إلى م³ (0 = مفتوح)","السعر MAD"]);layout.addWidget(self.tiers)
        buttons=QHBoxLayout();add=QPushButton("+ شريحة");remove=QPushButton("حذف شريحة");add.clicked.connect(lambda:self.add_tier());remove.clicked.connect(lambda:self.tiers.removeRow(self.tiers.currentRow()));buttons.addWidget(add);buttons.addWidget(remove);buttons.addStretch();layout.addLayout(buttons)
        tiers=db.query("SELECT * FROM tariff_tiers WHERE tariff_id=? ORDER BY sort_order",(record["id"],)) if record else []
        if tiers:
            for t in tiers:self.add_tier(t["from_qty"],t["to_qty"] or 0,t["unit_price"])
        else:self.add_tier(0,0,0)
        box=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);box.button(QDialogButtonBox.StandardButton.Save).setText("حفظ");box.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء");box.accepted.connect(self.accept);box.rejected.connect(self.reject);layout.addWidget(box)

    def add_tier(self,start=0,end=0,price=0):
        row=self.tiers.rowCount();self.tiers.insertRow(row)
        for col,value in enumerate((start,end,price)):self.tiers.setItem(row,col,QTableWidgetItem(str(value)))

    def values(self):
        tiers=[]
        for row in range(self.tiers.rowCount()):
            try:
                start=float(self.tiers.item(row,0).text());end=float(self.tiers.item(row,1).text());price=float(self.tiers.item(row,2).text())
            except Exception as exc:raise AppError(f"قيم غير صالحة في الشريحة {row+1}.") from exc
            tiers.append({"from_qty":start,"to_qty":end or None,"unit_price":price})
        return {"name":self.name.text(),"start_date":self.start.date().toString("yyyy-MM-dd"),"end_date":self.end.date().toString("yyyy-MM-dd") if self.has_end.isChecked() else None,
                "fixed_fee":self.fixed.value(),"late_fee":self.late.value(),"active":self.active.isChecked()},tiers


class BillingPage(Page):
    def __init__(self,context):
        super().__init__("التعرفات والفوترة","تصدر المسودات من قراءات معتمدة، ثم تراجع وتعتمد. لقطة التعرفة تحفظ داخل الفاتورة ولا تتأثر بالتحديثات.")
        self.context=context;self.db=context.db;self.user=context.user
        self.tabs=QTabWidget();self.layout.addWidget(self.tabs)
        self.invoices_tab=QWidget();l=QVBoxLayout(self.invoices_tab);tools=QHBoxLayout();l.addLayout(tools)
        self.period=QLineEdit(current_period(self.db));self.period.setMaximumWidth(100);self.status=QComboBox();self.status.addItem("كل الحالات","");[self.status.addItem(v,k) for k,v in (("draft","مسودة"),("issued","صادرة"),("cancelled","ملغاة"))]
        for w in (QLabel("الفترة"),self.period,self.status):tools.addWidget(w)
        def tool(text,fn,primary=False):
            b=QPushButton(text);b.setProperty("primary",primary);b.clicked.connect(fn);tools.addWidget(b);return b
        tool("عرض",self.refresh,True)
        if self.user.can("invoices.manage") or self.user.role=="admin":
            tool("إنشاء مسودات الفترة",self.generate);tool("مساهمة/رسم",self.contribution)
        if self.user.can("invoices.issue") or self.user.role=="admin":tool("اعتماد وإصدار",self.issue)
        tool("معاينة فاتورة",self.preview);tool("PDF",self.pdf)
        if self.user.role=="admin":tool("إلغاء موثق",self.cancel)
        tools.addStretch();self.table=PagedTable();l.addWidget(self.table);self.tabs.addTab(self.invoices_tab,"الفواتير")
        self.tariffs_tab=QWidget();tl=QVBoxLayout(self.tariffs_tab);tb=QHBoxLayout();tl.addLayout(tb)
        if self.user.can("tariffs.manage") or self.user.role=="admin":
            for text,fn in (("+ تعرفة جديدة",self.add_tariff),("تعديل غير مستخدمة",self.edit_tariff)):
                b=QPushButton(text);b.clicked.connect(fn);tb.addWidget(b)
        tb.addStretch();self.tariff_table=PagedTable();tl.addWidget(self.tariff_table);self.tabs.addTab(self.tariffs_tab,"التعرفات المحفوظة")
        self.refresh()

    def refresh(self):
        where,params=["1=1"],[]
        if self.period.text().strip():where.append("i.period=?");params.append(self.period.text().strip())
        if self.status.currentData():where.append("i.status=?");params.append(self.status.currentData())
        rows=self.db.query(f"""SELECT i.*,m.number,m.full_name,i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0) balance FROM invoices i JOIN members m ON m.id=i.member_id WHERE {' AND '.join(where)} ORDER BY i.id DESC""",tuple(params))
        self.table.set_data(["الفاتورة","الرقم/العداد","العضو","الفترة","الاستهلاك","الاستهلاك MAD","ثابت","إضافي","ضريبة","سابق","المجموع","المتبقي","الحالة","الاستحقاق"],
            [[r["invoice_no"],r["number"],r["full_name"],r["period"],r["consumption"],r["consumption_amount"],r["fixed_fee"],r["other_fee"]+r["late_fee"],r["tax_amount"],r["prior_balance"],r["total_due"],r["balance"],STATUS_AR.get(r["status"]),r["due_date"]] for r in rows],[r["id"] for r in rows])
        tariffs=self.db.query("SELECT t.*,(SELECT COUNT(*) FROM invoices WHERE tariff_id=t.id) used FROM tariffs t ORDER BY start_date DESC")
        self.tariff_table.set_data(["الاسم","البداية","النهاية","رسوم ثابتة","رسم تأخير","نشطة","فواتير مرتبطة","الشرائح"],
            [[t["name"],t["start_date"],t["end_date"] or "مفتوحة",t["fixed_fee"],t["late_fee"],"نعم" if t["active"] else "لا",t["used"]," / ".join(f"{x['from_qty']}–{x['to_qty'] or '∞'}: {x['unit_price']}" for x in self.db.query("SELECT * FROM tariff_tiers WHERE tariff_id=? ORDER BY sort_order",(t["id"],)))] for t in tariffs],[t["id"] for t in tariffs])

    def generate(self):
        period=self.period.text().strip()
        readings=self.db.query("""SELECT r.id FROM readings r WHERE r.period=? AND r.status='approved' AND NOT EXISTS
            (SELECT 1 FROM invoices i WHERE i.reading_id=r.id AND i.status!='cancelled') ORDER BY r.id""",(period,))
        if not readings:return error(self,"لا توجد قراءات معتمدة غير مفوترة في هذه الفترة.")
        if not confirm(self,f"سيتم إنشاء {len(readings)} مسودة فاتورة للفترة {period}. لن تسجل أي مسودة كدخل نقدي. هل تتابع؟"):return
        success=0;errors=[]
        for r in readings:
            try:InvoiceService(self.db).generate_from_reading(self.user,r["id"]);success+=1
            except Exception as exc:errors.append(f"قراءة {r['id']}: {exc}")
        self.refresh();info(self,f"أنشئت {success} مسودة. راجعها ثم اعتمد كل فاتورة.\n"+"\n".join(errors[:10]))

    def issue(self):
        iid=self.table.selected_id()
        if not iid:return error(self,"اختر مسودة فاتورة.")
        inv=self.db.one("SELECT * FROM invoices WHERE id=?",(iid,))
        if not confirm(self,f"اعتماد الفاتورة {inv['invoice_no']} بمبلغ {inv['total_due']:.2f} MAD؟ سيستخدم أي رصيد دائن متاح تلقائياً."):return
        run_action(self,lambda:InvoiceService(self.db).issue(self.user,iid),"تم إصدار الفاتورة.",self.refresh)

    def contribution(self):
        members=self.db.query("SELECT id,number,full_name FROM members WHERE archived=0 ORDER BY number")
        fields=[{"name":"member_id","label":"العضو","type":"combo","options":[(m["id"],f"{m['number']} — {m['full_name']}") for m in members]},
                {"name":"period","label":"الفترة","value":self.period.text(),"required":True},{"name":"description","label":"البيان","value":"مساهمة استثنائية","required":True},
                {"name":"amount","label":"المبلغ","type":"float","decimals":2,"min":0.01,"required":True},{"name":"issue","label":"إصدار مباشرة بعد المراجعة","type":"check","value":False}]
        d=FormDialog(self,"رسم عضوية أو مساهمة استثنائية",fields)
        if d.exec():
            v=d.values();run_action(self,lambda:InvoiceService(self.db).create_contribution(self.user,v["member_id"],v["period"],v["description"],v["amount"],v["issue"]),"تم إنشاء الفاتورة.",self.refresh)

    def preview(self):
        iid=self.table.selected_id()
        if not iid:return error(self,"اختر فاتورة.")
        PrintManager.preview(self,DocumentService(self.db).invoice_html(iid),"فاتورة")

    def pdf(self):
        iid=self.table.selected_id()
        if not iid:return error(self,"اختر فاتورة.")
        inv=self.db.one("SELECT invoice_no FROM invoices WHERE id=?",(iid,));result=PrintManager.export_pdf(self,DocumentService(self.db).invoice_html(iid),"فاتورة",inv["invoice_no"])
        if result:info(self,"تم حفظ PDF:\n"+str(result))

    def cancel(self):
        iid=self.table.selected_id()
        if not iid:return error(self,"اختر فاتورة.")
        if not confirm(self,"الإلغاء لا يحذف الفاتورة. يمنع الإلغاء عند وجود أداءات مرحلة. هل تتابع؟",True):return
        reason=ask_reason(self,"سبب إلغاء الفاتورة")
        if reason:run_action(self,lambda:InvoiceService(self.db).cancel(self.user,iid,reason),"تم إلغاء الفاتورة مع حفظ أصلها وسبب الإلغاء.",self.refresh)

    def add_tariff(self):
        d=TariffDialog(self,self.db)
        if d.exec():
            try:data,tiers=d.values();run_action(self,lambda:TariffService(self.db).save_tariff(self.user,data,tiers),"تم حفظ التعرفة.",self.refresh)
            except Exception as exc:error(self,exc)

    def edit_tariff(self):
        tid=self.tariff_table.selected_id()
        if not tid:return error(self,"اختر تعرفة.")
        d=TariffDialog(self,self.db,self.db.one("SELECT * FROM tariffs WHERE id=?",(tid,)))
        if d.exec():
            try:data,tiers=d.values();run_action(self,lambda:TariffService(self.db).save_tariff(self.user,data,tiers,tid),"تم حفظ التعرفة.",self.refresh)
            except Exception as exc:error(self,exc)
