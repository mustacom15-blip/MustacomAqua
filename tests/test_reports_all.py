from __future__ import annotations
from app.billing import InvoiceService
from app.finance import FinanceService
from app.operations import OperationsService
from app.reports import ReportService
from test_services import env,member,reading,tariff


def test_every_report_builds(env):
    db,users=env
    mid=member(db,users);tariff(db,users)
    iid=InvoiceService(db).generate_from_reading(users["treasurer"],reading(db,users,mid));InvoiceService(db).issue(users["president"],iid)
    cash=FinanceService(db).save_account(users["treasurer"],{"name":"الصندوق","type":"cash"})
    OperationsService(db).save_complaint(users["admin"],{"member_id":mid,"complaint_type":"faulty_meter","reported_date":"2026-01-01","description":"عطل","status":"open"})
    OperationsService(db).save_inventory_item(users["admin"],{"code":"M","name":"عداد","category":"عدادات","quantity":1})
    service=ReportService(db)
    cases={"members":{},"statement":{"member_id":mid},"readings":{"period":"2026-01"},"invoices":{"period":"2026-01"},"debts":{},
           "payments":{},"finance":{},"complaints":{},"inventory":{},"consumption_comparison":{"period":"2026-01","period2":"2026-02"},"summary":{"year":"2026"}}
    for name,filters in cases.items():
        report=service.build(name,filters)
        assert report.title and report.headers
        assert all(len(row)==len(report.headers) for row in report.rows),name
