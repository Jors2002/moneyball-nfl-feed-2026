"""Narrow Chiefs.com practice adapter. No medical/time imputation or publishing.

Only extracted facts are written. Raw HTML cache must live outside the repo.
Publicly readable content is not a general redistribution license.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from moneyball8_evidence import assess_evidence, timestamp

SOURCE_URL = "https://www.chiefs.com/news/week-9-injury-report-jets-vs-chiefs"
HOSTS = ("www.chiefs.com",)
PRACTICE = {"DNP": "DNP", "LP": "LIMITED", "FP": "FULL"}
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class ReportHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = None
        self.parts = []
        self.nodes = []
        self.metadata = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.metadata.append(attrs)
        if tag in {"h1", "h2", "h3", "li", "span"} or (tag == "script" and attrs.get("type") == "application/ld+json"):
            if self.capture is None:
                self.capture, self.parts = (tag, attrs), []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.capture and self.capture[0] == tag:
            self.nodes.append((tag, self.capture[1], "".join(self.parts).strip()))
            self.capture, self.parts = None, []


def _date(raw):
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def parse_report(html, *, fetched_at, now=None, event_date=None, expected_week=9):
    """event_date is a separately checked calendar day, never a clock timestamp.

    Repeated Wednesday headings under different teams are separate sections.
    Duplicate same-team/day sections are ambiguous and cannot be certified.
    """
    fetched = timestamp(fetched_at)
    now = now or fetched
    if now.tzinfo is None:
        raise ValueError("Aware now required")
    parser = ReportHTML()
    parser.feed(html)
    articles = []
    for tag, attrs, value in parser.nodes:
        if tag == "script":
            try:
                item = json.loads(value)
                items = item if isinstance(item, list) else item.get("@graph", [item])
                articles.extend(x for x in items if isinstance(x, dict) and x.get("@type") == "NewsArticle")
            except (ValueError, AttributeError):
                pass
    issues = []
    if len(articles) != 1:
        issues.append("AMBIGUOUS_OR_MISSING_ARTICLE_METADATA")
    article = articles[0] if len(articles) == 1 else {}
    candidates = {"published_at": [article.get("datePublished")],
                  "modified_at": [article.get("dateModified")]}
    for meta in parser.metadata:
        key = meta.get("property", meta.get("name", ""))
        if key in {"article:published_time", "datePublished"}:
            candidates["published_at"].append(meta.get("content"))
        elif key in {"article:modified_time", "dateModified"}:
            candidates["modified_at"].append(meta.get("content"))
    stamps = {}
    for field, values in candidates.items():
        clean = []
        for raw in values:
            if raw is None:
                continue
            try:
                clean.append(timestamp(raw))
            except (ValueError, TypeError):
                issues.append("AMBIGUOUS_" + field.upper())
        if len(set(clean)) > 1:
            issues.append("CONTRADICTORY_" + field.upper())
        stamps[field] = clean[0].isoformat() if clean and len(set(clean)) == 1 else None
    published = timestamp(stamps["published_at"]) if stamps["published_at"] else None
    modified = timestamp(stamps["modified_at"]) if stamps["modified_at"] else None
    if published and (published > fetched or fetched > now):
        issues.append("FUTURE_OR_INVALID_PUBLICATION_ORDER")
    if modified and (modified > fetched or (published and modified < published)):
        issues.append("INVALID_MODIFICATION_ORDER")
    display = {}
    for tag, attrs, value in parser.nodes:
        m = re.fullmatch(r"(Published|Updated): ([A-Za-z]{3} \d{2}, \d{4}) at (\d{2}:\d{2} [AP]M)", value)
        if m:
            display[m[1]] = datetime.strptime(m[2], "%b %d, %Y").date()
    if display.get("Updated") and display.get("Published") and display["Updated"] < display["Published"]:
        issues.append("DISPLAY_UPDATED_BEFORE_PUBLISHED")
    # The displayed clocks do not have an offset, so are never accepted as timestamps.
    headline = article.get("headline", "")
    if not re.search(r"\bWeek\s+" + str(expected_week) + r"\b.*Injury Report", headline, re.I):
        issues.append("WEEK_OR_REPORT_TITLE_MISMATCH")
    day = _date(event_date)
    if event_date and day is None:
        issues.append("INVALID_EVENT_DATE")
    team = weekday = event_at = None
    seen = set()
    records = []
    for tag, attrs, value in parser.nodes:
        if tag == "h2":
            team = value if value in {"Kansas City Chiefs", "New York Jets"} else None
            weekday = event_at = None
        elif tag == "h3" and team:
            weekday = next((d for d in DAYS if re.match(r"^" + d + r"\b", value)), None)
            event_at = attrs.get("data-event-at")  # Only if explicitly present at source.
            if (team, weekday) in seen:
                issues.append("DUPLICATE_TEAM_DAY_SECTION")
            seen.add((team, weekday))
        elif tag == "li" and team and weekday:
            m = re.fullmatch(r"([A-Z]{1,3}) (.+?)\*? - (.+?) - (DNP|LP|FP)", value)
            if not m:
                continue
            position, player, injury, code = m.groups()
            rec = {"player_name": player, "position": position, "team": team,
                   "injury": injury, "practice": PRACTICE[code], "game_status": "UNKNOWN",
                   "week": expected_week, "practice_day": weekday,
                   "event_date": day.isoformat() if day and day.strftime("%A") == weekday else None,
                   "event_date_evidence": "EXTERNALLY_VERIFIED_CALENDAR_DAY" if day and day.strftime("%A") == weekday else "WEEKDAY_ONLY",
                   "event_at": event_at, "published_at": stamps["published_at"],
                   "modified_at": stamps["modified_at"], "fetched_at": fetched_at,
                   "source_url": SOURCE_URL, "content_verified": True}
            records.append(rec)
    for rec in records:
        rec["assessment"] = assess_evidence(rec, now, official_hosts=HOSTS)
        if issues:
            rec["assessment"] = {"status": "SOURCE_DATE_CONTRADICTION", "usable_current": False,
                                 "official": True, "issues": sorted(set(issues))}
        elif not rec["event_at"]:
            rec["assessment"]["status"] = "OFFICIAL_CONTENT_EVENT_TIME_UNVERIFIED"
            rec["assessment"]["official"] = True
        rec["participation_probability"] = None
    return {"schema_version": "8.0.official.1", "source_url": SOURCE_URL,
            "fetched_at": fetched_at, "published_at": stamps["published_at"],
            "modified_at": stamps["modified_at"], "issues": sorted(set(issues)),
            "records": records, "raw_sha256": hashlib.sha256(html.encode()).hexdigest(),
            "limitations": ["Practice participation is not a game availability or snap forecast.",
                            "A verified practice calendar day is not an explicit event timestamp.",
                            "Chiefs.com only; no general redistribution license asserted."]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--event-date")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    for path in (args.cache, args.output):
        if path.resolve().is_relative_to(root):
            raise ValueError("Raw cache and evidence output must remain outside repository")
    with urlopen(Request(SOURCE_URL, headers={"User-Agent": "Moneyball8/0.1"}), timeout=20) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if not raw or len(raw) > 2 * 1024 * 1024:
            raise ValueError("Empty/oversized source")
    html = raw.decode("utf-8")
    result = parse_report(html, fetched_at=datetime.now(timezone.utc).isoformat(), event_date=args.event_date)
    if not result["records"]:
        raise ValueError("No recognized official practice records; existing output retained")
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_bytes(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(args.output) + ".tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    tmp.replace(args.output)
    print(json.dumps({"records": len(result["records"]), "issues": result["issues"],
                      "usable_current": sum(r["assessment"]["usable_current"] for r in result["records"])}))


if __name__ == "__main__":
    main()
