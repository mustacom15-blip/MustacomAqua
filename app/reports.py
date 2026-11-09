from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .finance import FinanceService
from .services import AppError, BaseService, D, money

STATUS_AR = {"active": "نشط", "suspended": "معلق", "withdrawn": "منسحب", "draft": "مسودة", "issued": "صادرة", "cancelled": "ملغاة",
             "posted": "مرحل", "open": "مفتوحة", "assigned": "مُسندة", "in_progress": "جارية", "completed": "منجزة", "closed": "مغلقة"}
METHOD_AR = {"cash": "نقداً", "cheque": "شيك", "transfer": "تحويل بنكي"}
TYPE_AR = {"leak": "تسرب", "outage": "انقطاع الماء", "low_pressure": "ضعف الضغط", "faulty_meter": "عطل عداد", "quality": "جودة الماء", "other": "أخرى"}

@dataclass
class ReportResult:
    title: str
    headers: list[str]
    rows: list[list[Any]]
    summary: list[tuple[str, Any]] = field(default_factory=list)
    subtitle: str = ""
    numeric_columns: set[int] = field(default_factory=set)


class ReportService(BaseService):
    def dashboard(self, period: str) -> dict:
        db = self.db
        stats = {"period": period}
        for status in ("active", "suspended", "withdrawn"):
            stats[status] = db.one("SELECT COUNT(*) FROM members WHERE archived=0 AND status=?", (status,))[0]
        stats["missing_readings"] = db.one("""SELECT COUNT(*) FROM members m WHERE m.archived=0 AND m.status='active' AND NOT EXISTS
            (SELECT 1 FROM readings r WHERE r.member_id=m.id AND r.period=? AND r.status!='cancelled')""", (period,))[0]
        stats["consumption"] = db.one("SELECT COALESCE(SUM(consumption),0) FROM readings WHERE period=? AND status='approved'", (period,))[0]
        inv = db.one("""SELECT COUNT(*),COALESCE(SUM(total_due),0),COALESCE(SUM(total_due-COALESCE((SELECT SUM(pa.amount)
            FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=invoices.id AND p.status='posted'),0)),0)
            FROM invoices WHERE period=? AND status='issued'""", (period,))
        stats.update(invoices_issued=inv[0], invoiced_amount=inv[1], unpaid_period=inv[2])
        stats["paid_period"] = db.one("""SELECT COALESCE(SUM(pa.amount),0) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            JOIN invoices i ON i.id=pa.invoice_id WHERE i.period=? AND p.status='posted'""", (period,))[0]
        debt = db.one("""SELECT COALESCE(SUM(i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0)),0),COUNT(*) FROM invoices i WHERE i.status='issued' AND
            i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0)>0.004""")
        stats.update(total_debt=debt[0], unpaid_invoices=debt[1])
        stats["overdue"] = db.one("""SELECT COALESCE(SUM(i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0)),0) FROM invoices i WHERE i.status='issued' AND i.due_date<? AND
            i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0)>0.004""", (date.today().isoformat(),))[0]
        with db.connect() as conn:
            accounts = conn.execute("SELECT * FROM accounts WHERE active=1").fetchall()
            balances = [(a["name"], a["type"], FinanceService.balance(conn, a["id"])) for a in accounts]
        stats["cash"] = sum((b for _, t, b in balances if t == "cash"), Decimal("0"))
        stats["bank"] = sum((b for _, t, b in balances if t == "bank"), Decimal("0"))
        stats["open_complaints"] = db.one("SELECT COUNT(*) FROM complaints WHERE status NOT IN ('completed','closed','cancelled')")[0]
        stats["overdue_maintenance"] = db.one("SELECT COUNT(*) FROM complaints WHERE status NOT IN ('completed','closed','cancelled') AND due_date<?", (date.today().isoformat(),))[0]
        stats["recent_readings"] = [dict(r) for r in db.query("""SELECT r.reading_date,m.number,m.full_name,r.period,r.current_reading,r.consumption,r.status
            FROM readings r JOIN members m ON m.id=r.member_id ORDER BY r.id DESC LIMIT 8""")]
        stats["recent_transactions"] = [dict(r) for r in db.query("""SELECT t.transaction_date,t.txn_no,t.kind,a.name account,t.amount,t.description
            FROM transactions t JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC LIMIT 8""")]
        factor = float(self.setting("high_consumption_factor", "2.5") or 2.5)
        stats["high_consumption"] = [dict(r) for r in db.query("""SELECT m.number,m.full_name,r.period,r.consumption,
            (SELECT AVG(r2.consumption) FROM readings r2 WHERE r2.member_id=r.member_id AND r2.id<r.id AND r2.status='approved') previous_average
            FROM readings r JOIN members m ON m.id=r.member_id WHERE r.status='approved' AND r.period=? AND r.consumption>10 AND
            r.consumption>(SELECT AVG(r2.consumption) FROM readings r2 WHERE r2.member_id=r.member_id AND r2.id<r.id AND r2.status='approved')*?""", (period, factor))]
        stats["zero_alerts"] = [dict(r) for r in db.query("""SELECT m.number,m.full_name,COUNT(*) zeros FROM readings r JOIN members m ON m.id=r.member_id
            WHERE r.status='approved' GROUP BY m.id HAVING SUM(CASE WHEN r.consumption=0 THEN 1 ELSE 0 END)>=? ORDER BY zeros DESC""",
            (int(self.setting("zero_reading_alert_count", "3") or 3),))]
        stats["faulty_meters"] = [dict(r) for r in db.query("""SELECT m.number,m.full_name,c.complaint_no,c.reported_date,c.status FROM complaints c
            LEFT JOIN members m ON m.id=c.member_id WHERE c.complaint_type='faulty_meter' AND c.status NOT IN ('completed','closed','cancelled')""")]
        return stats

    def build(self, report_type: str, filters: dict[str, Any]) -> ReportResult:
        method = getattr(self, f"report_{report_type}", None)
        if not method:
            raise AppError("نوع التقرير غير معروف.")
        return method(filters)

    def report_members(self, f: dict) -> ReportResult:
        where, params = ["m.archived=0"], []
        if f.get("status"): where.append("m.status=?"); params.append(f["status"])
        if f.get("area_id"): where.append("m.area_id=?"); params.append(f["area_id"])
        rows = self.db.query(f"""SELECT m.number,m.full_name,m.phone,a.name area,m.status,m.membership_date,m.initial_reading,m.address
            FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE {' AND '.join(where)} ORDER BY CAST(m.number AS REAL),m.number""", tuple(params))
        return ReportResult("تقرير الأعضاء", ["الرقم/العداد", "الاسم", "الهاتف", "المنطقة", "الحالة", "تاريخ العضوية", "قراءة أولية", "العنوان"],
                            [[r["number"],r["full_name"],r["phone"],r["area"],STATUS_AR.get(r["status"],r["status"]),r["membership_date"],r["initial_reading"],r["address"]] for r in rows],
                            [("عدد الأعضاء", len(rows))])

    def report_statement(self, f: dict) -> ReportResult:
        member_id = int(f["member_id"])
        member = self.db.one("SELECT m.*,a.name area FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE m.id=?", (member_id,))
        if not member: raise AppError("اختر العضو.")
        rows = self.db.query("""SELECT * FROM (
          SELECT i.issue_date date,i.invoice_no document,'فاتورة' type,i.total_due debit,0 credit,i.period detail,i.id sort_id FROM invoices i WHERE i.member_id=? AND i.status='issued'
          UNION ALL
          SELECT p.payment_date,p.receipt_no,'سند قبض',0,p.amount,'أداء '+p.method,p.id FROM payments p WHERE p.member_id=? AND p.status='posted'
        ) ORDER BY date,sort_id""", (member_id, member_id))
        balance = Decimal("0")
        output = []
        for r in rows:
            balance += D(r["debit"])-D(r["credit"])
            output.append([r["date"], r["document"], r["type"], r["detail"], float(money(r["debit"])), float(money(r["credit"])), float(money(balance))])
        invoices = self.db.one("SELECT COALESCE(SUM(total_due),0) FROM invoices WHERE member_id=? AND status='issued'", (member_id,))[0]
        paid = self.db.one("SELECT COALESCE(SUM(amount),0) FROM payments WHERE member_id=? AND status='posted'", (member_id,))[0]
        credit_row = self.db.one("""SELECT COALESCE(SUM(p.amount-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.payment_id=p.id),0)),0)
             FROM payments p WHERE p.member_id=? AND p.status='posted'""", (member_id,))[0]
        return ReportResult(f"كشف حساب العضو: {member['full_name']} — {member['number']}",
            ["التاريخ", "الوثيقة", "النوع", "البيان", "مدين", "دائن", "الرصيد"], output,
            [("المنطقة", member["area"] or "—"), ("الهاتف", member["phone"] or "—"), ("مجموع الفواتير", money(invoices)),
             ("مجموع الأداءات", money(paid)), ("الرصيد المستحق", money(balance)), ("رصيد دائن غير مخصص", money(credit_row))],
            numeric_columns={4,5,6})

    def report_readings(self, f: dict) -> ReportResult:
        where, params = ["r.status!='cancelled'"], []
        if f.get("period"): where.append("r.period=?"); params.append(f["period"])
        if f.get("area_id"): where.append("m.area_id=?"); params.append(f["area_id"])
        rows = self.db.query(f"""SELECT m.number,m.full_name,a.name area,r.period,r.reading_date,r.previous_reading,r.current_reading,r.consumption,r.reader_name,r.status,r.notes
            FROM readings r JOIN members m ON m.id=r.member_id LEFT JOIN areas a ON a.id=m.area_id WHERE {' AND '.join(where)} ORDER BY a.name,m.number""", tuple(params))
        total = sum((D(r["consumption"]) for r in rows), Decimal("0"))
        return ReportResult("تقرير القراءات والاستهلاك", ["الرقم", "العضو", "المنطقة", "الفترة", "التاريخ", "السابقة", "الحالية", "الاستهلاك", "القارئ", "الحالة", "ملاحظات"],
            [[r["number"],r["full_name"],r["area"],r["period"],r["reading_date"],r["previous_reading"],r["current_reading"],r["consumption"],r["reader_name"],STATUS_AR.get(r["status"]),r["notes"]] for r in rows],
            [("عدد القراءات",len(rows)),("مجموع الاستهلاك م³",money(total))], numeric_columns={5,6,7})

    def report_invoices(self, f: dict) -> ReportResult:
        where, params = ["1=1"], []
        for key, col in (("period","i.period"),("area_id","m.area_id")):
            if f.get(key): where.append(f"{col}=?"); params.append(f[key])
        balance_expr = "i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0)"
        if f.get("status") in ("paid","unpaid"):
            where.append("i.status='issued'")
            where.append(balance_expr+("<=0.004" if f["status"]=="paid" else ">0.004"))
        elif f.get("status"):
            where.append("i.status=?"); params.append(f["status"])
        rows = self.db.query(f"""SELECT i.*,m.number,m.full_name,a.name area,
            CASE WHEN i.status='cancelled' THEN 0 ELSE i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0) END balance
            FROM invoices i JOIN members m ON m.id=i.member_id LEFT JOIN areas a ON a.id=m.area_id WHERE {' AND '.join(where)} ORDER BY i.id DESC""", tuple(params))
        return ReportResult("تقرير الفواتير", ["الرقم", "العضو/العداد", "الاسم", "المنطقة", "الفترة", "الإصدار", "الاستهلاك", "المجموع", "المتبقي", "الحالة"],
            [[r["invoice_no"],r["number"],r["full_name"],r["area"],r["period"],r["issue_date"],r["consumption"],r["total_due"],r["balance"],STATUS_AR.get(r["status"],r["status"])] for r in rows],
            [("عدد الفواتير",len(rows)),("المجموع",money(sum((D(r["total_due"]) for r in rows if r["status"]!="cancelled"),Decimal(0)))),
             ("المتبقي",money(sum((D(r["balance"]) for r in rows if r["status"]=="issued"),Decimal(0))))], numeric_columns={6,7,8})

    def report_debts(self, f: dict) -> ReportResult:
        where, params = ["i.status='issued'"], []
        if f.get("area_id"): where.append("m.area_id=?"); params.append(f["area_id"])
        if f.get("period"): where.append("i.period=?"); params.append(f["period"])
        if f.get("overdue_only"): where.append("i.due_date<?"); params.append(date.today().isoformat())
        if f.get("min_age"):
            cutoff = date.today().toordinal()-int(f["min_age"])
            where.append("i.due_date<?"); params.append(date.fromordinal(cutoff).isoformat())
        having = "HAVING SUM(i.total_due)-SUM(COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0))>0.004"
        rows = self.db.query(f"""SELECT m.id,m.number,m.full_name,m.phone,a.name area,COUNT(i.id) invoice_count,
            SUM(i.total_due)-SUM(COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id WHERE pa.invoice_id=i.id AND p.status='posted'),0)) debt,
            MIN(i.due_date) oldest_due,MAX(0,CAST(julianday('now')-julianday(MIN(i.due_date)) AS INTEGER)) age
            FROM invoices i JOIN members m ON m.id=i.member_id LEFT JOIN areas a ON a.id=m.area_id WHERE {' AND '.join(where)}
            GROUP BY m.id {having} ORDER BY debt DESC""", tuple(params))
        output = [[r["number"],r["full_name"],r["phone"],r["area"],r["invoice_count"],r["debt"],r["oldest_due"],r["age"]] for r in rows]
        if f.get("min_value"):
            output = [r for r in output if D(r[5]) >= D(f["min_value"])]
        return ReportResult("تقرير الديون والمبالغ المتأخرة", ["الرقم", "العضو", "الهاتف", "المنطقة", "فواتير غير مؤداة", "الدين", "أقدم استحقاق", "أيام التأخير"], output,
            [("عدد الأعضاء",len(output)),("مجموع الديون",money(sum((D(r[5]) for r in output),Decimal(0))))], numeric_columns={4,5,7})

    def report_payments(self, f: dict) -> ReportResult:
        where, params = ["p.status='posted'"], []
        if f.get("date_from"): where.append("p.payment_date>=?"); params.append(f["date_from"])
        if f.get("date_to"): where.append("p.payment_date<=?"); params.append(f["date_to"])
        if f.get("method"): where.append("p.method=?"); params.append(f["method"])
        if f.get("user_id"): where.append("p.user_id=?"); params.append(f["user_id"])
        rows = self.db.query(f"""SELECT p.*,m.number,m.full_name,u.full_name username,a.name account,
            COALESCE((SELECT SUM(amount) FROM payment_allocations WHERE payment_id=p.id),0) allocated,
            (SELECT COUNT(*) FROM receipt_prints WHERE payment_id=p.id) prints
            FROM payments p JOIN members m ON m.id=p.member_id LEFT JOIN users u ON u.id=p.user_id JOIN accounts a ON a.id=p.account_id
            WHERE {' AND '.join(where)} ORDER BY p.payment_date DESC,p.id DESC""", tuple(params))
        return ReportResult("تقرير الأداءات وسندات القبض", ["السند", "التاريخ", "الرقم", "العضو", "المبلغ", "الطريقة", "المرجع", "الحساب", "المستخدم", "المخصص", "رصيد دائن", "الطبعات"],
            [[r["receipt_no"],r["payment_date"],r["number"],r["full_name"],r["amount"],METHOD_AR.get(r["method"]),r["reference"],r["account"],r["username"],r["allocated"],D(r["amount"])-D(r["allocated"]),r["prints"]] for r in rows],
            [("عدد السندات",len(rows)),("مجموع الأداءات",money(sum((D(r["amount"]) for r in rows),Decimal(0))))], numeric_columns={4,9,10})

    def report_finance(self, f: dict) -> ReportResult:
        where, params = ["t.status='posted'"], []
        if f.get("date_from"): where.append("t.transaction_date>=?"); params.append(f["date_from"])
        if f.get("date_to"): where.append("t.transaction_date<=?"); params.append(f["date_to"])
        if f.get("account_id"): where.append("t.account_id=?"); params.append(f["account_id"])
        rows = self.db.query(f"""SELECT t.*,a.name account,a.type,u.full_name username FROM transactions t JOIN accounts a ON a.id=t.account_id
            LEFT JOIN users u ON u.id=t.created_by WHERE {' AND '.join(where)} ORDER BY t.transaction_date,t.id""", tuple(params))
        labels = {"income":"دخل","expense":"مصروف","transfer_in":"تحويل وارد","transfer_out":"تحويل صادر","adjustment":"تسوية"}
        income = sum((D(r["amount"]) for r in rows if r["kind"] in ("income","transfer_in")),Decimal(0))
        expense = sum((D(r["amount"]) for r in rows if r["kind"] in ("expense","transfer_out")),Decimal(0))
        return ReportResult("تقرير الصندوق والبنك والمداخيل والمصاريف", ["الوثيقة", "التاريخ", "الحساب", "النوع", "التصنيف", "البيان", "المرجع", "المبلغ", "المستخدم"],
            [[r["txn_no"],r["transaction_date"],r["account"],labels.get(r["kind"],r["kind"]),r["category"],r["description"],r["reference"],r["amount"],r["username"]] for r in rows],
            [("الوارد (شامل التحويلات)",money(income)),("الصادر (شامل التحويلات)",money(expense)),("الفرق",money(income-expense))], numeric_columns={7})

    def report_complaints(self, f: dict) -> ReportResult:
        where, params = ["1=1"], []
        if f.get("status"): where.append("c.status=?"); params.append(f["status"])
        if f.get("date_from"): where.append("c.reported_date>=?"); params.append(f["date_from"])
        if f.get("date_to"): where.append("c.reported_date<=?"); params.append(f["date_to"])
        rows = self.db.query(f"""SELECT c.*,m.number,m.full_name FROM complaints c LEFT JOIN members m ON m.id=c.member_id WHERE {' AND '.join(where)} ORDER BY c.id DESC""", tuple(params))
        return ReportResult("تقرير الشكايات وأعمال الصيانة", ["الرقم", "التاريخ", "العضو", "الموقع", "النوع", "الأولوية", "الحالة", "المسؤول", "التشخيص", "العمل والقطع", "التكلفة", "الإنجاز"],
            [[r["complaint_no"],r["reported_date"],(r["number"]+" "+(r["full_name"] or "")) if r["number"] else "شبكة",r["location"],TYPE_AR.get(r["complaint_type"]),r["priority"],STATUS_AR.get(r["status"],r["status"]),r["assigned_to"],r["diagnosis"],(r["work_performed"] or "")+" "+(r["parts_used"] or ""),r["cost"],r["completion_date"]] for r in rows],
            [("عدد السجلات",len(rows)),("التكلفة",money(sum((D(r["cost"]) for r in rows),Decimal(0))))], numeric_columns={10})

    def report_inventory(self, f: dict) -> ReportResult:
        rows = self.db.query("SELECT * FROM inventory_items WHERE active=1 ORDER BY category,name")
        return ReportResult("تقرير المخزون والمعدات", ["الرمز", "المادة", "التصنيف", "الوحدة", "الكمية", "الحد الأدنى", "ثمن الشراء", "القيمة", "المورد", "تنبيه"],
            [[r["code"],r["name"],r["category"],r["unit"],r["quantity"],r["min_quantity"],r["purchase_price"],D(r["quantity"])*D(r["purchase_price"]),r["supplier"],"مخزون منخفض" if r["quantity"]<=r["min_quantity"] else ""] for r in rows],
            [("المواد المنخفضة",sum(1 for r in rows if r["quantity"]<=r["min_quantity"]))], numeric_columns={4,5,6,7})

    def report_consumption_comparison(self, f: dict) -> ReportResult:
        p1, p2 = f.get("period"), f.get("period2")
        if not p1 or not p2: raise AppError("حدد فترتين للمقارنة.")
        rows = self.db.query("""SELECT m.number,m.full_name,a.name area,
          COALESCE((SELECT consumption FROM readings r WHERE r.member_id=m.id AND r.period=? AND r.status='approved'),0) c1,
          COALESCE((SELECT consumption FROM readings r WHERE r.member_id=m.id AND r.period=? AND r.status='approved'),0) c2
          FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE m.archived=0 ORDER BY m.number""", (p1,p2))
        output = []
        for r in rows:
            diff = D(r["c2"])-D(r["c1"])
            pct = float(diff/D(r["c1"])*100) if D(r["c1"]) else None
            output.append([r["number"],r["full_name"],r["area"],r["c1"],r["c2"],float(diff),f"{pct:.1f}%" if pct is not None else "—"])
        return ReportResult(f"مقارنة الاستهلاك: {p1} / {p2}", ["الرقم", "العضو", "المنطقة", p1, p2, "الفرق م³", "التغير"], output,
            [("مجموع الفترة الأولى",money(sum((D(r[3]) for r in output),Decimal(0)))),("مجموع الفترة الثانية",money(sum((D(r[4]) for r in output),Decimal(0))))], numeric_columns={3,4,5})

    def report_summary(self, f: dict) -> ReportResult:
        year = str(f.get("year") or date.today().year)
        rows = self.db.query("""SELECT periods.period,
          COALESCE((SELECT SUM(consumption) FROM readings WHERE period=periods.period AND status='approved'),0) consumption,
          COALESCE((SELECT SUM(total_due) FROM invoices WHERE period=periods.period AND status='issued'),0) invoiced,
          COALESCE((SELECT SUM(p.amount) FROM payments p WHERE substr(p.payment_date,1,7)=periods.period AND p.status='posted'),0) paid,
          COALESCE((SELECT SUM(amount) FROM expenses WHERE substr(expense_date,1,7)=periods.period AND status='posted'),0) expenses
          FROM (SELECT DISTINCT period FROM readings WHERE period LIKE ? UNION SELECT DISTINCT period FROM invoices WHERE period LIKE ?) periods ORDER BY period""", (year+"%",year+"%"))
        return ReportResult(f"الملخص الشهري والسنوي — {year}", ["الفترة", "الاستهلاك م³", "الفواتير", "الأداءات", "المصاريف", "صافي التدفق"],
            [[r["period"],r["consumption"],r["invoiced"],r["paid"],r["expenses"],D(r["paid"])-D(r["expenses"])] for r in rows],
            [("فواتير السنة",money(sum((D(r["invoiced"]) for r in rows),Decimal(0)))),("أداءات السنة",money(sum((D(r["paid"]) for r in rows),Decimal(0)))),
             ("مصاريف السنة",money(sum((D(r["expenses"]) for r in rows),Decimal(0))))], numeric_columns={1,2,3,4,5})
