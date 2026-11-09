# Windows build and release checklist

For a cloud Windows build and downloadable installer artifacts, use `.github/workflows/build-windows-installer.yml` and follow `GITHUB_ACTIONS.md`. The instructions below are for a local Windows build.

## Prerequisites

- Windows 10 or Windows 11, 64-bit, fully updated.
- 64-bit Python 3.11 or 3.12 available on PATH.
- Inno Setup 6 installed in its default directory.
- At least 3 GB free disk space for the build environment.

## Build

Open PowerShell in the project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

To build only the PyInstaller application:

```powershell
.\build_windows.ps1 -SkipInstaller
```

If ISCC.exe is in a custom location:

```powershell
.\build_windows.ps1 -InnoCompiler "D:\Tools\Inno Setup 6\ISCC.exe"
```

The build stops if any service test fails. No database or sample member data is included in the installer.

## Release validation on a clean Windows VM/device

1. Install using the generated setup, verify the desktop shortcut and uninstall entry.
2. Complete first-run setup with a temporary test association.
3. Add a member, approved reading, tariff, draft and issued invoice.
4. Record partial and overpayment; verify balances and account credit.
5. Print an Arabic invoice and receipt physically and to Microsoft Print to PDF. Verify letter shaping and RTL.
6. Export every report type to PDF and XLSX.
7. Create encrypted and unencrypted backups; restore both after a change and verify the rollback.
8. Close and reopen the application; confirm persistence.
9. Sign in with every role and verify forbidden operations are unavailable.
10. Uninstall and verify application data is preserved. Reinstall and confirm the data opens.

For a production release, sign the EXE and installer with MUSTACOM SERVICES' code-signing certificate if available. This project does not invent or include a certificate.
