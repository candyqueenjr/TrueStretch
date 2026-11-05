# Changelog

All notable changes to TrueStretch. Versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-05

The first public release. 🎉

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
