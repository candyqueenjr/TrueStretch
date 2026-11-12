from .base import ComingSoon
from .valorant import Valorant

# Supported games, in sidebar order. New games: implement games.base.Game and add them here.
GAMES = [Valorant()]

COMING_SOON = [
    ComingSoon("cs2", "Counter-Strike 2", "Valve"),
    ComingSoon("fortnite", "Fortnite", "Epic Games"),
    ComingSoon("apex", "Apex Legends", "Respawn"),
]
