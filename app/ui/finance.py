from __future__ import annotations
from datetime import date
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout,QLabel,QLineEdit,QPushButton,QTabWidget,QVBoxLayout,QWidget

from ..documents import DocumentService
from ..finance import FinanceService
from ..printing import PrintManager
from ..reports import ReportService,money
from .dialogs import FormDialog
from .widgets import Card,Page,PagedTable,account_combo,ask_reason,confirm,error,info,run_action


class FinancePage(Page):
    def __init__(self,context):
        super().__init__("الصندوق والبنك والمصاريف","لا تسجل الفاتورة دخلاً. الرصيد = الافتتاحي + الأداءات والوارد − المصاريف والصادر، مع تحويلات وجلسات صندوق.")
        self.context=context;self.db=context.db;self.user=context.user
        self.cards=QHBoxLayout();self.layout.addLayout(self.cards)
        self.tabs=QTabWidget();self.layout.addWidget(self.tabs)
        self.accounts_table=PagedTable(30);self.transactions_table=PagedTable();self.expenses_table=PagedTable();self.sessions_table=PagedTable()
        self.tabs.addTab(self._with_tools(self.accounts_table,[("+ حساب",self.add_account)]),"الحسابات والأرصدة")
        self.tabs.addTab(self._with_tools(self.transactions_table,[("تحويل بين الحسابات",self.transfer),("طباعة الحركات",self.print_transactions)]),"الحركات المالية")
        self.tabs.addTab(self._with_tools(self.expenses_table,[("+ مصروف",self.add_expense),("فتح المرفق",self.open_attachment),("إلغاء مصروف",self.cancel_expense)]),"المصاريف")
        self.tabs.addTab(self._with_tools(self.sessions_table,[("فتح جلسة صندوق",self.open_session),("إغلاق ومطابقة",self.close_session)]),"جلسات الصندوق")
        self.refresh()

    def _with_tools(self,table,buttons):
        w=QWidget();l=QVBoxLayout(w);h=QHBoxLayout();l.addLayout(h)
        for text,fn in buttons:
            if fn in (self.cancel_expense,) and self.user.role!="admin":continue
            b=QPushButton(text);b.clicked.connect(fn);h.addWidget(b)
        h.addStretch();l.addWidget(table);return w

    def refresh(self):
        while self.cards.count():
            item=self.cards.takeAt(0);widget=item.widget()
            if widget:widget.deleteLater()
        with self.db.connect() as conn:
            accounts=self.db.query("SELECT * FROM accounts ORDER BY active DESC,id")
            for a in accounts:self.cards.addWidget(Card(a["name"]+(" (موقوف)" if not a["active"] else ""),f"{FinanceService.balance(conn,a['id']):,.2f} MAD","#176b73" if a["type"]=="cash" else "#315f91"))
        self.cards.addStretch()
        self.accounts_table.set_data(["الحساب","النوع","افتتاحي","نشط"],[[a["name"],"صندوق" if a["type"]=="cash" else "بنك",a["opening_balance"],"نعم" if a["active"] else "لا"] for a in accounts],[a["id"] for a in accounts])
        tx=self.db.query("""SELECT t.*,a.name account FROM transactions t JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC LIMIT 2000""")
        labels={"income":"دخل","expense":"مصروف","transfer_in":"تحويل وارد","transfer_out":"تحويل صادر","adjustment":"تسوية"}
        self.transactions_table.set_data(["الوثيقة","التاريخ","الحساب","النوع","التصنيف","البيان","المبلغ","الحالة"],[[r["txn_no"],r["transaction_date"],r["account"],labels.get(r["kind"]),r["category"],r["description"],r["amount"],r["status"]] for r in tx],[r["id"] for r in tx])
        ex=self.db.query("SELECT e.*,a.name account FROM expenses e JOIN accounts a ON a.id=e.account_id ORDER BY e.id DESC LIMIT 2000")
        self.expenses_table.set_data(["الرقم","التاريخ","التصنيف","الوصف","المبلغ","الحساب","مرفق","الحالة"],[[r["expense_no"],r["expense_date"],r["category"],r["description"],r["amount"],r["account"],"نعم" if r["attachment_path"] else "لا",r["status"]] for r in ex],[r["id"] for r in ex])
        ss=self.db.query("SELECT s.*,a.name account,u.full_name username FROM cash_sessions s JOIN accounts a ON a.id=s.account_id LEFT JOIN users u ON u.id=s.user_id ORDER BY s.id DESC")
        self.sessions_table.set_data(["الحساب","المستخدم","الفتح","افتتاحي","مقبوضات","مصاريف","متوقع","فعلي","الفرق","الحالة"],[[r["account"],r["username"],r["opened_at"],r["opening_balance"],r["expected_receipts"],r["expected_expenses"],r["expected_closing"],r["actual_closing"],r["difference"],"مفتوحة" if r["status"]=="open" else "مغلقة"] for r in ss],[r["id"] for r in ss])

    def add_account(self):
        fields=[{"name":"name","label":"اسم الحساب","required":True},{"name":"type","label":"النوع","type":"combo","options":[("cash","صندوق"),("bank","بنك")]},
                {"name":"opening_balance","label":"الرصيد الافتتاحي","type":"float","decimals":2,"min":-999999999},{"name":"active","label":"نشط","type":"check","value":True}]
        d=FormDialog(self,"حساب مالي",fields)
        if d.exec():run_action(self,lambda:FinanceService(self.db).save_account(self.user,d.values()),"تم حفظ الحساب.",self.refresh)

    def add_expense(self):
        fields=[{"name":"expense_date","label":"التاريخ","type":"date"},{"name":"amount","label":"المبلغ","type":"float","decimals":2,"min":0.01},
                {"name":"category","label":"التصنيف","type":"combo","options":["كهرباء","صيانة","أجور","معدات","نقل","ماء","إدارة","أخرى"]},
                {"name":"description","label":"الوصف","required":True},{"name":"account_id","label":"الحساب","type":"combo","options":[(a["id"],a["name"]) for a in self.db.query("SELECT * FROM accounts WHERE active=1")]},
                {"name":"attachment","label":"وثيقة داعمة (اختياري)","type":"file","filter":"وثائق وصور (*.pdf *.png *.jpg *.jpeg)"}]
        d=FormDialog(self,"تسجيل مصروف",fields)
        if d.exec():run_action(self,lambda:FinanceService(self.db).add_expense(self.user,d.values()),"تم تسجيل المصروف وترحيله من الحساب.",self.refresh)

    def transfer(self):
        accounts=[(a["id"],a["name"]) for a in self.db.query("SELECT * FROM accounts WHERE active=1")]
        fields=[{"name":"source","label":"من حساب","type":"combo","options":accounts},{"name":"destination","label":"إلى حساب","type":"combo","options":accounts},
                {"name":"amount","label":"المبلغ","type":"float","decimals":2,"min":0.01},{"name":"date","label":"التاريخ","type":"date"},{"name":"description","label":"البيان"}]
        d=FormDialog(self,"تحويل داخلي",fields)
        if d.exec():
            v=d.values();run_action(self,lambda:FinanceService(self.db).transfer(self.user,v["source"],v["destination"],v["amount"],v["date"],v["description"]),"تم التحويل كقيدين مترابطين.",self.refresh)

    def open_session(self):
        fields=[{"name":"account_id","label":"الصندوق","type":"combo","options":[(a["id"],a["name"]) for a in self.db.query("SELECT * FROM accounts WHERE active=1 AND type='cash'")]},
                {"name":"opening_balance","label":"الرصيد الفعلي عند الفتح","type":"float","decimals":2,"min":-99999999},{"name":"notes","label":"ملاحظات","type":"text"}]
        d=FormDialog(self,"فتح جلسة صندوق",fields)
        if d.exec():
            v=d.values();run_action(self,lambda:FinanceService(self.db).open_cash_session(self.user,v["account_id"],v["opening_balance"],v["notes"]),"فتحت الجلسة.",self.refresh)

    def close_session(self):
        sid=self.sessions_table.selected_id()
        if not sid:return error(self,"اختر جلسة.")
        fields=[{"name":"actual","label":"الرصيد النقدي الفعلي","type":"float","decimals":2,"min":-99999999},{"name":"notes","label":"ملاحظات المطابقة","type":"text"}]
        d=FormDialog(self,"إغلاق ومطابقة الصندوق",fields)
        if d.exec():
            v=d.values();difference=run_action(self,lambda:FinanceService(self.db).close_cash_session(self.user,sid,v["actual"],v["notes"]),refresh=self.refresh)
            if difference is not None:info(self,f"تم الإغلاق. فرق المطابقة: {difference:.2f} MAD")

    def open_attachment(self):
        eid=self.expenses_table.selected_id()
        if not eid:return error(self,"اختر مصروفاً.")
        path=self.db.one("SELECT attachment_path FROM expenses WHERE id=?",(eid,))[0]
        if not path or not Path(path).exists():return error(self,"لا يوجد مرفق أو نقل الملف من مكانه.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def cancel_expense(self):
        eid=self.expenses_table.selected_id()
        if not eid:return error(self,"اختر مصروفاً.")
        reason=ask_reason(self,"سبب إلغاء المصروف")
        if reason and confirm(self,"سيحفظ المصروف ويلغى قيده المالي. هل تتابع؟",True):run_action(self,lambda:FinanceService(self.db).cancel_expense(self.user,eid,reason),"تم الإلغاء مع حفظ السجل.",self.refresh)

    def print_transactions(self):
        report=ReportService(self.db).report_finance({"date_from":"0001-01-01","date_to":"9999-12-31"});PrintManager.preview(self,DocumentService(self.db).report_html(report),report.title)
