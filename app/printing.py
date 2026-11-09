from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Callable

from .paths import data_dir
from .reports import ReportResult
from .services import AppError


def export_excel(report: ReportResult, path: str | Path) -> Path:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise AppError("تصدير Excel يتطلب حزمة openpyxl المضمنة في التطبيق.") from exc
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "تقرير"
    ws.sheet_view.rightToLeft = True
    ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=max(1,len(report.headers)))
    cell = ws.cell(1,1,report.title)
    cell.font = Font(name="Arial",size=16,bold=True,color="123A54")
    cell.alignment = Alignment(horizontal="center")
    for col, header in enumerate(report.headers,1):
        c = ws.cell(3,col,header)
        c.font = Font(name="Arial",bold=True,color="FFFFFF")
        c.fill = PatternFill("solid",fgColor="123A54")
        c.alignment = Alignment(horizontal="center",vertical="center",wrap_text=True)
    for r_idx,row in enumerate(report.rows,4):
        for c_idx,value in enumerate(row,1):
            c = ws.cell(r_idx,c_idx,value)
            c.font = Font(name="Arial",size=10)
            c.alignment = Alignment(horizontal="right",vertical="top",wrap_text=True)
            if (c_idx-1) in report.numeric_columns and isinstance(value,(int,float)):
                c.number_format = '#,##0.00'
    start = len(report.rows)+5
    for i,(label,value) in enumerate(report.summary,start):
        ws.cell(i,1,label).font = Font(name="Arial",bold=True)
        ws.cell(i,2,str(value))
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(max(1,len(report.headers)))}{max(3,len(report.rows)+3)}"
    for i,header in enumerate(report.headers,1):
        values = [len(str(r[i-1] or "")) for r in report.rows[:200] if len(r)>=i]
        ws.column_dimensions[get_column_letter(i)].width = min(45,max(12,len(str(header))+2,max(values,default=0)+2))
    ws.row_dimensions[1].height = 28
    wb.save(target)
    return target


class PrintManager:
    printer_name = ""
    export_folder = ""

    @staticmethod
    def _document(html: str):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultStyleSheet("body{direction:rtl;font-family:Tahoma,Arial,sans-serif;} table{page-break-inside:auto;} tr{page-break-inside:avoid;}")
        doc.setHtml(html)
        return doc

    @staticmethod
    def _printer():
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if PrintManager.printer_name:
            printer.setPrinterName(PrintManager.printer_name)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(10,10,10,10),QPageLayout.Unit.Millimeter)
        return printer

    @classmethod
    def preview(cls,parent,html: str,title: str = "معاينة الطباعة",on_printed: Callable[[str],None] | None = None):
        from PySide6.QtPrintSupport import QPrintPreviewDialog
        printer = cls._printer()
        printer.setDocName(title)
        dialog = QPrintPreviewDialog(printer,parent)
        dialog.setWindowTitle(title)
        dialog.resize(1000,800)
        doc = cls._document(html)
        def paint(p):
            doc.print_(p)
            if on_printed:
                on_printed("print")
        dialog.paintRequested.connect(paint)
        # Keep document alive until the dialog closes.
        dialog._mustacom_document = doc
        dialog.exec()

    @classmethod
    def export_pdf(cls,parent,html: str,title: str,suggested_name: str,on_printed: Callable[[str],None] | None = None) -> Path | None:
        from PySide6.QtPrintSupport import QPrinter
        from PySide6.QtWidgets import QFileDialog
        export_root = Path(cls.export_folder).expanduser() if cls.export_folder else data_dir()/"exports"
        export_root.mkdir(parents=True, exist_ok=True)
        default = export_root/f"{suggested_name}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        filename,_ = QFileDialog.getSaveFileName(parent,"حفظ PDF",str(default),"PDF (*.pdf)")
        if not filename:
            return None
        printer = cls._printer()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(filename)
        printer.setDocName(title)
        doc = cls._document(html)
        doc.print_(printer)
        if on_printed:
            on_printed("pdf")
        return Path(filename)

    @classmethod
    def print_direct(cls,parent,html: str,title: str,on_printed: Callable[[str],None] | None = None) -> bool:
        from PySide6.QtPrintSupport import QPrintDialog
        printer = cls._printer()
        printer.setDocName(title)
        dialog = QPrintDialog(printer,parent)
        dialog.setWindowTitle("طباعة — "+title)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        doc = cls._document(html)
        doc.print_(printer)
        if on_printed:
            on_printed("print")
        return True
