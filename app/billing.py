from __future__ import annotations
import json
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .database import now
from .security import User
from .services import AppError, BaseService, D, money, row_dict, valid_date


class TariffService(BaseService):
    def save_tariff(self, user: User, data: dict, tiers: list[dict], tariff_id: int | None = None) -> int:
        self.require(user, "tariffs.manage")
        if not data.get("name", "").strip():
            raise AppError("اسم التعرفة مطلوب.")
        start = valid_date(data["start_date"], "بداية التعرفة")
        end = valid_date(data["end_date"], "نهاية التعرفة") if data.get("end_date") else None
        if end and end < start:
            raise AppError("نهاية التعرفة يجب ألا تسبق بدايتها.")
        if money(data.get("fixed_fee", 0)) < 0 or money(data.get("late_fee", 0)) < 0:
            raise AppError("الرسوم لا يمكن أن تكون سالبة.")
        clean = sorted(tiers, key=lambda t: D(t["from_qty"]))
        if not clean:
            raise AppError("أضف شريحة واحدة على الأقل وسعر المتر المكعب.")
        expected = Decimal("0")
        for i, tier in enumerate(clean):
            start_qty, end_qty, price = D(tier["from_qty"]), tier.get("to_qty"), money(tier["unit_price"])
            end_qty = D(end_qty) if end_qty not in (None, "") else None
            if start_qty != expected:
                raise AppError(f"الشرائح يجب أن تكون متصلة وتبدأ من صفر؛ البداية المتوقعة {expected}.")
            if price < 0 or (end_qty is not None and end_qty <= start_qty):
                raise AppError("تحقق من حدود الشرائح والأسعار.")
            if i < len(clean)-1 and end_qty is None:
                raise AppError("الشريحة المفتوحة يجب أن تكون الأخيرة.")
            if i == len(clean)-1 and end_qty is not None:
                # A final bounded tier is allowed; consumption above it uses its unit price.
                pass
            tier.update(from_qty=float(start_qty), to_qty=float(end_qty) if end_qty is not None else None, unit_price=float(price), sort_order=i)
            expected = end_qty if end_qty is not None else start_qty
        with self.db.transaction() as conn:
            if tariff_id:
                used = conn.execute("SELECT COUNT(*) FROM invoices WHERE tariff_id=?", (tariff_id,)).fetchone()[0]
                if used:
                    raise AppError("هذه التعرفة مستخدمة في فواتير. أنشئ تعرفة جديدة بتاريخ جديد للحفاظ على الفواتير السابقة.")
            overlap = conn.execute("""SELECT id FROM tariffs WHERE active=1 AND (? IS NULL OR start_date<=?) AND (end_date IS NULL OR end_date>=?)
                                      AND (? IS NULL OR id<>?) LIMIT 1""", (end, end or start, start, tariff_id, tariff_id)).fetchone()
            if overlap and data.get("active", True):
                raise AppError("توجد تعرفة نشطة متداخلة مع هذه المدة. أغلق القديمة أولاً أو غيّر التواريخ.")
            before = row_dict(conn.execute("SELECT * FROM tariffs WHERE id=?", (tariff_id,)).fetchone()) if tariff_id else None
            vals = (data["name"].strip(), start, end, float(money(data.get("fixed_fee", 0))), float(money(data.get("late_fee", 0))), int(data.get("active", True)))
            if tariff_id:
                conn.execute("UPDATE tariffs SET name=?,start_date=?,end_date=?,fixed_fee=?,late_fee=?,active=? WHERE id=?", vals+(tariff_id,))
                conn.execute("DELETE FROM tariff_tiers WHERE tariff_id=?", (tariff_id,))
                record_id = tariff_id
                action = "تعديل تعرفة"
            else:
                cur = conn.execute("INSERT INTO tariffs(name,start_date,end_date,fixed_fee,late_fee,active,created_at) VALUES(?,?,?,?,?,?,?)", vals+(now(),))
                record_id = cur.lastrowid
                action = "إضافة تعرفة"
            for tier in clean:
                conn.execute("INSERT INTO tariff_tiers(tariff_id,from_qty,to_qty,unit_price,sort_order) VALUES(?,?,?,?,?)",
                             (record_id, tier["from_qty"], tier["to_qty"], tier["unit_price"], tier["sort_order"]))
            self.audit(conn, user, action, "tariffs", record_id, before, {"data": data, "tiers": clean})
            return record_id

    @staticmethod
    def calculate(tiers: list[dict | sqlite3.Row], consumption: Decimal) -> tuple[Decimal, list[dict]]:
        """Progressive tiers. Above a bounded final tier, the final unit price applies."""
        remaining = max(consumption, Decimal("0"))
        total = Decimal("0")
        details: list[dict] = []
        ordered = sorted(tiers, key=lambda x: D(x["from_qty"]))
        for i, tier in enumerate(ordered):
            if remaining <= 0:
                break
            lower = D(tier["from_qty"])
            if consumption <= lower:
                break
            upper = D(tier["to_qty"]) if tier["to_qty"] is not None else None
            available = consumption - lower
            qty = min(available, upper-lower) if upper is not None else available
            qty = min(qty, remaining)
            if qty <= 0:
                continue
            price = money(tier["unit_price"])
            amount = money(qty * price)
            total += amount
            details.append({"label": f"الشريحة {i+1}", "quantity": float(qty), "unit_price": float(price), "amount": float(amount),
                            "from": float(lower), "to": float(upper) if upper is not None else None})
            remaining -= qty
        if remaining > 0 and ordered:
            # Normally only possible after a bounded final tier.
            price = money(ordered[-1]["unit_price"])
            amount = money(remaining * price)
            total += amount
            details.append({"label": "ما فوق الشريحة الأخيرة", "quantity": float(remaining), "unit_price": float(price), "amount": float(amount)})
        return money(total), details


class InvoiceService(BaseService):
    def _outstanding(self, conn, member_id: int, exclude_id: int | None = None) -> Decimal:
        row = conn.execute("""SELECT COALESCE(SUM(i.total_due),0)-COALESCE((
            SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            JOIN invoices i2 ON i2.id=pa.invoice_id WHERE i2.member_id=? AND p.status='posted'),0)
            FROM invoices i WHERE i.member_id=? AND i.status='issued'""", (member_id, member_id)).fetchone()
        # Aggregate subtraction above is safe per member; no invoice rows also yields zero.
        return max(money(row[0] or 0), Decimal("0"))

    @staticmethod
    def invoice_balance(conn, invoice_id: int) -> Decimal:
        row = conn.execute("""SELECT i.total_due-COALESCE(SUM(CASE WHEN p.status='posted' THEN pa.amount ELSE 0 END),0)
            FROM invoices i LEFT JOIN payment_allocations pa ON pa.invoice_id=i.id
            LEFT JOIN payments p ON p.id=pa.payment_id WHERE i.id=? GROUP BY i.id""", (invoice_id,)).fetchone()
        return max(money(row[0] if row else 0), Decimal("0"))

    def generate_from_reading(self, user: User, reading_id: int, other_fee: Any = 0, other_label: str = "") -> int:
        self.require(user, "invoices.manage")
        with self.db.transaction() as conn:
            reading = self.get(conn, "readings", reading_id)
            if reading["status"] != "approved":
                raise AppError("لا تصدر فاتورة إلا من قراءة معتمدة.")
            exists = conn.execute("SELECT invoice_no FROM invoices WHERE reading_id=? AND status!='cancelled'", (reading_id,)).fetchone()
            if exists:
                raise AppError(f"توجد فاتورة لهذه القراءة: {exists[0]}")
            tariff = conn.execute("""SELECT * FROM tariffs WHERE active=1 AND start_date<=? AND (end_date IS NULL OR end_date>=?)
                                      ORDER BY start_date DESC LIMIT 1""", (reading["reading_date"], reading["reading_date"])).fetchone()
            if not tariff:
                raise AppError("لا توجد تعرفة نشطة تغطي تاريخ القراءة.")
            tiers = conn.execute("SELECT * FROM tariff_tiers WHERE tariff_id=? ORDER BY sort_order", (tariff["id"],)).fetchall()
            consumption = D(reading["consumption"])
            consumption_amount, details = TariffService.calculate(tiers, consumption)
            fixed = money(tariff["fixed_fee"])
            extra = money(other_fee)
            if extra < 0:
                raise AppError("الرسم الإضافي لا يمكن أن يكون سالباً.")
            prior = self._outstanding(conn, reading["member_id"])
            late = Decimal("0")
            apply_late = conn.execute("SELECT value FROM settings WHERE key='apply_late_fee'").fetchone()[0] == "1"
            if apply_late and prior > 0:
                overdue = conn.execute("SELECT COUNT(*) FROM invoices WHERE member_id=? AND status='issued' AND due_date<?", (reading["member_id"], date.today().isoformat())).fetchone()[0]
                late = money(tariff["late_fee"]) if overdue else Decimal("0")
            tax_enabled = conn.execute("SELECT value FROM settings WHERE key='tax_enabled'").fetchone()[0] == "1"
            tax_rate = D(conn.execute("SELECT value FROM settings WHERE key='tax_rate'").fetchone()[0] or 0)
            if tax_enabled and (tax_rate < 0 or tax_rate > 100):
                raise AppError("نسبة الضريبة يجب أن تكون بين 0 و100.")
            tax = money((consumption_amount + fixed + extra) * tax_rate / 100) if tax_enabled else Decimal("0")
            total = money(consumption_amount + fixed + extra + late + tax)
            number = self.next_number(conn, "invoice")
            snapshot = {"tariff": row_dict(tariff), "tiers": [row_dict(t) for t in tiers], "calculation": details,
                        "tax_enabled": tax_enabled, "tax_rate": float(tax_rate), "tax_amount": float(tax),
                        "note": "الرصيد السابق للإعلام؛ يؤدى عبر فواتيره الأصلية ولا يضاعف دين هذه الفاتورة."}
            cur = conn.execute("""INSERT INTO invoices(invoice_no,member_id,reading_id,period,tariff_id,tariff_snapshot_json,
                previous_reading,current_reading,consumption,consumption_amount,fixed_fee,other_fee,late_fee,tax_amount,prior_balance,total_due,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (number, reading["member_id"], reading_id, reading["period"], tariff["id"],
                json.dumps(snapshot, ensure_ascii=False), reading["previous_reading"], reading["current_reading"], float(consumption),
                float(consumption_amount), float(fixed), float(extra), float(late), float(tax), float(prior), float(total), user.id, now()))
            invoice_id = cur.lastrowid
            for i, item in enumerate(details):
                conn.execute("INSERT INTO invoice_items(invoice_id,label,quantity,unit_price,amount,sort_order) VALUES(?,?,?,?,?,?)",
                             (invoice_id, item["label"], item["quantity"], item["unit_price"], item["amount"], i))
            sort = len(details)
            if fixed:
                conn.execute("INSERT INTO invoice_items(invoice_id,label,quantity,unit_price,amount,sort_order) VALUES(?,?,?,?,?,?)",
                             (invoice_id, "رسوم ثابتة", 1, float(fixed), float(fixed), sort)); sort += 1
            if extra:
                conn.execute("INSERT INTO invoice_items(invoice_id,label,quantity,unit_price,amount,sort_order) VALUES(?,?,?,?,?,?)",
                             (invoice_id, other_label.strip() or "رسوم عضوية أو مساهمة استثنائية", 1, float(extra), float(extra), sort)); sort += 1
            if late:
                conn.execute("INSERT INTO invoice_items(invoice_id,label,quantity,unit_price,amount,sort_order) VALUES(?,?,?,?,?,?)",
                             (invoice_id, "رسم التأخير", 1, float(late), float(late), sort)); sort += 1
            if tax:
                conn.execute("INSERT INTO invoice_items(invoice_id,label,quantity,unit_price,amount,sort_order) VALUES(?,?,?,?,?,?)",
                             (invoice_id, f"الضريبة ({tax_rate}%)", 1, float(tax), float(tax), sort))
            self.audit(conn, user, "إنشاء مسودة فاتورة", "invoices", invoice_id, after={"invoice_no": number, "total_due": float(total), "tax": float(tax), "prior_balance": float(prior)})
            return invoice_id

    def create_contribution(self, user: User, member_id: int, period: str, description: str, amount: Any, issue: bool = False) -> int:
        self.require(user, "invoices.manage")
        amount = money(amount)
        if amount <= 0 or not description.strip() or not period.strip():
            raise AppError("الوصف والمبلغ والفترة مطلوبة، والمبلغ يجب أن يكون موجباً.")
        with self.db.transaction() as conn:
            self.get(conn, "members", member_id)
            prior = self._outstanding(conn, member_id)
            number = self.next_number(conn, "invoice")
            cur = conn.execute("""INSERT INTO invoices(invoice_no,member_id,period,kind,prior_balance,other_fee,total_due,status,issue_date,due_date,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,'draft',NULL,NULL,?,?)""", (number, member_id, period, "contribution", float(prior), float(amount), float(amount), user.id, now()))
            conn.execute("INSERT INTO invoice_items(invoice_id,label,quantity,unit_price,amount) VALUES(?,?,1,?,?)",
                         (cur.lastrowid, description.strip(), float(amount), float(amount)))
            self.audit(conn, user, "إنشاء مساهمة أو رسم عضوية", "invoices", cur.lastrowid, after={"amount": float(amount), "description": description})
            invoice_id = cur.lastrowid
        if issue:
            self.issue(user, invoice_id)
        return invoice_id

    def issue(self, user: User, invoice_id: int, use_credit: bool = True) -> None:
        self.require(user, "invoices.issue")
        with self.db.transaction() as conn:
            invoice = self.get(conn, "invoices", invoice_id)
            if invoice["status"] != "draft":
                raise AppError("الفاتورة ليست مسودة.")
            due_days = int((conn.execute("SELECT value FROM settings WHERE key='payment_due_days'").fetchone() or [30])[0] or 30)
            issue_date = date.today().isoformat()
            conn.execute("UPDATE invoices SET status='issued',issue_date=?,due_date=? WHERE id=?", (issue_date, (date.today()+timedelta(days=due_days)).isoformat(), invoice_id))
            self.audit(conn, user, "اعتماد وإصدار فاتورة", "invoices", invoice_id, row_dict(invoice), {"status": "issued", "issue_date": issue_date})
            if use_credit:
                self._allocate_available_credit(conn, user, invoice_id)

    def _allocate_available_credit(self, conn, user: User, invoice_id: int) -> None:
        invoice = self.get(conn, "invoices", invoice_id)
        remaining = self.invoice_balance(conn, invoice_id)
        if remaining <= 0:
            return
        credits = conn.execute("""SELECT p.id,p.amount-COALESCE(SUM(pa.amount),0) credit FROM payments p
            LEFT JOIN payment_allocations pa ON pa.payment_id=p.id WHERE p.member_id=? AND p.status='posted'
            GROUP BY p.id HAVING credit>0.004 ORDER BY p.payment_date,p.id""", (invoice["member_id"],)).fetchall()
        for credit in credits:
            if remaining <= 0:
                break
            amount = min(remaining, money(credit["credit"]))
            if amount <= 0:
                continue
            conn.execute("INSERT OR IGNORE INTO payment_allocations(payment_id,invoice_id,amount) VALUES(?,?,?)", (credit["id"], invoice_id, float(amount)))
            remaining = money(remaining-amount)
            self.audit(conn, user, "استخدام رصيد العضو", "payment_allocations", None, after={"payment_id": credit["id"], "invoice_id": invoice_id, "amount": float(amount)})

    def cancel(self, user: User, invoice_id: int, reason: str) -> None:
        if user.role != "admin":
            raise AppError("إلغاء الفاتورة يتطلب مدير النظام.")
        if not reason.strip():
            raise AppError("سبب الإلغاء مطلوب.")
        with self.db.transaction() as conn:
            invoice = self.get(conn, "invoices", invoice_id)
            if invoice["status"] == "cancelled":
                raise AppError("الفاتورة ملغاة مسبقاً.")
            paid = conn.execute("""SELECT COALESCE(SUM(pa.amount),0) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
                                   WHERE pa.invoice_id=? AND p.status='posted'""", (invoice_id,)).fetchone()[0]
            if D(paid) > 0:
                raise AppError("لا يمكن إلغاء فاتورة عليها أداءات. عالج السندات المرتبطة أولاً مع حفظ التدقيق.")
            conn.execute("UPDATE invoices SET status='cancelled',cancelled_by=?,cancelled_at=?,cancel_reason=? WHERE id=?", (user.id, now(), reason.strip(), invoice_id))
            self.audit(conn, user, "إلغاء فاتورة", "invoices", invoice_id, row_dict(invoice), {"status": "cancelled"}, reason)


class PaymentService(BaseService):
    def record(self, user: User, data: dict, allocations: dict[int, Any] | None = None, auto_oldest: bool = True) -> int:
        self.require(user, "payments.manage")
        amount = money(data["amount"])
        if amount <= 0:
            raise AppError("مبلغ الأداء يجب أن يكون أكبر من صفر.")
        payment_date = valid_date(data["payment_date"], "تاريخ الأداء")
        if data["method"] not in ("cash", "cheque", "transfer"):
            raise AppError("طريقة الأداء غير صالحة.")
        if data["method"] in ("cheque", "transfer") and not data.get("reference", "").strip():
            raise AppError("رقم الشيك أو مرجع التحويل مطلوب.")
        with self.db.transaction() as conn:
            member = self.get(conn, "members", int(data["member_id"]))
            account = self.get(conn, "accounts", int(data["account_id"]))
            if not account["active"]:
                raise AppError("الحساب المالي موقوف.")
            if data["method"] == "cash" and account["type"] != "cash":
                raise AppError("الأداء النقدي يجب أن يسجل في حساب الصندوق.")
            if data["method"] == "transfer" and account["type"] != "bank":
                raise AppError("التحويل البنكي يجب أن يسجل في حساب بنكي.")
            selected: dict[int, Decimal] = {}
            if allocations:
                for invoice_id, value in allocations.items():
                    value = money(value)
                    if value > 0:
                        selected[int(invoice_id)] = value
            if auto_oldest and not selected:
                available = amount
                invoices = conn.execute("""SELECT i.*,i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                    JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0) balance
                    FROM invoices i WHERE i.member_id=? AND i.status='issued' ORDER BY i.due_date,i.id""", (member["id"],)).fetchall()
                for invoice in invoices:
                    if available <= 0:
                        break
                    balance = money(invoice["balance"])
                    if balance > 0:
                        part = min(balance, available)
                        selected[invoice["id"]] = part
                        available = money(available-part)
            if sum(selected.values(), Decimal("0")) > amount:
                raise AppError("مجموع المبالغ الموزعة أكبر من مبلغ السند.")
            for invoice_id, part in selected.items():
                invoice = self.get(conn, "invoices", invoice_id)
                if invoice["member_id"] != member["id"] or invoice["status"] != "issued":
                    raise AppError("إحدى الفواتير غير صالحة لهذا العضو أو غير صادرة.")
                if part > InvoiceService.invoice_balance(conn, invoice_id):
                    raise AppError(f"المبلغ المخصص للفاتورة {invoice['invoice_no']} يتجاوز رصيدها.")
            number = self.next_number(conn, "receipt")
            cur = conn.execute("""INSERT INTO payments(receipt_no,member_id,payment_date,amount,method,reference,account_id,user_id,notes,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (number, member["id"], payment_date, float(amount), data["method"], data.get("reference", "").strip(),
                account["id"], user.id, data.get("notes", ""), now()))
            payment_id = cur.lastrowid
            for invoice_id, part in selected.items():
                conn.execute("INSERT INTO payment_allocations(payment_id,invoice_id,amount) VALUES(?,?,?)", (payment_id, invoice_id, float(part)))
            txn_no = self.next_number(conn, "transaction")
            conn.execute("""INSERT INTO transactions(txn_no,account_id,kind,payment_id,amount,transaction_date,category,description,reference,created_by,created_at)
                VALUES(?,?,'income',?,?,?,'أداءات الأعضاء',?,?,?,?)""", (txn_no, account["id"], payment_id, float(amount), payment_date,
                f"سند قبض {number} — {member['full_name']} ({member['number']})", data.get("reference", ""), user.id, now()))
            credit = money(amount-sum(selected.values(), Decimal("0")))
            self.audit(conn, user, "تسجيل سند قبض", "payments", payment_id, after={"receipt_no": number, "amount": float(amount),
                       "allocations": {str(k): float(v) for k, v in selected.items()}, "member_credit": float(credit)})
            return payment_id

    def cancel(self, user: User, payment_id: int, reason: str) -> None:
        if user.role != "admin":
            raise AppError("إلغاء سند القبض يتطلب مدير النظام.")
        if not reason.strip():
            raise AppError("سبب إلغاء السند مطلوب.")
        with self.db.transaction() as conn:
            payment = self.get(conn, "payments", payment_id)
            if payment["status"] == "cancelled":
                raise AppError("السند ملغى مسبقاً.")
            conn.execute("UPDATE payments SET status='cancelled',cancelled_at=?,cancelled_by=?,cancel_reason=? WHERE id=?", (now(), user.id, reason.strip(), payment_id))
            conn.execute("UPDATE transactions SET status='cancelled' WHERE payment_id=?", (payment_id,))
            # Allocations remain as immutable historical evidence; posted-balance queries ignore them.
            self.audit(conn, user, "إلغاء سند قبض مع حفظه", "payments", payment_id, row_dict(payment), {"status": "cancelled"}, reason)

    def record_print(self, user: User, payment_id: int, output_type: str) -> None:
        with self.db.transaction() as conn:
            self.get(conn, "payments", payment_id)
            conn.execute("INSERT INTO receipt_prints(payment_id,printed_at,printed_by,output_type) VALUES(?,?,?,?)", (payment_id, now(), user.id, output_type))
            self.audit(conn, user, "طباعة أو إعادة طباعة سند", "payments", payment_id, after={"output_type": output_type})
