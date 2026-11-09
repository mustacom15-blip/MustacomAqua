from __future__ import annotations
import json
import re
import shutil
import sqlite3
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .database import Database, now
from .paths import data_dir
from .security import User, hash_password, verify_password


class AppError(Exception):
    """Business error safe to show to the user."""


def D(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception as exc:
        raise AppError("قيمة رقمية غير صالحة.") from exc


def money(value: Any) -> Decimal:
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def valid_date(value: str, label: str = "التاريخ") -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError) as exc:
        raise AppError(f"{label} غير صالح. استخدم الصيغة YYYY-MM-DD.") from exc


def row_dict(row: sqlite3.Row | dict | None) -> dict:
    return dict(row) if row is not None else {}


class BaseService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def require(user: User, permission: str) -> None:
        if not user.active or not user.can(permission):
            raise AppError("ليس لديك صلاحية لتنفيذ هذه العملية.")

    @staticmethod
    def audit(conn, user: User | None, action: str, entity: str, entity_id: Any = None,
              before: Any = None, after: Any = None, reason: str = "") -> None:
        conn.execute("""INSERT INTO audit_log(at,user_id,username,action,entity,entity_id,reason,before_json,after_json)
                        VALUES(?,?,?,?,?,?,?,?,?)""", (
            now(), user.id if user else None, user.username if user else "النظام", action, entity,
            str(entity_id) if entity_id is not None else None, reason or None,
            json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(after, ensure_ascii=False, default=str) if after is not None else None))

    @staticmethod
    def get(conn, table: str, record_id: int):
        # Table names are internal constants only.
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if not row:
            raise AppError("السجل المطلوب غير موجود.")
        return row

    def setting(self, key: str, default: str = "") -> str:
        row = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
        return str(row[0]) if row and row[0] is not None else default

    def settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] or "" for r in self.db.query("SELECT key,value FROM settings")}

    def next_number(self, conn, kind: str) -> str:
        allowed = {"invoice", "receipt", "expense", "transaction", "complaint"}
        if kind not in allowed:
            raise ValueError(kind)
        prefix_key = "complaint_prefix" if kind == "complaint" else f"{kind}_prefix"
        prefix_row = conn.execute("SELECT value FROM settings WHERE key=?", (prefix_key,)).fetchone()
        prefix = (prefix_row[0] if prefix_row else None) or kind[:3].upper()
        key = f"next_{kind}"
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        number = int(row[0]) if row else 1
        year_row = conn.execute("SELECT value FROM settings WHERE key='financial_year'").fetchone()
        year = (year_row[0] if year_row else "") or str(date.today().year)
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(number + 1)))
        return f"{prefix}-{year}-{number:06d}"


class AuthService(BaseService):
    def needs_setup(self) -> bool:
        return self.db.one("SELECT COUNT(*) FROM users") [0] == 0

    def create_first_admin(self, username: str, full_name: str, password: str, association: dict[str, str]) -> None:
        if not self.needs_setup():
            raise AppError("تم إعداد النظام مسبقاً.")
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            raise AppError("اسم المستخدم: 3 إلى 40 حرفاً لاتينياً أو رقماً دون مسافات.")
        if not full_name.strip():
            raise AppError("الاسم الكامل مطلوب.")
        with self.db.transaction() as conn:
            cur = conn.execute("INSERT INTO users(username,password_hash,full_name,role,created_at) VALUES(?,?,?,?,?)",
                               (username, hash_password(password), full_name.strip(), "admin", now()))
            user = User(cur.lastrowid, username, full_name.strip(), "admin")
            for key in ("association_name", "association_address", "association_phone", "association_email", "currency"):
                if key in association:
                    conn.execute("UPDATE settings SET value=? WHERE key=?", (association[key].strip(), key))
            self.audit(conn, user, "إعداد أول مدير", "users", cur.lastrowid, after={"username": username})

    def login(self, username: str, password: str) -> User:
        row = self.db.one("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),))
        if not row or not row["active"] or not verify_password(password, row["password_hash"]):
            raise AppError("اسم المستخدم أو كلمة المرور غير صحيحة، أو الحساب موقوف.")
        with self.db.transaction() as conn:
            conn.execute("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"]))
        return User(row["id"], row["username"], row["full_name"], row["role"], bool(row["active"]))

    def save_user(self, actor: User, data: dict, user_id: int | None = None) -> int:
        self.require(actor, "*")
        username = data["username"].strip()
        full_name = data["full_name"].strip()
        role = data["role"]
        if role not in ("admin", "president", "treasurer", "reader", "reception", "auditor"):
            raise AppError("الدور غير صالح.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username) or not full_name:
            raise AppError("تحقق من اسم المستخدم والاسم الكامل.")
        with self.db.transaction() as conn:
            before = row_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()) if user_id else None
            if before and "password_hash" in before:
                before["password_hash"] = "[محمي]"
            if user_id:
                if before and before["username"].lower() == actor.username.lower() and not data.get("active", True):
                    raise AppError("لا يمكنك إيقاف حسابك الحالي.")
                conn.execute("UPDATE users SET username=?,full_name=?,role=?,active=? WHERE id=?",
                             (username, full_name, role, int(data.get("active", True)), user_id))
                if data.get("password"):
                    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data["password"]), user_id))
                record_id = user_id
                action = "تعديل مستخدم"
            else:
                if not data.get("password"):
                    raise AppError("كلمة المرور مطلوبة للمستخدم الجديد.")
                cur = conn.execute("INSERT INTO users(username,password_hash,full_name,role,active,created_at) VALUES(?,?,?,?,?,?)",
                                   (username, hash_password(data["password"]), full_name, role, int(data.get("active", True)), now()))
                record_id = cur.lastrowid
                action = "إضافة مستخدم"
            after = {"username": username, "full_name": full_name, "role": role, "active": bool(data.get("active", True))}
            self.audit(conn, actor, action, "users", record_id, before, after)
            return record_id


class MemberService(BaseService):
    REQUIRED = ("number", "full_name", "membership_date")

    def _validate(self, data: dict) -> None:
        for key in self.REQUIRED:
            if not str(data.get(key, "")).strip():
                raise AppError({"number": "رقم العضو/العداد مطلوب.", "full_name": "اسم العضو مطلوب.", "membership_date": "تاريخ العضوية مطلوب."}[key])
        if not re.fullmatch(r"[A-Za-z0-9/_-]{1,40}", str(data["number"]).strip()):
            raise AppError("رقم العضو/العداد يجب ألا يحتوي على مسافات أو رموز غير مدعومة.")
        valid_date(data["membership_date"], "تاريخ العضوية")
        if data.get("initial_reading_date"):
            valid_date(data["initial_reading_date"], "تاريخ القراءة الأولية")
        if D(data.get("initial_reading", 0)) < 0:
            raise AppError("القراءة الأولية لا يمكن أن تكون سالبة.")
        if data.get("status") not in ("active", "suspended", "withdrawn"):
            raise AppError("حالة العضو غير صالحة.")

    def save(self, user: User, data: dict, member_id: int | None = None, reason: str = "") -> int:
        self.require(user, "members.manage")
        self._validate(data)
        with self.db.transaction() as conn:
            before = row_dict(conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()) if member_id else {}
            if member_id and not before:
                raise AppError("العضو غير موجود.")
            if member_id and D(before["initial_reading"]) != D(data.get("initial_reading", 0)):
                has_readings = conn.execute("SELECT COUNT(*) FROM readings WHERE member_id=?", (member_id,)).fetchone()[0]
                if has_readings and (user.role != "admin" or not reason.strip()):
                    raise AppError("تغيير القراءة الأولية بعد وجود قراءات يتطلب مدير النظام وسبباً موثقاً.")
            if member_id and before["number"] != data["number"].strip():
                linked = conn.execute("""SELECT (EXISTS(SELECT 1 FROM readings WHERE member_id=?) OR
                    EXISTS(SELECT 1 FROM invoices WHERE member_id=?) OR EXISTS(SELECT 1 FROM payments WHERE member_id=?) OR
                    EXISTS(SELECT 1 FROM complaints WHERE member_id=?))""", (member_id,)*4).fetchone()[0]
                if linked and user.role != "admin":
                    raise AppError("لا يمكن تغيير الرقم بعد وجود سجلات مرتبطة إلا بواسطة مدير النظام.")
                if linked and not reason.strip():
                    raise AppError("سبب تغيير رقم العضو/العداد مطلوب وموثق.")
            values = (data["number"].strip(), data["full_name"].strip(), data.get("phone", "").strip(),
                      data.get("address", "").strip(), data.get("area_id") or None, data.get("national_id", "").strip(),
                      data["membership_date"], data.get("status", "active"), data.get("meter_install_date") or None,
                      data.get("meter_location", "").strip(), float(D(data.get("initial_reading", 0))),
                      data.get("initial_reading_date") or None, data.get("notes", "").strip(), now())
            if member_id:
                conn.execute("""UPDATE members SET number=?,full_name=?,phone=?,address=?,area_id=?,national_id=?,membership_date=?,status=?,
                    meter_install_date=?,meter_location=?,initial_reading=?,initial_reading_date=?,notes=?,updated_at=? WHERE id=?""", values+(member_id,))
                record_id = member_id
                action = "تعديل عضو"
            else:
                cur = conn.execute("""INSERT INTO members(number,full_name,phone,address,area_id,national_id,membership_date,status,
                    meter_install_date,meter_location,initial_reading,initial_reading_date,notes,updated_at,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values+(now(),))
                record_id = cur.lastrowid
                action = "إضافة عضو"
            if before and before["number"] != data["number"].strip():
                conn.execute("""INSERT INTO member_number_history(member_id,old_number,new_number,reason,user_id,username,changed_at)
                                VALUES(?,?,?,?,?,?,?)""", (member_id, before["number"], data["number"].strip(), reason, user.id, user.username, now()))
            self.audit(conn, user, action, "members", record_id, before or None, data, reason)
            return record_id

    def delete_or_archive(self, user: User, member_id: int, reason: str, force_archive: bool = False) -> str:
        self.require(user, "members.manage")
        attachment_dir: Path | None = None
        with self.db.transaction() as conn:
            member = self.get(conn, "members", member_id)
            linked = conn.execute("""SELECT
              (SELECT COUNT(*) FROM readings WHERE member_id=?) readings,
              (SELECT COUNT(*) FROM invoices WHERE member_id=?) invoices,
              (SELECT COUNT(*) FROM payments WHERE member_id=?) payments,
              (SELECT COUNT(*) FROM complaints WHERE member_id=?) complaints""", (member_id,)*4).fetchone()
            has_linked = sum(linked) > 0
            if has_linked or force_archive:
                if user.role != "admin":
                    raise AppError("العضو له سجلات مرتبطة. يمكنك تعليقه، والأرشفة النهائية يجريها مدير النظام.")
                if not reason.strip():
                    raise AppError("سبب الأرشفة/الحذف مطلوب.")
                conn.execute("UPDATE members SET archived=1,status='withdrawn',updated_at=? WHERE id=?", (now(), member_id))
                self.audit(conn, user, "حذف منطقي مع حفظ التاريخ" if has_linked else "أرشفة عضو", "members", member_id, row_dict(member),
                           {"archived": 1, "status": "withdrawn", "financial_history_preserved": True}, reason)
                result = "archived"
            else:
                attachment_dir = data_dir()/"attachments"/"members"/str(member_id)
                conn.execute("DELETE FROM members WHERE id=?", (member_id,))
                self.audit(conn, user, "حذف نهائي لعضو بلا سجلات", "members", member_id, row_dict(member), None, reason)
                result = "deleted"
        # Delete physical attachments only after the database transaction has committed.
        if attachment_dir and attachment_dir.exists():
            shutil.rmtree(attachment_dir)
        return result

    def add_document(self, user: User, member_id: int, source: str) -> str:
        self.require(user, "members.manage")
        self.get_member(member_id)
        src = Path(source)
        if not src.is_file():
            raise AppError("الملف المرفق غير موجود.")
        if src.stat().st_size > 25 * 1024 * 1024:
            raise AppError("حجم المرفق يتجاوز 25 ميغابايت.")
        target_dir = data_dir() / "attachments" / "members" / str(member_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{datetime.now():%Y%m%d%H%M%S%f}_{src.name}"
        shutil.copy2(src, target)
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO member_documents(member_id,file_path,original_name,added_at,added_by) VALUES(?,?,?,?,?)",
                         (member_id, str(target), src.name, now(), user.id))
            self.audit(conn, user, "إرفاق وثيقة", "members", member_id, after={"file": src.name})
        return str(target)

    def get_member(self, member_id: int):
        row = self.db.one("SELECT m.*,a.name area_name FROM members m LEFT JOIN areas a ON a.id=m.area_id WHERE m.id=?", (member_id,))
        if not row:
            raise AppError("العضو غير موجود.")
        return row


class ReadingService(BaseService):
    def _previous(self, conn, member_id: int, reading_date: str, reading_id: int | None = None) -> Decimal:
        params: list[Any] = [member_id, reading_date]
        exclude = ""
        if reading_id:
            exclude = " AND id<>?"
            params.append(reading_id)
        row = conn.execute(f"SELECT reading_date,current_reading FROM readings WHERE member_id=? AND reading_date<=? AND status!='cancelled'{exclude} ORDER BY reading_date DESC,id DESC LIMIT 1", params).fetchone()
        if row:
            return D(row["current_reading"])
        member = self.get(conn, "members", member_id)
        return D(member["initial_reading"])

    def save(self, user: User, data: dict, reading_id: int | None = None, reason: str = "") -> int:
        self.require(user, "readings.manage")
        member_id = int(data["member_id"])
        period = data["period"].strip()
        frequency = self.setting("billing_frequency", "monthly")
        patterns = {"monthly": r"\d{4}-(0[1-9]|1[0-2])", "bimonthly": r"\d{4}-B[1-6]",
                    "custom": r"\d{4}-((0[1-9]|1[0-2])|B[1-6]|P(0[1-9]|1[0-2]))"}
        if not re.fullmatch(patterns.get(frequency, patterns["monthly"]), period):
            hints = {"monthly": "YYYY-MM مثل 2026-11", "bimonthly": "YYYY-B1 إلى YYYY-B6؛ كل فترة شهران", "custom": "YYYY-MM أو YYYY-B1 أو YYYY-P01 حسب نظام الجمعية"}
            raise AppError("فترة الفوترة لا تطابق الدورية المختارة في الإعدادات. الصيغة: "+hints.get(frequency, hints["monthly"]))
        reading_date = valid_date(data["reading_date"], "تاريخ القراءة")
        current = D(data["current_reading"])
        if current < 0:
            raise AppError("القراءة الحالية لا يمكن أن تكون سالبة.")
        with self.db.transaction() as conn:
            member = self.get(conn, "members", member_id)
            duplicate = conn.execute("SELECT id FROM readings WHERE member_id=? AND period=? AND status!='cancelled' AND (? IS NULL OR id<>?)",
                                     (member_id, period, reading_id, reading_id)).fetchone()
            if duplicate:
                raise AppError("توجد قراءة لهذا العضو في فترة الفوترة نفسها.")
            if member["status"] != "active" and not reading_id:
                raise AppError("لا يمكن إضافة قراءة جديدة لعضو غير نشط.")
            before = row_dict(conn.execute("SELECT * FROM readings WHERE id=?", (reading_id,)).fetchone()) if reading_id else {}
            later = conn.execute("SELECT COUNT(*) FROM readings WHERE member_id=? AND reading_date>? AND status!='cancelled' AND (? IS NULL OR id<>?)",
                                 (member_id, reading_date, reading_id, reading_id)).fetchone()[0]
            if later and not reading_id:
                raise AppError("توجد قراءة بتاريخ لاحق لهذا العضو. أدخل القراءات بترتيب زمني لحماية حساب السابقة والاستهلاك.")
            previous = D(data["previous_reading"]) if reading_id and data.get("manual_previous") else self._previous(conn, member_id, reading_date, reading_id)
            consumption = current - previous
            if consumption < 0:
                if user.role != "admin" or not reason.strip():
                    raise AppError("الاستهلاك السالب مرفوض. التصحيح الاستثنائي يتطلب مدير النظام وسبباً موثقاً.")
            if before and before["status"] == "approved" and user.role not in ("admin", "president"):
                raise AppError("تعديل قراءة معتمدة يتطلب صلاحية خاصة.")
            if before and not reason.strip():
                raise AppError("سبب تصحيح القراءة مطلوب.")
            if reading_id:
                invoice = conn.execute("SELECT id FROM invoices WHERE reading_id=? AND status!='cancelled'", (reading_id,)).fetchone()
                if invoice:
                    raise AppError("لا تعدّل قراءة مرتبطة بفاتورة. ألغِ الفاتورة أولاً وفق الصلاحيات ثم صحح القراءة.")
                conn.execute("""UPDATE readings SET reading_date=?,previous_reading=?,current_reading=?,consumption=?,notes=?,correction_reason=?,updated_at=? WHERE id=?""",
                             (reading_date, float(previous), float(current), float(consumption), data.get("notes", ""), reason, now(), reading_id))
                record_id = reading_id
                action = "تصحيح قراءة"
            else:
                cur = conn.execute("""INSERT INTO readings(member_id,period,reading_date,previous_reading,current_reading,consumption,reader_id,reader_name,notes,created_by,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (member_id, period, reading_date, float(previous), float(current), float(consumption),
                    user.id, user.full_name, data.get("notes", ""), user.id, now(), now()))
                record_id = cur.lastrowid
                action = "إضافة قراءة"
            after = row_dict(conn.execute("SELECT * FROM readings WHERE id=?", (record_id,)).fetchone())
            if before:
                conn.execute("INSERT INTO reading_history(reading_id,changed_at,user_id,username,reason,before_json,after_json) VALUES(?,?,?,?,?,?,?)",
                             (record_id, now(), user.id, user.username, reason, json.dumps(before, default=str), json.dumps(after, default=str)))
            self.audit(conn, user, action, "readings", record_id, before or None, after, reason)
            return record_id

    def approve(self, user: User, reading_id: int) -> None:
        self.require(user, "readings.approve")
        with self.db.transaction() as conn:
            before = self.get(conn, "readings", reading_id)
            if before["status"] != "draft":
                raise AppError("القراءة ليست في حالة مسودة.")
            conn.execute("UPDATE readings SET status='approved',updated_at=? WHERE id=?", (now(), reading_id))
            self.audit(conn, user, "اعتماد قراءة", "readings", reading_id, row_dict(before), {"status": "approved"})

    def meter_event(self, user: User, data: dict) -> int:
        self.require(user, "readings.manage")
        if not data.get("reason", "").strip():
            raise AppError("سبب إصلاح أو استبدال العداد مطلوب.")
        valid_date(data["event_date"])
        if data["event_type"] not in ("replacement", "repair", "fault"):
            raise AppError("نوع العملية غير صالح.")
        with self.db.transaction() as conn:
            self.get(conn, "members", int(data["member_id"]))
            cur = conn.execute("""INSERT INTO meter_events(member_id,event_type,event_date,old_reading,new_reading,reason,technician,cost,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (data["member_id"], data["event_type"], data["event_date"], float(D(data.get("old_reading", 0))),
                float(D(data.get("new_reading", 0))), data["reason"].strip(), data.get("technician", ""), float(money(data.get("cost", 0))), user.id, now()))
            self.audit(conn, user, "حدث عداد", "meter_events", cur.lastrowid, after=data)
            return cur.lastrowid
