# Privacy

TrueStretch runs entirely on your PC. It has no account, no analytics, no telemetry and no ads.

## The only network request

TrueStretch checks for a newer version by asking GitHub's public API for the latest release of this repository
(`https://api.github.com/repos/candyqueenjr/TrueStretch/releases/latest`). It does this when it starts and a few
times a day while it runs. The request contains nothing about you or your PC beyond what any web request contains
(your IP address, seen by GitHub — see [GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement)).
When an update is available and you accept it, the new `TrueStretch.exe` is downloaded from GitHub and its SHA-256
checksum is verified before it replaces the old one.

You can turn the update check off in **Settings → General**.

Buttons such as *Report a problem* or *Get the latest driver* open a web page in your browser only when you click
them.

## What stays on your PC

- Settings, backups and logs are stored in `%APPDATA%\TrueStretch`. The program itself unpacks into
  `%LOCALAPPDATA%\TrueStretch\<version>`.
- TrueStretch reads VALORANT's own settings files and log (`%LOCALAPPDATA%\VALORANT\Saved`) to set the resolution and
  to know when a match has loaded. It never reads game memory and never sends any of it anywhere.

## Support file

**Settings → Support file** creates a zip on *your* Desktop with TrueStretch's logs and settings, a summary of your
screens and graphics card, and only the display-related lines of VALORANT's log, with account IDs and web addresses
removed. Nothing is uploaded: you decide whether to attach it to a bug report.

## Statement

This program will not transfer any information to other networked systems unless specifically requested by the user
or the person installing or operating it, except the anonymous update check described above, which can be turned off.
