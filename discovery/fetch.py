"""Lettura lenta e rispettosa delle pagine pubbliche (solo libreria standard)."""
from __future__ import annotations

import random
from collections import deque
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .parse import extract_id

BASE = "https://chromewebstore.google.com"
UA = "OrfaneResearchBot/1.0 (+ricerca di mercato; poche richieste al secondo)"


class Fetcher:
    def __init__(self, delay: float = 1.0, timeout: float = 20.0, retries: int = 2):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last = 0.0

    def _wait(self) -> None:
        gap = self.delay * random.uniform(0.8, 1.4)
        elapsed = time.monotonic() - self._last
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last = time.monotonic()

    def get(self, url: str) -> tuple[int, str]:
        """Ritorna (status_http, testo). status 0 = errore di rete."""
        for attempt in range(self.retries + 1):
            self._wait()
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.status, r.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return e.code, ""
                if e.code == 429 or e.code >= 500:
                    time.sleep(10 * (attempt + 1))  # rallenta se Google chiede di rallentare
                    continue
                return e.code, ""
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(3 * (attempt + 1))
        return 0, ""


def _locs(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]


def sitemap_detail_urls(fetcher: Fetcher, max_shards: int | None = None) -> list[tuple[str, str]]:
    """Scorre l'indice della sitemap e ritorna [(ext_id, url)] delle pagine /detail/."""
    status, index = fetcher.get(f"{BASE}/sitemap")
    if status != 200:
        raise RuntimeError(f"Sitemap non raggiungibile (HTTP {status})")
    todo = deque(_locs(index))
    out: dict[str, str] = {}
    seen: set[str] = set()
    shards = 0
    while todo:
        url = todo.popleft()
        if url in seen:
            continue
        seen.add(url)
        if "/detail/" in url:
            if ext := extract_id(url):
                out[ext] = url
            continue
        if max_shards is not None and shards >= max_shards:
            continue
        shards += 1
        status, body = fetcher.get(url)
        if status != 200 or not body.strip():
            continue
        try:
            locs = _locs(body)
        except ET.ParseError:
            continue
        todo.extend(locs)  # puo' contenere altre sitemap o pagine detail
    return list(out.items())
