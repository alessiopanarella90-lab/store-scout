# Store scout

Reads public Chrome Web Store listing pages at a gentle pace (about one request per
0.6 seconds per worker) and stores basic public metadata: users, rating, number of
ratings, last update date, version and category.

- Standard-library Python 3.11, no dependencies.
- Runs on GitHub Actions with 6 parallel workers; each worker always handles the
  same slice of extensions and keeps its own SQLite database.
- Databases are published as assets of the `data` release.

```bash
python -m discovery.run sitemap --out-tsv urls.tsv.gz
ORFANE_DB=shard-0.sqlite python -m discovery.run import-urls --file urls.tsv.gz --shard 0 --shards 6
ORFANE_DB=shard-0.sqlite python -m discovery.run crawl --minutes 30 --limit 500
python -m discovery.run merge --out all.sqlite shard-*.sqlite
```
