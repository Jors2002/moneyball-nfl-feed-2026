"""Bounded public-source cache with provenance and atomic last-good retention.

Historical caching is a cost optimization, not a point-in-time archive. Release
assets may be revised upstream; delete the cached entry to request a new vintage.
Callers serialize runs; this module does not provide a distributed lock.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com"}

def fetch(url, path, *, immutable=False, timeout=30, opener=urlopen):
    from urllib.parse import urlparse
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in ALLOWED_HOSTS:
        raise ValueError("Only approved public GitHub data sources allowed")
    path = Path(path)
    meta_path = Path(str(path) + ".provenance.json")
    try:
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if not isinstance(meta, dict):
            meta = {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        meta = {}  # Damaged metadata is a cache miss, never permission to trust bytes.
    valid = (path.exists() and meta.get("url") == url and
             hashlib.sha256(path.read_bytes()).hexdigest() == meta.get("sha256"))
    if immutable and valid:
        return dict(meta, cache_status="VERIFIED_IMMUTABLE_HIT")
    headers = {"User-Agent": "Moneyball8/0.1"}
    if valid and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    try:
        response = opener(Request(url, headers=headers), timeout=timeout)
        with response:
            content = response.read(50 * 1024 * 1024 + 1)
            if not content or len(content) > 50 * 1024 * 1024:
                raise ValueError("Empty or oversized source; last good file retained")
            # These endpoints must serve CSV text, not successful HTML error pages.
            prefix = content[:300].lstrip().lower()
            if prefix.startswith((b"<!doctype html", b"<html")) or b"," not in content.splitlines()[0]:
                raise ValueError("Source is not a CSV; last good file retained")
            new = {"url": url, "sha256": hashlib.sha256(content).hexdigest(),
                   "bytes": len(content), "etag": response.headers.get("ETag"),
                   "source_last_modified": response.headers.get("Last-Modified"),
                   "fetched_at": datetime.now(timezone.utc).isoformat(),
                   "event_timestamp": None,
                   "note": "Fetch time and HTTP Last-Modified are not player event timestamps"}
    except HTTPError as exc:
        if exc.code == 304 and valid:
            return dict(meta, cache_status="HTTP_NOT_MODIFIED")
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    tmp_meta = Path(str(meta_path) + ".tmp")
    tmp_meta.write_text(json.dumps(new, indent=2) + "\n")
    tmp_meta.replace(meta_path)
    return dict(new, cache_status="DOWNLOADED")
