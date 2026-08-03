from __future__ import annotations

import argparse
import sys

from .paths import AppPaths
from .service import LegendService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="活俠伝の伝説TXTを管理します。")
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="MOD受信箱と伝説フォルダを同期して終了します。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = AppPaths.discover()
    service = LegendService(paths)
    if args.sync_only:
        try:
            result = service.sync(scan_files=True)
            if sys.stdout is not None:
                print(
                    f"取込={result.inbox_imported} 失敗={result.inbox_failed} "
                    f"走査={result.scanned} DB={paths.database_path}"
                )
            return 1 if result.inbox_failed else 0
        finally:
            service.close()

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .ui import create_main_window

    app = QApplication(sys.argv)
    app.setApplicationName("活俠伝 伝説管理")
    app.setOrganizationName("LOM JP Community")

    lock = QLockFile(str(paths.manager_directory / "viewer.lock"))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        QMessageBox.warning(None, "起動済み", "伝説管理アプリはすでに起動しています。")
        service.close()
        return 2

    window = create_main_window(service)
    window.show()
    try:
        return app.exec()
    finally:
        lock.unlock()
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
