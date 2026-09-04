#!/usr/bin/env python3
"""Fetch official circulars/notices from the SEBI, NSE and BSE public RSS feeds
into docs/data/circulars.json — the dataset behind the public site.

Python 3 stdlib only, no dependencies. Run from anywhere:

    python3 scripts/fetch_circulars.py

Behaviour:
  - merges new feed items into the existing dataset (dedupe by source+url)
  - a source that fails to respond keeps its previously fetched items and is
    marked stale in the per-source status block (the site surfaces this)
  - exits non-zero only if ALL sources fail
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "docs" / "data" / "circulars.json"
MAX_ITEMS = 6000  # ≈ a year+ of all three feeds; keeps the JSON snappy to load
IST = timezone(timedelta(hours=5, minutes=30))
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

FEEDS = [
    ("SEBI", "https://www.sebi.gov.in/sebirss.xml"),
    ("NSE", "https://nsearchives.nseindia.com/content/RSS/Circulars.xml"),
    ("BSE", "https://www.bseindia.com/data/xml/notices.xml"),
]

# NSE circular file names encode the issuing department, e.g. CML76207.pdf.
# Only codes we are confident about are mapped; unknown codes display as-is.
NSE_DEPTS = {
    "CML": "Listing",
    "CMTR": "Trading",
    "SURV": "Surveillance",
    "FAOP": "Futures & Options",
    "FO": "Futures & Options",
    "MFSS": "Mutual Funds",
    "NMF": "Mutual Funds",
    "EGR": "Electronic Gold Receipts",
    "SLBS": "Securities Lending",
    "CD": "Currency Derivatives",
    "CDS": "Currency Derivatives",
    "COM": "Commodity Derivatives",
    "CMDT": "Commodity Derivatives",
    "DEBT": "Debt",
    "WDTR": "Debt",
    "IPO": "Primary Market",
    "SME": "SME / Emerge",
    "INSP": "Inspection",
    "CMPT": "Clearing & Settlement",
    "INVG": "Investigation",
}

# SEBI item URLs carry the section in their path.
SEBI_SECTIONS = [
    ("/legal/master-circulars/", "Master Circular"),
    ("/legal/circulars/", "Circular"),
    ("/enforcement/orders/", "Order"),
    ("/enforcement/", "Enforcement"),
    ("/media-and-notifications/press-releases/", "Press Release"),
    ("/media-and-notifications/public-notices/", "Public Notice"),
    ("/media-and-notifications/", "Notification"),
    ("/legal/regulations/", "Regulation"),
    ("/legal/rules/", "Rules"),
    ("/legal/acts/", "Act"),
    ("/reports-and-statistics/", "Report"),
]

# Keyword classifier for BSE notices (and NSE items with unknown dept codes).
# Ordered — first match wins.
KEYWORD_RULES = [
    ("Surveillance", r"surveillan|\besm\b|\bgsm\b|\basm\b|st-asm|price band"),
    ("Listing", r"listing|listed|delist|allotment|public issue|\bipo\b|rights issue|rights entitlement|bonus|amalgamation|scheme of arrangement|change of name"),
    ("Corporate Action", r"dividend|stock split|sub-?division|record date|book closure|buy-?back"),
    ("Derivatives", r"derivativ|futures|\boptions\b|expiry|contract specifications"),
    ("Mutual Funds", r"mutual fund|star mf|\bmf\b"),
    ("Debt", r"\bdebt\b|\bbonds?\b|\bncds?\b|commercial paper|debenture|\bg-?sec\b"),
    ("Clearing & Settlement", r"settlement|margin|collateral|pay-?in|pay-?out|\bauction\b"),
    ("Trading", r"trading|\btrade\b|market timing|circuit|holiday|mock session"),
    ("Membership", r"\bmembers?\b|\bbrokers?\b"),
    ("Compliance", r"compliance|regulatory|\bkyc\b|\baml\b|cyber"),
    ("Investor", r"investor"),
]
KEYWORD_RULES = [(cat, re.compile(rx, re.I)) for cat, rx in KEYWORD_RULES]


def fetch(url: str, attempts: int = 3, timeout: int = 45) -> bytes:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/xml,text/xml,*/*",
                    "Accept-Language": "en-IN,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 — any network/HTTP failure retries
            last = exc
            if i < attempts - 1:
                time.sleep(5 * (i + 1))
    raise last


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_rss(raw: bytes):
    if raw.startswith(b"\xef\xbb\xbf"):  # BSE serves a UTF-8 BOM
        raw = raw[3:]
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        pubdate = (it.findtext("pubDate") or "").strip()
        if title and link:
            items.append((title, link, pubdate))
    return items


SEBI_DATE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})")


def parse_date(raw: str):
    """Return (date_iso, hh:mm IST or None). Dates are IST calendar dates."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    m = SEBI_DATE.match(raw)  # SEBI style: "04 Sep, 2026 +0530" (day precision)
    if m:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                dt = datetime.strptime(" ".join(m.groups()), fmt)
                return dt.date().isoformat(), None
            except ValueError:
                continue
    try:  # RFC 822 style: NSE (+0530, midnight) and BSE (GMT, real timestamps)
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        ist = dt.astimezone(IST)
        hhmm = ist.strftime("%H:%M")
        return ist.date().isoformat(), None if hhmm == "00:00" else hhmm
    except Exception:
        return None, None


def keyword_category(title: str) -> str:
    for cat, rx in KEYWORD_RULES:
        if rx.search(title):
            return cat
    return "Notice"


def classify(source: str, title: str, url: str):
    """Return (category, reference-number-or-None)."""
    if source == "SEBI":
        for prefix, cat in SEBI_SECTIONS:
            if prefix in url:
                return cat, None
        return "Update", None
    if source == "NSE":
        m = re.search(r"/content/circulars/([A-Za-z]+)(\d+)\.", url)
        if m:
            code, num = m.group(1).upper(), m.group(2)
            return NSE_DEPTS.get(code, code), f"{code}{num}"
        return keyword_category(title), None
    if source == "BSE":
        m = re.search(r"/Notices/(\d{8}-\d+)", url)
        return keyword_category(title), (m.group(1) if m else None)
    return "Notice", None


def main() -> None:
    existing, meta_prev = {}, {}
    if DATA_FILE.exists():
        try:
            prev = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            existing = {it["id"]: it for it in prev.get("items", [])}
            meta_prev = prev.get("sources", {})
        except Exception as exc:
            print(f"warn: could not read existing dataset ({exc}); starting fresh")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sources_meta, ok_sources = {}, 0

    for source, url in FEEDS:
        info = dict(meta_prev.get(source, {}))
        info["feed"] = url
        try:
            rows = parse_rss(fetch(url))
            fresh = 0
            for title, link, pubdate in rows:
                date_iso, hhmm = parse_date(pubdate)
                if not date_iso:
                    date_iso = datetime.now(IST).date().isoformat()
                iid = hashlib.sha1(f"{source}|{link}".encode()).hexdigest()[:12]
                category, ref = classify(source, title, link)
                item = {
                    "id": iid,
                    "source": source,
                    "title": title,
                    "url": link,
                    "date": date_iso,
                    "time": hhmm,
                    "category": category,
                    "ref": ref,
                    "first_seen": now,
                }
                if iid in existing:
                    item["first_seen"] = existing[iid].get("first_seen", now)
                else:
                    fresh += 1
                existing[iid] = item
            info.update(ok=True, last_success=now, last_count=len(rows), last_new=fresh, error=None)
            ok_sources += 1
            print(f"{source}: {len(rows)} items in feed, {fresh} new")
        except Exception as exc:
            info.update(ok=False, error=f"{type(exc).__name__}: {exc}", last_attempt=now)
            print(f"{source}: FAILED — {exc}")
        sources_meta[source] = info

    items = sorted(
        existing.values(),
        key=lambda it: (it["date"], it.get("time") or "", it["id"]),
        reverse=True,
    )[:MAX_ITEMS]

    out = {
        "site": "myfinancial · Official Circulars",
        "generated_at": now,
        "sources": sources_meta,
        "count": len(items),
        "items": items,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {DATA_FILE.relative_to(ROOT)} — {len(items)} items total")

    if ok_sources == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
