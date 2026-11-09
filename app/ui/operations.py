from __future__ import annotations
from datetime import date

from PySide6.QtWidgets import QCheckBox,QComboBox,QHBoxLayout,QLabel,QLineEdit,QPushButton,QTabWidget,QVBoxLayout,QWidget

from ..operations import OperationsService
from ..reports import STATUS_AR,TYPE_AR,money
from .dialogs import FormDialog
from .widgets import Page,PagedTable,area_combo,error,info,run_action


class ComplaintsPage(Page):
    def __init__(self,context):
        super().__init__("الشكايات والصيانة","شكايات الأعضاء أو مواقع الشبكة والمضخات والخزانات، الإسناد والتشخيص وقطع الغيار والتكلفة والإنجاز.")
        self.context=context;self.db=context.db;self.user=context.user
        self.status=QComboBox();self.status.addItem("كل الحالات","");[self.status.addItem(v,k) for k,v in (("open","مفتوحة"),("assigned","مسندة"),("in_progress","جارية"),("completed","منجزة"),("closed","مغلقة"),("cancelled","ملغاة"))]
        self.overdue=QCheckBox("المتأخرة فقط");self.toolbar.addWidget(self.status);self.toolbar.addWidget(self.overdue);self.button("عرض",self.refresh,True);self.toolbar.addStretch()
        if self.user.can("complaints.manage") or self.user.role=="admin":
            self.button("+ شكاية / عمل",self.add);self.button("تحديث وتشخيص وإنجاز",self.edit)
        self.table=PagedTable();self.layout.addWidget(self.table);self.refresh()

    def refresh(self):
        where,params=["1=1"],[]
        if self.status.currentData():where.append("c.status=?");params.append(self.status.currentData())
        if self.overdue.isChecked():where.append("c.due_date<? AND c.status NOT IN ('completed','closed','cancelled')");params.append(date.today().isoformat())
        rows=self.db.query(f"""SELECT c.*,m.number,m.full_name FROM complaints c LEFT JOIN members m ON m.id=c.member_id WHERE {' AND '.join(where)} ORDER BY c.id DESC""",tuple(params))
        self.table.set_data(["الرقم","التاريخ","العضو/العداد","الموقع","النوع","الأولوية","الحالة","المسؤول","الاستحقاق","التكلفة","الإنجاز"],
            [[r["complaint_no"],r["reported_date"],(r["number"]+" "+r["full_name"]) if r["number"] else "شبكة",r["location"],TYPE_AR.get(r["complaint_type"]),r["priority"],STATUS_AR.get(r["status"]),r["assigned_to"],r["due_date"],r["cost"],r["completion_date"]] for r in rows],[r["id"] for r in rows])

    def _dialog(self,record=None):
        r=dict(record) if record else {}
        fields=[{"name":"member_id","label":"العضو (أو اتركه لموقع شبكة)","type":"combo","value":r.get("member_id"),"options":[(None,"موقع شبكة / مضخة / خزان")]+[(m["id"],f"{m['number']} — {m['full_name']}") for m in self.db.query("SELECT * FROM members WHERE archived=0")]},
                {"name":"location","label":"موقع الشبكة/المعدة","value":r.get("location")},
                {"name":"complaint_type","label":"النوع","type":"combo","value":r.get("complaint_type","leak"),"options":list(TYPE_AR.items())},
                {"name":"reported_date","label":"تاريخ التبليغ","type":"date","value":r.get("reported_date")},{"name":"priority","label":"الأولوية","type":"combo","value":r.get("priority","medium"),"options":[("low","منخفضة"),("medium","متوسطة"),("high","عالية"),("urgent","مستعجلة")]},
                {"name":"due_date","label":"موعد الإنجاز المتوقع","type":"date","value":r.get("due_date")},{"name":"description","label":"الوصف","type":"text","required":True,"value":r.get("description")},
                {"name":"status","label":"الحالة","type":"combo","value":r.get("status","open"),"options":[(x,STATUS_AR.get(x,x)) for x in ("open","assigned","in_progress","completed","closed","cancelled")]},
                {"name":"assigned_to","label":"التقني/المسؤول","value":r.get("assigned_to")},{"name":"diagnosis","label":"التشخيص","type":"text","value":r.get("diagnosis")},
                {"name":"work_performed","label":"العمل المنجز","type":"text","value":r.get("work_performed")},{"name":"parts_used","label":"القطع المستعملة","type":"text","value":r.get("parts_used")},
                {"name":"cost","label":"التكلفة","type":"float","decimals":2,"value":r.get("cost",0)},{"name":"completion_date","label":"تاريخ الإنجاز","type":"date","value":r.get("completion_date")}]
        return FormDialog(self,"تحديث شكاية/صيانة" if record else "شكاية أو عمل صيانة",fields)

    def add(self):
        d=self._dialog()
        if d.exec():run_action(self,lambda:OperationsService(self.db).save_complaint(self.user,d.values()),"تم تسجيل الشكاية/العمل.",self.refresh)

    def edit(self):
        cid=self.table.selected_id()
        if not cid:return error(self,"اختر سجلاً.")
        d=self._dialog(self.db.one("SELECT * FROM complaints WHERE id=?",(cid,)))
        if d.exec():run_action(self,lambda:OperationsService(self.db).save_complaint(self.user,d.values(),cid),"تم تحديث العمل.",self.refresh)


class InventoryPage(Page):
    def __init__(self,context):
        super().__init__("المخزون والمعدات","استلام وصرف وجرد موثق، ربط القطع بأعمال الصيانة، وتنبيه عند بلوغ الحد الأدنى.")
        self.context=context;self.db=context.db;self.user=context.user
        self.low=QCheckBox("المخزون المنخفض فقط");self.toolbar.addWidget(self.low);self.button("عرض",self.refresh,True);self.toolbar.addStretch()
        self.button("+ مادة",self.add_item);self.button("تعديل المادة",self.edit_item);self.button("استلام / صرف / جرد",self.move)
        self.tabs=QTabWidget();self.layout.addWidget(self.tabs);self.items=PagedTable();self.moves=PagedTable();self.tabs.addTab(self.items,"المواد");self.tabs.addTab(self.moves,"الحركات");self.refresh()

    def refresh(self):
        rows=self.db.query("SELECT * FROM inventory_items WHERE active=1 ORDER BY category,name")
        if self.low.isChecked():rows=[r for r in rows if r["quantity"]<=r["min_quantity"]]
        self.items.set_data(["الرمز","المادة","التصنيف","الوحدة","الكمية","الحد الأدنى","الشراء","المورد","تنبيه"],[[r["code"],r["name"],r["category"],r["unit"],r["quantity"],r["min_quantity"],r["purchase_price"],r["supplier"],"منخفض" if r["quantity"]<=r["min_quantity"] else ""] for r in rows],[r["id"] for r in rows])
        moves=self.db.query("""SELECT v.*,i.code,i.name,u.full_name username,c.complaint_no FROM inventory_moves v JOIN inventory_items i ON i.id=v.item_id LEFT JOIN users u ON u.id=v.user_id LEFT JOIN complaints c ON c.id=v.complaint_id ORDER BY v.id DESC LIMIT 2000""")
        labels={"in":"استلام","out":"صرف","adjustment":"جرد/تسوية"}
        self.moves.set_data(["التاريخ","الرمز","المادة","النوع","الكمية/الفرق","السبب","العمل","المستخدم"],[[r["move_date"],r["code"],r["name"],labels.get(r["move_type"]),r["quantity"],r["reason"],r["complaint_no"],r["username"]] for r in moves],[r["id"] for r in moves])

    def _dialog(self,record=None):
        r=dict(record) if record else {}
        fields=[{"name":"code","label":"الرمز","required":True,"value":r.get("code")},{"name":"name","label":"اسم المادة","required":True,"value":r.get("name")},
                {"name":"category","label":"التصنيف","type":"combo","value":r.get("category","عدادات"),"options":["عدادات","أنابيب","مضخات","وصلات","قطع غيار","خزانات","أخرى"]},
                {"name":"unit","label":"الوحدة","value":r.get("unit","قطعة")},{"name":"quantity","label":"الكمية الحالية","type":"float","value":r.get("quantity",0)},
                {"name":"min_quantity","label":"الحد الأدنى","type":"float","value":r.get("min_quantity",0)},{"name":"purchase_price","label":"ثمن الشراء","type":"float","decimals":2,"value":r.get("purchase_price",0)},
                {"name":"supplier","label":"المورد","value":r.get("supplier")},{"name":"active","label":"نشطة","type":"check","value":r.get("active",True)}]
        return FormDialog(self,"مادة مخزون",fields)

    def add_item(self):
        d=self._dialog()
        if d.exec():run_action(self,lambda:OperationsService(self.db).save_inventory_item(self.user,d.values()),"تم حفظ المادة.",self.refresh)

    def edit_item(self):
        iid=self.items.selected_id()
        if not iid:return error(self,"اختر مادة.")
        d=self._dialog(self.db.one("SELECT * FROM inventory_items WHERE id=?",(iid,)))
        if d.exec():run_action(self,lambda:OperationsService(self.db).save_inventory_item(self.user,d.values(),iid),"تم الحفظ.",self.refresh)

    def move(self):
        iid=self.items.selected_id()
        fields=[{"name":"item_id","label":"المادة","type":"combo","value":iid,"options":[(r["id"],f"{r['code']} — {r['name']}") for r in self.db.query("SELECT * FROM inventory_items WHERE active=1")]},
                {"name":"move_type","label":"نوع الحركة","type":"combo","options":[("in","استلام"),("out","صرف"),("adjustment","فرق جرد (+/-)")]},
                {"name":"quantity","label":"الكمية أو الفرق","type":"float","min":-999999,"value":1},{"name":"unit_cost","label":"تكلفة الوحدة","type":"float","decimals":2},
                {"name":"move_date","label":"التاريخ","type":"date"},{"name":"reason","label":"السبب","required":True},
                {"name":"complaint_id","label":"ربط بعمل صيانة","type":"combo","options":[(None,"بدون")]+[(r["id"],r["complaint_no"]) for r in self.db.query("SELECT id,complaint_no FROM complaints ORDER BY id DESC LIMIT 200")]}]
        d=FormDialog(self,"حركة مخزون",fields)
        if d.exec():run_action(self,lambda:OperationsService(self.db).inventory_move(self.user,d.values()),"تم تسجيل الحركة وتحديث الكمية.",self.refresh)
