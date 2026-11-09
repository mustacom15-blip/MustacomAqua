# Build and download the Windows installer with GitHub Actions

The workflow is `.github/workflows/build-windows-installer.yml`. It builds on GitHub's **Windows x64 runner**, not on Linux. It does not require any paid service or custom secret.

## Current build status

Adding the workflow does **not** mean that Windows binaries have already been generated. There is no installer download URL until a workflow run finishes successfully or a tagged GitHub Release is published. Check the repository's Actions page for the actual result.

## 1. Put the complete project on GitHub

Create a GitHub repository, then run these commands in the project folder (replace the repository URL):

```bash
git init
git add .
git commit -m "MUSTACOM AQUA GESTION PRO 1.0.0"
git branch -M main
git remote add origin https://github.com/YOUR-USER/YOUR-REPOSITORY.git
git push -u origin main
```

Commit the entire project, including:

- `.github/workflows/build-windows-installer.yml`
- `app/`, `run.py`, `requirements.txt`, and `tests/`
- `MustacomAqua.spec`, `build_windows.ps1`, and `installer/`
- `assets/mustacom_logo.png` and `assets/app.ico`
- `help/guide_ar.html`

The workflow installs Python dependencies and Inno Setup on the runner. No database, customer data, password, signing certificate, or secret is included.

## 2. Run the workflow

1. Open the GitHub repository.
2. Select **Actions → Build Windows Installer**.
3. Select **Run workflow**, keep `main`, and confirm.
4. Wait for every step to finish successfully.

It also runs on pushes to `main` and on pull requests. A failure in the tests, PyInstaller, packaged EXE smoke test, Inno Setup, portable ZIP creation, or checksum generation stops the job and prevents a successful build from being reported.

## 3. Download the generated files

After a **successful** run, open its summary page and use the **Artifacts** section:

| Artifact | Contents |
|---|---|
| `MUSTACOM-Aqua-Windows-Installer` | `MustacomAquaGestionPro_Setup_1.0.0.exe` and `SHA256SUMS.txt` |
| `MUSTACOM-Aqua-Windows-Portable` | `MustacomAquaGestionPro_Portable_1.0.0.zip` and `SHA256SUMS.txt` |

The generic Actions address is:

```text
https://github.com/YOUR-USER/YOUR-REPOSITORY/actions
```

Replace the placeholders, choose the successful run, and download its artifacts. GitHub may require you to sign in if the repository is private. Artifacts expire after 30 days.

The portable artifact is a **portable application folder in ZIP format**: extract the entire folder, keep `_internal` beside `MustacomAquaGestionPro.exe`, and run that EXE. It is not a single-file executable.

## 4. Optional: publish a permanent GitHub Release

Create and push a version tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

After the tagged workflow succeeds, the same installer, portable ZIP, and checksums are attached to the Release. Then the download page is:

```text
https://github.com/YOUR-USER/YOUR-REPOSITORY/releases/tag/v1.0.0
```

The workflow uses the repository's automatic `GITHUB_TOKEN`; no additional token setup is normally needed. If your organization restricts Actions permissions, allow **Read and write permissions** for GitHub Actions in the repository settings so tagged Releases can be published.

## 5. Verify the download

On Windows, compare the installer hash with `SHA256SUMS.txt`:

```powershell
Get-FileHash -Algorithm SHA256 .\MustacomAquaGestionPro_Setup_1.0.0.exe
```

Before production deployment:

1. Install on a clean Windows 10/11 x64 machine or VM.
2. Confirm the desktop shortcut and uninstall entry.
3. Complete first-run setup with test data.
4. Test members, readings, billing, partial payments, backup, and restore.
5. Print Arabic invoices and receipts physically and to PDF.
6. Uninstall and verify that application data is preserved.

## Build details

- Runner: `windows-latest`, 64-bit
- Python: 3.11 x64
- GUI: PySide6, bundled by PyInstaller
- Installer: Inno Setup 6 installed by Chocolatey
- Tests: the complete pytest suite, including Qt offscreen tests
- Packaged smoke test: the built EXE must remain running for 20 seconds
- Installer assets: the MUSTACOM logo, application icon, Arabic help, Python runtime, Qt plugins, openpyxl, and cryptography are included through `MustacomAqua.spec`
- Outputs: signed only if you later add your own code-signing step; **the current build is unsigned**, so Windows SmartScreen may show a warning

Application data remains outside the installer at:

```text
%LOCALAPPDATA%\MUSTACOM\MustacomAquaGestionPro\mustacom_aqua.db
```

## Local alternative

On a Windows development machine with Python 3.11/3.12 and Inno Setup 6:

```bat
build_installer.bat
```

See `installer/README_WINDOWS.md` for the detailed local release checklist.

---

### ملخص بالعربية

بعد رفع المشروع إلى GitHub، افتح **Actions → Build Windows Installer → Run workflow**. عند نجاح التشغيل فقط ستظهر روابط Artifacts لتحميل مثبّت Inno Setup والنسخة المحمولة. لإصدار دائم، أنشئ Tag باسم `v1.0.0` وادفعه إلى GitHub؛ تُرفع الملفات تلقائياً إلى Release. مجرد إضافة ملف workflow لا يعني أن المثبّت قد أُنشئ، ولا يوجد رابط تنزيل فعلي قبل نجاح التشغيل على GitHub.
