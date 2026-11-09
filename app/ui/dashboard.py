from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView,QComboBox,QGridLayout,QGroupBox,QHBoxLayout,QLabel,QScrollArea,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget

from ..reports import ReportService, STATUS_AR
from ..services import money
from .widgets import Card, Page, current_period


class DashboardPage(Page):
    def __init__(self,context):
        super().__init__("لوحة القيادة","مؤشرات الفترة المختارة، الأرصدة الفعلية للصندوق والبنك، والتنبيهات التشغيلية.")
        self.context=context;self.db=context.db
        self.period=QComboBox();self.period.setEditable(True);self.period.addItems(self._periods());self.period.setCurrentText(current_period(self.db))
        self.period.currentTextChanged.connect(self.refresh)
        self.toolbar.addWidget(QLabel("فترة الفوترة"));self.toolbar.addWidget(self.period);self.button("تحديث",self.refresh,True);self.toolbar.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.layout.addWidget(scroll)
        content=QWidget();scroll.setWidget(content);self.body=QVBoxLayout(content)
        self.cards={}
        grid=QGridLayout();self.body.addLayout(grid)
        definitions=[("active","الأعضاء النشطون"),("suspended","المعلقون"),("withdrawn","المنسحبون"),("missing_readings","بدون قراءة"),
                     ("consumption","الاستهلاك م³"),("invoices_issued","الفواتير الصادرة"),("paid_period","المحصل من فواتير الفترة"),("unpaid_period","غير محصل بالفترة"),
                     ("total_debt","مجموع الديون"),("overdue","متأخرات مستحقة"),("cash","الصندوق"),("bank","البنك"),
                     ("open_complaints","شكايات مفتوحة"),("overdue_maintenance","صيانة متأخرة")]
        for i,(key,title) in enumerate(definitions):
            card=Card(title);self.cards[key]=card;grid.addWidget(card,i//5,i%5)
        tables=QHBoxLayout();self.body.addLayout(tables)
        self.recent_readings=self._small_table(["التاريخ","الرقم","العضو","الاستهلاك","الحالة"]);self.recent_tx=self._small_table(["التاريخ","الوثيقة","الحساب","النوع","المبلغ"])
        g1=QGroupBox("أحدث القراءات");QVBoxLayout(g1).addWidget(self.recent_readings);tables.addWidget(g1)
        g2=QGroupBox("أحدث الحركات المالية");QVBoxLayout(g2).addWidget(self.recent_tx);tables.addWidget(g2)
        if context.user.role in ("reader","reception"):
            for key in ("invoices_issued","paid_period","unpaid_period","total_debt","overdue","cash","bank"):
                self.cards[key].hide()
            g2.hide()
        self.alerts=QLabel();self.alerts.setWordWrap(True);self.alerts.setTextFormat(Qt.TextFormat.RichText)
        alerts_box=QGroupBox("التنبيهات");QVBoxLayout(alerts_box).addWidget(self.alerts);self.body.addWidget(alerts_box)
        self.refresh()

    def _periods(self):
        rows=self.db.query("SELECT period FROM readings UNION SELECT period FROM invoices ORDER BY period DESC LIMIT 36")
        values=[r[0] for r in rows]
        return values or [current_period(self.db)]

    def _small_table(self,headers):
        t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers);t.setMinimumHeight(220);t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);t.verticalHeader().setVisible(False)
        return t

    @staticmethod
    def _fill(table,rows):
        table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):table.setItem(i,j,QTableWidgetItem("" if value is None else str(value)))
        table.resizeColumnsToContents()

    def refresh(self):
        try:
            s=ReportService(self.db).dashboard(self.period.currentText())
            for key,card in self.cards.items():
                value=s[key]
                if key in ("consumption","paid_period","unpaid_period","total_debt","overdue","cash","bank"):value=f"{money(value):,.2f}"
                card.set(value)
            self._fill(self.recent_readings,[[r["reading_date"],r["number"],r["full_name"],r["consumption"],STATUS_AR.get(r["status"],r["status"])] for r in s["recent_readings"]])
            kinds={"income":"دخل","expense":"مصروف","transfer_in":"تحويل وارد","transfer_out":"تحويل صادر"}
            self._fill(self.recent_tx,[[r["transaction_date"],r["txn_no"],r["account"],kinds.get(r["kind"],r["kind"]),f"{money(r['amount']):.2f}"] for r in s["recent_transactions"]])
            alerts=[]
            for r in s["high_consumption"]:alerts.append(f"⚠ استهلاك مرتفع: {r['number']} — {r['full_name']} ({r['consumption']} م³، المتوسط السابق {r['previous_average']:.1f})")
            for r in s["zero_alerts"]:alerts.append(f"⚠ قراءات صفرية متكررة: {r['number']} — {r['full_name']} ({r['zeros']})")
            for r in s["faulty_meters"]:alerts.append(f"🔧 عداد مشكوك فيه: {r['number'] or 'شبكة'} — {r['full_name'] or r['complaint_no']}")
            if s["overdue"]>0:alerts.append(f"⚠ متأخرات مالية مستحقة: {money(s['overdue']):.2f} MAD")
            if s["missing_readings"]>0:alerts.append(f"⚠ {s['missing_readings']} عضواً نشطاً بلا قراءة في الفترة {s['period']}")
            self.alerts.setText("<br/>".join(alerts) if alerts else "✓ لا توجد تنبيهات حرجة في البيانات الحالية.")
        except Exception as exc:self.alerts.setText(str(exc))
