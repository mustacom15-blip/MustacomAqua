from __future__ import annotations
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QComboBox,QFileDialog,QLabel,QLineEdit,QMessageBox

from ..documents import DocumentService
from ..printing import PrintManager
from ..reports import STATUS_AR
from ..services import AppError, ReadingService, money
from .dialogs import FormDialog,ViewDialog
from .widgets import Page,PagedTable,area_combo,ask_reason,current_period,error,info,member_combo,run_action


class ReadingsPage(Page):
    def __init__(self,context):
        super().__init__("العدادات والقراءات","إدخال يدوي أو Excel، منع الازدواج والاستهلاك السالب، اعتماد وتصحيحات موثقة، وأوراق قراءة حسب المنطقة.")
        self.context=context;self.db=context.db;self.user=context.user
        self.period=QLineEdit(current_period(self.db));self.period.setMaximumWidth(100);self.area=area_combo(self.db)
        self.toolbar.addWidget(QLabel("الفترة"));self.toolbar.addWidget(self.period);self.toolbar.addWidget(self.area);self.button("عرض",self.refresh,True);self.toolbar.addStretch()
        if self.user.can("readings.manage") or self.user.role=="admin":
            self.button("+ قراءة",self.add);self.button("تصحيح",self.edit);self.button("استيراد Excel",self.import_excel);self.button("حدث عداد",self.meter_event)
        if self.user.can("readings.approve") or self.user.role=="admin":self.button("اعتماد",self.approve)
        self.button("ورقة قراءة",self.sheet);self.button("غير المقروءين",self.missing)
        self.table=PagedTable();self.layout.addWidget(self.table);self.refresh()

    def refresh(self):
        where,params=["r.period=?"],[self.period.text().strip()]
        if self.area.currentData():where.append("m.area_id=?");params.append(self.area.currentData())
        rows=self.db.query(f"""SELECT r.*,m.number,m.full_name,a.name area,(SELECT COUNT(*) FROM invoices i WHERE i.reading_id=r.id AND i.status!='cancelled') invoiced
            FROM readings r JOIN members m ON m.id=r.member_id LEFT JOIN areas a ON a.id=m.area_id WHERE {' AND '.join(where)} ORDER BY m.number""",tuple(params))
        self.rows=rows
        self.table.set_data(["الرقم/العداد","العضو","المنطقة","التاريخ","السابقة","الحالية","الاستهلاك","القارئ","الحالة","فاتورة","ملاحظات"],
            [[r["number"],r["full_name"],r["area"],r["reading_date"],r["previous_reading"],r["current_reading"],r["consumption"],r["reader_name"],STATUS_AR.get(r["status"]),"نعم" if r["invoiced"] else "لا",r["notes"]] for r in rows],[r["id"] for r in rows])

    def _dialog(self,record=None):
        r=dict(record) if record else {}
        fields=[{"name":"member_id","label":"العضو/العداد","type":"combo","required":True,"value":r.get("member_id"),"options":[(None,"اختر…")]+[(m["id"],f"{m['number']} — {m['full_name']}") for m in self.db.query("SELECT id,number,full_name FROM members WHERE archived=0 AND status='active' ORDER BY number")]},
                {"name":"period","label":"الفترة YYYY-MM","required":True,"value":r.get("period",self.period.text())},
                {"name":"reading_date","label":"تاريخ القراءة","type":"date","value":r.get("reading_date")},
                {"name":"previous_reading","label":"السابقة (تصحيحها للمدير فقط)","type":"float","value":r.get("previous_reading",0)},
                {"name":"current_reading","label":"القراءة الحالية","type":"float","required":True,"value":r.get("current_reading",0)},
                {"name":"notes","label":"ملاحظات","type":"text","value":r.get("notes")}]
        return FormDialog(self,"تصحيح قراءة" if record else "إضافة قراءة",fields)

    def add(self):
        dialog=self._dialog()
        if dialog.exec():
            values=dialog.values();values.pop("previous_reading",None)
            run_action(self,lambda:ReadingService(self.db).save(self.user,values),"حفظت القراءة كمسودة؛ اعتمدها قبل إنشاء الفاتورة.",self.refresh)

    def edit(self):
        rid=self.table.selected_id()
        if not rid:return error(self,"اختر قراءة.")
        record=self.db.one("SELECT * FROM readings WHERE id=?",(rid,));dialog=self._dialog(record)
        if dialog.exec():
            reason=ask_reason(self,"سبب تصحيح القراءة")
            if not reason:return
            values=dialog.values();values["manual_previous"]=self.user.role=="admin"
            run_action(self,lambda:ReadingService(self.db).save(self.user,values,rid,reason),"تم التصحيح وحفظ القيم السابقة والسبب في السجل.",self.refresh)

    def approve(self):
        rid=self.table.selected_id()
        if not rid:return error(self,"اختر قراءة.")
        run_action(self,lambda:ReadingService(self.db).approve(self.user,rid),"تم اعتماد القراءة.",self.refresh)

    def sheet(self):
        run_action(self,lambda:PrintManager.preview(self,DocumentService(self.db).reading_sheet_html(self.period.text(),self.area.currentData(),self.user.full_name),"ورقة قراءة"))

    def missing(self):
        where,params=["m.status='active'","m.archived=0"],[]
        if self.area.currentData():where.append("m.area_id=?");params.append(self.area.currentData())
        rows=self.db.query(f"""SELECT m.number,m.full_name,m.phone,a.name area FROM members m LEFT JOIN areas a ON a.id=m.area_id
            WHERE {' AND '.join(where)} AND NOT EXISTS(SELECT 1 FROM readings r WHERE r.member_id=m.id AND r.period=? AND r.status!='cancelled') ORDER BY m.number""",tuple(params)+ (self.period.text(),))
        body="<h2>أعضاء بلا قراءة — "+self.period.text()+"</h2><table border='1' cellspacing='0' cellpadding='6' width='100%'><tr><th>الرقم</th><th>الاسم</th><th>الهاتف</th><th>المنطقة</th></tr>"
        body+="".join(f"<tr><td>{r['number']}</td><td>{r['full_name']}</td><td>{r['phone'] or ''}</td><td>{r['area'] or ''}</td></tr>" for r in rows)+"</table>"
        ViewDialog(self,"القراءات الناقصة",body).exec()

    def meter_event(self):
        fields=[{"name":"member_id","label":"العضو/العداد","type":"combo","options":[(m["id"],f"{m['number']} — {m['full_name']}") for m in self.db.query("SELECT * FROM members WHERE archived=0")]},
                {"name":"event_type","label":"العملية","type":"combo","options":[("repair","إصلاح"),("replacement","استبدال"),("fault","تسجيل عطل")]},
                {"name":"event_date","label":"التاريخ","type":"date"},{"name":"old_reading","label":"القراءة القديمة","type":"float"},
                {"name":"new_reading","label":"القراءة الجديدة","type":"float"},{"name":"technician","label":"التقني"},
                {"name":"cost","label":"التكلفة","type":"float","decimals":2},{"name":"reason","label":"السبب","type":"text","required":True}]
        dialog=FormDialog(self,"إصلاح / استبدال / عطل عداد",fields)
        if dialog.exec():run_action(self,lambda:ReadingService(self.db).meter_event(self.user,dialog.values()),"تم تسجيل حدث العداد مع التاريخ والسبب.")

    def import_excel(self):
        filename,_=QFileDialog.getOpenFileName(self,"استيراد القراءات",str(Path.home()),"Excel (*.xlsx)")
        if not filename:return
        try:
            from openpyxl import load_workbook
            ws=load_workbook(filename,read_only=True,data_only=True).active
            rows=list(ws.iter_rows(values_only=True))
            if not rows:raise AppError("الملف فارغ.")
            headers=[str(x or "").strip() for x in rows[0]]
            aliases={"number":["number","member_number","الرقم","رقم العضو"],"period":["period","الفترة"],"reading_date":["reading_date","date","التاريخ"],"current_reading":["current_reading","current","القراءة الحالية"],"notes":["notes","ملاحظات"]}
            indices={}
            for key,names in aliases.items():
                indices[key]=next((i for i,h in enumerate(headers) if h in names),None)
            if any(indices[k] is None for k in ("number","period","reading_date","current_reading")):
                raise AppError("الأعمدة المطلوبة: number, period, reading_date, current_reading وعمود notes اختياري. الصف الأول عناوين.")
            members={r["number"]:r["id"] for r in self.db.query("SELECT id,number FROM members")}
            service=ReadingService(self.db);success=0;errors=[]
            for line,row in enumerate(rows[1:],2):
                try:
                    number=str(row[indices["number"]] or "").strip()
                    if number.endswith(".0"):number=number[:-2]
                    if number not in members:raise AppError("رقم العضو غير موجود: "+number)
                    raw_date=row[indices["reading_date"]]
                    reading_date=raw_date.date().isoformat() if hasattr(raw_date,"date") else str(raw_date)[:10]
                    service.save(self.user,{"member_id":members[number],"period":str(row[indices["period"]]).strip(),"reading_date":reading_date,
                        "current_reading":row[indices["current_reading"]],"notes":str(row[indices["notes"]] or "") if indices["notes"] is not None else ""})
                    success+=1
                except Exception as exc:errors.append(f"سطر {line}: {exc}")
            self.refresh();info(self,f"تم استيراد {success} قراءة كمسودات.\n"+("أخطاء:\n"+"\n".join(errors[:15]) if errors else "لا توجد أخطاء."))
        except Exception as exc:error(self,exc)
