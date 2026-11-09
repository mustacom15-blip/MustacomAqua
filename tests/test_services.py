from __future__ import annotations
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.backup import BackupService
from app.billing import InvoiceService, PaymentService, TariffService
from app.database import Database
from app.finance import FinanceService
from app.operations import OperationsService
from app.reports import ReportService
from app.security import User
from app.services import AppError, AuthService, MemberService, ReadingService


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSTACOM_DATA_DIR", str(tmp_path/"data"))
    db = Database(tmp_path/"test.db")
    auth = AuthService(db)
    auth.create_first_admin("admin", "المدير", "StrongPass123", {"association_name":"جمعية الاختبار"})
    admin = auth.login("admin", "StrongPass123")
    for username, role in (("treasurer","treasurer"),("president","president"),("reader","reader")):
        auth.save_user(admin,{"username":username,"full_name":username,"role":role,"password":"StrongPass123","active":True})
    users = {r:auth.login(r,"StrongPass123") for r in ("treasurer","president","reader")}
    users["admin"] = admin
    with db.transaction() as c:
        c.execute("INSERT INTO areas(name) VALUES('الحي الأول')")
    return db, users


def member(db, users, number="001"):
    return MemberService(db).save(users["admin"], {"number":number,"full_name":"عضو "+number,"phone":"0600000000","membership_date":"2026-01-01","area_id":1,"initial_reading":100,"initial_reading_date":"2026-01-01","status":"active"})


def reading(db, users, member_id, current=125, period="2026-01", status=True):
    service = ReadingService(db)
    rid = service.save(users["reader"],{"member_id":member_id,"period":period,"reading_date":period+"-28","current_reading":current})
    if status: service.approve(users["president"],rid)
    return rid


def tariff(db, users):
    return TariffService(db).save_tariff(users["treasurer"],{"name":"تعرفة 2026","start_date":"2026-01-01","fixed_fee":10,"late_fee":5,"active":True},[
        {"from_qty":0,"to_qty":10,"unit_price":2},{"from_qty":10,"to_qty":20,"unit_price":3},{"from_qty":20,"to_qty":None,"unit_price":5}])


def test_authentication_and_permissions(env):
    db, users = env
    assert users["reader"].can("readings.manage")
    assert not users["reader"].can("payments.manage")
    with pytest.raises(AppError):
        PaymentService(db).record(users["reader"],{})


def test_member_number_and_safe_delete(env):
    db, users = env
    mid = member(db,users)
    rid = reading(db,users,mid)
    with pytest.raises(AppError): MemberService(db).save(users["admin"],{**dict(db.one("SELECT * FROM members WHERE id=?",(mid,))),"number":"002"},mid)
    changed = MemberService(db).save(users["admin"],{**dict(db.one("SELECT * FROM members WHERE id=?",(mid,))),"number":"002"},mid,"تصحيح موثق")
    assert changed == mid
    history = db.one("SELECT * FROM member_number_history WHERE member_id=?",(mid,))
    assert history["old_number"] == "001" and history["new_number"] == "002"
    assert MemberService(db).delete_or_archive(users["admin"],mid,"طلب موثق") == "archived"
    assert db.one("SELECT COUNT(*) FROM readings WHERE member_id=?",(mid,))[0] == 1
    empty = member(db,users,"003")
    assert MemberService(db).delete_or_archive(users["admin"],empty,"إدخال خاطئ") == "deleted"


def test_reading_rules_and_audit(env):
    db, users = env
    mid = member(db,users)
    rid = reading(db,users,mid)
    with pytest.raises(AppError): reading(db,users,mid,130)
    draft = ReadingService(db).save(users["reader"],{"member_id":mid,"period":"2026-02","reading_date":"2026-02-28","current_reading":140})
    with pytest.raises(AppError): ReadingService(db).save(users["reader"],{**dict(db.one("SELECT * FROM readings WHERE id=?",(draft,))),"current_reading":120},draft,"خطأ")
    ReadingService(db).save(users["admin"],{**dict(db.one("SELECT * FROM readings WHERE id=?",(draft,))),"current_reading":120,"manual_previous":True},draft,"تصحيح استثنائي موثق")
    assert db.one("SELECT COUNT(*) FROM reading_history WHERE reading_id=?",(draft,))[0] == 1


def test_progressive_tariff_and_invoice_snapshot(env):
    db, users = env
    mid, tid = member(db,users), tariff(db,users)
    rid = reading(db,users,mid,125) # 25 m3 = 20+30+25 = 75, +10 = 85
    iid = InvoiceService(db).generate_from_reading(users["treasurer"],rid)
    invoice = db.one("SELECT * FROM invoices WHERE id=?",(iid,))
    assert Decimal(str(invoice["consumption_amount"])) == Decimal("75.00")
    assert Decimal(str(invoice["total_due"])) == Decimal("85.00")
    InvoiceService(db).issue(users["president"],iid)
    with pytest.raises(AppError): TariffService(db).save_tariff(users["treasurer"],{"name":"new","start_date":"2026-01-01","fixed_fee":99},[{"from_qty":0,"to_qty":None,"unit_price":9}],tid)
    assert db.one("SELECT total_due FROM invoices WHERE id=?",(iid,))[0] == 85
    with pytest.raises(AppError): InvoiceService(db).generate_from_reading(users["treasurer"],rid)


def test_partial_payment_credit_and_invoice_never_income(env):
    db, users = env
    mid = member(db,users)
    rid, _ = reading(db,users,mid), tariff(db,users)
    iid = InvoiceService(db).generate_from_reading(users["treasurer"],rid)
    InvoiceService(db).issue(users["president"],iid)
    finance = FinanceService(db)
    cash = finance.save_account(users["treasurer"],{"name":"الصندوق","type":"cash","opening_balance":0})
    assert finance.balance(db.connect(),cash) == 0
    pid = PaymentService(db).record(users["treasurer"],{"member_id":mid,"payment_date":"2026-02-01","amount":40,"method":"cash","account_id":cash})
    assert db.one("SELECT COUNT(*) FROM payment_allocations WHERE payment_id=?",(pid,))[0] == 1
    assert InvoiceService.invoice_balance(db.connect(),iid) == 45
    with db.connect() as c: assert finance.balance(c,cash) == 40
    PaymentService(db).record(users["treasurer"],{"member_id":mid,"payment_date":"2026-02-02","amount":100,"method":"cash","account_id":cash})
    assert InvoiceService.invoice_balance(db.connect(),iid) == 0
    report = ReportService(db).report_statement({"member_id":mid})
    assert dict(report.summary)["رصيد دائن غير مخصص"] == Decimal("55.00")
    # Credit automatically covers a later contribution without duplicating cash.
    cid = InvoiceService(db).create_contribution(users["treasurer"],mid,"2026-03","مساهمة",20)
    InvoiceService(db).issue(users["president"],cid)
    assert InvoiceService.invoice_balance(db.connect(),cid) == 0
    with db.connect() as c: assert finance.balance(c,cash) == 140


def test_receipt_cancellation_preserves_records(env):
    db, users = env
    mid = member(db,users); tariff(db,users)
    iid = InvoiceService(db).generate_from_reading(users["treasurer"],reading(db,users,mid))
    InvoiceService(db).issue(users["president"],iid)
    cash = FinanceService(db).save_account(users["treasurer"],{"name":"الصندوق","type":"cash"})
    pid = PaymentService(db).record(users["treasurer"],{"member_id":mid,"payment_date":"2026-02-01","amount":85,"method":"cash","account_id":cash})
    PaymentService(db).cancel(users["admin"],pid,"خطأ في الإدخال")
    assert db.one("SELECT status FROM payments WHERE id=?",(pid,))[0] == "cancelled"
    assert InvoiceService.invoice_balance(db.connect(),iid) == 85
    with pytest.raises(Exception): db.query("DELETE FROM payments WHERE id=?",(pid,))


def test_expenses_transfers_and_cash_session(env):
    db, users = env
    fs = FinanceService(db)
    cash = fs.save_account(users["treasurer"],{"name":"الصندوق","type":"cash","opening_balance":1000})
    bank = fs.save_account(users["treasurer"],{"name":"البنك","type":"bank","opening_balance":500})
    fs.add_expense(users["treasurer"],{"expense_date":"2026-01-10","amount":100,"category":"كهرباء","description":"فاتورة الكهرباء","account_id":cash})
    fs.transfer(users["treasurer"],cash,bank,200,"2026-01-11","إيداع")
    with db.connect() as c:
        assert fs.balance(c,cash) == 700 and fs.balance(c,bank) == 700
    session = fs.open_cash_session(users["treasurer"],cash,700)
    difference = fs.close_cash_session(users["treasurer"],session,680)
    assert difference == -20


def test_complaint_inventory_and_installments(env):
    db, users = env
    mid = member(db,users)
    ops = OperationsService(db)
    cid = ops.save_complaint(users["admin"],{"member_id":mid,"complaint_type":"leak","reported_date":"2026-01-01","priority":"high","description":"تسرب","status":"open"})
    item = ops.save_inventory_item(users["admin"],{"code":"PIPE","name":"أنبوب","category":"أنابيب","quantity":5,"min_quantity":2,"purchase_price":10})
    ops.inventory_move(users["admin"],{"item_id":item,"move_type":"out","quantity":2,"reason":"إصلاح","move_date":"2026-01-02","complaint_id":cid})
    assert db.one("SELECT quantity FROM inventory_items WHERE id=?",(item,))[0] == 3
    with pytest.raises(AppError): ops.inventory_move(users["admin"],{"item_id":item,"move_type":"out","quantity":9,"reason":"صرف","move_date":"2026-01-02"})


def test_reports_and_encrypted_backup_restore(env, tmp_path):
    db, users = env
    mid = member(db,users); tariff(db,users)
    iid = InvoiceService(db).generate_from_reading(users["treasurer"],reading(db,users,mid))
    InvoiceService(db).issue(users["president"],iid)
    assert ReportService(db).report_debts({}).rows
    assert ReportService(db).dashboard("2026-01")["invoices_issued"] == 1
    service = BackupService(db)
    backup = service.create(users["admin"],str(tmp_path/"backups"),"BackupPass123")
    assert BackupService.inspect(backup,"BackupPass123")["database_sha256"]
    db2path = tmp_path/"other.db"
    service.portable_copy(users["admin"],db2path)
    assert Database(db2path).one("SELECT COUNT(*) FROM members")[0] == 1
