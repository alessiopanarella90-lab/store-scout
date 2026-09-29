"""Comandi del motore di scoperta.

  python -m discovery.run sitemap   # aggiorna l'elenco delle estensioni dallo store
  python -m discovery.run crawl     # legge un blocco di pagine (limite di tempo e numero)
  python -m discovery.run report    # scrive report.md con le migliori occasioni
"""
from __future__ import annotations

import argparse
import gzip
import os
import zlib
import sys
import time
from datetime import date
from pathlib import Path

from . import db
from .fetch import Fetcher, sitemap_detail_urls
from .parse import parse_listing
from .report import build_report
from .score import rank

DB_PATH = os.environ.get("ORFANE_DB", "data/store.sqlite")


def shard_of(ext_id: str, shards: int) -> int:
    """Assegna sempre la stessa estensione allo stesso processo parallelo."""
    return zlib.crc32(ext_id.encode()) % shards


def cmd_sitemap(args) -> int:
    items = sitemap_detail_urls(Fetcher(delay=args.delay), max_shards=args.max_shards)
    if args.out_tsv:
        with gzip.open(args.out_tsv, "wt", encoding="utf-8") as f:
            for ext_id, url in items:
                f.write(f"{ext_id}\t{url}\n")
        print(f"Sitemap: {len(items)} estensioni scritte in {args.out_tsv}.")
    else:
        con = db.connect(DB_PATH)
        new = db.upsert_urls(con, items)
        print(f"Sitemap: {len(items)} estensioni trovate, {new} nuove.")
    if not items:
        print("ERRORE: nessuna estensione trovata nella sitemap.", file=sys.stderr)
        return 1
    return 0


def cmd_import_urls(args) -> int:
    con = db.connect(DB_PATH)
    items = []
    with gzip.open(args.file, "rt", encoding="utf-8") as f:
        for line in f:
            ext_id, _, url = line.rstrip("\n").partition("\t")
            if ext_id and url and shard_of(ext_id, args.shards) == args.shard:
                items.append((ext_id, url))
    new = db.upsert_urls(con, items)
    print(f"Parte {args.shard + 1}/{args.shards}: {len(items)} estensioni, {new} nuove.")
    return 0


def cmd_merge(args) -> int:
    """Unisce i database dei processi paralleli in uno solo (per il report)."""
    Path(args.out).unlink(missing_ok=True)
    con = db.connect(args.out)
    for i, src in enumerate(args.inputs):
        con.execute(f"ATTACH DATABASE ? AS s{i}", (src,))
        con.execute(f"INSERT OR REPLACE INTO extensions SELECT * FROM s{i}.extensions")
        con.execute(f"INSERT OR REPLACE INTO user_history SELECT * FROM s{i}.user_history")
        con.execute(f"INSERT INTO runs SELECT * FROM s{i}.runs")
        con.commit()
        con.execute(f"DETACH DATABASE s{i}")
    n = con.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]
    print(f"Uniti {len(args.inputs)} database: {n} estensioni.")
    return 0


def cmd_crawl(args) -> int:
    con = db.connect(DB_PATH)
    fetcher = Fetcher(delay=args.delay)
    batch = db.next_batch(con, args.limit, args.refresh_days)
    deadline = time.monotonic() + args.minutes * 60
    started = db.now()
    fetched = ok = errors = 0
    for row in batch:
        if time.monotonic() > deadline:
            break
        url = row["url"] + ("&" if "?" in row["url"] else "?") + "hl=en"
        status, html = fetcher.get(url)
        fetched += 1
        if status == 200:
            listing = parse_listing(html, row["url"])
            listing.ext_id = row["ext_id"]
            db.save_listing(con, listing.as_dict(), status)
            ok += listing.is_complete
        elif status in (404, 410):
            db.mark_removed(con, row["ext_id"], status)
        else:
            db.mark_error(con, row["ext_id"], status)
            errors += 1
        if fetched % 100 == 0:
            con.commit()
            print(f"  {fetched} lette, {ok} complete, {errors} errori")
    con.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?)", (started, db.now(), fetched, ok, errors, "crawl")
    )
    con.commit()
    print(f"Crawl: {fetched} pagine, {ok} lette correttamente, {errors} errori.")

    # Controllo di sicurezza: se la lettura fallisce spesso, Google ha cambiato la pagina.
    if fetched >= 50 and ok / fetched < 0.6:
        print("ERRORE: meno del 60% delle pagine lette correttamente, va aggiornato il parser.",
              file=sys.stderr)
        return 2
    return 0


def _stats(con) -> dict:
    q = lambda sql: con.execute(sql).fetchone()[0]
    return {
        "total": q("SELECT COUNT(*) FROM extensions"),
        "fetched": q("SELECT COUNT(*) FROM extensions WHERE last_fetched IS NOT NULL"),
        "removed": q("SELECT COUNT(*) FROM extensions WHERE removed_at IS NOT NULL"),
    }


def cmd_report(args) -> int:
    con = db.connect(DB_PATH)
    where = "" if args.include_reported else "WHERE reported_at IS NULL"
    rows = [dict(r) for r in con.execute(f"SELECT * FROM extensions {where}")]
    seen = set()
    if args.seen_file and Path(args.seen_file).exists() and not args.include_reported:
        seen = set(Path(args.seen_file).read_text().split())
        rows = [r for r in rows if r["ext_id"] not in seen]
    top = rank(rows, top=args.top)
    Path(args.out).write_text(build_report(top, _stats(con), date.today()), encoding="utf-8")
    if args.mark and top:
        ts = db.now()
        con.executemany("UPDATE extensions SET reported_at=? WHERE ext_id=?",
                        [(ts, r["ext_id"]) for r in top])
        con.commit()
    if args.mark and args.seen_file and top:
        Path(args.seen_file).write_text("\n".join(sorted(seen | {r["ext_id"] for r in top})) + "\n")
    print(f"Report scritto in {args.out} con {len(top)} candidati.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="discovery")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sitemap")
    s.add_argument("--delay", type=float, default=1.0)
    s.add_argument("--max-shards", type=int, default=None)
    s.add_argument("--out-tsv", default=None, help="scrive l'elenco in un file .tsv.gz invece che nel database")
    s.set_defaults(func=cmd_sitemap)

    iu = sub.add_parser("import-urls")
    iu.add_argument("--file", required=True)
    iu.add_argument("--shard", type=int, default=0)
    iu.add_argument("--shards", type=int, default=1)
    iu.set_defaults(func=cmd_import_urls)

    m = sub.add_parser("merge")
    m.add_argument("--out", required=True)
    m.add_argument("inputs", nargs="+")
    m.set_defaults(func=cmd_merge)

    c = sub.add_parser("crawl")
    c.add_argument("--limit", type=int, default=5000)
    c.add_argument("--minutes", type=float, default=150)
    c.add_argument("--delay", type=float, default=1.0)
    c.add_argument("--refresh-days", type=int, default=30)
    c.set_defaults(func=cmd_crawl)

    r = sub.add_parser("report")
    r.add_argument("--top", type=int, default=10)
    r.add_argument("--out", default="report.md")
    r.add_argument("--mark", action="store_true", help="non riproporre gli stessi candidati")
    r.add_argument("--include-reported", action="store_true")
    r.add_argument("--seen-file", default=None, help="elenco degli ID gia' proposti")
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
