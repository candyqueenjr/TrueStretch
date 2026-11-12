"""Follows a game's own log to know when a match has loaded and when the player is back in the menus.

True stretched in VALORANT (2026 patches) only works when the desktop switches to the stretched resolution
AFTER the match map has loaded, and back to native before the menu - switching earlier gives black bars.
"""

import os
from pathlib import Path


class MatchWatcher:
    def __init__(self, log_path, parse_line, menu_maps):
        self.path = Path(log_path)
        self.parse_line = parse_line          # line -> (map_name, ready) or None
        self.menu_maps = {m.lower() for m in menu_maps}
        self.offset = 0
        self.ident = None
        self.map = None
        self.ready = False
        self.game_resolution = None           # the size the game last said it renders at

    @property
    def in_match(self):
        return bool(self.map) and self.ready and self.map.lower() not in self.menu_maps

    def reset(self):
        self.offset, self.ident, self.map, self.ready = 0, None, None, False
        self.game_resolution = None

    def arm(self):
        """The game has just started: whatever is in the log now is from the LAST session (the game replaces the
        file a moment later). Skip it, so an old 'map loaded' line can't stretch the screen while the game is
        still starting - that makes VALORANT adapt to the stretched desktop and the stretch is lost."""
        self.map, self.ready, self.game_resolution = None, False, None
        try:
            st = os.stat(self.path)
            self.ident, self.offset = self._ident(st), st.st_size
        except OSError:
            self.ident, self.offset = None, 0

    @staticmethod
    def _ident(st):
        # Windows keeps a file's creation time when it is deleted and re-created under the same name within
        # seconds ("tunnelling"), so the creation time alone can't tell a fresh log from the old one; the file
        # id (st_ino) does change.
        return (st.st_ctime_ns, getattr(st, "st_ino", 0))

    def poll(self):
        """Read what the game logged since last time. Returns True if in_match changed."""
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        before = self.in_match
        ident = self._ident(st)
        if ident != self.ident or st.st_size < self.offset:   # the game started a fresh log
            self.ident, self.offset = ident, 0
            self.map, self.ready, self.game_resolution = None, False, None
        if st.st_size == self.offset:
            return self.in_match != before
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(st.st_size - self.offset)
        except OSError:
            return self.in_match != before
        last_nl = chunk.rfind(b"\n")
        if last_nl < 0:
            return self.in_match != before      # wait for a complete line
        self.offset += last_nl + 1
        for raw in chunk[:last_nl].split(b"\n"):
            parsed = self.parse_line(raw.decode("utf-8", errors="replace"))
            if not parsed:
                continue
            if parsed[0] == "map":
                self.map, self.ready = parsed[1], parsed[2]
            elif parsed[0] == "leave":
                self.ready = False                # leaving the match: native again before the next map loads
            elif parsed[0] == "resolution":
                self.game_resolution = (parsed[1], parsed[2])
        return self.in_match != before
