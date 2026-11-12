# Security

## Only download from here

The only official place to get TrueStretch is
**[github.com/candyqueenjr/TrueStretch/releases](https://github.com/candyqueenjr/TrueStretch/releases)**.
Copies from anywhere else (Discord uploads, other websites, "cracked" or "premium" versions) may be modified — don't run
them.

## Check that your file is genuine

Every release lists the SHA-256 checksum of `TrueStretch.exe` (also attached as `TrueStretch.exe.sha256`). To check
your copy, open PowerShell in the folder with the file and run:

```powershell
Get-FileHash .\TrueStretch.exe -Algorithm SHA256
```

The `Hash` it prints must match the one on the release page exactly. The built-in updater performs this same check
automatically before installing any update.

## What TrueStretch does and doesn't do

- ✅ Changes your Windows display resolution and graphics-driver scaling
- ✅ Edits VALORANT's own `GameUserSettings.ini` (after backing it up)
- ✅ Turns monitor drivers off/on in Device Manager (Windows asks for permission)
- ✅ Reads VALORANT's log file to know when a match has loaded
- ✅ Asks GitHub whether a newer version exists (can be turned off)
- ❌ Never reads or writes game memory, injects code, or interacts with Vanguard
- ❌ Never collects or sends personal data

## “Windows protected your PC” / antivirus warnings

TrueStretch is free and open source. Releases aren't code-signed yet (signing through SignPath Foundation is being set
up — see the [code signing policy](README.md#code-signing-policy)), so Windows SmartScreen may warn the first time you run it, and some
antivirus programs flag new unsigned programs by default. If your antivirus flags the official file (with a matching
checksum), please report it as a false positive to your antivirus vendor — and let us know in an issue.

## Reporting a vulnerability

Found a security problem? Please **don't** open a public issue. Use
[GitHub's private vulnerability reporting](https://github.com/candyqueenjr/TrueStretch/security/advisories/new) instead.
