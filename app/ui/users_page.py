from __future__ import annotations
import html

from PySide6.QtWidgets import QComboBox,QHBoxLayout,QLabel,QLineEdit,QPushButton,QTabWidget,QVBoxLayout,QWidget

from ..security import ROLES
from ..services import AuthService
from .dialogs import FormDialog,ViewDialog
from .widgets import Page,PagedTable,error,run_action


class UsersPage(Page):
    def __init__(self,context):
        super().__init__("المستخدمون والصلاحيات وسجل التدقيق","حسابات بكلمات مرور PBKDF2، أدوار وظيفية، وتوثيق العمليات الحساسة والقيم قبل وبعد.")
        self.context=context;self.db=context.db;self.user=context.user
        self.tabs=QTabWidget();self.layout.addWidget(self.tabs)
        users=QWidget();l=QVBoxLayout(users);h=QHBoxLayout();l.addLayout(h)
        for text,fn in (("+ مستخدم",self.add),("تعديل / دور / كلمة مرور",self.edit)):
            b=QPushButton(text);b.clicked.connect(fn);h.addWidget(b)
        h.addStretch();self.table=PagedTable();l.addWidget(self.table);self.tabs.addTab(users,"المستخدمون")
        audit=QWidget();al=QVBoxLayout(audit);ah=QHBoxLayout();al.addLayout(ah)
        self.search=QLineEdit();self.search.setPlaceholderText("مستخدم، عملية، كيان، رقم سجل…");self.search.returnPressed.connect(self.refresh_audit)
        b=QPushButton("بحث");b.clicked.connect(self.refresh_audit);ah.addWidget(self.search);ah.addWidget(b)
        details=QPushButton("تفاصيل قبل/بعد");details.clicked.connect(self.audit_details);ah.addWidget(details);ah.addStretch()
        self.audit=PagedTable(100);al.addWidget(self.audit);self.tabs.addTab(audit,"سجل التدقيق")
        self.refresh();self.refresh_audit()

    def refresh(self):
        rows=self.db.query("SELECT * FROM users ORDER BY username")
        self.table.set_data(["اسم المستخدم","الاسم","الدور","نشط","آخر دخول","أنشئ"],[[r["username"],r["full_name"],ROLES.get(r["role"]),"نعم" if r["active"] else "لا",r["last_login"],r["created_at"]] for r in rows],[r["id"] for r in rows])

    def _dialog(self,record=None):
        r=dict(record) if record else {}
        fields=[{"name":"username","label":"اسم المستخدم (لاتيني)","required":True,"value":r.get("username")},{"name":"full_name","label":"الاسم الكامل","required":True,"value":r.get("full_name")},
                {"name":"role","label":"الدور","type":"combo","value":r.get("role","reception"),"options":list(ROLES.items())},
                {"name":"password","label":"كلمة مرور جديدة"+(" (اتركها فارغة للإبقاء)" if record else ""),"type":"password"},
                {"name":"active","label":"حساب نشط","type":"check","value":r.get("active",True)}]
        return FormDialog(self,"مستخدم",fields)

    def add(self):
        d=self._dialog()
        if d.exec():run_action(self,lambda:AuthService(self.db).save_user(self.user,d.values()),"تم إنشاء المستخدم.",self.refresh)

    def edit(self):
        uid=self.table.selected_id()
        if not uid:return error(self,"اختر مستخدماً.")
        d=self._dialog(self.db.one("SELECT * FROM users WHERE id=?",(uid,)))
        if d.exec():run_action(self,lambda:AuthService(self.db).save_user(self.user,d.values(),uid),"تم تحديث المستخدم.",self.refresh)

    def refresh_audit(self):
        term=self.search.text().strip();where="";params=()
        if term:where="WHERE username LIKE ? OR action LIKE ? OR entity LIKE ? OR entity_id LIKE ? OR reason LIKE ?";params=(f"%{term}%",)*5
        rows=self.db.query(f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT 5000",params)
        self.audit.set_data(["التاريخ","المستخدم","العملية","الكيان","السجل","السبب"],[[r["at"],r["username"],r["action"],r["entity"],r["entity_id"],r["reason"]] for r in rows],[r["id"] for r in rows])

    def audit_details(self):
        aid=self.audit.selected_id()
        if not aid:return error(self,"اختر عملية.")
        r=self.db.one("SELECT * FROM audit_log WHERE id=?",(aid,))
        body=f"<h2>{html.escape(r['action'])}</h2><p>{r['at']} — {html.escape(r['username'])} — {html.escape(r['entity'])} / {html.escape(r['entity_id'] or '')}</p><p><b>السبب:</b> {html.escape(r['reason'] or '')}</p><h3>قبل</h3><pre dir='ltr'>{html.escape(r['before_json'] or '—')}</pre><h3>بعد</h3><pre dir='ltr'>{html.escape(r['after_json'] or '—')}</pre>"
        ViewDialog(self,"تفاصيل التدقيق",body).exec()
