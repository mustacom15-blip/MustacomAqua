from __future__ import annotations
import base64
import html
import json
from pathlib import Path
from typing import Any

from .billing import InvoiceService
from .reports import METHOD_AR, ReportResult, STATUS_AR
from .services import BaseService, D, money

DEVELOPER = "MUSTACOM SERVICES — 0708785153 — contact@mustacom.com"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def logo_uri(path: str) -> str:
    if not path:
        return ""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > 5*1024*1024:
            return ""
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64,"+base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return ""


BASE_CSS = """
@page { size: A4; margin: 12mm; }
body { font-family: 'Noto Naskh Arabic','Tahoma','Arial',sans-serif; direction:rtl; color:#17212b; font-size:11pt; }
h1 { color:#123a54; font-size:20pt; margin:4px 0 8px; } h2 { color:#176b73; font-size:15pt; }
.header { width:100%; border-bottom:3px solid #e5ac1c; padding-bottom:8px; margin-bottom:12px; }
.header td { vertical-align:middle; } .assoc { font-size:17pt; font-weight:bold; color:#123a54; }
.contact { color:#536371; font-size:9pt; } .logo { max-width:110px; max-height:85px; }
.meta { background:#eef5f7; padding:10px; margin:8px 0; border-radius:5px; }
table.data { border-collapse:collapse; width:100%; margin-top:8px; }
table.data th { background:#123a54; color:white; padding:7px; border:1px solid #bac8ce; }
table.data td { padding:6px; border:1px solid #cbd5da; vertical-align:top; }
table.data tr:nth-child(even) td { background:#f5f8fa; }
.num { direction:ltr; text-align:center; white-space:nowrap; } .total { font-size:14pt; font-weight:bold; color:#123a54; }
.summary { margin-top:12px; padding:8px; border:1px solid #e5ac1c; }
.footer { margin-top:20px; padding-top:8px; border-top:1px solid #ccd5d9; color:#6a7882; font-size:8pt; text-align:center; }
.small { font-size:9pt; color:#586873; } .badge { color:#176b73; font-weight:bold; }
"""


class DocumentService(BaseService):
    def _shell(self, title: str, body: str, document_no: str = "") -> str:
        s = self.settings()
        logo = logo_uri(s.get("association_logo", ""))
        logo_html = f'<img class="logo" src="{logo}"/>' if logo else ""
        number = f'<span class="badge">رقم الوثيقة: {esc(document_no)}</span><br/>' if document_no else ""
        return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>{BASE_CSS}</style></head><body>
        <table class="header" width="100%"><tr><td align="right"><div class="assoc">{esc(s.get('association_name'))}</div>
        <div class="contact">{esc(s.get('association_address'))}<br/>{esc(s.get('association_phone'))} {esc(s.get('association_email'))}</div></td>
        <td align="left">{logo_html}</td></tr></table>
        <h1>{esc(title)}</h1>{number}<span class="small">تاريخ الإنشاء: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M}</span>
        {body}<div class="footer">تطوير: {DEVELOPER}<br/>MUSTACOM AQUA GESTION PRO</div></body></html>"""

    def report_html(self, report: ReportResult) -> str:
        headers = "".join(f"<th>{esc(h)}</th>" for h in report.headers)
        body_rows = []
        for row in report.rows:
            cells = "".join(f'<td class="{"num" if i in report.numeric_columns else ""}">{esc(v)}</td>' for i,v in enumerate(row))
            body_rows.append(f"<tr>{cells}</tr>")
        summary = " &nbsp; | &nbsp; ".join(f"<b>{esc(k)}:</b> {esc(v)}" for k,v in report.summary)
        subtitle = f'<div class="meta">{esc(report.subtitle)}</div>' if report.subtitle else ""
        body = f'{subtitle}<table class="data"><thead><tr>{headers}</tr></thead><tbody>{"".join(body_rows) or "<tr><td>لا توجد بيانات</td></tr>"}</tbody></table><div class="summary">{summary}</div>'
        return self._shell(report.title, body)

    def invoice_html(self, invoice_id: int) -> str:
        inv = self.db.one("""SELECT i.*,m.number,m.full_name,m.phone,m.address,a.name area FROM invoices i JOIN members m ON m.id=i.member_id
            LEFT JOIN areas a ON a.id=m.area_id WHERE i.id=?""", (invoice_id,))
        if not inv:
            from .services import AppError
            raise AppError("الفاتورة غير موجودة.")
        items = self.db.query("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY sort_order,id", (invoice_id,))
        with self.db.connect() as conn:
            balance = InvoiceService.invoice_balance(conn, invoice_id)
        if inv["status"] == "cancelled":
            balance = D(0)
        paid = D(inv["total_due"])-balance if inv["status"] != "cancelled" else D(0)
        rows = "".join(f'<tr><td>{esc(x["label"])}</td><td class="num">{x["quantity"]:.3f}</td><td class="num">{x["unit_price"]:.2f}</td><td class="num">{x["amount"]:.2f}</td></tr>' for x in items)
        currency = self.setting("currency","MAD")
        body = f"""<div class="meta"><b>العضو:</b> {esc(inv['full_name'])} &nbsp; <b>رقم العضو/العداد:</b> {esc(inv['number'])}<br/>
        <b>المنطقة:</b> {esc(inv['area'])} &nbsp; <b>الهاتف:</b> {esc(inv['phone'])} &nbsp; <b>العنوان:</b> {esc(inv['address'])}<br/>
        <b>الفترة:</b> {esc(inv['period'])} &nbsp; <b>الإصدار:</b> {esc(inv['issue_date'])} &nbsp; <b>الاستحقاق:</b> {esc(inv['due_date'])} &nbsp;
        <b>الحالة:</b> {esc(STATUS_AR.get(inv['status'],inv['status']))}</div>
        <table class="data"><tr><th>القراءة السابقة</th><th>القراءة الحالية</th><th>الاستهلاك م³</th></tr>
        <tr><td class="num">{inv['previous_reading']:.3f}</td><td class="num">{inv['current_reading']:.3f}</td><td class="num">{inv['consumption']:.3f}</td></tr></table>
        <table class="data"><thead><tr><th>البيان</th><th>الكمية</th><th>سعر الوحدة</th><th>المبلغ {esc(currency)}</th></tr></thead><tbody>{rows}</tbody></table>
        <div class="summary"><b>رصيد سابق عند الإصدار (للإعلام، ضمن فواتيره الأصلية):</b> {D(inv['prior_balance']):.2f} {esc(currency)}<br/>
        <span class="total">مجموع هذه الفاتورة: {D(inv['total_due']):.2f} {esc(currency)}</span><br/>
        <b>المؤدى:</b> {paid:.2f} &nbsp; <b>المتبقي:</b> {balance:.2f}<br/>
        <span class="small">إجمالي الحساب عند الإصدار = {D(inv['total_due'])+D(inv['prior_balance']):.2f} {esc(currency)}. لا يضاف الرصيد السابق إلى دين هذه الفاتورة مرة ثانية.</span></div>
        {f'<div class="meta"><b>سبب الإلغاء:</b> {esc(inv["cancel_reason"])} — {esc(inv["cancelled_at"])}</div>' if inv['status']=='cancelled' else ''}"""
        return self._shell("فاتورة ماء" if inv["kind"]=="water" else "فاتورة مساهمة",body,inv["invoice_no"])

    def receipt_html(self, payment_id: int) -> str:
        p = self.db.one("""SELECT p.*,m.number,m.full_name,a.name account FROM payments p JOIN members m ON m.id=p.member_id
            JOIN accounts a ON a.id=p.account_id WHERE p.id=?""", (payment_id,))
        if not p:
            from .services import AppError
            raise AppError("سند القبض غير موجود.")
        allocations = self.db.query("""SELECT i.invoice_no,i.period,pa.amount FROM payment_allocations pa JOIN invoices i ON i.id=pa.invoice_id
            WHERE pa.payment_id=? ORDER BY i.due_date""", (payment_id,))
        allocated = sum((D(a["amount"]) for a in allocations),D(0))
        currency = self.setting("currency","MAD")
        rows = "".join(f'<tr><td>{esc(a["invoice_no"])}</td><td>{esc(a["period"])}</td><td class="num">{D(a["amount"]):.2f}</td></tr>' for a in allocations)
        body = f"""<div class="meta"><b>العضو:</b> {esc(p['full_name'])} &nbsp; <b>رقم العضو/العداد:</b> {esc(p['number'])}<br/>
        <b>التاريخ:</b> {esc(p['payment_date'])} &nbsp; <b>طريقة الأداء:</b> {esc(METHOD_AR.get(p['method']))} &nbsp;
        <b>المرجع:</b> {esc(p['reference'])} &nbsp; <b>الحساب:</b> {esc(p['account'])}</div>
        <p class="total">المبلغ المستلم: {D(p['amount']):.2f} {esc(currency)}</p>
        <h2>الفواتير المشمولة</h2><table class="data"><tr><th>الفاتورة</th><th>الفترة</th><th>المخصص {esc(currency)}</th></tr>{rows or '<tr><td colspan="3">رصيد دائن / دون تخصيص</td></tr>'}</table>
        <div class="summary"><b>المخصص:</b> {allocated:.2f} &nbsp; <b>الرصيد الدائن من هذا السند:</b> {D(p['amount'])-allocated:.2f} {esc(currency)}</div>
        {f'<div class="meta"><b>سند ملغى:</b> {esc(p["cancel_reason"])} — {esc(p["cancelled_at"])}</div>' if p['status']=='cancelled' else ''}
        <br/><table width="100%"><tr><td>توقيع المحصل</td><td align="left">توقيع العضو</td></tr></table>"""
        return self._shell("سند قبض",body,p["receipt_no"])

    def member_card_html(self, member_id: int) -> str:
        m = self.db.one("SELECT m.*,a.name area FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE m.id=?",(member_id,))
        if not m:
            from .services import AppError
            raise AppError("العضو غير موجود.")
        body = f"""<div class="meta"><h2>{esc(m['full_name'])}</h2><p class="total">رقم العضو/العداد: {esc(m['number'])}</p>
        <b>الحالة:</b> {esc(STATUS_AR.get(m['status']))} &nbsp; <b>الهاتف:</b> {esc(m['phone'])}<br/>
        <b>المنطقة:</b> {esc(m['area'])} &nbsp; <b>العنوان:</b> {esc(m['address'])}<br/>
        <b>تاريخ العضوية:</b> {esc(m['membership_date'])} &nbsp; <b>تركيب العداد:</b> {esc(m['meter_install_date'])}<br/>
        <b>موقع العداد:</b> {esc(m['meter_location'])} &nbsp; <b>القراءة الأولية:</b> {m['initial_reading']:.3f} ({esc(m['initial_reading_date'])})</div>
        <p class="small">هذه البطاقة تعتمد الرقم الموحد للعضوية والعداد في جميع القراءات والفواتير والأداءات والشكايات.</p>"""
        return self._shell("بطاقة عضو",body,m["number"])

    def reminder_html(self, member_id: int) -> str:
        member = self.db.one("SELECT m.*,a.name area FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE m.id=?",(member_id,))
        debts = self.db.query("""SELECT i.*,i.total_due-COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa JOIN payments p ON p.id=pa.payment_id
            WHERE pa.invoice_id=i.id AND p.status='posted'),0) balance FROM invoices i WHERE i.member_id=? AND i.status='issued'""",(member_id,))
        debts = [d for d in debts if D(d["balance"])>0]
        total = sum((D(d["balance"]) for d in debts),D(0))
        rows = "".join(f'<tr><td>{esc(d["invoice_no"])}</td><td>{esc(d["period"])}</td><td>{esc(d["due_date"])}</td><td class="num">{D(d["balance"]):.2f}</td></tr>' for d in debts)
        body = f"""<p>السيد(ة) <b>{esc(member['full_name'])}</b>، رقم العضو/العداد <b>{esc(member['number'])}</b>، المنطقة {esc(member['area'])}.</p>
        <p>نرجو منكم تسوية المبالغ المستحقة التالية، أو الاتصال بالجمعية لدراسة إمكانية التقسيط:</p>
        <table class="data"><tr><th>الفاتورة</th><th>الفترة</th><th>الاستحقاق</th><th>المتبقي</th></tr>{rows}</table>
        <p class="total">مجموع الدين: {total:.2f} {esc(self.setting('currency','MAD'))}</p><p>وتقبلوا فائق التقدير.</p>"""
        return self._shell("تذكير بالأداء",body)

    def reading_sheet_html(self, period: str, area_id: int | None = None, reader: str = "") -> str:
        where, params = ["m.status='active'","m.archived=0"], []
        if area_id: where.append("m.area_id=?"); params.append(area_id)
        members = self.db.query(f"""SELECT m.*,a.name area,(SELECT current_reading FROM readings r WHERE r.member_id=m.id AND r.status!='cancelled' ORDER BY reading_date DESC,id DESC LIMIT 1) last_reading
            FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE {' AND '.join(where)} ORDER BY a.name,m.number""",tuple(params))
        rows = "".join(f'<tr><td>{esc(m["number"])}</td><td>{esc(m["full_name"])}</td><td>{esc(m["area"])}</td><td class="num">{m["last_reading"] if m["last_reading"] is not None else m["initial_reading"]}</td><td></td><td></td><td></td></tr>' for m in members)
        body = f'<div class="meta"><b>الفترة:</b> {esc(period)} &nbsp; <b>قارئ العداد:</b> {esc(reader)}<br/>تملأ القراءة الحالية والتاريخ والملاحظات، ثم تراجع قبل الإدخال والاعتماد.</div><table class="data"><tr><th>الرقم/العداد</th><th>العضو</th><th>المنطقة</th><th>القراءة السابقة</th><th>القراءة الحالية</th><th>التاريخ</th><th>ملاحظات</th></tr>{rows}</table>'
        return self._shell("ورقة قراءة العدادات",body)
