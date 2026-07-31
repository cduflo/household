"""Fetch a page, reduce it to stable readable text, and diff against last time.

Two things matter here. First, politeness: these are volunteer clubs on shared
hosting, so we crawl slowly and identify ourselves. Second, noise suppression:
most of these sites regenerate timestamps, session tokens and rotating banners
on every load, and a naive hash would report a change every single run.
"""
import hashlib
import re
import time
import difflib

import requests
from bs4 import BeautifulSoup

DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "nav", "footer"]

# Volatile fragments that change on every page load and mean nothing to us.
NOISE = [
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|am|pm)?\b"),
    re.compile(r"\b(session|token|nonce|csrf)[=:][A-Za-z0-9_\-]+", re.I),
    re.compile(r"\?v=\d+"),
    re.compile(r"\b\d{10,}\b"),
]


def fetch(url, user_agent, timeout=25):
    """Return (text, http_status, error). text is '' when the fetch failed."""
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
    except requests.RequestException as exc:
        return "", None, f"{type(exc).__name__}: {exc}"

    if resp.status_code >= 400:
        return "", resp.status_code, f"HTTP {resp.status_code}"

    return extract_text(resp.text), resp.status_code, None


def extract_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()

    raw = soup.get_text("\n")
    lines = []
    for line in raw.splitlines():
        line = " ".join(line.split())
        if not line or len(line) < 3:
            continue
        for pattern in NOISE:
            line = pattern.sub("", line)
        line = " ".join(line.split())
        if line:
            lines.append(line)

    # Collapse repeats: nav menus render two or three times on most of these sites.
    seen, out = set(), []
    for line in lines:
        low = line.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(line)
    return "\n".join(out)


def digest(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def added_lines(old_text, new_text):
    """Lines present in new_text but not old_text, in document order.

    We score only the additions. A litter announcement is always an addition,
    and ignoring removals keeps a reshuffled nav menu from looking like news.
    """
    if not old_text:
        return []
    old = old_text.splitlines()
    new = new_text.splitlines()
    diff = difflib.ndiff(old, new)
    return [line[2:].strip() for line in diff if line.startswith("+ ") and line[2:].strip()]


def polite_sleep(seconds):
    if seconds > 0:
        time.sleep(seconds)
