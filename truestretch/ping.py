"""Server ping board: VALORANT's own ping to every game server of the player's region, read from the game's log.

In the lobby VALORANT measures its ping to every game server ("game pod") of the region and sends the figures to
Riot with its party requests. They end up in `%LOCALAPPDATA%\\VALORANT\\Saved\\Logs\\ShooterGame.log` as one line
per request, for example:

    [2026.11.21-19.36.42:097][729]LogPlatformCommon: Platform HTTP Query End. QueryName: [Party_FetchPlayer],
    URL [GET https://glz-eu-1.eu.a.pvp.net/parties/v1/players/<account id>?aresriot.aws-euc1-prod.eu-gp-frankfurt-1=55
    &aresriot.aws-ist1-prod.eu-gp-istanbul-2=44&…&preferredgamepods=aresriot.aws-euc1-prod.eu-gp-frankfurt-1], …

The same line carries the player's account id in the URL path: only the server names and the milliseconds are
kept, never the line. Before the first measurement of a session VALORANT logs
`LogPingManager: Warning: Failure to ping endpoint aresriot.<server>, not reporting stats.` for every server it
couldn't reach yet - every three minutes, for most servers, even in a healthy session, so those lines are ignored.
The measurements themselves are taken once per game start. Format verified on real logs, release-13.10, 2026-11-24.

Riot publishes the server status of every region as JSON (the feed behind status.riotgames.com):
`https://valorant.secure.dyn.riotcdn.net/channels/public/x/status/<region>.json`.

Read only: nothing here changes anything on the PC or in the game."""

import json
import re
import statistics
import threading
import urllib.request
from datetime import datetime, timedelta

from . import APP_NAME, VERSION
from .matchperf import _logs, _read, _utc
from .paths import DATA_DIR, atomic_write_text, log

PING_FILE = DATA_DIR / "ping.json"
KEEP = 400                      # measurements kept (VALORANT takes a few per lobby visit: this is months of play)
RECENT_DAYS = 14                # "typical" ping = median over this many days
STEADY_MS = 10                  # between-session spread at or under this = steady
STATUS_URL = "https://valorant.secure.dyn.riotcdn.net/channels/public/x/status/{region}.json"
STATUS_PAGE = "https://status.riotgames.com/valorant?region={region}&locale=en_US"
TIMEOUT = 10
STALE_NOTICE_DAYS = 30          # Riot leaves some notices up for months; older ones are counted, not listed

_STAMP = re.compile(r"^\[(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d):\d+\]")
_PING = re.compile(r"aresriot\.([A-Za-z0-9._-]+)=(\d+)")
_PREFERRED = re.compile(r"preferredgamepods=([A-Za-z0-9._,-]+)")
_POD = re.compile(r"(?:^|\.)([a-z]+)-gp-([a-z0-9]+)-(\d+)$")

REGIONS = {"eu": "Europe", "na": "North America", "latam": "Latin America", "br": "Brazil", "ap": "Asia Pacific",
           "kr": "Korea"}
# Server names are written as one word; the ones that aren't a plain city name.
CITIES = {
    "capetown": "Cape Town", "hongkong": "Hong Kong", "saopaulo": "São Paulo", "mexicocity": "Mexico City",
    "losangeles": "Los Angeles", "newyork": "New York", "norcal": "Northern California", "socal": "Southern California",
    "nvirginia": "Virginia", "virginia": "Virginia", "telaviv": "Tel Aviv", "kualalumpur": "Kuala Lumpur",
    "sanjose": "San Jose", "saltlake": "Salt Lake City", "buenosaires": "Buenos Aires", "jakarta": "Jakarta",
    "bahrain": "Bahrain", "istanbul": "Istanbul", "riyadh": "Riyadh", "mumbai": "Mumbai", "tokyo": "Tokyo",
    "seoul": "Seoul", "sydney": "Sydney", "singapore": "Singapore", "santiago": "Santiago", "miami": "Miami",
    "dallas": "Dallas", "chicago": "Chicago", "atlanta": "Atlanta", "ashburn": "Ashburn", "oregon": "Oregon",
    "texas": "Texas", "frankfurt": "Frankfurt", "london": "London", "paris": "Paris", "madrid": "Madrid",
    "stockholm": "Stockholm", "warsaw": "Warsaw", "milan": "Milan", "bogota": "Bogotá", "lima": "Lima",
}

_lock = threading.Lock()


# ---- names --------------------------------------------------------------------------------------------------------

def pod_parts(pod):
    """'aws-euc1-prod.eu-gp-frankfurt-1' -> ('eu', 'frankfurt', 1); None when the name has another shape."""
    m = _POD.search(pod or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def city(pod):
    parts = pod_parts(pod)
    if not parts:
        return pod or "?"
    _, name, n = parts
    nice = CITIES.get(name) or name.capitalize()
    return nice if n == 1 else f"{nice} {n}"


def region_of(pod):
    parts = pod_parts(pod)
    return parts[0] if parts else None


# ---- the game log -------------------------------------------------------------------------------------------------

def parse(text):
    """Measurements in log order: [{"when": datetime (local), "pods": {server: ms}, "preferred": [server]}].
    Nothing else from the line is kept."""
    samples = []
    for line in text.splitlines():
        if "aresriot." not in line or "=" not in line:
            continue
        stamp = _STAMP.match(line)
        when = _utc(stamp) if stamp else None
        if when is None:
            continue
        pods = {pod: int(ms) for pod, ms in _PING.findall(line)}
        if not pods:
            continue
        pref = _PREFERRED.search(line)
        preferred = []
        if pref:
            for p in pref.group(1).split(","):
                p = p[len("aresriot."):] if p.startswith("aresriot.") else p
                if p and p not in preferred:
                    preferred.append(p)
        samples.append({"when": when, "pods": pods, "preferred": preferred})
    return samples


def scan(log_dir):
    """Every measurement in the current log and the backups VALORANT keeps."""
    samples = []
    for path in _logs(log_dir):
        samples += parse(_read(path))
    return samples


# ---- the history file ---------------------------------------------------------------------------------------------

def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _parse(text):
    try:
        return datetime.fromisoformat(text) if text else None
    except (TypeError, ValueError):
        return None


def _key(rec):
    return rec["when"], tuple(sorted(rec["pods"].items()))


def load():
    """Stored measurements, oldest first ([] when there are none yet or the file is unreadable)."""
    try:
        data = json.loads(PING_FILE.read_text(encoding="utf-8"))
        rows = data.get("samples", []) if isinstance(data, dict) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("ping.json unreadable (%s); starting a new ping history", exc)
        try:
            PING_FILE.replace(PING_FILE.with_suffix(".broken.json"))
        except OSError:
            pass
        return []
    out = []
    for r in rows:
        if not (isinstance(r, dict) and isinstance(r.get("pods"), dict) and _parse(r.get("when"))):
            continue
        pods = {str(k): int(v) for k, v in r["pods"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if pods:
            out.append({"when": r["when"], "pods": pods,
                        "preferred": [str(p) for p in (r.get("preferred") or []) if isinstance(p, str)]})
    return sorted(out, key=lambda r: r["when"])


def _save(records):
    try:
        atomic_write_text(PING_FILE, json.dumps({"version": 1, "samples": records[-KEEP:]}, indent=1))
    except OSError as exc:
        log.warning("Couldn't save the ping history: %s", exc)


def update(log_dir):
    """Store every measurement found in VALORANT's logs that isn't stored yet (VALORANT deletes its old logs after
    a few sessions; the history would otherwise be a few days long). Returns all stored samples, oldest first."""
    with _lock:
        stored = load()
        known = {_key(r) for r in stored}
        found = scan(log_dir)
        new = []
        for s in found:
            rec = {"when": _iso(s["when"]), "pods": s["pods"], "preferred": s["preferred"]}
            if _key(rec) in known:
                continue
            known.add(_key(rec))
            new.append(rec)
        if new:
            stored = sorted(stored + new, key=lambda r: r["when"])[-KEEP:]
            _save(stored)
        return stored


# ---- the board ----------------------------------------------------------------------------------------------------

def quality(ms):
    """A word for a ping, the way players talk about it."""
    if ms is None:
        return "unknown"
    if ms <= 40:
        return "great"
    if ms <= 70:
        return "good"
    if ms <= 100:
        return "okay"
    return "high"


def board(samples, now=None, days=RECENT_DAYS):
    """Everything the Servers tab shows, from stored samples (oldest first). None without any measurement.
    rows: one per server, lowest current ping first - {"pod", "city", "region", "now", "typical" (median over the
    last `days`), "best", "worst", "samples", "preferred" (VALORANT's pick in the latest measurement)}."""
    if not samples:
        return None
    now = now or datetime.now()
    latest = samples[-1]
    latest_when = _parse(latest["when"])
    recent = [s for s in samples if (_parse(s["when"]) or now) >= now - timedelta(days=days)]
    if len(recent) < 3:
        recent = samples[-20:]
    all_pods = set(latest["pods"])
    for s in recent:
        all_pods |= set(s["pods"])
    rows = []
    for pod in all_pods:
        values = [s["pods"][pod] for s in recent if pod in s["pods"]]
        rows.append({"pod": pod, "city": city(pod), "region": region_of(pod), "now": latest["pods"].get(pod),
                     "typical": statistics.median(values) if values else None,
                     "best": min(values) if values else None, "worst": max(values) if values else None,
                     "samples": len(values), "preferred": pod in latest["preferred"]})
    rows.sort(key=lambda r: (r["now"] is None, r["now"] if r["now"] is not None else (r["typical"] or 9999),
                             r["city"]))
    regions = [r["region"] for r in rows if r["region"] and r["now"] is not None] or [r["region"] for r in rows
                                                                                       if r["region"]]
    region = max(set(regions), key=regions.count) if regions else None
    preferred = [r for r in rows if r["preferred"]]
    best = rows[0] if rows and rows[0]["now"] is not None else None
    focus = preferred[0] if preferred else best
    spread = sessions = None
    if focus:
        vals = [s["pods"][focus["pod"]] for s in recent if focus["pod"] in s["pods"]]
        if len(vals) >= 3:
            spread = (min(vals), max(vals))
            sessions = len(vals)
    return {"when": latest_when, "region": region, "region_name": REGIONS.get(region, region or "your region"),
            "rows": rows, "preferred": preferred, "best": best, "focus": focus, "spread": spread,
            "sessions": sessions, "samples": len(samples), "recent": len(recent), "days": days}


def insights(b):
    """Plain lines for the player: [(icon, colour key, text)]."""
    if not b:
        return [("info", "muted", "Once VALORANT has started once you'll see here which server it picks for you, "
                                  "which one has your lowest ping, how steady your ping is from one game start to "
                                  "the next, and which Network Buffering setting fits your connection.")]
    lines = []
    pref, best, focus = (b["preferred"][0] if b["preferred"] else None), b["best"], b["focus"]
    if pref and best and pref["pod"] != best["pod"] and pref["now"] is not None and best["now"] is not None \
            and pref["now"] - best["now"] >= 8:
        lines.append(("info", "info", f"VALORANT lists {pref['city']} as your preferred server ({pref['now']} ms), "
                                      f"but {best['city']} measured lower ({best['now']} ms). There is no server "
                                      "picker in VALORANT: matchmaking decides, and either can happen."))
    elif pref and pref["now"] is not None:
        q = quality(pref["now"])
        tail = {"great": "that's as good as it gets.", "good": "a good connection for ranked.",
                "okay": "fine for most games; you may lose some close duels on ping.",
                "high": "high — you'll feel it in duels. A cable instead of Wi-Fi is the first thing to try."}[q]
        lines.append(("check-circle" if q in ("great", "good") else "alert", "success" if q in ("great", "good")
                      else "warning", f"Your server is {pref['city']} at {pref['now']} ms — {tail}"))
    elif best and best["now"] is not None:
        lines.append(("info", "info", f"Your lowest ping is to {best['city']} ({best['now']} ms, "
                                      f"{quality(best['now'])})."))
    if focus and b["spread"]:
        lo, hi = b["spread"]
        n = b["sessions"]
        if hi - lo <= STEADY_MS:
            lines.append(("check-circle", "success", f"Steady: across your last {n} game starts your ping to "
                                                     f"{focus['city']} stayed between {lo} and {hi} ms. Keep "
                                                     "Network Buffering on Minimum in VALORANT (Settings › "
                                                     "General) — it adds no delay."))
        else:
            lines.append(("alert", "warning", f"Unsteady: across your last {n} game starts your ping to "
                                              f"{focus['city']} moved between {lo} and {hi} ms. If players skip "
                                              "or teleport, set Network Buffering to Moderate in VALORANT "
                                              "(Settings › General): it smooths that out for a little delay. A "
                                              "cable instead of Wi-Fi usually fixes the cause."))
    return lines


# ---- Riot's server status ---------------------------------------------------------------------------------------

def _text(items, key="content"):
    for loc in ("en_US", "en_SG", "en_GB"):
        for it in items or []:
            if isinstance(it, dict) and it.get("locale") == loc and it.get(key):
                return str(it[key])
    for it in items or []:
        if isinstance(it, dict) and it.get(key):
            return str(it[key])
    return ""


def _when(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (AttributeError, ValueError):
        return None


def parse_status(data, region=None, now=None):
    """Riot's status JSON -> {"region", "name", "entries": [{"kind", "title", "severity", "text", "updated",
    "platforms"}] newest first (Windows only, or no platform given), "older": entries older than
    STALE_NOTICE_DAYS, "checked"}."""
    now = now or datetime.now()
    entries = []
    for kind, plural in (("incident", "incidents"), ("maintenance", "maintenances")):
        for e in (data.get(plural) or []) if isinstance(data, dict) else []:
            if not isinstance(e, dict):
                continue
            platforms = [str(p).lower() for p in (e.get("platforms") or [])]
            if platforms and "windows" not in platforms:
                continue
            updates = [u for u in (e.get("updates") or []) if isinstance(u, dict) and u.get("publish", True)]
            updates.sort(key=lambda u: str(u.get("created_at") or ""), reverse=True)
            latest = updates[0] if updates else {}
            updated = _when(str(latest.get("created_at") or e.get("updated_at") or e.get("created_at") or ""))
            entries.append({"kind": kind, "title": _text(e.get("titles")) or ("Maintenance" if kind == "maintenance"
                                                                              else "Incident"),
                            "severity": str(e.get("incident_severity") or e.get("maintenance_status") or ""),
                            "text": _text(latest.get("translations")), "updated": updated, "platforms": platforms})
    entries.sort(key=lambda e: e["updated"] or datetime.min, reverse=True)
    fresh = [e for e in entries if e["updated"] and e["updated"] >= now - timedelta(days=STALE_NOTICE_DAYS)]
    older = [e for e in entries if e not in fresh]
    rid = str(data.get("id") or region or "").lower() if isinstance(data, dict) else (region or "")
    name = (data.get("name") if isinstance(data, dict) else None) or REGIONS.get(rid, rid.upper() or "your region")
    return {"region": rid, "name": name, "entries": fresh, "older": older, "checked": now}


def fetch_status(region):
    """Riot's current notices for a region (eu, na, latam, br, ap, kr). Network: call it from a worker thread.
    Raises OSError/ValueError when the feed can't be read."""
    url = STATUS_URL.format(region=region)
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_status(data, region)


def status_page(region):
    return STATUS_PAGE.format(region=region or "na")
