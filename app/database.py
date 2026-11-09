from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

SCHEMA = r"""
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','president','treasurer','reader','reception','auditor')),
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, last_login TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, user_id INTEGER, username TEXT NOT NULL,
 action TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT, reason TEXT,
 before_json TEXT, after_json TEXT
);
CREATE TABLE IF NOT EXISTS areas (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS members (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL UNIQUE COLLATE NOCASE,
 full_name TEXT NOT NULL, phone TEXT, address TEXT, area_id INTEGER REFERENCES areas(id) ON DELETE RESTRICT,
 national_id TEXT, membership_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','withdrawn')),
 meter_install_date TEXT, meter_location TEXT, initial_reading REAL NOT NULL DEFAULT 0 CHECK(initial_reading>=0),
 initial_reading_date TEXT, notes TEXT, archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS member_documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 file_path TEXT NOT NULL, original_name TEXT NOT NULL, added_at TEXT NOT NULL, added_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS member_number_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 old_number TEXT NOT NULL, new_number TEXT NOT NULL, reason TEXT NOT NULL, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 username TEXT NOT NULL, changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS readings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 period TEXT NOT NULL, reading_date TEXT NOT NULL, previous_reading REAL NOT NULL, current_reading REAL NOT NULL,
 consumption REAL NOT NULL, reader_id INTEGER REFERENCES users(id) ON DELETE SET NULL, reader_name TEXT NOT NULL,
 notes TEXT, status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','cancelled')),
 correction_reason TEXT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reading_member_period ON readings(member_id,period) WHERE status!='cancelled';
CREATE TABLE IF NOT EXISTS reading_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE RESTRICT,
 changed_at TEXT NOT NULL, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, username TEXT NOT NULL,
 reason TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meter_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 event_type TEXT NOT NULL CHECK(event_type IN ('replacement','repair','fault')), event_date TEXT NOT NULL,
 old_reading REAL NOT NULL DEFAULT 0, new_reading REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL,
 technician TEXT, cost REAL NOT NULL DEFAULT 0, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tariffs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT,
 fixed_fee REAL NOT NULL DEFAULT 0, late_fee REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tariff_tiers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, tariff_id INTEGER NOT NULL REFERENCES tariffs(id) ON DELETE CASCADE,
 from_qty REAL NOT NULL, to_qty REAL, unit_price REAL NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
 CHECK(from_qty>=0 AND unit_price>=0 AND (to_qty IS NULL OR to_qty>from_qty))
);
CREATE TABLE IF NOT EXISTS invoices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT NOT NULL UNIQUE,
 member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 reading_id INTEGER UNIQUE REFERENCES readings(id) ON DELETE RESTRICT,
 period TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'water' CHECK(kind IN ('water','contribution')),
 tariff_id INTEGER REFERENCES tariffs(id) ON DELETE RESTRICT, tariff_snapshot_json TEXT,
 previous_reading REAL NOT NULL DEFAULT 0, current_reading REAL NOT NULL DEFAULT 0, consumption REAL NOT NULL DEFAULT 0,
 consumption_amount REAL NOT NULL DEFAULT 0, fixed_fee REAL NOT NULL DEFAULT 0, other_fee REAL NOT NULL DEFAULT 0,
 late_fee REAL NOT NULL DEFAULT 0, tax_amount REAL NOT NULL DEFAULT 0, prior_balance REAL NOT NULL DEFAULT 0, total_due REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','issued','cancelled')),
 issue_date TEXT, due_date TEXT, notes TEXT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL, cancelled_by INTEGER REFERENCES users(id) ON DELETE SET NULL, cancelled_at TEXT, cancel_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_member_period ON invoices(member_id,period,kind) WHERE status!='cancelled';
CREATE TABLE IF NOT EXISTS invoice_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
 label TEXT NOT NULL, quantity REAL NOT NULL DEFAULT 1, unit_price REAL NOT NULL DEFAULT 0, amount REAL NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, type TEXT NOT NULL CHECK(type IN ('cash','bank')),
 opening_balance REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_no TEXT NOT NULL UNIQUE,
 member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT, payment_date TEXT NOT NULL,
 amount REAL NOT NULL CHECK(amount>0), method TEXT NOT NULL CHECK(method IN ('cash','cheque','transfer')),
 reference TEXT, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted','cancelled')),
 notes TEXT, created_at TEXT NOT NULL, cancelled_at TEXT, cancelled_by INTEGER REFERENCES users(id) ON DELETE SET NULL, cancel_reason TEXT
);
CREATE TABLE IF NOT EXISTS payment_allocations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT, amount REAL NOT NULL CHECK(amount>0),
 UNIQUE(payment_id,invoice_id)
);
CREATE TABLE IF NOT EXISTS receipt_prints (
 id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
 printed_at TEXT NOT NULL, printed_by INTEGER REFERENCES users(id) ON DELETE SET NULL, output_type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, txn_no TEXT NOT NULL UNIQUE,
 account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('income','expense','transfer_in','transfer_out','adjustment')),
 payment_id INTEGER REFERENCES payments(id) ON DELETE RESTRICT, expense_id INTEGER,
 amount REAL NOT NULL CHECK(amount>0), transaction_date TEXT NOT NULL, category TEXT,
 description TEXT NOT NULL, reference TEXT, transfer_group TEXT, status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted','cancelled')),
 created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
 id INTEGER PRIMARY KEY AUTOINCREMENT, expense_no TEXT NOT NULL UNIQUE, expense_date TEXT NOT NULL,
 amount REAL NOT NULL CHECK(amount>0), category TEXT NOT NULL, description TEXT NOT NULL,
 account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT, attachment_path TEXT,
 status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted','cancelled')), created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, cancelled_at TEXT, cancelled_by INTEGER, cancel_reason TEXT
);
CREATE TABLE IF NOT EXISTS cash_sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT, opened_at TEXT NOT NULL,
 opening_txn_id INTEGER NOT NULL DEFAULT 0, opening_balance REAL NOT NULL, expected_receipts REAL NOT NULL DEFAULT 0, expected_expenses REAL NOT NULL DEFAULT 0,
 expected_closing REAL, actual_closing REAL, difference REAL, closed_at TEXT,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')), notes TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 invoice_id INTEGER REFERENCES invoices(id) ON DELETE RESTRICT, reminder_date TEXT NOT NULL,
 method TEXT NOT NULL, outcome TEXT, notes TEXT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS installments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 total_amount REAL NOT NULL, start_date TEXT NOT NULL, installments_count INTEGER NOT NULL,
 frequency_days INTEGER NOT NULL DEFAULT 30, status TEXT NOT NULL DEFAULT 'active', notes TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS installment_lines (
 id INTEGER PRIMARY KEY AUTOINCREMENT, agreement_id INTEGER NOT NULL REFERENCES installments(id) ON DELETE CASCADE,
 due_date TEXT NOT NULL, amount REAL NOT NULL, status TEXT NOT NULL DEFAULT 'due', paid_date TEXT
);
CREATE TABLE IF NOT EXISTS complaints (
 id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_no TEXT NOT NULL UNIQUE,
 member_id INTEGER REFERENCES members(id) ON DELETE RESTRICT, location TEXT,
 complaint_type TEXT NOT NULL, reported_date TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'medium',
 description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', assigned_to TEXT,
 diagnosis TEXT, work_performed TEXT, parts_used TEXT, cost REAL NOT NULL DEFAULT 0,
 completion_date TEXT, due_date TEXT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
 category TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'قطعة', quantity REAL NOT NULL DEFAULT 0,
 min_quantity REAL NOT NULL DEFAULT 0, purchase_price REAL NOT NULL DEFAULT 0, supplier TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS inventory_moves (
 id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
 move_type TEXT NOT NULL CHECK(move_type IN ('in','out','adjustment')), quantity REAL NOT NULL,
 unit_cost REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL, move_date TEXT NOT NULL,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, complaint_id INTEGER REFERENCES complaints(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_members_area_status ON members(area_id,status);
CREATE INDEX IF NOT EXISTS idx_readings_period ON readings(period);
CREATE INDEX IF NOT EXISTS idx_invoices_period_status ON invoices(period,status);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);

CREATE TRIGGER IF NOT EXISTS no_delete_invoices BEFORE DELETE ON invoices BEGIN SELECT RAISE(ABORT,'لا يمكن حذف الفواتير المالية'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_payments BEFORE DELETE ON payments BEGIN SELECT RAISE(ABORT,'لا يمكن حذف سندات القبض'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_invoice_items BEFORE DELETE ON invoice_items BEGIN SELECT RAISE(ABORT,'لا يمكن حذف بنود الفاتورة'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_allocations BEFORE DELETE ON payment_allocations BEGIN SELECT RAISE(ABORT,'لا يمكن حذف تخصيصات الأداء'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_member_history BEFORE DELETE ON members WHEN EXISTS(SELECT 1 FROM invoices WHERE member_id=OLD.id) OR EXISTS(SELECT 1 FROM payments WHERE member_id=OLD.id) OR EXISTS(SELECT 1 FROM readings WHERE member_id=OLD.id) BEGIN SELECT RAISE(ABORT,'العضو له سجل تاريخي؛ استخدم الأرشفة'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_expenses BEFORE DELETE ON expenses BEGIN SELECT RAISE(ABORT,'لا يمكن حذف المصاريف؛ استخدم الإلغاء الموثق'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_transactions BEFORE DELETE ON transactions BEGIN SELECT RAISE(ABORT,'لا يمكن حذف الحركات المالية'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_receipt_prints BEFORE DELETE ON receipt_prints BEGIN SELECT RAISE(ABORT,'سجل الطباعة محفوظ'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_reading_history BEFORE DELETE ON reading_history BEGIN SELECT RAISE(ABORT,'تاريخ تصحيح القراءات محفوظ'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_number_history BEFORE DELETE ON member_number_history BEGIN SELECT RAISE(ABORT,'تاريخ تغيير الأرقام محفوظ'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_audit BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'سجل التدقيق غير قابل للحذف'); END;
CREATE TRIGGER IF NOT EXISTS no_update_audit BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'سجل التدقيق غير قابل للتعديل'); END;
"""

DEFAULT_SETTINGS = {
    "association_name": "جمعية مياه الشرب",
    "association_address": "", "association_phone": "", "association_email": "", "association_logo": "",
    "currency": "MAD", "financial_year": "", "billing_frequency": "monthly",
    "invoice_prefix": "FAC", "receipt_prefix": "REC", "expense_prefix": "DEP", "transaction_prefix": "TRS",
    "next_invoice": "1", "next_receipt": "1", "next_expense": "1", "next_transaction": "1", "next_complaint": "1",
    "high_consumption_factor": "2.5", "zero_reading_alert_count": "3", "overdue_days": "30",
    "apply_late_fee": "0", "payment_due_days": "30", "backup_folder": "", "backup_time": "18:00",
    "auto_backup": "0", "backup_retention": "0", "export_folder": "", "printer_name": "",
    "language": "ar", "tax_enabled": "0", "tax_rate": "0",
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
            # Small forward-compatible migrations for databases created by earlier builds.
            invoice_columns = {r[1] for r in conn.execute("PRAGMA table_info(invoices)")}
            if "tax_amount" not in invoice_columns:
                conn.execute("ALTER TABLE invoices ADD COLUMN tax_amount REAL NOT NULL DEFAULT 0")
            session_columns = {r[1] for r in conn.execute("PRAGMA table_info(cash_sessions)")}
            if "opening_txn_id" not in session_columns:
                conn.execute("ALTER TABLE cash_sessions ADD COLUMN opening_txn_id INTEGER NOT NULL DEFAULT 0")
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def integrity_check(self) -> str:
        return self.one("PRAGMA integrity_check")[0]

    def backup_to(self, destination: str | Path) -> None:
        dest = sqlite3.connect(str(destination))
        try:
            with self.connect() as source:
                source.backup(dest)
        finally:
            dest.close()
