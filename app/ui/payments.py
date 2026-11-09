from __future__ import annotations
from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import (QCheckBox,QComboBox,QDateEdit,QDialog,QDialogButtonBox,QDoubleSpinBox,QFormLayout,QHBoxLayout,
    QLabel,QLineEdit,QPlainTextEdit,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget)

from ..billing import InvoiceService,PaymentService
from ..documents import DocumentService
from ..printing import PrintManager
from ..reports import METHOD_AR,STATUS_AR,money
from ..services import AppError,D
from .widgets import Page,PagedTable,account_combo,ask_reason,confirm,error,info,member_combo,run_action


class PaymentDialog(QDialog):
    def __init__(self,parent,db,member_id=None):
        super().__init__(parent);self.db=db;self.setWindowTitle("تسجيل أداء وتوزيعه على الفواتير");self.resize(800,700)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.member=member_combo(db,False);self.member.currentIndexChanged.connect(self.load_invoices)
        if member_id:
            idx=self.member.findData(member_id);self.member.setCurrentIndex(idx)
        self.payment_date=QDateEdit(QDateEdit().date().currentDate());self.payment_date.setCalendarPopup(True);self.payment_date.setDisplayFormat("yyyy-MM-dd")
        self.amount=QDoubleSpinBox();self.amount.setRange(0.01,999999999);self.amount.setDecimals(2);self.amount.valueChanged.connect(self.update_summary)
        self.method=QComboBox();[self.method.addItem(v,k) for k,v in (("cash","نقداً"),("cheque","شيك"),("transfer","تحويل بنكي"))]
        self.account=account_combo(db);self.reference=QLineEdit();self.notes=QPlainTextEdit();self.notes.setMaximumHeight(60)
        self.auto=QCheckBox("توزيع تلقائي على أقدم الديون");self.auto.setChecked(True);self.auto.stateChanged.connect(self.update_summary)
        form.addRow("العضو/العداد",self.member);form.addRow("التاريخ",self.payment_date);form.addRow("المبلغ",self.amount);form.addRow("الطريقة",self.method);form.addRow("الحساب",self.account);form.addRow("مرجع الشيك/التحويل",self.reference);form.addRow(self.auto);form.addRow("ملاحظات",self.notes)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(["الفاتورة","الفترة","الاستحقاق","المتبقي","المبلغ المخصص"]);layout.addWidget(self.table)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        box=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);box.button(QDialogButtonBox.StandardButton.Save).setText("تسجيل السند");box.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء");box.accepted.connect(self.validate);box.rejected.connect(self.reject);layout.addWidget(box)
        self.load_invoices()

    def load_invoices(self):
        mid=self.member.currentData();self.invoices=[]
        if not mid:return
        self.invoices=self.db.query("""SELECT i.*,i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0) balance FROM invoices i WHERE i.member_id=? AND i.status='issued' ORDER BY i.due_date,i.id""",(mid,))
        self.table.setRowCount(len(self.invoices))
        for i,r in enumerate(self.invoices):
            for j,v in enumerate((r["invoice_no"],r["period"],r["due_date"],f"{r['balance']:.2f}")):self.table.setItem(i,j,QTableWidgetItem(str(v)))
            spin=QDoubleSpinBox();spin.setRange(0,float(r["balance"]));spin.setDecimals(2);spin.setEnabled(not self.auto.isChecked());spin.valueChanged.connect(self.update_summary);self.table.setCellWidget(i,4,spin)
        total=sum((D(r["balance"]) for r in self.invoices),D(0));self.amount.setValue(float(total) if total>0 else 0.01);self.update_summary()

    def update_summary(self):
        if not hasattr(self,"summary"):return
        if self.auto.isChecked():
            for i in range(self.table.rowCount()):self.table.cellWidget(i,4).setEnabled(False)
            available=D(self.amount.value());allocated=D(0)
            for r in self.invoices:
                part=min(available,D(r["balance"]));allocated+=part;available-=part
        else:
            for i in range(self.table.rowCount()):self.table.cellWidget(i,4).setEnabled(True)
            allocated=sum((D(self.table.cellWidget(i,4).value()) for i in range(self.table.rowCount())),D(0))
        credit=D(self.amount.value())-allocated
        self.summary.setText(f"المخصص للفواتير: {money(allocated):.2f} MAD — الرصيد الدائن المتبقي: {money(max(credit,D(0))):.2f} MAD"+(" — تنبيه: التوزيع اليدوي أكبر من السند" if credit<0 else ""))

    def validate(self):
        if not self.member.currentData() or not self.account.currentData():return error(self,"اختر العضو والحساب.")
        if not self.auto.isChecked() and sum(self.table.cellWidget(i,4).value() for i in range(self.table.rowCount()))>self.amount.value():return error(self,"التوزيع أكبر من مبلغ السند.")
        self.accept()

    def values(self):
        allocations=None if self.auto.isChecked() else {self.invoices[i]["id"]:self.table.cellWidget(i,4).value() for i in range(self.table.rowCount()) if self.table.cellWidget(i,4).value()>0}
        return {"member_id":self.member.currentData(),"payment_date":self.payment_date.date().toString("yyyy-MM-dd"),"amount":self.amount.value(),
                "method":self.method.currentData(),"account_id":self.account.currentData(),"reference":self.reference.text(),"notes":self.notes.toPlainText()},allocations,self.auto.isChecked()


class PaymentsPage(Page):
    def __init__(self,context):
        super().__init__("الأداءات وسندات القبض","أداء كامل أو جزئي، توزيع على فاتورة أو أكثر، رصيد دائن، وسندات محفوظة لا تحذف.")
        self.context=context;self.db=context.db;self.user=context.user
        self.tabs=QTabWidget();self.layout.addWidget(self.tabs)
        tab=QWidget();layout=QVBoxLayout(tab);tools=QHBoxLayout();layout.addLayout(tools)
        self.date_from=QLineEdit(date.today().replace(day=1).isoformat());self.date_to=QLineEdit(date.today().isoformat())
        for w in (QLabel("من"),self.date_from,QLabel("إلى"),self.date_to):tools.addWidget(w)
        def b(text,fn):
            x=QPushButton(text);x.clicked.connect(fn);tools.addWidget(x);return x
        b("عرض",self.refresh);b("+ سند قبض",self.add);b("معاينة السند",self.preview);b("PDF",self.pdf);b("طباعة",self.print_receipt)
        if self.user.role=="admin":b("إلغاء موثق",self.cancel)
        tools.addStretch();self.table=PagedTable();layout.addWidget(self.table);self.tabs.addTab(tab,"السندات")
        self.refresh()

    def refresh(self):
        rows=self.db.query("""SELECT p.*,m.number,m.full_name,a.name account,COALESCE((SELECT SUM(amount) FROM payment_allocations WHERE payment_id=p.id),0) allocated,
            (SELECT COUNT(*) FROM receipt_prints WHERE payment_id=p.id) prints FROM payments p JOIN members m ON m.id=p.member_id JOIN accounts a ON a.id=p.account_id
            WHERE p.payment_date BETWEEN ? AND ? ORDER BY p.id DESC""",(self.date_from.text(),self.date_to.text()))
        self.table.set_data(["السند","التاريخ","الرقم/العداد","العضو","المبلغ","الطريقة","المرجع","الحساب","المخصص","دائن","الحالة","الطبعات"],
            [[r["receipt_no"],r["payment_date"],r["number"],r["full_name"],r["amount"],METHOD_AR.get(r["method"]),r["reference"],r["account"],r["allocated"],D(r["amount"])-D(r["allocated"]),STATUS_AR.get(r["status"]),r["prints"]] for r in rows],[r["id"] for r in rows])

    def add(self):
        if not self.user.can("payments.manage") and self.user.role!="admin":return error(self,"ليس لديك صلاحية تسجيل الأداءات.")
        d=PaymentDialog(self,self.db)
        if d.exec():
            data,allocations,auto=d.values()
            pid=run_action(self,lambda:PaymentService(self.db).record(self.user,data,allocations,auto),refresh=self.refresh)
            if pid:
                info(self,"تم تسجيل السند وترحيل المبلغ فعلياً إلى الحساب المالي.")
                if confirm(self,"هل تريد معاينة سند القبض الآن؟"):PrintManager.preview(self,DocumentService(self.db).receipt_html(pid),"سند قبض")

    def preview(self):
        pid=self.table.selected_id()
        if not pid:return error(self,"اختر سنداً.")
        PrintManager.preview(self,DocumentService(self.db).receipt_html(pid),"سند قبض")

    def pdf(self):
        pid=self.table.selected_id()
        if not pid:return error(self,"اختر سنداً.")
        p=self.db.one("SELECT receipt_no FROM payments WHERE id=?",(pid,));result=PrintManager.export_pdf(self,DocumentService(self.db).receipt_html(pid),"سند قبض",p["receipt_no"],lambda typ:PaymentService(self.db).record_print(self.user,pid,typ))
        if result:self.refresh();info(self,"تم حفظ PDF وتسجيل الطبعة.")

    def print_receipt(self):
        pid=self.table.selected_id()
        if not pid:return error(self,"اختر سنداً.")
        if PrintManager.print_direct(self,DocumentService(self.db).receipt_html(pid),"سند قبض",lambda typ:PaymentService(self.db).record_print(self.user,pid,typ)):self.refresh()

    def cancel(self):
        pid=self.table.selected_id()
        if not pid:return error(self,"اختر سنداً.")
        if not confirm(self,"سيحفظ السند وكل توزيعاته في التاريخ، وتلغى حركته المالية وتعود أرصدة الفواتير. لا يمكن حذف السند. هل تتابع؟",True):return
        reason=ask_reason(self,"سبب إلغاء سند القبض")
        if reason:run_action(self,lambda:PaymentService(self.db).cancel(self.user,pid,reason),"تم إلغاء السند مع حفظه في سجل التدقيق.",self.refresh)
