from __future__ import annotations
from datetime import date, timedelta

from .database import now
from .security import User
from .services import AppError, BaseService, D, money, row_dict, valid_date

COMPLAINT_TYPES = ("leak", "outage", "low_pressure", "faulty_meter", "quality", "other")
COMPLAINT_STATUSES = ("open", "assigned", "in_progress", "completed", "closed", "cancelled")


class OperationsService(BaseService):
    def save_complaint(self, user: User, data: dict, complaint_id: int | None = None) -> int:
        self.require(user, "complaints.manage")
        if data.get("complaint_type") not in COMPLAINT_TYPES or data.get("status") not in COMPLAINT_STATUSES:
            raise AppError("نوع الشكاية أو حالتها غير صالح.")
        if not data.get("description", "").strip() or not (data.get("member_id") or data.get("location", "").strip()):
            raise AppError("الوصف مطلوب، واربط الشكاية بعضو أو حدد موقع الشبكة.")
        valid_date(data["reported_date"], "تاريخ الشكاية")
        if data.get("due_date"):
            valid_date(data["due_date"], "تاريخ الاستحقاق")
        if data.get("completion_date"):
            valid_date(data["completion_date"], "تاريخ الإنجاز")
        if data.get("status") in ("completed", "closed") and not data.get("completion_date"):
            data["completion_date"] = date.today().isoformat()
        with self.db.transaction() as conn:
            if data.get("member_id"):
                self.get(conn, "members", int(data["member_id"]))
            before = row_dict(conn.execute("SELECT * FROM complaints WHERE id=?", (complaint_id,)).fetchone()) if complaint_id else None
            vals = (data.get("member_id") or None, data.get("location", "").strip(), data["complaint_type"], data["reported_date"],
                    data.get("priority", "medium"), data["description"].strip(), data["status"], data.get("assigned_to", "").strip(),
                    data.get("diagnosis", "").strip(), data.get("work_performed", "").strip(), data.get("parts_used", "").strip(),
                    float(money(data.get("cost", 0))), data.get("completion_date") or None, data.get("due_date") or None, now())
            if complaint_id:
                conn.execute("""UPDATE complaints SET member_id=?,location=?,complaint_type=?,reported_date=?,priority=?,description=?,status=?,
                    assigned_to=?,diagnosis=?,work_performed=?,parts_used=?,cost=?,completion_date=?,due_date=?,updated_at=? WHERE id=?""", vals+(complaint_id,))
                record_id, action = complaint_id, "تحديث شكاية أو صيانة"
            else:
                number = self.next_number(conn, "complaint")
                cur = conn.execute("""INSERT INTO complaints(complaint_no,member_id,location,complaint_type,reported_date,priority,description,status,
                    assigned_to,diagnosis,work_performed,parts_used,cost,completion_date,due_date,updated_at,created_by)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (number,)+vals+(user.id,))
                record_id, action = cur.lastrowid, "تسجيل شكاية"
            self.audit(conn, user, action, "complaints", record_id, before, data)
            return record_id

    def save_inventory_item(self, user: User, data: dict, item_id: int | None = None) -> int:
        self.require(user, "inventory.manage")
        if not data.get("code", "").strip() or not data.get("name", "").strip():
            raise AppError("رمز المادة واسمها مطلوبان.")
        for key in ("quantity", "min_quantity", "purchase_price"):
            if D(data.get(key, 0)) < 0:
                raise AppError("الكميات والأسعار لا يمكن أن تكون سالبة.")
        with self.db.transaction() as conn:
            before = row_dict(conn.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()) if item_id else None
            if before and conn.execute("SELECT COUNT(*) FROM inventory_moves WHERE item_id=?", (item_id,)).fetchone()[0] and D(before["quantity"]) != D(data.get("quantity", 0)):
                raise AppError("عدّل المخزون بحركة استلام أو صرف أو جرد، وليس من بطاقة المادة.")
            vals = (data["code"].strip(), data["name"].strip(), data.get("category", "أخرى"), data.get("unit", "قطعة"),
                    float(D(data.get("quantity", 0))), float(D(data.get("min_quantity", 0))), float(money(data.get("purchase_price", 0))),
                    data.get("supplier", "").strip(), int(data.get("active", True)))
            if item_id:
                conn.execute("UPDATE inventory_items SET code=?,name=?,category=?,unit=?,quantity=?,min_quantity=?,purchase_price=?,supplier=?,active=? WHERE id=?", vals+(item_id,))
                record_id, action = item_id, "تعديل مادة مخزون"
            else:
                cur = conn.execute("INSERT INTO inventory_items(code,name,category,unit,quantity,min_quantity,purchase_price,supplier,active) VALUES(?,?,?,?,?,?,?,?,?)", vals)
                record_id, action = cur.lastrowid, "إضافة مادة مخزون"
            self.audit(conn, user, action, "inventory_items", record_id, before, data)
            return record_id

    def inventory_move(self, user: User, data: dict) -> int:
        self.require(user, "inventory.manage")
        move_type = data.get("move_type")
        qty = D(data.get("quantity", 0))
        if move_type not in ("in", "out", "adjustment") or qty == 0:
            raise AppError("نوع الحركة غير صالح أو الكمية صفر. في الجرد يمكن إدخال فرق موجب أو سالب.")
        if not data.get("reason", "").strip():
            raise AppError("سبب حركة المخزون مطلوب.")
        valid_date(data["move_date"], "تاريخ الحركة")
        with self.db.transaction() as conn:
            item = self.get(conn, "inventory_items", int(data["item_id"]))
            delta = qty if move_type == "in" else -qty if move_type == "out" else qty
            if move_type in ("in", "out") and qty < 0:
                raise AppError("أدخل كمية موجبة للاستلام أو الصرف.")
            new_qty = D(item["quantity"])+delta
            if new_qty < 0:
                raise AppError("الصرف أكبر من الكمية المتوفرة.")
            if data.get("complaint_id"):
                self.get(conn, "complaints", int(data["complaint_id"]))
            cur = conn.execute("""INSERT INTO inventory_moves(item_id,move_type,quantity,unit_cost,reason,move_date,user_id,complaint_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", (item["id"], move_type, float(qty), float(money(data.get("unit_cost", 0))), data["reason"].strip(),
                data["move_date"], user.id, data.get("complaint_id") or None, now()))
            conn.execute("UPDATE inventory_items SET quantity=? WHERE id=?", (float(new_qty), item["id"]))
            self.audit(conn, user, "حركة مخزون", "inventory_moves", cur.lastrowid, row_dict(item), {"old_quantity": item["quantity"], "new_quantity": float(new_qty), **data})
            return cur.lastrowid

    def record_reminder(self, user: User, data: dict) -> int:
        self.require(user, "debts.manage")
        if not data.get("method", "").strip():
            raise AppError("طريقة إرسال التذكير مطلوبة.")
        valid_date(data["reminder_date"], "تاريخ التذكير")
        with self.db.transaction() as conn:
            self.get(conn, "members", int(data["member_id"]))
            cur = conn.execute("INSERT INTO reminders(member_id,invoice_id,reminder_date,method,outcome,notes,created_by) VALUES(?,?,?,?,?,?,?)",
                               (data["member_id"], data.get("invoice_id") or None, data["reminder_date"], data["method"], data.get("outcome", ""), data.get("notes", ""), user.id))
            self.audit(conn, user, "تسجيل تذكير أداء", "reminders", cur.lastrowid, after=data)
            return cur.lastrowid

    def create_installments(self, user: User, member_id: int, start_date: str, count: int, frequency_days: int, notes: str = "") -> int:
        self.require(user, "debts.manage")
        valid_date(start_date, "بداية الاتفاق")
        if count < 2 or count > 120 or frequency_days < 1:
            raise AppError("عدد الأقساط من 2 إلى 120 والفاصل يوم واحد على الأقل.")
        with self.db.transaction() as conn:
            self.get(conn, "members", member_id)
            debt_row = conn.execute("""SELECT COALESCE(SUM(i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0)),0)
                FROM invoices i WHERE i.member_id=? AND i.status='issued'""", (member_id,)).fetchone()
            total = money(debt_row[0])
            if total <= 0:
                raise AppError("لا يوجد دين قائم لإبرام تقسيط.")
            cur = conn.execute("INSERT INTO installments(member_id,total_amount,start_date,installments_count,frequency_days,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                               (member_id, float(total), start_date, count, frequency_days, notes, now()))
            base = total / count
            allocated = money(0)
            start = date.fromisoformat(start_date)
            for i in range(count):
                amount = money(total-allocated) if i == count-1 else money(base)
                allocated = money(allocated+amount)
                conn.execute("INSERT INTO installment_lines(agreement_id,due_date,amount) VALUES(?,?,?)",
                             (cur.lastrowid, (start+timedelta(days=i*frequency_days)).isoformat(), float(amount)))
            self.audit(conn, user, "اتفاق تقسيط", "installments", cur.lastrowid, after={"member_id": member_id, "total": float(total), "count": count})
            return cur.lastrowid
