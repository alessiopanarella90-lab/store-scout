from datetime import date

from discovery import db
from discovery.parse import parse_listing, extract_id, _num
from discovery.score import opportunity_score, rank
from discovery.report import build_report

EXT_ID = "ghgllnooogmjjaolampnnidchlkjgfoo"
URL = f"https://chromewebstore.google.com/detail/vinted-relister/{EXT_ID}"

# Testo modellato su una pagina reale dello store (settembre 2026)
FIXTURE = f"""<html><head><title>Vinted Relister - Chrome Web Store</title>
<script>var junk = "999 users Updated January 1, 2000";</script></head><body>
<h1>Vinted Relister</h1><div>3.3</div><div>out of 5</div><span>41 ratings</span>
<div>Extension</div><div>Shopping</div><div>1,000 users</div>
<h2>Details</h2><div>Version</div><div>0.1.0</div>
<div>Updated</div><div>September 25, 2025</div><div>Size</div><div>45.41KiB</div>
</body></html>"""


def test_extract_id():
    assert extract_id(URL) == EXT_ID
    assert extract_id(f"https://chromewebstore.google.com/detail/{EXT_ID}") == EXT_ID
    assert extract_id("https://example.com") is None


def test_num():
    assert _num("1,000") == 1000
    assert _num("10,000+") == 10000
    assert _num("2.3K") == 2300
    assert _num("1M") == 1_000_000


def test_parse_listing():
    l = parse_listing(FIXTURE, URL)
    assert l.ext_id == EXT_ID
    assert l.name == "Vinted Relister"
    assert l.users == 1000          # non 999 dallo script
    assert l.rating == 3.3
    assert l.rating_count == 41
    assert l.updated == "2025-09-25"
    assert l.version == "0.1.0"
    assert l.category == "Shopping"
    assert l.is_complete


def test_score_filters():
    today = date(2026, 9, 27)
    # troppo pochi utenti
    assert opportunity_score(1000, "2022-01-01", 3.0, 100, category="Tools", today=today) == 0
    # aggiornata di recente
    assert opportunity_score(50_000, "2026-06-01", 3.0, 100, category="Tools", today=today) == 0
    # buona occasione
    good = opportunity_score(50_000, "2022-01-01", 3.0, 100, category="Tools", today=today)
    assert good > 0
    # voto basso = punteggio piu' alto
    assert opportunity_score(50_000, "2022-01-01", 2.0, 100, category="Tools", today=today) > good
    # rimossa conta anche se aggiornata di recente
    assert opportunity_score(50_000, "2026-06-01", 4.5, 100, removed=True, category="Tools", today=today) > 0
    # app o tema (senza categoria estensione) esclusi
    assert opportunity_score(50_000, "2022-01-01", 2.0, 100, category=None, today=today) == 0


def test_db_flow_and_report(tmp_path):
    con = db.connect(tmp_path / "t.sqlite")
    assert db.upsert_urls(con, [(EXT_ID, URL), ("a" * 32, "u2")]) == 2
    assert db.upsert_urls(con, [(EXT_ID, URL)]) == 0
    batch = db.next_batch(con, 10, 30)
    assert len(batch) == 2
    l = parse_listing(FIXTURE, URL)
    l.users = 80_000
    l.updated = "2022-03-01"
    db.save_listing(con, l.as_dict(), 200)
    db.mark_removed(con, "a" * 32, 404)
    con.commit()
    assert len(db.next_batch(con, 10, 30)) == 0
    rows = [dict(r) for r in con.execute("SELECT * FROM extensions")]
    top = rank(rows, today=date(2026, 9, 27))
    assert top[0]["ext_id"] == EXT_ID
    md = build_report(top, {"total": 2, "fetched": 2, "removed": 1}, date(2026, 9, 28))
    assert "Vinted Relister" in md and "80.000" in md

def test_shards_and_merge(tmp_path, monkeypatch):
    import gzip
    from discovery import run
    ids = [f"{c}" * 32 for c in "abcdefghijklmnop"]
    tsv = tmp_path / "urls.tsv.gz"
    with gzip.open(tsv, "wt") as f:
        for i in ids:
            f.write(f"{i}\thttps://chromewebstore.google.com/detail/x/{i}\n")
    parts = []
    total = 0
    for k in range(3):
        path = tmp_path / f"shard-{k}.sqlite"
        monkeypatch.setattr(run, "DB_PATH", str(path))
        run.main(["import-urls", "--file", str(tsv), "--shard", str(k), "--shards", "3"])
        con = db.connect(path)
        total += con.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]
        con.close()
        parts.append(str(path))
    assert total == len(ids)  # ogni estensione in una sola parte
    out = tmp_path / "all.sqlite"
    run.main(["merge", "--out", str(out), *parts])
    assert db.connect(out).execute("SELECT COUNT(*) FROM extensions").fetchone()[0] == len(ids)
