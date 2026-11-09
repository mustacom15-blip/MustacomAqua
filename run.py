from __future__ import annotations
import logging
import os
import sys
import traceback
from pathlib import Path

# Keep Qt's data/cache outside the project when packaged.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING","1")

from app.database import Database
from app.paths import data_dir,database_path,resource_dir
from app.services import AuthService


def configure_logging():
    log=data_dir()/"logs"/"application.log"
    logging.basicConfig(filename=log,level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s",encoding="utf-8")


def main():
    configure_logging()
    from PySide6.QtCore import QLockFile,Qt
    from PySide6.QtWidgets import QApplication,QMessageBox
    from app.ui.auth import LoginDialog,SetupDialog
    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_theme
    app=QApplication(sys.argv);app.setApplicationName("MUSTACOM AQUA GESTION PRO");app.setOrganizationName("MUSTACOM SERVICES")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft);apply_theme(app)
    lock=QLockFile(str(data_dir()/"application.lock"));lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        QMessageBox.warning(None,"التطبيق مفتوح","توجد نسخة أخرى من التطبيق مفتوحة. هذا يمنع تعارض قاعدة البيانات والنسخ الاحتياطي.")
        return 0
    db=Database(database_path())
    def excepthook(exc_type,exc,tb):
        logging.critical("Unhandled exception",exc_info=(exc_type,exc,tb))
        QMessageBox.critical(None,"خطأ غير متوقع",f"{exc}\n\nحفظت التفاصيل في مجلد logs داخل بيانات التطبيق.")
    sys.excepthook=excepthook
    while True:
        if AuthService(db).needs_setup():
            setup=SetupDialog(db)
            if not setup.exec():return 0
        login=LoginDialog(db)
        if not login.exec():return 0
        window=MainWindow(db,login.user)
        logging.info("Application started by %s",login.user.username)
        window.show()
        code=app.exec()
        if code!=20:return code
        # Restore completed; reconstruct database and authenticate again.
        db=Database(database_path())


if __name__=="__main__":
    try:sys.exit(main())
    except Exception:
        configure_logging();logging.critical("Startup failure",exc_info=True)
        raise
