from __future__ import annotations
import shutil
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .database import now
from .paths import data_dir
from .security import User
from .services import AppError, BaseService, D, money, row_dict, valid_date


class FinanceService(BaseService):
    def save_account(self, user: User, data: dict, account_id: int | None = None) -> int:
        self.require(user, "finance.manage")
        if not data.get("name", "").strip() or data.get("type") not in ("cash", "bank"):
            raise AppError("اسم الحساب ونوعه (صندوق أو بنك) مطلوبان.")
        opening = money(data.get("opening_balance", 0))
        with self.db.transaction() as conn:
            before = row_dict(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()) if account_id else None
            if before and conn.execute("SELECT COUNT(*) FROM transactions WHERE account_id=?", (account_id,)).fetchone()[0]:
                if D(before["opening_balance"]) != opening:
                    raise AppError("لا يغير الرصيد الافتتاحي بعد وجود حركات؛ استخدم قيد تسوية موثقاً.")
            if account_id:
                conn.execute("UPDATE accounts SET name=?,type=?,opening_balance=?,active=? WHERE id=?",
                             (data["name"].strip(), data["type"], float(opening), int(data.get("active", True)), account_id))
                record_id = account_id
                action = "تعديل حساب مالي"
            else:
                cur = conn.execute("INSERT INTO accounts(name,type,opening_balance,active) VALUES(?,?,?,?)",
                                   (data["name"].strip(), data["type"], float(opening), int(data.get("active", True))))
                record_id = cur.lastrowid
                action = "إضافة حساب مالي"
            self.audit(conn, user, action, "accounts", record_id, before, data)
            return record_id

    @staticmethod
    def balance(conn, account_id: int, at_date: str | None = None) -> Decimal:
        date_filter = " AND t.transaction_date<=?" if at_date else ""
        params: list = [account_id]
        if at_date:
            params = [at_date, account_id]
        row = conn.execute(f"""SELECT a.opening_balance+COALESCE(SUM(CASE WHEN t.status='posted' AND t.kind IN ('income','transfer_in')
            THEN t.amount WHEN t.status='posted' AND t.kind IN ('expense','transfer_out') THEN -t.amount
            WHEN t.status='posted' AND t.kind='adjustment' THEN t.amount ELSE 0 END),0)
            FROM accounts a LEFT JOIN transactions t ON t.account_id=a.id{date_filter} WHERE a.id=? GROUP BY a.id""", params).fetchone()
        return money(row[0] if row else 0)

    def add_expense(self, user: User, data: dict) -> int:
        self.require(user, "finance.manage")
        amount = money(data["amount"])
        if amount <= 0 or not data.get("description", "").strip() or not data.get("category", "").strip():
            raise AppError("المبلغ والتصنيف والوصف مطلوبة، والمبلغ موجب.")
        expense_date = valid_date(data["expense_date"], "تاريخ المصروف")
        attachment = ""
        if data.get("attachment"):
            src = Path(data["attachment"])
            if not src.is_file():
                raise AppError("وثيقة المصروف غير موجودة.")
            folder = data_dir() / "attachments" / "expenses"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{datetime.now():%Y%m%d%H%M%S%f}_{src.name}"
            shutil.copy2(src, target)
            attachment = str(target)
        with self.db.transaction() as conn:
            account = self.get(conn, "accounts", int(data["account_id"]))
            if not account["active"]:
                raise AppError("الحساب موقوف.")
            number = self.next_number(conn, "expense")
            cur = conn.execute("""INSERT INTO expenses(expense_no,expense_date,amount,category,description,account_id,attachment_path,created_at,created_by)
                VALUES(?,?,?,?,?,?,?,?,?)""", (number, expense_date, float(amount), data["category"].strip(), data["description"].strip(),
                account["id"], attachment or None, now(), user.id))
            expense_id = cur.lastrowid
            txn_no = self.next_number(conn, "transaction")
            cur_tx = conn.execute("""INSERT INTO transactions(txn_no,account_id,kind,expense_id,amount,transaction_date,category,description,reference,created_by,created_at)
                VALUES(?,?,'expense',?,?,?,?,?,?,?,?)""", (txn_no, account["id"], expense_id, float(amount), expense_date,
                data["category"].strip(), data["description"].strip(), number, user.id, now()))
            conn.execute("UPDATE transactions SET expense_id=? WHERE id=?", (expense_id, cur_tx.lastrowid))
            self.audit(conn, user, "تسجيل مصروف", "expenses", expense_id, after={**data, "attachment": attachment, "expense_no": number})
            return expense_id

    def cancel_expense(self, user: User, expense_id: int, reason: str) -> None:
        if user.role != "admin" or not reason.strip():
            raise AppError("الإلغاء يتطلب مدير النظام وسبباً واضحاً.")
        with self.db.transaction() as conn:
            expense = self.get(conn, "expenses", expense_id)
            if expense["status"] == "cancelled":
                raise AppError("المصروف ملغى مسبقاً.")
            conn.execute("UPDATE expenses SET status='cancelled',cancelled_at=?,cancelled_by=?,cancel_reason=? WHERE id=?", (now(), user.id, reason.strip(), expense_id))
            conn.execute("UPDATE transactions SET status='cancelled' WHERE expense_id=?", (expense_id,))
            self.audit(conn, user, "إلغاء مصروف", "expenses", expense_id, row_dict(expense), {"status": "cancelled"}, reason)

    def transfer(self, user: User, source_id: int, destination_id: int, amount, transfer_date: str, description: str) -> str:
        self.require(user, "finance.manage")
        amount = money(amount)
        if source_id == destination_id or amount <= 0:
            raise AppError("اختر حسابين مختلفين ومبلغاً موجباً.")
        valid_date(transfer_date)
        group = str(uuid.uuid4())
        with self.db.transaction() as conn:
            source, destination = self.get(conn, "accounts", source_id), self.get(conn, "accounts", destination_id)
            if not source["active"] or not destination["active"]:
                raise AppError("أحد الحسابين موقوف.")
            if self.balance(conn, source_id) < amount:
                raise AppError("رصيد الحساب المصدر غير كاف لإتمام التحويل.")
            for account, kind in ((source, "transfer_out"), (destination, "transfer_in")):
                txn_no = self.next_number(conn, "transaction")
                conn.execute("""INSERT INTO transactions(txn_no,account_id,kind,amount,transaction_date,category,description,transfer_group,created_by,created_at)
                    VALUES(?,?,?,?,?,'تحويل داخلي',?,?,?,?)""", (txn_no, account["id"], kind, float(amount), transfer_date,
                    description.strip() or f"تحويل من {source['name']} إلى {destination['name']}", group, user.id, now()))
            self.audit(conn, user, "تحويل بين الحسابات", "transactions", group, after={"source": source_id, "destination": destination_id, "amount": float(amount)})
            return group

    def open_cash_session(self, user: User, account_id: int, opening_balance, notes: str = "") -> int:
        self.require(user, "finance.manage")
        with self.db.transaction() as conn:
            account = self.get(conn, "accounts", account_id)
            if account["type"] != "cash":
                raise AppError("جلسة الصندوق متاحة للحسابات النقدية فقط.")
            if conn.execute("SELECT COUNT(*) FROM cash_sessions WHERE account_id=? AND status='open'", (account_id,)).fetchone()[0]:
                raise AppError("توجد جلسة صندوق مفتوحة لهذا الحساب.")
            last_txn = conn.execute("SELECT COALESCE(MAX(id),0) FROM transactions WHERE account_id=?", (account_id,)).fetchone()[0]
            cur = conn.execute("INSERT INTO cash_sessions(user_id,account_id,opened_at,opening_txn_id,opening_balance,status,notes) VALUES(?,?,?,?,?,'open',?)",
                               (user.id, account_id, now(), last_txn, float(money(opening_balance)), notes))
            self.audit(conn, user, "فتح جلسة صندوق", "cash_sessions", cur.lastrowid, after={"opening_balance": float(money(opening_balance))})
            return cur.lastrowid

    def close_cash_session(self, user: User, session_id: int, actual_closing, notes: str = "") -> Decimal:
        self.require(user, "finance.manage")
        actual = money(actual_closing)
        with self.db.transaction() as conn:
            session = self.get(conn, "cash_sessions", session_id)
            if session["status"] != "open":
                raise AppError("الجلسة مغلقة مسبقاً.")
            close = now()
            row = conn.execute("""SELECT
              COALESCE(SUM(CASE WHEN kind IN ('income','transfer_in') AND status='posted' THEN amount ELSE 0 END),0),
              COALESCE(SUM(CASE WHEN kind IN ('expense','transfer_out') AND status='posted' THEN amount ELSE 0 END),0)
              FROM transactions WHERE account_id=? AND id>?""", (session["account_id"], session["opening_txn_id"])).fetchone()
            receipts, expenses = money(row[0]), money(row[1])
            expected = money(D(session["opening_balance"])+receipts-expenses)
            difference = money(actual-expected)
            conn.execute("""UPDATE cash_sessions SET expected_receipts=?,expected_expenses=?,expected_closing=?,actual_closing=?,difference=?,
                closed_at=?,status='closed',notes=? WHERE id=?""", (float(receipts), float(expenses), float(expected), float(actual), float(difference), close,
                "\n".join(x for x in (session["notes"], notes) if x), session_id))
            self.audit(conn, user, "إغلاق جلسة صندوق", "cash_sessions", session_id, row_dict(session), {"expected": float(expected), "actual": float(actual), "difference": float(difference)})
            return difference
