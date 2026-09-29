"""Estrae i dati di un'estensione dalla pagina pubblica del Chrome Web Store.

Lavora sul testo visibile della pagina (versione inglese, ?hl=en), non sulla
struttura HTML, cosi' resta robusto se Google cambia il markup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime
from html.parser import HTMLParser
from typing import Optional

ID_RE = re.compile(r"/detail/(?:[^/]+/)?([a-p]{32})")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)


@dataclass
class Listing:
    ext_id: str
    name: Optional[str] = None
    users: Optional[int] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    updated: Optional[str] = None  # ISO yyyy-mm-dd
    version: Optional[str] = None
    category: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def is_complete(self) -> bool:
        return self.users is not None and self.updated is not None


def extract_id(url: str) -> Optional[str]:
    m = ID_RE.search(url)
    return m.group(1) if m else None


def _num(raw: str) -> Optional[int]:
    raw = raw.strip().replace(",", "").replace("+", "")
    mult = 1
    if raw[-1:].upper() == "K":
        mult, raw = 1_000, raw[:-1]
    elif raw[-1:].upper() == "M":
        mult, raw = 1_000_000, raw[:-1]
    try:
        return int(float(raw) * mult)
    except ValueError:
        return None


USERS_RE = re.compile(r"([\d][\d,\.]*[KM]?\+?)\s+users?\b", re.I)
RATING_COUNT_RE = re.compile(r"([\d][\d,\.]*[KM]?)\s+ratings?\b", re.I)
RATING_RE = re.compile(r"\b([0-5](?:\.\d)?)\s+out of\s+5", re.I)
UPDATED_RE = re.compile(r"Updated\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
VERSION_RE = re.compile(r"\bVersion\s*:?\s*([0-9][\w\.\-]*)")
CATEGORY_RE = re.compile(r"\bExtension\s*(Accessibility|Art & Design|Communication|Developer Tools|"
                         r"Education|Entertainment|Functionality & UI|Games|Household|Just for Fun|"
                         r"News & Weather|Privacy & Security|Shopping|Social|Tools|Travel|Well-being|"
                         r"Workflow & Planning)")


def parse_listing(html: str, url: str) -> Listing:
    ext_id = extract_id(url) or ""
    tx = _TextExtractor()
    tx.feed(html)
    text = " \n ".join(tx.parts)

    listing = Listing(ext_id=ext_id)
    title = tx.title.strip()
    if title:
        listing.name = re.sub(r"\s*-\s*Chrome Web Store\s*$", "", title).strip() or None

    if m := USERS_RE.search(text):
        listing.users = _num(m.group(1))
    if m := RATING_COUNT_RE.search(text):
        listing.rating_count = _num(m.group(1))
    if m := RATING_RE.search(text):
        listing.rating = float(m.group(1))
    if m := UPDATED_RE.search(text):
        try:
            listing.updated = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    if m := VERSION_RE.search(text):
        listing.version = m.group(1)
    if m := CATEGORY_RE.search(text):
        listing.category = m.group(1)
    return listing
