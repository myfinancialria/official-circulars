# myfinancial · Official Circulars

**Live site:** https://myfinancialria.github.io/official-circulars/

A self-updating public index of official regulatory circulars, notices, orders and press
releases from **SEBI**, **NSE** and **BSE** — aggregated from their official public RSS
feeds, stored as a clean JSON dataset, and published as a fast static page on GitHub Pages.

Every entry links to the **original document on the official site** — this project indexes,
it does not republish.

## Data sources

| Source | Official feed | What it carries |
|--------|---------------|-----------------|
| SEBI | `https://www.sebi.gov.in/sebirss.xml` | Circulars, master circulars, orders, press releases, public notices |
| NSE | `https://nsearchives.nseindia.com/content/RSS/Circulars.xml` | Exchange circulars (department decoded from the file code, e.g. `CML` → Listing, `SURV` → Surveillance) |
| BSE | `https://www.bseindia.com/data/xml/notices.xml` | Notices & circulars (timestamped, keyword-categorised) |

## How it stays fresh

`.github/workflows/update-circulars.yml` runs **twice daily** (09:45 IST and 18:45 IST,
plus manual *Run workflow*):

1. `scripts/fetch_circulars.py` (Python 3 stdlib, zero dependencies) pulls all three feeds,
   normalises dates to IST, classifies each item, and merges into `docs/data/circulars.json`
   (dedupe by source + URL; history accumulates up to 6,000 items).
2. If the dataset changed, the workflow commits it, and GitHub Pages redeploys automatically
   (Pages serves `main:/docs`).

**Resilience:** a feed that fails to respond keeps its previously fetched items and is marked
stale — the site footer shows per-source freshness. The job only fails if *all three* feeds fail.

## The dataset

`docs/data/circulars.json` is a stable, fetchable public dataset:

```
https://myfinancialria.github.io/official-circulars/data/circulars.json
```

```jsonc
{
  "generated_at": "2026-09-04T16:30:00+00:00",
  "sources": { "SEBI": { "ok": true, "last_success": "…", "last_new": 4, … }, … },
  "count": 99,
  "items": [
    {
      "id": "a1b2c3d4e5f6",          // sha1(source|url), stable
      "source": "NSE",                // SEBI | NSE | BSE
      "title": "…",
      "url": "https://…/CML76207.pdf",// original document, official host
      "date": "2026-09-04",           // IST calendar date
      "time": "15:08",                // IST, when the feed provides it (BSE); else null
      "category": "Listing",          // SEBI section / NSE department / keyword class
      "ref": "CML76207",              // circular/notice number when derivable
      "first_seen": "…"               // when this index first saw it
    }
  ]
}
```

## Run locally

```bash
python3 scripts/fetch_circulars.py      # refresh the dataset
python3 -m http.server -d docs          # open http://localhost:8000
```

## Roadmap

- **AI summaries** — per-circular plain-English summaries and impact tags (needs an
  `ANTHROPIC_API_KEY` repo secret and a summarise step in the workflow).
- **Backfill** — seed history beyond what the RSS feeds carry (~30 latest per source).
- **Republished RSS/e-mail digest** — a single merged feed of all three sources.

## Credits & disclaimer

- Concept inspired by [rhnvrm/stock-market-circulars](https://github.com/rhnvrm/stock-market-circulars)
  (seen via [codingCoffee's fork](https://github.com/codingCoffee/stock-market-circulars));
  this is an independent from-scratch implementation.
- All circulars and documents are the property of SEBI, NSE and BSE respectively and are
  always linked at their official source.
- **Not investment advice.** This is an informational index maintained by
  [myfinancial](https://github.com/myfinancialria) for research convenience.

Code is [MIT-licensed](LICENSE).
