# Changelog

All notable changes to TrueStretch. Versions follow [Semantic Versioning](https://semver.org/).

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
