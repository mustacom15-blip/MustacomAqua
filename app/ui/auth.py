from __future__ import annotations
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QTabWidget,
    QVBoxLayout,QWidget,QDoubleSpinBox,QDateEdit,QPlainTextEdit)

from ..billing import TariffService
from ..database import Database
from ..finance import FinanceService
from ..paths import resource_dir
from ..security import User
from ..services import AppError, AuthService
from .widgets import error, info


class LoginDialog(QDialog):
    def __init__(self,db: Database):
        super().__init__();self.db=db;self.user=None
        self.setWindowTitle("تسجيل الدخول — MUSTACOM AQUA GESTION PRO");self.setFixedSize(470,520)
        layout=QVBoxLayout(self);layout.setContentsMargins(38,25,38,25)
        logo=QLabel();logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix=QPixmap(str(resource_dir()/"assets"/"mustacom_logo.png"))
        if not pix.isNull():logo.setPixmap(pix.scaled(210,145,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo)
        title=QLabel("MUSTACOM AQUA GESTION PRO");title.setObjectName("PageTitle");title.setAlignment(Qt.AlignmentFlag.AlignCenter);title.setWordWrap(True);layout.addWidget(title)
        form=QFormLayout();self.username=QLineEdit();self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.login)
        form.addRow("اسم المستخدم",self.username);form.addRow("كلمة المرور",self.password);layout.addLayout(form)
        button=QPushButton("دخول");button.setProperty("primary",True);button.clicked.connect(self.login);layout.addWidget(button)
        layout.addStretch();layout.addWidget(QLabel("MUSTACOM SERVICES — 0708785153\ncontact@mustacom.com",alignment=Qt.AlignmentFlag.AlignCenter))

    def login(self):
        try:
            self.user=AuthService(self.db).login(self.username.text(),self.password.text())
            self.accept()
        except AppError as exc:error(self,exc)


class SetupDialog(QDialog):
    def __init__(self,db: Database):
        super().__init__();self.db=db;self.setWindowTitle("الإعداد الأول للتطبيق");self.resize(700,680)
        layout=QVBoxLayout(self)
        title=QLabel("مرحباً بك — إعداد الجمعية والحساب الأول");title.setObjectName("PageTitle");layout.addWidget(title)
        note=QLabel("لا توجد بيانات تجريبية. أدخل بيانات الإنتاج الحقيقية. يمكن تعديل التعرفة والإعدادات لاحقاً دون تغيير الفواتير القديمة.");note.setWordWrap(True);layout.addWidget(note)
        tabs=QTabWidget();layout.addWidget(tabs)
        admin=QWidget();af=QFormLayout(admin)
        self.full_name=QLineEdit();self.username=QLineEdit("admin");self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password);self.password2=QLineEdit();self.password2.setEchoMode(QLineEdit.EchoMode.Password)
        af.addRow("الاسم الكامل *",self.full_name);af.addRow("اسم المستخدم (لاتيني) *",self.username);af.addRow("كلمة المرور (8+) *",self.password);af.addRow("تأكيد كلمة المرور *",self.password2);tabs.addTab(admin,"1. مدير النظام")
        assoc=QWidget();f=QFormLayout(assoc)
        self.assoc_name=QLineEdit();self.assoc_phone=QLineEdit();self.assoc_email=QLineEdit();self.assoc_address=QPlainTextEdit();self.assoc_address.setMaximumHeight(80)
        f.addRow("اسم الجمعية *",self.assoc_name);f.addRow("الهاتف",self.assoc_phone);f.addRow("البريد",self.assoc_email);f.addRow("العنوان",self.assoc_address);tabs.addTab(assoc,"2. الجمعية")
        tariff=QWidget();tf=QFormLayout(tariff)
        self.price=QDoubleSpinBox();self.price.setRange(0.001,99999);self.price.setDecimals(3);self.price.setSuffix(" MAD / م³")
        self.fixed=QDoubleSpinBox();self.fixed.setRange(0,999999);self.fixed.setDecimals(2)
        self.start=QDateEdit(QDate.currentDate());self.start.setCalendarPopup(True);self.start.setDisplayFormat("yyyy-MM-dd")
        self.areas=QLineEdit();self.areas.setPlaceholderText("مثال: الحي الأول، الحي الثاني")
        tf.addRow("سعر متر مكعب *",self.price);tf.addRow("رسوم ثابتة للفاتورة",self.fixed);tf.addRow("بداية التعرفة",self.start);tf.addRow("المناطق (افصل بفاصلة)",self.areas)
        tabs.addTab(tariff,"3. التعرفة والمناطق")
        opening=QWidget();of=QFormLayout(opening)
        self.cash=QDoubleSpinBox();self.cash.setRange(-99999999,99999999);self.cash.setDecimals(2)
        self.bank=QDoubleSpinBox();self.bank.setRange(-99999999,99999999);self.bank.setDecimals(2)
        of.addRow("الرصيد الافتتاحي للصندوق",self.cash);of.addRow("الرصيد الافتتاحي للبنك",self.bank)
        of.addRow(QLabel("بعد الحفظ أضف الأعضاء من شاشة «الأعضاء». لكل عضو رقم موحد للعضوية والعداد وقراءة أولية وتاريخها؛ تلك هي القراءات الافتتاحية المطلوبة."))
        tabs.addTab(opening,"4. الأرصدة الافتتاحية")
        save=QPushButton("حفظ وبدء الاستخدام");save.setProperty("primary",True);save.clicked.connect(self.save);layout.addWidget(save)

    def save(self):
        try:
            if self.password.text()!=self.password2.text():raise AppError("تأكيد كلمة المرور غير مطابق.")
            if not self.assoc_name.text().strip():raise AppError("اسم الجمعية مطلوب.")
            association={"association_name":self.assoc_name.text(),"association_phone":self.assoc_phone.text(),"association_email":self.assoc_email.text(),
                         "association_address":self.assoc_address.toPlainText(),"currency":"MAD"}
            AuthService(self.db).create_first_admin(self.username.text(),self.full_name.text(),self.password.text(),association)
            admin=AuthService(self.db).login(self.username.text(),self.password.text())
            TariffService(self.db).save_tariff(admin,{"name":"التعرفة الافتتاحية","start_date":self.start.date().toString("yyyy-MM-dd"),"fixed_fee":self.fixed.value(),"late_fee":0,"active":True},
                                               [{"from_qty":0,"to_qty":None,"unit_price":self.price.value()}])
            FinanceService(self.db).save_account(admin,{"name":"الصندوق الرئيسي","type":"cash","opening_balance":self.cash.value(),"active":True})
            FinanceService(self.db).save_account(admin,{"name":"الحساب البنكي","type":"bank","opening_balance":self.bank.value(),"active":True})
            with self.db.transaction() as conn:
                for name in self.areas.text().replace("،",",").split(","):
                    if name.strip():conn.execute("INSERT OR IGNORE INTO areas(name) VALUES(?)",(name.strip(),))
            info(self,"اكتمل الإعداد. يمكنك الآن تسجيل الدخول وإضافة الأعضاء والقراءات الأولية.")
            self.accept()
        except Exception as exc:error(self,exc)
