from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .database import Database, now
from .paths import data_dir
from .security import User
from .services import AppError, BaseService

MAGIC = b"MUSTACOM-AQUA-BACKUP-v1\n"


class BackupService(BaseService):
    def __init__(self, db: Database):
        super().__init__(db)
        self.last_error = ""

    def create(self, user: User, folder: str | None = None, password: str = "", include_attachments: bool = True) -> Path:
        if user.role != "admin":
            raise AppError("النسخ الاحتياطي متاح لمدير النظام فقط.")
        target_dir = Path(folder or self.setting("backup_folder") or (data_dir() / "backups")).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.resolve() == self.db.path.parent.resolve():
            raise AppError("اختر مجلداً مختلفاً عن مجلد قاعدة البيانات.")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        with tempfile.TemporaryDirectory(prefix="mustacom_backup_") as tmp:
            tmp_path = Path(tmp)
            db_copy = tmp_path / "mustacom_aqua.db"
            self.db.backup_to(db_copy)
            check = Database(db_copy).integrity_check()
            if check != "ok":
                raise AppError(f"فشل فحص سلامة النسخة: {check}")
            zip_path = tmp_path / "payload.zip"
            digest = hashlib.sha256(db_copy.read_bytes()).hexdigest()
            manifest = {"application": "MUSTACOM AQUA GESTION PRO", "format": 1, "created_at": now(),
                        "database_sha256": digest, "includes_attachments": include_attachments}
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(db_copy, "mustacom_aqua.db")
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                association_logo = self.setting("association_logo", "")
                if association_logo and Path(association_logo).is_file():
                    zf.write(association_logo, "association_logo/"+Path(association_logo).name)
                if include_attachments:
                    attachments = data_dir() / "attachments"
                    if attachments.exists():
                        for path in attachments.rglob("*"):
                            if path.is_file():
                                zf.write(path, str(Path("attachments") / path.relative_to(attachments)))
            if password:
                if len(password) < 8:
                    raise AppError("كلمة مرور النسخة الاحتياطية: 8 أحرف على الأقل.")
                try:
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                    from cryptography.hazmat.primitives import hashes
                except ImportError as exc:
                    raise AppError("التشفير يتطلب حزمة cryptography المضمنة في المثبت.") from exc
                salt, nonce = os.urandom(16), os.urandom(12)
                kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
                encrypted = AESGCM(kdf.derive(password.encode("utf-8"))).encrypt(nonce, zip_path.read_bytes(), MAGIC)
                target = target_dir / f"MustacomAqua_{timestamp}.mustabak"
                target.write_bytes(MAGIC+salt+nonce+encrypted)
            else:
                target = target_dir / f"MustacomAqua_{timestamp}.zip"
                shutil.copy2(zip_path, target)
        with self.db.transaction() as conn:
            self.audit(conn, user, "نسخة احتياطية", "backup", target.name, after={"path": str(target), "encrypted": bool(password)})
            conn.execute("UPDATE settings SET value=? WHERE key='backup_folder'", (str(target_dir),))
        self._apply_retention(user, target_dir)
        return target

    def _apply_retention(self, user: User, folder: Path) -> None:
        retention = int(self.setting("backup_retention", "0") or 0)
        if retention <= 0:
            return
        files = sorted(list(folder.glob("MustacomAqua_*.zip"))+list(folder.glob("MustacomAqua_*.mustabak")), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[retention:]:
            old.unlink()
            with self.db.transaction() as conn:
                self.audit(conn, user, "حذف نسخة وفق سياسة الاحتفاظ", "backup", old.name, before={"path": str(old)}, reason=f"الاحتفاظ بآخر {retention} نسخ")

    @staticmethod
    def inspect(path: str | Path, password: str = "") -> dict:
        source = Path(path)
        if not source.is_file():
            raise AppError("ملف النسخة الاحتياطية غير موجود.")
        try:
            raw = source.read_bytes()
            if raw.startswith(MAGIC):
                if not password:
                    raise AppError("هذه النسخة مشفرة؛ أدخل كلمة المرور.")
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                from cryptography.hazmat.primitives import hashes
                salt, nonce, encrypted = raw[len(MAGIC):len(MAGIC)+16], raw[len(MAGIC)+16:len(MAGIC)+28], raw[len(MAGIC)+28:]
                kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
                raw = AESGCM(kdf.derive(password.encode("utf-8"))).decrypt(nonce, encrypted, MAGIC)
            import io
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                db_bytes = zf.read("mustacom_aqua.db")
                if hashlib.sha256(db_bytes).hexdigest() != manifest["database_sha256"]:
                    raise AppError("بصمة قاعدة البيانات لا تطابق بيان النسخة.")
                return manifest
        except AppError:
            raise
        except Exception as exc:
            raise AppError("تعذر فتح النسخة. تحقق من الملف وكلمة المرور وسلامة النسخة.") from exc

    def restore(self, user: User, source: str | Path, password: str = "") -> None:
        if user.role != "admin":
            raise AppError("الاستعادة متاحة لمدير النظام فقط.")
        source = Path(source)
        self.inspect(source, password)
        # Read before the safety backup in case a configured retention policy removes older files.
        source_bytes = source.read_bytes()
        source_name = str(source)
        # A safety copy is mandatory before replacing the current database.
        safety = self.create(user, password="", include_attachments=True)
        with tempfile.TemporaryDirectory(prefix="mustacom_restore_") as tmp:
            tmp_path = Path(tmp)
            raw = source_bytes
            if raw.startswith(MAGIC):
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                from cryptography.hazmat.primitives import hashes
                salt, nonce, encrypted = raw[len(MAGIC):len(MAGIC)+16], raw[len(MAGIC)+16:len(MAGIC)+28], raw[len(MAGIC)+28:]
                kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
                raw = AESGCM(kdf.derive(password.encode("utf-8"))).decrypt(nonce, encrypted, MAGIC)
            (tmp_path/"payload.zip").write_bytes(raw)
            with zipfile.ZipFile(tmp_path/"payload.zip") as zf:
                for name in zf.namelist():
                    p = Path(name)
                    if p.is_absolute() or ".." in p.parts:
                        raise AppError("مسار غير آمن داخل النسخة.")
                zf.extract("mustacom_aqua.db", tmp_path)
                restored = Database(tmp_path/"mustacom_aqua.db")
                if restored.integrity_check() != "ok":
                    raise AppError("قاعدة البيانات المستعادة غير سليمة.")
                # Validate essential tables before touching the live file.
                tables = {r[0] for r in restored.query("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"members","invoices","payments","users","audit_log"}.issubset(tables):
                    raise AppError("النسخة لا تحتوي بنية تطبيق صالحة.")
                # Close all test connections before replacement. Qt is stopped/restarted by the UI.
                replacement = tmp_path/"replacement.db"
                shutil.copy2(tmp_path/"mustacom_aqua.db", replacement)
                for name in zf.namelist():
                    if name.startswith("attachments/") and not name.endswith("/"):
                        destination = data_dir()/name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src, open(destination,"wb") as dst:
                            shutil.copyfileobj(src,dst)
                restored_logo = ""
                for name in zf.namelist():
                    if name.startswith("association_logo/") and not name.endswith("/"):
                        destination = data_dir()/Path(name).name
                        with zf.open(name) as src, open(destination,"wb") as dst:
                            shutil.copyfileobj(src,dst)
                        restored_logo = str(destination)
                self.db.path.parent.mkdir(parents=True, exist_ok=True)
                # Replace main DB; remove stale WAL/SHM so they cannot contaminate restored data.
                for suffix in ("-wal","-shm"):
                    side = Path(str(self.db.path)+suffix)
                    if side.exists(): side.unlink()
                os.replace(replacement, self.db.path)
        with self.db.transaction() as conn:
            # Absolute paths from the old computer must not be retained after migration.
            for doc in conn.execute("SELECT id,member_id,file_path FROM member_documents").fetchall():
                new_path = data_dir()/"attachments"/"members"/str(doc["member_id"])/Path(doc["file_path"]).name
                conn.execute("UPDATE member_documents SET file_path=? WHERE id=?", (str(new_path), doc["id"]))
            for expense in conn.execute("SELECT id,attachment_path FROM expenses WHERE attachment_path IS NOT NULL").fetchall():
                new_path = data_dir()/"attachments"/"expenses"/Path(expense["attachment_path"]).name
                conn.execute("UPDATE expenses SET attachment_path=? WHERE id=?", (str(new_path), expense["id"]))
            if restored_logo:
                conn.execute("UPDATE settings SET value=? WHERE key='association_logo'", (restored_logo,))
            else:
                current_logo = conn.execute("SELECT value FROM settings WHERE key='association_logo'").fetchone()
                if current_logo and current_logo[0] and not Path(current_logo[0]).is_file():
                    conn.execute("UPDATE settings SET value='' WHERE key='association_logo'")
            restored_user = conn.execute("SELECT id,username,full_name,role,active FROM users WHERE id=?", (user.id,)).fetchone()
            audit_user = user if restored_user else None
            self.audit(conn, audit_user, "استعادة نسخة احتياطية", "backup", source_name, after={"safety_backup": str(safety)}, reason="استعادة مؤكدة من مدير النظام")

    def portable_copy(self, user: User, destination: str | Path) -> Path:
        if user.role != "admin":
            raise AppError("نقل قاعدة البيانات متاح لمدير النظام فقط.")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.db.backup_to(target)
        if Database(target).integrity_check() != "ok":
            raise AppError("فشل فحص النسخة المحمولة.")
        with self.db.transaction() as conn:
            self.audit(conn, user, "تصدير قاعدة محمولة", "backup", str(target))
        return target
