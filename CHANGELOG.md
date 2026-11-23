# Changelog

All notable changes to TrueStretch. Versions follow [Semantic Versioning](https://semver.org/).

## [2.0.1] — 2026-11-23

A design pass over every page, tab and dialog in both themes at 1280×800 and 900×620.

### Changed
- **Checks that fail say what's wrong** (`Check.problem` / `Check.headline` in `engine.py`): "VALORANT not found", "Riot Client not found", "Monitor drivers still on", "No account ticked", "1440 × 1080 isn't available on your display", "Stretch scaling isn't automatic". The one-line summary uses a red cross for a blocking problem and a yellow triangle for a warning.
- **VALORANT page when the game is missing:** a Get VALORANT button next to the problem; no version shown for a game that isn't installed; the first-run tour no longer lists the missing game twice.
- **Top navigation on narrow windows:** all five tabs keep their labels (tighter font and padding under 1000 px) instead of four icons and one word; buttons re-measure after the font change so labels aren't clipped when the window grows again.
- **Optimize Max score card:** score and counts stay on one row on narrow windows, only the buttons wrap (232 px tall at 900 px instead of 320).
- **Settings tab bar** is a centred `QTabBar` over a `QStackedWidget` (document-mode `QTabWidget` ignored the centre alignment).
- **Matches summary cards** are top-aligned so captions line up when one subtitle wraps.
- **My PC screen rows** in plain words (Windows scaling, monitor driver state, connection, graphics card).

### Fixed
- **My PC page could open half-empty** (empty "Your screens" card, health cards stretched to fill the space) until the window was resized: widgets added to a visible card during a refresh waited for Qt's queued show, which didn't arrive in that flow. `Page.settle()` (run by the window after every refresh) shows such widgets at once, as Qt would, and requests a layout pass. The screens section is also guarded: a failed display read shows a one-line note and the rest of the page still refreshes.

### Internal
- `tests/test_ui.py`: offscreen layout tests on the real window (check wording, Get VALORANT visibility, nav labels at 900/1100/1280, centred Settings tabs, score-card height, Matches alignment, My PC failure path). Added to `run_all.py`.
- `tests/shots3.py` captures every page, tab and dialog (`SHOT_THEMES`, `SHOT_PAGES`, including welcome, update, troubleshooting, confirm and report dialogs).

## [2.0.0] — 2026-11-22

A full audit of the UI, the code and player requests, and the fixes that came out of it.

### Added
- **Matches page and after-match report** (`history.py`, `ui/matches_page.py`).
  - Every finished match is stored in `%APPDATA%\TrueStretch\matches.json`, written atomically, keeping the last 300.
  - Each match records the map, length, average FPS, slow-frame share, engine latency and the FPS limiter, plus the stretch size and whether Optimize Max was active.
  - The page shows summary cards, an FPS chart and "what changed your FPS" insights (Optimize Max before/after, by stretch size, most common limiter).
  - A short report appears after each match. It can be turned off in Settings › Behaviour.
  - Round blocks now carry the map name.
- **Troubleshooting window.**
  - Opens from the VALORANT page and from Settings › Help.
  - Opens by itself after a failed Test stretch.

### Changed
- **VALORANT page.**
  - Compact header; the "more games soon" line is gone.
  - The checklist collapses to one line when everything passes; failing checks are listed first.
  - The duplicate "In VALORANT right now" card is folded into the summary.
  - The unused setup-guide tab, which was still being built and refreshed, is removed.
  - The "Set full-screen scaling automatically" switch is back, now on the Display tab.
  - Only the visible tab is refreshed.
- **Accounts tab.**
  - Rename button.
  - The list is rebuilt only when it changes, and never while a name is being edited.
  - The "Locked" column only appears when a file is locked.
- **Optimize Max.**
  - Filters are To do / Optional / Already optimal / Everything, defaulting to To do.
  - One Optimize button; the per-row Apply buttons are gone.
  - Selections are kept by item id across filters and scans.
  - The technical report opens in a dialog.
  - The score is coloured by value.
  - Plainer labels: "Optional" and "Set in game".
  - Undo failures are reported.
- **Theme.**
  - Red is reserved for primary actions.
  - Toggles and checkboxes use off-white instead of red.
  - Links use the text colour.
  - A distinct danger colour.
  - Higher-contrast faint text in both themes.
  - Light-theme colour fixes.
  - Keyboard focus outlines appear only after Tab.
  - Accessible names on rows and tiles.
  - Switching theme rebuilds the pages so icons follow at once.
- **Main window.**
  - Sized to fit the screen.
  - PLAY shows Starting… and is disabled while launching or when VALORANT isn't installed.
  - The status badge only appears when there's something to say.
  - Errors appear once, in a message box only, not also as a toast.
  - A warning when another program holds the hotkeys.
  - Pages aren't refreshed while the window is hidden.
  - Question dialogs have verb buttons instead of Yes/No.
- **First-run tour.**
  - A "VALORANT isn't installed" step with Get VALORANT and Look again.
  - Fix buttons sit inline next to each problem.
  - A responsive grid for the stretch tiles, with the same availability rule as the VALORANT page.
- **Test stretch.** A timeout no longer counts as "black bars", and Enter means "it fills".

### Fixed
- **In-match scaling no longer saves to Windows' display database.** It is applied without `SDC_SAVE_TO_DATABASE`, which had written the stretched mode into Windows' saved display settings, so a power cut mid-match could boot the PC stretched.
- **`revert_display` is reliable.**
  - The target comes from the display that was actually stretched.
  - Falls back to Windows' saved mode.
  - Clears the session only after checking that the screen left the stretched size.
  - Otherwise it retries every few seconds, never mid-match, and tells the player once.
- **`Engine.poll` is guarded.** Each distinct error is logged and shown once, and the crash handler is non-reentrant.
- **The guard process respects "When TrueStretch quits: keep stretched"** (`keep_on_exit`) and logs to its own `watchdog.log`, so the main log rotates again.
- **Crash-safe writes everywhere.**
  - Atomic, fsynced writes (`paths.atomic_write_text` / `atomic_write_bytes`) for settings, session state, the optimizer undo list, VALORANT ini restores and backup restores.
  - `IniFile.save` uses a unique temp file, an fsync and a process-wide lock.
  - It refuses to save a file that could only be decoded lossily.
  - A damaged `session.json` / `optimizer-undo.json` / `matches.json` is set aside as `.broken.json`, and Optimize refuses to run while the undo list is damaged.
- **Smaller fixes.**
  - A VALORANT log renamed mid-scan no longer makes the game look "not installed".
  - The resolution cache is dropped when a driver update removes the custom resolution.
  - "Switch to X Hz" isn't offered while stretched.
  - The checklist's resolution and scaling rows can now actually fail (they were always green).

### Tests
- New `tests/test_safety.py`: switch-back paths, no-save scaling, the guard's keep-stretched case, atomic writes, damaged files and lossy ini files.
- New `tests/test_history.py`: map parsing (including "Infinity" ≠ the "Init" menu), storage, duplicates, VALORANT log rotation and the after-match note.
- Both run in CI.

## [1.10.1] — 2026-11-22

### Fixed
- **Old versions' unpack folders are now really deleted.** The one-file TrueStretch.exe unpacks itself once per
  version into `%LOCALAPPDATA%\TrueStretch\<version>` (about 80 MB each). The clean-up that was meant to remove the
  previous versions after an update compared the wrong path (the TrueStretch.exe you double-click instead of the
  unpacked copy that actually runs), so it never removed anything and every version you ever ran stayed on the
  drive. The app now finds the folder it really runs from, deletes the other version folders at every start, and
  leaves a folder alone while another copy of TrueStretch is still running from it (it goes at the next start).
  Settings, backups and logs are in a different place and are not touched.

## [1.10.0] — 2026-11-21

### Optimize Max
- **Vignette and Improve Clarity are read for real.** The two *Inside VALORANT* rows that used to say "Set in game"
  now read their values (`VignetteEnabled`, `ImproveClarity`) from the account settings file like the other rows:
  Off is marked as done, On points to VALORANT → Settings → Video → Graphics Quality, and a setting you never touched
  shows "Game default". Read-only, as before: these live in your Riot account, so only the game can change them.

## [1.9.0] — 2026-11-20

### Optimize Max
- **Who took the processor.** When the processor sets your FPS, the *Your last match* row now says how many of your
  processor threads VALORANT itself kept busy on average and how many your other programs took (from the game's own
  per-round statistics). If other programs took a thread or more, the row points to the Startup and Background
  checks; if they took little, the processor's own speed is the limit and the power settings matter. Read-only;
  hidden when the graphics card or the FPS limit sets the FPS, and on logs without the two lines.

## [1.8.0] — 2026-11-19

### Optimize Max
- **Game delay.** The *Your last match* row now shows VALORANT's own *engine latency*: how many milliseconds the
  game itself took per frame on average in your last match, which is the part of your input delay the game adds
  (mouse and monitor add theirs). Averaged over every frame of the match, from the game's per-round statistics.
  Read-only; logs without the line don't show it.
- **Before vs after, now with delay.** When matches before and after your first Optimize Max change can be compared,
  the row also shows the game delay on both sides (only when every compared match has the figure).

## [1.7.1] — 2026-11-18

### Optimize Max
- **Who filled the memory.** When Windows memory was 90% full or more in your last match, the *Your last match* row
  now says how much VALORANT itself used and how much the other programs used (from the game's own per-round
  statistics, at the round where memory was fullest). The advice depends on it: close other apps when they used most
  of it, or more memory (RAM) when the game itself needs most of it. Logs without these lines keep the short advice.

## [1.7.0] — 2026-11-18

### Optimize Max
- **Before vs after Optimize Max.** The *Your last match* row now also compares your real average FPS in the
  matches played after your first Optimize Max change with the matches played before it (up to 5 matches and at
  least 5 minutes of play on each side; a match running at the moment of the change counts on neither side), from
  VALORANT's own per-round statistics. Read-only. Shown only when the logs VALORANT keeps have matches on both sides,
  and not when the in-game FPS limit sets the FPS.

## [1.6.0] — 2026-11-16

### Works on PCs with Smart App Control
- **Install without TrueStretch.exe.** Windows 11's *Smart App Control* blocks every program that isn't code-signed,
  with no "Run anyway" button, so TrueStretch.exe couldn't start on those PCs. There is now a one-command install
  that runs TrueStretch from its open-source code with the official Python (signed by the Python Software
  Foundation) and Qt (signed by The Qt Company), which Smart App Control allows. Open PowerShell and paste
  `irm https://candyqueenjr.github.io/TrueStretch/install.ps1 | iex`. It installs Python for your user if needed,
  puts TrueStretch on the Desktop and in the Start menu, and starts it. It changes no Windows security setting.
- **That install updates itself too.** When a new version is out, *Update and restart* downloads the new source,
  checks it is the right version, and swaps it in on restart. Settings stay.

### App
- **Star on GitHub.** Settings › Help and About have a *Star on GitHub* button: TrueStretch is free and open source,
  and stars help other players find it.

## [1.5.0] — 2026-11-13

### Optimize Max
- **Page file.** The page file is extra room on your drive that Windows uses when memory is full. Some "FPS boost"
  guides and tweak tools switch it off; that adds no FPS, and when memory runs out the game freezes or closes in the
  middle of a match. A new check under Windows shows whether your page file is on. If it is switched off, Apply lets
  Windows manage it again — the factory setting — with one administrator prompt and a restart. A page file that is
  on (managed by Windows, or with a size you picked) is shown as fine and never changed. Undo puts back exactly what
  was there before, and the row tells you when a change is still waiting for a restart.

## [1.4.0] — 2026-11-12

### Optimize Max
- **Your last match.** VALORANT writes its own performance statistics into its log at the end of every round
  (frames drawn, round length, how long the graphics card worked on each frame). TrueStretch now reads the rounds of
  your last match and shows one row under Your PC: your real average FPS, and what limits it — the graphics card
  (lower graphics quality or a stretched resolution helps most), the processor (graphics settings add little; the
  Windows, startup and background checks matter most), or your in-game FPS limit. It also points out stutters (more
  than 1% of frames slower than 60 FPS), memory over 90% full during the match, and shader stutters. Read-only, and
  hidden until you have played a match.

## [1.3.0] — 2026-11-12

### Optimize Max
- **Graphics chip VALORANT used.** On laptops with two graphics chips (the built-in Intel/AMD one and the NVIDIA/AMD
  gaming card), Windows decides which one runs the game, and the built-in chip costs a lot of FPS. VALORANT records
  the chip it used in its own log at every start; TrueStretch now reads that record and shows it under Windows, so
  you can see that the game really runs on the gaming card. If it ran on the built-in chip, the row says so and
  points to "VALORANT on the fast graphics card", which fixes it from the next start. If the game ran with no
  graphics driver at all (Windows' basic display driver), the row warns about that too. Read-only, and hidden on PCs
  with a single graphics card.

## [1.2.0] — 2026-11-09

### Optimize Max
- **Keyboard shortcut pop-ups.** Three new Windows checks: the Sticky Keys shortcut (press Shift 5 times), the
  Filter Keys shortcut (hold the right Shift key for 8 seconds) and the Toggle Keys shortcut (hold Num Lock for
  5 seconds). Windows turns these on by default; all three are things you do while walking, crouching or holding an
  angle, and the pop-up appears over VALORANT and steals focus — Filter Keys also makes Windows ignore quick key
  presses. Apply turns off **only the shortcut**, never the feature: Sticky, Filter and Toggle Keys stay available in
  Windows Settings > Accessibility > Keyboard. If you actually use one of them (it is switched on), TrueStretch leaves
  it alone and shows it as information.
- The change is applied live and kept for the next sign-in; Undo restores the exact original Windows setting and
  registry copy.
- **Inside VALORANT now shows your real settings.** The 14 settings that live in your Riot account (NVIDIA Reflex,
  Multithreaded Rendering, Material/Texture/Detail/UI quality, Anti-Aliasing, Anisotropic Filtering, Bloom,
  Distortion, Cast Shadows, the FPS limit) are read from VALORANT's own settings file for the account you played
  last, instead of a blank "Set in game". Each one is marked **Optimized** or **Manual** with the value it has now,
  the value to pick and the exact menu — for example "Multithreaded Rendering: Off → On" or "60 FPS cap (screen:
  144 Hz)". TrueStretch only reads these; only the game can change them. Settings you never touched show as
  "Game default".

### Fixed
- **Your other per-app graphics choices are kept.** Windows stores several settings for one program in the same
  place — the graphics card to use, Auto HDR, and its own bookkeeping. When TrueStretch set VALORANT to the
  high-performance graphics card (the game page toggle or the Optimize Max check), it replaced that whole entry
  and could drop your Auto HDR choice for VALORANT. It now changes only the graphics-card part and leaves the rest
  exactly as Windows wrote it. The Optimize Max row also says "Power saving" instead of "Let Windows decide" when
  VALORANT is pinned to the slow graphics chip.

## [1.1.1] — 2026-11-06

### Fixed
- **TrueStretch didn't open on some PCs (nothing happened when you clicked it).** Microsoft Defender's
  machine-learning check flagged 1.1.0 as `Program:Win32/Contebrew.A!ml` — a false positive. The single .exe used to
  unpack its program into the Temp folder on every start, and launching programs from Temp is what Defender's model
  treats as suspicious. TrueStretch now unpacks once into its own folder (`%LOCALAPPDATA%\TrueStretch\<version>`),
  which Defender accepts — and it starts faster, because it reuses that folder.
- Old versions' folders are cleaned up automatically after an update.

> If 1.1.0 is blocked on your PC, it can't update itself — download 1.1.1 again from the
> [release page](https://github.com/candyqueenjr/TrueStretch/releases/latest). Your settings are kept.

## [1.1.0] — 2026-11-05

### Optimize Max (new)
- One scan runs **68 checks across 12 categories** and lists **every change on its own** — current value, target
  value, why it matters, and how big the impact is — with an **optimization score** out of 100.
- **Windows:** power mode, Game Mode, Xbox Game Bar background recording, optimizations for windowed games,
  hardware-accelerated GPU scheduling, refresh rate, VALORANT on the fast graphics card, transparency effects,
  pending restarts.
- **Windows power plan:** processor minimum state, processor boost mode, core parking, USB selective suspend,
  PCI Express link power saving, Wi-Fi power saving (plugged-in values only).
- **NVIDIA:** power management, texture filtering, vertical sync, low latency mode, preferred refresh rate and the
  driver frame cap — in VALORANT's own program profile only, so other games are untouched.
- **VALORANT files:** VSync, HDR, dynamic resolution and every graphics quality group, for every account on the PC
  (and HP OMEN AI's copy).
- **Startup apps:** each program that starts with Windows, one by one (Discord, Chrome, Overwolf, …).
- **Background & overlays:** Discord, NVIDIA overlay and Instant Replay, RTSS, Overwolf, Medal, OBS, Wallpaper
  Engine, and programs using lots of memory — with how to turn each one off.
- **Your PC:** memory speed (XMP/EXPO) and single-channel memory, SSD or hard drive, Wi-Fi or cable, driver age,
  battery, memory integrity.
- **Inside VALORANT / AMD Software / Intel Graphics:** the settings only those programs can change, each with where
  to change it.
- Nothing changes until you press Apply. Scanning and applying run in the background with live progress. Every
  change is **verified** afterwards, and **Undo** puts back the exact original value.
- **Diagnostics** tab: the full technical report (every value, where it was read, every change made) — copy it or
  save it to your Desktop. Your Riot account ID is hidden.

### New layout and look
- VALORANT-style top bar with a centered **PLAY** button; four clear sections: VALORANT, Optimize, My PC, Settings
  (with Backups and About inside).
- Tactical design: deep navy, off-white highlights, sharp edges, uppercase condensed headings, framed buttons — and a
  new logo.
- Responsive everywhere: content stays centered on wide monitors and reflows on small windows (down to 900 × 600).
- Faster: only the page on screen redraws.

### Fixed
- Undo of game-file changes now also restores the copy HP OMEN AI keeps, and removes settings that didn't exist
  before.

## [1.0.0] — 2026-11-05

The first public release.

### Stretching
- True stretched resolution for VALORANT using the 2026 method: the game starts at your native resolution and the
  desktop switches to the stretched size only once a match or the Range has loaded.
- Switches back to native the moment a match is found or you return to the menu, so agent select never locks the
  wrong size.
- Four stretch levels (Light, Classic 4:3, Strong, Extreme) plus custom sizes; change live with
  <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>↑</kbd>/<kbd>↓</kbd>, toggle with <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>S</kbd>.

### Automatic setup on every PC
- Adds the custom resolution to the graphics driver automatically — NVIDIA, AMD and Intel.
- Falls back to the closest built-in resolution when a driver can't add one.
- Sets graphics-driver scaling to full screen; turns monitor drivers off with a single Windows prompt.
- Sets up every Riot account, including new ones after their first sign-in, and repairs settings VALORANT or other
  programs (such as HP OMEN AI) changed.

### Safety
- Backups of every file before each change; *Restore normal* puts the originals back.
- A guard process restores your normal resolution even if TrueStretch crashes or is closed.
- Warns when VALORANT locked itself to the wrong size and tells you how to fix it.

### App
- *My PC*: screens, graphics, drivers and Windows settings explained, with one-click fixes.
- Auto-updates from GitHub with SHA-256 verification.
- *Support file* button for bug reports.

[1.0.0]: https://github.com/candyqueenjr/TrueStretch/releases/tag/v1.0.0
