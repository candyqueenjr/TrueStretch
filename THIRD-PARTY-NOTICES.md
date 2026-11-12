# Third-party software

`TrueStretch.exe` contains the following open-source components. All of them are used under their own licenses,
which allow redistribution; none of them are modified.

| Component | License | Source |
|---|---|---|
| Python 3.12 runtime | Python Software Foundation License (PSF-2.0) | https://www.python.org/ |
| Qt 6 (via PySide6) | GNU Lesser General Public License v3 (LGPL-3.0) | https://code.qt.io/ |
| PySide6 / Shiboken6 | GNU Lesser General Public License v3 (LGPL-3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Nuitka runtime (compiler used for the release build) | Apache License 2.0 | https://github.com/Nuitka/Nuitka |
| Barlow and Barlow Condensed fonts | SIL Open Font License 1.1 — see [assets/fonts/OFL.txt](assets/fonts/OFL.txt) | https://github.com/jpt/barlow |

## Qt and PySide6 (LGPL-3.0)

The Qt and PySide6 libraries are included as separate, unmodified DLL files: at start the program unpacks into
`%LOCALAPPDATA%\TrueStretch\<version>`, where they can be inspected or replaced. The complete source code of
TrueStretch, together with the exact build script (`build.ps1`) and dependency versions (`requirements.txt`), is
in this repository, so anyone can rebuild the program against a modified version of these libraries.

Build tools that are not part of the program: Pillow (icon rendering, HPND license), MinGW-w64 GCC (downloaded by
Nuitka).
