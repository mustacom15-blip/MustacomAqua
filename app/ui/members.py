from __future__ import annotations
import html
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox,QFileDialog,QHBoxLayout,QLabel,QLineEdit,QPushButton

from ..documents import DocumentService
from ..printing import PrintManager
from ..reports import ReportService, STATUS_AR
from ..services import AppError, MemberService, money
from .dialogs import FormDialog, ViewDialog
from .widgets import Page,PagedTable,area_combo,ask_reason,confirm,error,info,run_action


class MembersPage(Page):
    def __init__(self,context):
        super().__init__("إدارة الأعضاء","رقم العضوية هو رقم العداد نفسه في كل السجلات. البحث والطباعة والكشوف والمرفقات والأرشفة الآمنة.")
        self.context=context;self.db=context.db;self.user=context.user
        self.search=QLineEdit();self.search.setPlaceholderText("رقم، اسم، هاتف، عنوان…");self.search.setMinimumWidth(230);self.search.returnPressed.connect(self.refresh)
        self.area=area_combo(self.db);self.status=QComboBox();self.status.addItem("كل الحالات","");[self.status.addItem(v,k) for k,v in (("active","نشط"),("suspended","معلق"),("withdrawn","منسحب"))]
        self.toolbar.addWidget(self.search);self.toolbar.addWidget(self.area);self.toolbar.addWidget(self.status);self.button("بحث",self.refresh,True)
        self.toolbar.addStretch()
        if self.user.can("members.manage") or self.user.role=="admin":
            self.button("+ عضو جديد",self.add)
            self.button("تعديل",self.edit)
            self.button("حذف / أرشفة",self.delete,False,True)
            self.button("إرفاق وثيقة",self.attach)
        self.table=PagedTable();self.layout.addWidget(self.table)
        if self.user.role not in ("reader","reception"):self.table.rowActivated.connect(lambda _:self.history())
        bottom=QHBoxLayout();self.layout.addLayout(bottom)
        actions=[]
        if self.user.role not in ("reader","reception"):
            actions += [("السجل الكامل",self.history),("كشف الحساب",self.statement)]
        if self.user.can("print") or self.user.role=="admin":actions.append(("بطاقة العضو",self.member_card))
        if self.user.can("export") or self.user.role=="admin":actions.append(("تصدير القائمة Excel",self.export))
        for text,callback in actions:
            b=QPushButton(text);b.clicked.connect(callback);bottom.addWidget(b)
        bottom.addStretch();self.refresh()

    def _filters(self):
        where,params=["m.archived=0"],[]
        term=self.search.text().strip()
        if term:
            where.append("(m.number LIKE ? OR m.full_name LIKE ? OR m.phone LIKE ? OR m.address LIKE ? OR m.national_id LIKE ?)");params += [f"%{term}%"]*5
        if self.area.currentData():where.append("m.area_id=?");params.append(self.area.currentData())
        if self.status.currentData():where.append("m.status=?");params.append(self.status.currentData())
        return " AND ".join(where),params

    def refresh(self):
        where,params=self._filters()
        rows=self.db.query(f"""SELECT m.*,a.name area,(SELECT COUNT(*) FROM invoices i WHERE i.member_id=m.id AND i.status='issued') invoices,
            (SELECT COALESCE(SUM(i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0)),0)
             FROM invoices i WHERE i.member_id=m.id AND i.status='issued') debt
            FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE {where} ORDER BY m.number""",tuple(params))
        self.rows=rows
        if self.user.role in ("reader","reception"):
            self.table.set_data(["الرقم/العداد","الاسم","الهاتف","المنطقة","الحالة","تاريخ العضوية"],[[r["number"],r["full_name"],r["phone"],r["area"],STATUS_AR.get(r["status"]),r["membership_date"]] for r in rows],[r["id"] for r in rows])
        else:
            self.table.set_data(["الرقم/العداد","الاسم","الهاتف","المنطقة","الحالة","تاريخ العضوية","الفواتير","الدين"],[[r["number"],r["full_name"],r["phone"],r["area"],STATUS_AR.get(r["status"]),r["membership_date"],r["invoices"],f"{money(r['debt']):.2f}"] for r in rows],[r["id"] for r in rows])

    def _dialog(self,record=None):
        r=dict(record) if record else {}
        fields=[{"name":"number","label":"رقم العضو/العداد","required":True,"value":r.get("number")},
                {"name":"full_name","label":"الاسم الكامل","required":True,"value":r.get("full_name")},
                {"name":"phone","label":"الهاتف","value":r.get("phone")},{"name":"national_id","label":"رقم البطاقة الوطنية (اختياري)","value":r.get("national_id")},
                {"name":"area_id","label":"المنطقة","type":"combo","value":r.get("area_id"),"options":[(None,"—")]+[(x["id"],x["name"]) for x in self.db.query("SELECT * FROM areas WHERE active=1")]},
                {"name":"address","label":"العنوان","value":r.get("address")},{"name":"membership_date","label":"تاريخ العضوية","type":"date","required":True,"value":r.get("membership_date")},
                {"name":"status","label":"الحالة","type":"combo","value":r.get("status","active"),"options":[("active","نشط"),("suspended","معلق"),("withdrawn","منسحب")]},
                {"name":"meter_install_date","label":"تاريخ تركيب العداد","type":"date","value":r.get("meter_install_date")},
                {"name":"meter_location","label":"موقع العداد","value":r.get("meter_location")},
                {"name":"initial_reading","label":"القراءة الأولية","type":"float","value":r.get("initial_reading",0)},
                {"name":"initial_reading_date","label":"تاريخ القراءة الأولية","type":"date","value":r.get("initial_reading_date")},
                {"name":"notes","label":"ملاحظات","type":"text","value":r.get("notes")}]
        return FormDialog(self,"تعديل العضو" if record else "عضو جديد",fields)

    def add(self):
        dialog=self._dialog()
        if dialog.exec():
            run_action(self,lambda:MemberService(self.db).save(self.user,dialog.values()),"تمت إضافة العضو.",self.refresh)

    def edit(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً من القائمة.")
        record=MemberService(self.db).get_member(mid);dialog=self._dialog(record)
        if dialog.exec():
            reason=""
            if dialog.values()["number"]!=record["number"] or float(dialog.values()["initial_reading"])!=float(record["initial_reading"]):reason=ask_reason(self,"توثيق تغيير الرقم أو القراءة الأولية")
            if reason is None:return
            run_action(self,lambda:MemberService(self.db).save(self.user,dialog.values(),mid,reason),"تم حفظ بيانات العضو.",self.refresh)

    def delete(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        m=MemberService(self.db).get_member(mid)
        counts=self.db.one("""SELECT (SELECT COUNT(*) FROM readings WHERE member_id=?) r,(SELECT COUNT(*) FROM invoices WHERE member_id=?) i,
            (SELECT COUNT(*) FROM payments WHERE member_id=?) p,(SELECT COUNT(*) FROM complaints WHERE member_id=?) c""",(mid,)*4)
        linked=sum(counts)>0
        consequence=("له سجلات مرتبطة. لن تحذف أي فاتورة أو قراءة أو أداء أو شكاية؛ سيصبح منسحباً ومؤرشفاً مع حفظ التاريخ المحاسبي كاملاً." if linked else "لا توجد سجلات مرتبطة؛ سيحذف نهائياً مع مرفقاته بعد التأكيد.")
        if not confirm(self,f"العضو: {m['full_name']}\nالرقم/العداد: {m['number']}\nقراءات {counts['r']}، فواتير {counts['i']}، أداءات {counts['p']}، شكايات {counts['c']}.\n{consequence}\nهل تريد المتابعة؟",True):return
        reason=ask_reason(self)
        if not reason:return
        result=run_action(self,lambda:MemberService(self.db).delete_or_archive(self.user,mid,reason),refresh=self.refresh)
        if result:info(self,"تمت الأرشفة مع حفظ التاريخ." if result=="archived" else "تم الحذف النهائي للعضو الذي لا يملك سجلات.")

    def history(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        m=MemberService(self.db).get_member(mid)
        sections=[f"<h2>{html.escape(m['full_name'])} — {html.escape(m['number'])}</h2><p>{html.escape(m['phone'] or '')} — {html.escape(m['area_name'] or '')}</p>"]
        queries=[("القراءات","SELECT period الفترة,reading_date التاريخ,previous_reading السابقة,current_reading الحالية,consumption الاستهلاك,status الحالة,correction_reason سبب_التصحيح FROM readings WHERE member_id=? ORDER BY id DESC"),
                 ("الفواتير","SELECT invoice_no الرقم,period الفترة,total_due المجموع,status الحالة,issue_date الإصدار,due_date الاستحقاق FROM invoices WHERE member_id=? ORDER BY id DESC"),
                 ("الأداءات","SELECT receipt_no السند,payment_date التاريخ,amount المبلغ,method الطريقة,status الحالة FROM payments WHERE member_id=? ORDER BY id DESC"),
                 ("الشكايات","SELECT complaint_no الرقم,reported_date التاريخ,complaint_type النوع,description الوصف,status الحالة,assigned_to المسؤول FROM complaints WHERE member_id=? ORDER BY id DESC"),
                 ("تاريخ تغيير الرقم","SELECT old_number القديم,new_number الجديد,reason السبب,username المستخدم,changed_at التاريخ FROM member_number_history WHERE member_id=? ORDER BY id DESC"),
                 ("أحداث العداد","SELECT event_type النوع,event_date التاريخ,old_reading القراءة_القديمة,new_reading القراءة_الجديدة,reason السبب,technician التقني FROM meter_events WHERE member_id=? ORDER BY id DESC")]
        for title,sql in queries:
            rows=self.db.query(sql,(mid,));sections.append(f"<h3>{title} ({len(rows)})</h3>")
            if rows:
                sections.append("<table border='1' cellspacing='0' cellpadding='5' width='100%'><tr>"+"".join(f"<th>{html.escape(k)}</th>" for k in rows[0].keys())+"</tr>")
                for r in rows:sections.append("<tr>"+"".join(f"<td>{html.escape(str(r[k] or ''))}</td>" for k in r.keys())+"</tr>")
                sections.append("</table>")
        docs=self.db.query("SELECT * FROM member_documents WHERE member_id=?",(mid,));sections.append("<h3>المرفقات</h3><ul>"+"".join(f"<li>{html.escape(d['original_name'])}</li>" for d in docs)+"</ul>")
        ViewDialog(self,"السجل الكامل للعضو","".join(sections)).exec()

    def member_card(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        PrintManager.preview(self,DocumentService(self.db).member_card_html(mid),"بطاقة عضو")

    def statement(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        report=ReportService(self.db).report_statement({"member_id":mid});PrintManager.preview(self,DocumentService(self.db).report_html(report),report.title)

    def attach(self):
        mid=self.table.selected_id()
        if not mid:return error(self,"اختر عضواً.")
        filename,_=QFileDialog.getOpenFileName(self,"إرفاق وثيقة أو صورة",str(Path.home()),"وثائق وصور (*.pdf *.png *.jpg *.jpeg);;كل الملفات (*)")
        if filename:
            result=run_action(self,lambda:MemberService(self.db).add_document(self.user,mid,filename),"تم حفظ المرفق داخل مجلد بيانات التطبيق وإدراجه في النسخ الاحتياطي.")
            if result:QDesktopServices.openUrl(QUrl.fromLocalFile(result))

    def export(self):
        from ..printing import export_excel
        from ..reports import ReportResult
        report=ReportResult("قائمة الأعضاء",self.table.headers,self.table.rows)
        filename,_=QFileDialog.getSaveFileName(self,"تصدير Excel","members.xlsx","Excel (*.xlsx)")
        if filename:run_action(self,lambda:export_excel(report,filename),"تم تصدير Excel.")
