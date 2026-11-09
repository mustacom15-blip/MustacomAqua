# Verification report — MUSTACOM AQUA GESTION PRO 1.0.0

Date: 2026-11-08

## Automated result

```text
16 passed in 11.24s
QT_QPA_PLATFORM=offscreen python3 -m pytest -q
```

Coverage includes:

1. Authentication and role permissions.
2. Shared member/meter number changes and safe deletion/archive.
3. Duplicate and negative readings and documented correction history.
4. Progressive tariffs and immutable invoice tariff snapshots.
5. Partial payment, oldest-debt allocation, member credit and no invoice-as-cash behaviour.
6. Receipt cancellation with preserved financial history.
7. Expenses, transfers and cash reconciliation.
8. Complaints and inventory stock validation.
9. Reports, dashboard and encrypted backup/portable database.
10. Optional tax calculation and immutable tax snapshot.
11. Paid and unpaid invoice filters.
12. Actual encrypted-backup restoration and mandatory safety copy.
13. Two-month billing-period enforcement.
14. Construction of every report and row/header consistency.
15. All 14 administrator screens and actual Arabic invoice PDF generation.
16. Navigation for reader, reception, auditor, president and treasurer roles.

Additional offscreen integration verification generated Arabic invoice, receipt and statement PDFs and an XLSX report successfully.

## Data integrity protections

SQLite foreign keys, immediate transactions, unique indexes, WAL mode, online backups, integrity checks and restrictive triggers protect invoices, receipts, allocations, expenses, transactions, reading corrections, number history and the audit log.

## GitHub Actions workflow validation

The Windows workflow YAML was parsed successfully and contains 10 steps covering dependency setup, tests, PyInstaller, Inno Setup, packaged EXE smoke testing, portable ZIP creation, checksums, artifact upload, and optional tagged Release publication. All referenced logo, icon, help, specification, and installer assets are present.

**Windows runner execution is pending. No Windows installer artifact or download link has been generated in this workspace.**

## Platform disclosure

The automated tests and PDF generation were run in the provided Linux workspace using Qt offscreen. Windows-specific PyInstaller/Inno Setup scripts are included, but a Windows EXE/installer was not produced or claimed as tested here. Build and perform the release checklist in `installer/README_WINDOWS.md` on Windows 10/11 before production deployment.

No production database or sample association/member data is included.
