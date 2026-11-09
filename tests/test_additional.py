from __future__ import annotations
from decimal import Decimal

from app.backup import BackupService
from app.billing import InvoiceService
from app.database import Database
from app.reports import ReportService
from app.services import MemberService,ReadingService,AppError
import pytest
from test_services import env,member,reading,tariff


def test_optional_tax_is_snapshotted(env):
    db,users=env
    with db.transaction() as c:
        c.execute("UPDATE settings SET value='1' WHERE key='tax_enabled'")
        c.execute("UPDATE settings SET value='20' WHERE key='tax_rate'")
    mid=member(db,users);tariff(db,users)
    iid=InvoiceService(db).generate_from_reading(users["treasurer"],reading(db,users,mid))
    inv=db.one("SELECT * FROM invoices WHERE id=?",(iid,))
    # Base 85 + 17 tax.
    assert Decimal(str(inv["tax_amount"]))==Decimal("17.00")
    assert Decimal(str(inv["total_due"]))==Decimal("102.00")
    with db.transaction() as c:c.execute("UPDATE settings SET value='0' WHERE key='tax_enabled'")
    assert db.one("SELECT total_due FROM invoices WHERE id=?",(iid,))[0]==102


def test_paid_and_unpaid_invoice_filters(env):
    db,users=env
    mid=member(db,users);tariff(db,users)
    iid=InvoiceService(db).generate_from_reading(users["treasurer"],reading(db,users,mid))
    assert len(ReportService(db).report_invoices({"status":"unpaid"}).rows)==0 # draft is not an issued debt
    InvoiceService(db).issue(users["president"],iid)
    assert len(ReportService(db).report_invoices({"status":"unpaid"}).rows)==1
    assert len(ReportService(db).report_invoices({"status":"paid"}).rows)==0


def test_bimonthly_billing_period_is_enforced(env):
    db,users=env
    mid=member(db,users)
    with db.transaction() as c:c.execute("UPDATE settings SET value='bimonthly' WHERE key='billing_frequency'")
    with pytest.raises(AppError):
        ReadingService(db).save(users["reader"],{"member_id":mid,"period":"2026-01","reading_date":"2026-02-28","current_reading":110})
    rid=ReadingService(db).save(users["reader"],{"member_id":mid,"period":"2026-B1","reading_date":"2026-02-28","current_reading":110})
    assert db.one("SELECT period FROM readings WHERE id=?",(rid,))[0]=="2026-B1"


def test_restore_reverts_database_and_creates_safety_copy(env,tmp_path):
    db,users=env
    mid=member(db,users,"100")
    backup=BackupService(db).create(users["admin"],str(tmp_path/"restore_backups"),"BackupPass123")
    member(db,users,"200")
    assert db.one("SELECT COUNT(*) FROM members")[0]==2
    BackupService(db).restore(users["admin"],backup,"BackupPass123")
    assert db.one("SELECT COUNT(*) FROM members")[0]==1
    assert db.one("SELECT number FROM members")[0]=="100"
    assert db.integrity_check()=="ok"
    assert len(list((tmp_path/"restore_backups").glob("*.zip")))>=1
