from __future__ import annotations
from datetime import date

from PySide6.QtWidgets import QCheckBox,QHBoxLayout,QLabel,QLineEdit,QPushButton,QTabWidget,QVBoxLayout,QWidget

from ..documents import DocumentService
from ..operations import OperationsService
from ..printing import PrintManager
from ..reports import ReportService,money
from .dialogs import FormDialog,ViewDialog
from .widgets import Page,PagedTable,area_combo,error,info,run_action


class DebtsPage(Page):
    def __init__(self,context):
        super().__init__("الديون والتذكيرات والتقسيط","تصفية حسب المنطقة والفترة والقيمة وعمر التأخير، مع توثيق إرسال التذكير ونتيجته.")
        self.context=context;self.db=context.db;self.user=context.user
        self.area=area_combo(self.db);self.period=QLineEdit();self.period.setPlaceholderText("كل الفترات");self.min_age=QLineEdit("0");self.min_age.setMaximumWidth(65);self.min_value=QLineEdit("0");self.min_value.setMaximumWidth(90);self.overdue=QCheckBox("المتأخرة فقط")
        for w in (self.area,QLabel("الفترة"),self.period,QLabel("أيام التأخير ≥"),self.min_age,QLabel("الدين ≥"),self.min_value,self.overdue):self.toolbar.addWidget(w)
        self.button("عرض",self.refresh,True);self.toolbar.addStretch()
        self.button("طباعة القائمة",self.print_list);self.button("تذكير للعضو",self.print_reminder);self.button("تسجيل الإرسال والنتيجة",self.record_reminder);self.button("اتفاق تقسيط",self.installments);self.button("عرض الاتفاقات",self.show_installments)
        self.table=PagedTable();self.layout.addWidget(self.table);self.refresh()

    def filters(self):return {"area_id":self.area.currentData(),"period":self.period.text().strip(),"min_age":int(self.min_age.text() or 0),"min_value":float(self.min_value.text() or 0),"overdue_only":self.overdue.isChecked()}

    def refresh(self):
        try:
            self.report=ReportService(self.db).report_debts(self.filters())
            # Debt report member IDs are recovered in display order for selection.
            ids=[]
            for row in self.report.rows:
                m=self.db.one("SELECT id FROM members WHERE number=?",(row[0],));ids.append(m[0] if m else None)
            self.table.set_data(self.report.headers,self.report.rows,ids)
        except Exception as exc:error(self,exc)

    def print_list(self):PrintManager.preview(self,DocumentService(self.db).report_html(self.report),self.report.title)

    def print_reminder(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً مديناً.")
        PrintManager.preview(self,DocumentService(self.db).reminder_html(mid),"تذكير بالأداء")

    def record_reminder(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        fields=[{"name":"reminder_date","label":"تاريخ الإرسال/التسليم","type":"date"},
                {"name":"method","label":"الطريقة","type":"combo","options":["تسليم ورقي","هاتف","رسالة SMS","واتساب","زيارة","أخرى"]},
                {"name":"invoice_id","label":"فاتورة محددة (اختياري)","type":"combo","options":[(None,"كل الديون")]+[(r["id"],r["invoice_no"]) for r in self.db.query("SELECT id,invoice_no FROM invoices WHERE member_id=? AND status='issued'",(mid,))]},
                {"name":"outcome","label":"النتيجة","value":"لم يتم الرد / وعد بالأداء / تم التسليم"},{"name":"notes","label":"ملاحظات","type":"text"}]
        d=FormDialog(self,"توثيق التذكير",fields)
        if d.exec():run_action(self,lambda:OperationsService(self.db).record_reminder(self.user,{**d.values(),"member_id":mid}),"تم توثيق التذكير ونتيجته.")

    def installments(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        fields=[{"name":"start_date","label":"أول استحقاق","type":"date"},{"name":"count","label":"عدد الأقساط","type":"int","min":2,"max":120,"value":6},
                {"name":"frequency_days","label":"الفاصل بالأيام","type":"int","min":1,"max":365,"value":30},{"name":"notes","label":"شروط وملاحظات","type":"text"}]
        d=FormDialog(self,"اتفاق تقسيط الدين الحالي",fields)
        if d.exec():
            v=d.values();run_action(self,lambda:OperationsService(self.db).create_installments(self.user,mid,v["start_date"],v["count"],v["frequency_days"],v["notes"]),"تم إنشاء جدول الأقساط.")

    def show_installments(self):
        rows=self.db.query("""SELECT i.*,m.number,m.full_name FROM installments i JOIN members m ON m.id=i.member_id ORDER BY i.id DESC""")
        body="<h2>اتفاقات التقسيط</h2>"
        for a in rows:
            body+=f"<h3>{a['number']} — {a['full_name']} — {a['total_amount']:.2f} MAD</h3><p>{a['notes'] or ''}</p><table border='1' cellspacing='0' cellpadding='5'><tr><th>الاستحقاق</th><th>المبلغ</th><th>الحالة</th></tr>"
            lines=self.db.query("SELECT * FROM installment_lines WHERE agreement_id=?",(a["id"],))
            body+="".join(f"<tr><td>{x['due_date']}</td><td>{x['amount']:.2f}</td><td>{x['status']}</td></tr>" for x in lines)+"</table>"
        ViewDialog(self,"اتفاقات التقسيط",body or "لا توجد").exec()
