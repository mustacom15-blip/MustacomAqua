from __future__ import annotations
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon,QPixmap
from PySide6.QtWidgets import QFrame,QHBoxLayout,QLabel,QMainWindow,QPushButton,QScrollArea,QStackedWidget,QVBoxLayout,QWidget

from ..paths import resource_dir
from ..security import ROLES
from .dashboard import DashboardPage
from .members import MembersPage
from .readings import ReadingsPage
from .billing import BillingPage
from .payments import PaymentsPage
from .finance import FinancePage
from .debts import DebtsPage
from .operations import ComplaintsPage,InventoryPage
from .reports_page import ReportsPage
from .settings_page import SettingsPage
from .users_page import UsersPage
from .backup_page import BackupPage
from .help_page import HelpPage
from .theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(self,db,user):
        super().__init__();self.db=db;self.user=user;self.context=SimpleNamespace(db=db,user=user)
        from ..printing import PrintManager
        prefs={r["key"]:r["value"] or "" for r in db.query("SELECT key,value FROM settings WHERE key IN ('printer_name','export_folder')")}
        PrintManager.printer_name=prefs.get("printer_name","");PrintManager.export_folder=prefs.get("export_folder","")
        self.setWindowTitle("MUSTACOM AQUA GESTION PRO");self.resize(1500,920);self.setMinimumSize(1150,720)
        icon=resource_dir()/"assets"/"mustacom_logo.png"
        if icon.exists():self.setWindowIcon(QIcon(str(icon)))
        central=QWidget();root=QHBoxLayout(central);root.setContentsMargins(0,0,0,0);root.setSpacing(0);self.setCentralWidget(central)
        sidebar=QWidget();sidebar.setObjectName("Sidebar");sidebar.setFixedWidth(225);side=QVBoxLayout(sidebar);side.setContentsMargins(10,18,10,12);root.addWidget(sidebar)
        logo=QLabel();logo.setAlignment(Qt.AlignmentFlag.AlignCenter);pix=QPixmap(str(icon))
        if not pix.isNull():logo.setPixmap(pix.scaled(150,90,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));side.addWidget(logo)
        brand=QLabel("AQUA GESTION PRO");brand.setObjectName("Brand");brand.setAlignment(Qt.AlignmentFlag.AlignCenter);side.addWidget(brand)
        sub=QLabel("إدارة جمعيات مياه الشرب");sub.setObjectName("SubBrand");sub.setAlignment(Qt.AlignmentFlag.AlignCenter);side.addWidget(sub);side.addSpacing(12)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);nav_widget=QWidget();nav_widget.setStyleSheet("background:#102f43");self.nav_layout=QVBoxLayout(nav_widget);self.nav_layout.setContentsMargins(0,0,0,0);self.nav_layout.setSpacing(2);scroll.setWidget(nav_widget);side.addWidget(scroll)
        assoc=self.db.one("SELECT value FROM settings WHERE key='association_name'")[0]
        self.user_label=QLabel(f"{user.full_name}\n{ROLES.get(user.role,user.role)}");self.user_label.setAlignment(Qt.AlignmentFlag.AlignCenter);self.user_label.setWordWrap(True);side.addWidget(self.user_label)
        logout=QPushButton("تسجيل الخروج");logout.setProperty("nav",True);logout.clicked.connect(self.logout);side.addWidget(logout)
        content=QWidget();cl=QVBoxLayout(content);cl.setContentsMargins(0,0,0,0);cl.setSpacing(0);root.addWidget(content,1)
        top=QWidget();top.setStyleSheet("background:white;border-bottom:1px solid #d7e0e4");th=QHBoxLayout(top);th.setContentsMargins(18,10,18,10)
        title=QLabel(assoc);title.setStyleSheet("font-size:14pt;font-weight:bold;color:#123a54");th.addWidget(title);th.addStretch();th.addWidget(QLabel("يعمل محلياً دون إنترنت • البيانات محفوظة تلقائياً"));cl.addWidget(top)
        self.stack=QStackedWidget();cl.addWidget(self.stack,1)
        self.nav_buttons=[];self.pages=[]
        definitions=[("⌂  لوحة القيادة",DashboardPage,True),("👥  الأعضاء",MembersPage,user.can("members.view")),("▥  القراءات والعدادات",ReadingsPage,user.can("readings.view")),
                     ("▤  التعرفات والفوترة",BillingPage,user.role in ("admin","president","treasurer")),("▣  الأداءات والسندات",PaymentsPage,user.role in ("admin","treasurer")),
                     ("◫  الصندوق والبنك",FinancePage,user.role in ("admin","treasurer")),("◷  الديون والتقسيط",DebtsPage,user.role in ("admin","treasurer")),
                     ("⚒  الشكايات والصيانة",ComplaintsPage,user.can("complaints.view")),("▦  المخزون والمعدات",InventoryPage,user.role=="admin"),
                     ("▧  التقارير والتصدير",ReportsPage,user.can("reports.view")),("⚙  إعدادات الجمعية",SettingsPage,user.role=="admin"),
                     ("♟  المستخدمون والتدقيق",UsersPage,user.role=="admin"),("⛁  النسخ الاحتياطي",BackupPage,user.role=="admin"),("؟  الدليل وحول",HelpPage,True)]
        for text,cls,visible in definitions:
            if not visible:continue
            page=cls(self.context);index=self.stack.addWidget(page);button=QPushButton(text);button.setProperty("nav",True);button.setCheckable(True);button.clicked.connect(lambda checked=False,i=index,b=text:self.navigate(i,b))
            self.nav_layout.addWidget(button);self.nav_buttons.append(button);self.pages.append(page)
        self.nav_layout.addStretch()
        if self.nav_buttons:self.nav_buttons[0].setChecked(True);self.stack.setCurrentIndex(0)
        self.statusBar().showMessage("قاعدة البيانات: "+str(db.path))

    def navigate(self,index,title):
        self.stack.setCurrentIndex(index)
        for b in self.nav_buttons:b.setChecked(False)
        self.nav_buttons[index].setChecked(True)
        page=self.stack.currentWidget()
        if hasattr(page,"refresh"):
            try:page.refresh()
            except Exception:pass

    def logout(self):
        self.close()
