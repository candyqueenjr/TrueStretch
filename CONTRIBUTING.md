# Contributing

Thanks for helping make TrueStretch better. Bug reports with a support file (**Settings → Support file**) are the
most useful contribution of all — see [Report a problem](https://github.com/candyqueenjr/TrueStretch/issues/new/choose).

## Run from source

Windows 10/11, Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Project layout

| Path | What it is |
|---|---|
| `main.py` | Entry point (app, `--watchdog` guard process, `--update`) |
| `truestretch/engine.py` | Stretch logic: match detection, resolution switching, first-run setup |
| `truestretch/games/valorant.py` | Everything VALORANT-specific (settings files, log lines) |
| `truestretch/display*.py`, `nvidia.py`, `nvdrs.py`, `amd.py`, `intel.py` | Windows display API and the NVIDIA / AMD / Intel driver APIs |
| `truestretch/optimizer*.py` | Optimize Max: every check with scan / apply / verify / undo |
| `truestretch/updater.py` | Self-update from GitHub releases (SHA-256 verified) |
| `truestretch/ui/` | The PySide6 interface |
| `tests/` | Tests — `run_all.py` runs them |
| `build.ps1` | Builds `dist\TrueStretch.exe` (`-Protected` = Nuitka, the release build) |

## Tests

```powershell
python tests/run_all.py --ci      # read-only tests, run on every push by GitHub Actions
python tests/run_all.py           # full suite: needs VALORANT installed and closed; briefly switches the screen
                                  # resolution and applies + undoes every Optimize Max change on your PC
python tests/run_all.py --build   # also the compiled-exe checks (self-update cycle, Microsoft Defender launch)
```

## Rules for changes

- **Never touch the game while it runs**, never read or write game memory, never interact with Vanguard / anti-cheat.
- **Never change Windows security settings** (Defender, Smart App Control, memory integrity, UAC).
- Every system change must be **backed up, verified and undoable**, and explained to the player in plain words.
- No telemetry, no new network requests (see [PRIVACY.md](PRIVACY.md)).
- Pull requests are reviewed by a maintainer before merging; see the code signing policy in the [README](README.md#code-signing-policy).

## Releases

1. Set `VERSION` in `truestretch/__init__.py`, add `release-notes/<version>.md` and a `CHANGELOG.md` entry.
2. Run the full suite with `--build` on a real gaming PC.
3. Push a tag `v<version>`. GitHub Actions builds the exe from the tagged source, submits it to SignPath for
   signing (a maintainer approves each signing request) and publishes the release with its SHA-256 checksum.

By contributing you agree that your contribution is licensed under this project's [license](LICENSE).
