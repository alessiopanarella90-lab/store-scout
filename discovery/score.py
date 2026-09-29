"""Punteggio 'occasione': tanti utenti, fermo da tanto, utenti scontenti.

Regole semplici e leggibili, da ritoccare dopo i primi report.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

MIN_USERS = 5_000
MIN_STALE_DAYS = 540  # ~18 mesi senza aggiornamenti

# Categorie dove un rifacimento ha poco senso o il rischio e' alto
EXCLUDED_CATEGORIES = {"Games", "Just for Fun"}

# Marchi noti: non si possono rifare senza violare il marchio, e spesso hanno gia' un sostituto ufficiale
BRANDS = ("google", "microsoft", "adobe", "apple", "norton", "zoho", "mcafee", "avast", "amazon",
          "facebook", "netflix", "spotify", "dropbox", "evernote", "yahoo", "cut the rope")


def days_since(iso: Optional[str], today: Optional[date] = None) -> Optional[int]:
    if not iso:
        return None
    today = today or date.today()
    return (today - date.fromisoformat(iso)).days


def opportunity_score(
    users: Optional[int],
    updated: Optional[str],
    rating: Optional[float],
    rating_count: Optional[int],
    removed: bool = False,
    category: Optional[str] = None,
    today: Optional[date] = None,
) -> float:
    """0 = non interessante. Piu' alto = occasione migliore."""
    if not users or users < MIN_USERS:
        return 0.0
    # category None = app o tema (non un'estensione): fuori
    if category is None or category in EXCLUDED_CATEGORIES:
        return 0.0
    stale = days_since(updated, today)
    if not removed and (stale is None or stale < MIN_STALE_DAYS):
        return 0.0

    demand = math.log10(users)  # 5k -> 3.7, 100k -> 5, 1M -> 6
    staleness = 2.0 if removed else min((stale or 0) / 365, 5) / 2 + 0.5  # 0.5..3
    if rating is None or not rating_count or rating_count < 10:
        pain = 1.0
    else:
        pain = 1.0 + max(0.0, 4.5 - rating) / 2  # voto basso = utenti scontenti = spazio per noi
    return round(demand * staleness * pain, 3)


def rank(rows: list[dict], today: Optional[date] = None, top: int = 10) -> list[dict]:
    scored = []
    for r in rows:
        if any(b in (r.get("name") or "").lower() for b in BRANDS):
            continue
        s = opportunity_score(
            r.get("users"), r.get("updated"), r.get("rating"), r.get("rating_count"),
            removed=bool(r.get("removed_at")), category=r.get("category"), today=today,
        )
        if s > 0:
            scored.append({**r, "score": s, "stale_days": days_since(r.get("updated"), today)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top]
