from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

from app.billing import InvoiceService,TariffService
from app.database import Database
from app.documents import DocumentService
from app.printing import PrintManager
from app.security import User
from app.services import AuthService,MemberService,ReadingService
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app=QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return app


def test_all_admin_pages_and_arabic_pdf(qapp,tmp_path,monkeypatch):
    monkeypatch.setenv("MUSTACOM_DATA_DIR",str(tmp_path/"data"))
    db=Database(tmp_path/"ui.db");auth=AuthService(db)
    auth.create_first_admin("admin","مدير","password123",{"association_name":"جمعية الاختبار"})
    user=auth.login("admin","password123")
    with db.transaction() as c:c.execute("INSERT INTO areas(name) VALUES('المنطقة')")
    mid=MemberService(db).save(user,{"number":"001","full_name":"عضو اختبار","membership_date":"2026-01-01","area_id":1,"initial_reading":10,"initial_reading_date":"2026-01-01","status":"active"})
    TariffService(db).save_tariff(user,{"name":"تعرفة","start_date":"2026-01-01","fixed_fee":5,"late_fee":0,"active":True},[{"from_qty":0,"to_qty":None,"unit_price":3}])
    rid=ReadingService(db).save(user,{"member_id":mid,"period":"2026-01","reading_date":"2026-01-31","current_reading":30});ReadingService(db).approve(user,rid)
    iid=InvoiceService(db).generate_from_reading(user,rid);InvoiceService(db).issue(user,iid)
    window=MainWindow(db,user);window.show();qapp.processEvents()
    assert window.stack.count()==14
    for i in range(window.stack.count()):
        window.stack.setCurrentIndex(i);qapp.processEvents()
        assert window.stack.currentWidget().isVisible()
    output=tmp_path/"arabic_invoice.pdf"
    printer=PrintManager._printer();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(output))
    doc=PrintManager._document(DocumentService(db).invoice_html(iid));doc.print_(printer)
    assert output.stat().st_size>10_000
    window.close()


def test_role_navigation_opens(qapp,tmp_path,monkeypatch):
    monkeypatch.setenv("MUSTACOM_DATA_DIR",str(tmp_path/"data_roles"))
    db=Database(tmp_path/"roles.db")
    for role in ("reader","reception","auditor","president","treasurer"):
        user=User(50,role,role,role)
        window=MainWindow(db,user)
        assert window.stack.count()>=3
        for i in range(window.stack.count()):window.stack.setCurrentIndex(i)
        window.close()
