"""Discover registered publishers, archive dated releases and import ONS Table 1."""

import argparse
import calendar
from collections import defaultdict
from contextlib import closing
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from .group_events import read_jsonl, string_field, timestamp, write_jsonl
from .luna import canonical_json


DATA = Path(__file__).with_name("official")
DEFAULT_PACK = DATA / "observations.jsonl"
SOURCES = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
RATES = {"Bank Rate", "deposit facility rate"}


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[-+]?\d{1,12}(?:\.\d{1,8})?", value):
        raise ValueError("expected a decimal string")
    return format(Decimal(value).normalize(), "f") if Decimal(value) else "0"


def safe_url(url, hosts=None):
    parts = urlsplit(url)
    if (parts.scheme not in ({"https"} if hosts else {"http", "https"}) or not parts.hostname
            or parts.username is not None or parts.password is not None
            or (hosts and (parts.hostname not in hosts or parts.port not in {None, 443}))):
        raise ValueError("invalid source URL or unregistered issuer host")
    return url


def validate_dimensions(geo, measure, period, basis):
    if measure in RATES:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) or basis != "level":
            raise ValueError("policy observations require a decision date and a level")
        date.fromisoformat(period)
    else:
        if not re.fullmatch(r"\d{4}-\d{2}", period) or basis not in {"mom", "yoy"}:
            raise ValueError("statistical observations require a month and comparison basis")
        date.fromisoformat(period + "-01")
    if not any(measure in agency["series"].get(geo, []) for agency in SOURCES.values()):
        raise ValueError("unknown geography and measure")


class ReleaseIndex:
    def __init__(self, paths, cutoff):
        self.cells = defaultdict(list)
        self.versions = []
        versions = {}
        for path in paths:
            for location, row in read_jsonl(path):
                try:
                    issuer = string_field(row, "issuer")
                    hosts = SOURCES[issuer]["hosts"]
                    url = safe_url(string_field(row, "url"), hosts)
                    release = string_field(row, "release_id")
                    available = timestamp(row["available_at"])
                    if "csv_url" in row:
                        safe_url(row["csv_url"], hosts)
                    vintage = row.get("vintage", "final")
                    if vintage not in {"final", "decision", "corrected", "flash", "preliminary"}:
                        raise ValueError("unknown release vintage")
                    ref = {"issuer": issuer, "release_id": release, "url": url, "vintage": vintage,
                           "available_at": available.isoformat(), "version": digest(row)}
                    if not isinstance(row["cells"], list) or not row["cells"]:
                        raise ValueError("release has no observations")
                    cells = {}
                    for geo, measure, period, basis, value, locator in row["cells"]:
                        validate_dimensions(geo, measure, period, basis)
                        if measure not in SOURCES[issuer]["series"].get(geo, []) or not isinstance(locator, str) or not locator.strip():
                            raise ValueError("wrong issuer or missing cell locator")
                        key = (geo, measure, period, basis)
                        if key in cells:
                            raise ValueError("duplicate observation in release")
                        cells[key] = {**ref, "locator": locator, "value": number(value), "unit": "%"}
                    version_key = (issuer, release, available)
                    if version_key in versions and versions[version_key][0] != ref:
                        raise ValueError("conflicting versions at the same availability time")
                    versions[version_key] = (ref, cells)
                except (KeyError, TypeError, InvalidOperation, ValueError) as error:
                    raise ValueError(f"{location}: {error}") from error
        latest = {}
        self.history = []
        for (issuer, release, available), entry in sorted(versions.items()):
            if available < cutoff:
                latest[issuer, release] = entry
                self.history.append(((issuer, release), available, entry[1]))
        for ref, cells in latest.values():
            self.versions.append(ref)
            for key, cell in cells.items():
                self.cells[key].append(cell)

    def lookup(self, key, as_of=None):
        key = tuple(key)
        if as_of is None:
            records = self.cells.get(key, [])
        else:
            latest = {}
            for release, available, cells in self.history:
                if available <= as_of:
                    latest[release] = cells
            records = [cells[key] for cells in latest.values() if key in cells]
        if not records:
            return []
        newest = max(timestamp(row["available_at"]) for row in records)
        return [row for row in records if timestamp(row["available_at"]) == newest]


def archive(db, issuer, url, refresh=False):
    hosts = SOURCES[issuer]["hosts"]
    safe_url(url, hosts)
    db.execute("CREATE TABLE IF NOT EXISTS release_file "
               "(url TEXT, fetched_at TEXT, sha256 TEXT, body BLOB, PRIMARY KEY(url, sha256))")
    db.execute("CREATE TABLE IF NOT EXISTS release_latest (url TEXT PRIMARY KEY, sha256 TEXT)")
    if not refresh:
        cached = db.execute("SELECT body FROM release_file LEFT JOIN release_latest USING (url) "
                            "WHERE url=? ORDER BY release_file.sha256=release_latest.sha256 DESC, fetched_at DESC LIMIT 1",
                            (url,)).fetchone()
        if cached:
            return cached[0]

    class OfficialRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            safe_url(newurl, hosts)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = Request(url, headers={"User-Agent": "VoxNews release verifier/1.0"})
    try:
        with build_opener(OfficialRedirect()).open(request, timeout=25) as response:
            body = response.read(16_000_001)
    except URLError as error:
        if sys.platform != "win32" or not isinstance(error.reason, ssl.SSLCertVerificationError):
            raise
        # Windows' native TLS client can complete issuer chains missing from OpenSSL.
        # Do not follow redirects here. A new host must pass the same registry check.
        result = subprocess.run(["curl.exe", "--proto", "=https", "--fail", "--silent", "--show-error",
                                 "--max-time", "25", "--max-filesize", "16000000", "--write-out", "%{http_code}",
                                 url], capture_output=True, timeout=30)
        if result.returncode or result.stdout[-3:] != b"200":
            raise ValueError(f"native HTTPS client could not fetch {url}") from error
        body = result.stdout[:-3]
    if not body or len(body) > 16_000_000:
        raise ValueError("empty or oversized official document")
    checksum = hashlib.sha256(body).hexdigest()
    with db:
        db.execute("INSERT OR IGNORE INTO release_file VALUES (?,?,?,?)", (
            url, datetime.now(timezone.utc).isoformat(), checksum, body))
        db.execute("INSERT OR REPLACE INTO release_latest VALUES (?,?)", (url, checksum))
    return body


def discover(raw, issuer, start=None, before=None, keyword=""):
    """A feed item is a discovery lead. Its date and title never verify a claim."""
    root = ElementTree.fromstring(raw)
    if root.tag.rsplit("}", 1)[-1] not in {"rss", "RDF", "feed"}:
        raise ValueError(f"{issuer} returned an unrecognised feed")
    found = {}
    for item in root.findall(".//{*}item") + root.findall(".//{*}entry"):
        title = (item.findtext("{*}title") or "").strip()
        link = item.find("{*}link")
        if link is None or keyword.casefold() not in title.casefold():
            continue
        url = (link.get("href") or link.text or "").strip()
        if url.startswith("http://"):
            url = "https://" + url[7:]
        try:
            safe_url(url, SOURCES[issuer]["hosts"])
        except ValueError:
            continue
        published = next((item.findtext("{*}" + tag) for tag in ("pubDate", "published", "date", "updated")
                          if item.findtext("{*}" + tag)), None)
        if published:
            try:
                dt = timestamp(published)
            except ValueError:
                # Some publishers use an ISO-style offset in an RFC 822 date.
                dt = parsedate_to_datetime(re.sub(r"([+-]\d\d):(\d\d)$", r"\1\2", published))
            published = dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else None
        if (start or before) and not published:
            continue
        if published and ((start and timestamp(published) < start) or (before and timestamp(published) >= before)):
            continue
        found[url] = {"issuer": issuer, "title": title, "url": url, "feed_timestamp": published}
    return list(found.values())


def ons_cells(raw):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    for index, row in enumerate(rows):
        # ONS column headings contain embedded line breaks, including within '12-month'.
        headings = [re.sub(r"\s+", "", title).lower() for title in row]
        if "cpi12-monthrate(%)" in headings:
            break
    else:
        raise ValueError("missing ONS CPI annual-rate column")
    columns = {}
    for series in ("CPI", "CPIH"):
        for months, basis in [(12, "yoy"), (1, "mom")]:
            title = f"{series}{months}-monthrate(%)".lower()
            if headings.count(title) != 1:
                raise ValueError(f"missing or ambiguous ONS column {title}")
            columns[headings.index(title)] = (series, months, basis)
    cells, year = [], None
    for row in rows[index + 1:]:
        if not row or row[0].strip().startswith("Source"):
            break
        if row[0].strip():
            year = int(row[0])
        if year is None or len(row) <= max(columns):
            raise ValueError("incomplete ONS data row")
        month = list(calendar.month_abbr).index(row[1].strip())
        for column, (series, months, basis) in columns.items():
            cells.append(["GB", series, f"{year:04}-{month:02}", basis, number(row[column].strip()),
                          f"Table 1 / {calendar.month_abbr[month]} {year} / {series} {months}-month rate (%)"])
    if not cells:
        raise ValueError("empty ONS table")
    return cells


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sources", "discover", "archive", "import-ons"))
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--cache", type=Path, default=Path("output/official.sqlite3"))
    parser.add_argument("--release-id", help="select one release in the pack")
    parser.add_argument("--output", type=Path, help="new JSONL pack for import-ons")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--issuer", choices=SOURCES, action="append", help="restrict RSS discovery")
    parser.add_argument("--from", dest="start", help="inclusive date or timestamp for RSS discovery")
    parser.add_argument("--before", help="exclusive date or timestamp for RSS discovery")
    parser.add_argument("--keyword", default="", help="case-insensitive release-title filter")
    args = parser.parse_args()
    if args.action == "sources":
        print(json.dumps(SOURCES, ensure_ascii=False, indent=2))
        return
    try:
        if args.output and args.output.resolve() in {args.pack.resolve(), args.cache.resolve()}:
            raise ValueError("choose a separate output pack")
        if args.action == "discover":
            issuers = args.issuer or [name for name, src in SOURCES.items() if "rss" in src]
            start = timestamp(args.start, allow_date=True) if args.start else None
            before = timestamp(args.before, allow_date=True) if args.before else None
            if start and before and start >= before:
                raise ValueError("--from must precede --before")
            items = []
            args.cache.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(args.cache)) as db:
                for issuer in issuers:
                    if "rss" not in SOURCES[issuer]:
                        raise ValueError(f"browse the catalogue for {issuer}: {SOURCES[issuer]['catalogue']}")
                    feed = archive(db, issuer, SOURCES[issuer]["rss"], args.refresh)
                    items.extend(discover(feed, issuer, start, before, args.keyword))
            if args.output:
                write_jsonl(args.output, items)
            else:
                for item in items:
                    print(canonical_json(item))
            return
        ReleaseIndex([args.pack], datetime.max.replace(tzinfo=timezone.utc))
        pack = [row for _, row in read_jsonl(args.pack)]
        rows = [row for row in pack if not args.release_id or row["release_id"] == args.release_id]
        if not rows:
            raise ValueError("no releases selected")
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(args.cache)) as db:
            if args.action == "archive":
                for row in rows:
                    archive(db, row["issuer"], row["url"], args.refresh)
                print(f"Archived {len(rows)} official release(s) in {args.cache}")
                return
            if len(rows) != 1 or not args.output or rows[0]["issuer"] != "ONS":
                raise ValueError("select one ONS release with --release-id and specify --output")
            row = rows[0]
            raw = archive(db, "ONS", row["csv_url"], args.refresh)
            cells = ons_cells(raw)
            imported = {tuple(cell[:4]): cell for cell in cells}
            for expected in row["cells"]:
                if expected[1] in {"CPI", "CPIH"}:
                    if imported.get(tuple(expected[:4]), [None]*5)[4] != number(expected[4]):
                        raise ValueError("official CSV differs from the pack; review the release vintage")
                else:
                    cells.append(expected)
            expanded = {**row, "cells": cells, "csv_sha256": hashlib.sha256(raw).hexdigest()}
            write_jsonl(args.output, [expanded if entry is row else entry for entry in pack])
    except (OSError, sqlite3.Error, ValueError, KeyError, ElementTree.ParseError) as error:
        parser.exit(1, f"release import failed: {error}\n")


if __name__ == "__main__":
    main()
