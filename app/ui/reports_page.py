from __future__ import annotations
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QComboBox,QFileDialog,QGridLayout,QGroupBox,QLabel,QLineEdit,QTextBrowser

from ..documents import DocumentService
from ..printing import PrintManager,export_excel
from ..reports import ReportService
from ..services import AppError
from .widgets import Page,area_combo,current_period,error,info,member_combo,run_action


REPORTS=[("members","الأعضاء حسب الحالة والمنطقة"),("statement","كشف حساب عضو"),("readings","القراءات والاستهلاك"),
         ("invoices","الفواتير المؤداة وغير المؤداة والملغاة"),("debts","الديون والمتأخرات"),("payments","الأداءات والسندات"),
         ("finance","الصندوق والبنك والمصاريف"),("complaints","الشكايات والصيانة"),("inventory","المخزون والمعدات"),
         ("consumption_comparison","مقارنة الاستهلاك بين فترتين"),("summary","الملخص الشهري والسنوي")]


class ReportsPage(Page):
    def __init__(self,context):
        super().__init__("التقارير والطباعة والتصدير","كل التقارير بمعاينة عربية RTL، وطباعة أو PDF أو Excel. اختر المرشحات ثم اضغط «إنشاء التقرير».")
        self.context=context;self.db=context.db;self.user=context.user;self.report=None
        filters=QGroupBox("التقرير والمرشحات");grid=QGridLayout(filters);self.layout.insertWidget(2,filters)
        self.type=QComboBox();[self.type.addItem(label,key) for key,label in REPORTS]
        self.period=QLineEdit(current_period(self.db));self.period2=QLineEdit();self.period2.setPlaceholderText("الفترة الثانية")
        self.area=area_combo(self.db);self.member=member_combo(self.db)
        self.status=QComboBox();self.status.addItem("الكل","");[self.status.addItem(label,key) for key,label in (("active","نشط"),("suspended","معلق"),("withdrawn","منسحب"),("issued","صادرة"),("paid","مؤداة بالكامل"),("unpaid","غير مؤداة كلياً/جزئياً"),("cancelled","ملغاة"),("open","مفتوحة"),("completed","منجزة"))]
        self.date_from=QLineEdit(date.today().replace(day=1).isoformat());self.date_to=QLineEdit(date.today().isoformat())
        self.method=QComboBox();self.method.addItem("كل طرق الأداء","");[self.method.addItem(v,k) for k,v in (("cash","نقداً"),("cheque","شيك"),("transfer","تحويل"))]
        self.user_filter=QComboBox();self.user_filter.addItem("كل المستخدمين",None)
        for u in self.db.query("SELECT id,full_name FROM users ORDER BY full_name"):self.user_filter.addItem(u["full_name"],u["id"])
        self.account=QComboBox();self.account.addItem("كل الحسابات",None)
        for a in self.db.query("SELECT id,name FROM accounts"):self.account.addItem(a["name"],a["id"])
        self.year=QLineEdit(str(date.today().year));self.year.setMaximumWidth(75)
        widgets=[("نوع التقرير",self.type),("الفترة",self.period),("فترة المقارنة",self.period2),("المنطقة",self.area),("العضو",self.member),("الحالة",self.status),
                 ("من تاريخ",self.date_from),("إلى تاريخ",self.date_to),("طريقة الأداء",self.method),("المستخدم",self.user_filter),("الحساب",self.account),("السنة",self.year)]
        for i,(label,w) in enumerate(widgets):grid.addWidget(QLabel(label),(i//4)*2,i%4);grid.addWidget(w,(i//4)*2+1,i%4)
        self.button("إنشاء التقرير",self.build,True);self.button("معاينة الطباعة",self.preview);self.button("PDF",self.pdf);self.button("Excel",self.excel);self.toolbar.addStretch()
        self.browser=QTextBrowser();self.layout.addWidget(self.browser);self.build()

    def filters(self):
        return {"period":self.period.text().strip(),"period2":self.period2.text().strip(),"area_id":self.area.currentData(),"member_id":self.member.currentData(),
                "status":self.status.currentData(),"date_from":self.date_from.text().strip(),"date_to":self.date_to.text().strip(),"method":self.method.currentData(),
                "user_id":self.user_filter.currentData(),"account_id":self.account.currentData(),"year":self.year.text().strip()}

    def build(self):
        try:
            self.report=ReportService(self.db).build(self.type.currentData(),self.filters())
            self.browser.setHtml(DocumentService(self.db).report_html(self.report))
        except Exception as exc:self.report=None;error(self,exc)

    def preview(self):
        if self.report:PrintManager.preview(self,DocumentService(self.db).report_html(self.report),self.report.title)

    def pdf(self):
        if not self.report:return error(self,"أنشئ التقرير أولاً.")
        name={"members":"members","statement":"statement","readings":"readings","invoices":"invoices","debts":"debts","payments":"payments","finance":"finance","complaints":"complaints","inventory":"inventory","consumption_comparison":"consumption","summary":"summary"}[self.type.currentData()]
        result=PrintManager.export_pdf(self,DocumentService(self.db).report_html(self.report),self.report.title,name)
        if result:info(self,"تم حفظ PDF:\n"+str(result))

    def excel(self):
        if not self.report:return error(self,"أنشئ التقرير أولاً.")
        filename,_=QFileDialog.getSaveFileName(self,"تصدير Excel",str(Path.home()/(self.type.currentData()+".xlsx")),"Excel (*.xlsx)")
        if filename:run_action(self,lambda:export_excel(self.report,filename),"تم تصدير ملف Excel.")
