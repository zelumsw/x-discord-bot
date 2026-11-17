"""
Runs ONCE each time GitHub Actions starts it (every ~5 minutes).
Checks the feeds, sends new posts to Discord, and remembers what it has
already sent in seen.json (which the workflow saves back to the repository).

Secrets come from GitHub Secrets (never write them in this file):
  WEBHOOK_URL  - your Discord webhook URL
  FEEDS        - one feed per line, written as:  Name=https://rss.app/feeds/XXXX.xml
"""

import json
import os
import re
import sys
import time

import feedparser
import requests

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
FEEDS_TEXT = os.environ.get("FEEDS", "")

SEEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
KEEP_LAST = 300  # how many post ids to remember per feed


def log(msg):
    print(msg, flush=True)


def safe(error, *secrets):
    """Error text with secrets removed (this repository's logs are public)."""
    text = f"{type(error).__name__}: {error}"
    for s in secrets:
        if s:
            text = text.replace(s, "<hidden>")
    return text


def parse_feeds(text):
    feeds = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, url = line.partition("=")
        name, url = name.strip(), url.strip()
        if not sep or not url.startswith("http") or not name or name.startswith("http"):
            log("Skipping a FEEDS line that isn't written as Name=URL.")
            continue
        feeds.append((name, url))
    return feeds


def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            with open(SEEN_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            log("Could not read seen.json, starting fresh.")
    return {}


def save_seen(seen):
    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f, indent=1, sort_keys=True)
        f.write("\n")


def to_embed_link(url):
    # fxtwitter.com makes Discord show the post as a nice embed
    m = re.search(r"/([^/]+)/status/(\d+)", url)
    if m:
        return f"https://fxtwitter.com/{m.group(1)}/status/{m.group(2)}"
    return url


def send_to_discord(text):
    r = requests.post(WEBHOOK_URL, json={"content": text}, timeout=15)
    r.raise_for_status()


def fetch_feed(url):
    r = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DiscordPostBot/1.0)"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"Feed returned HTTP {r.status_code}")
    return feedparser.parse(r.content).entries


def check_feed(name, url, seen):
    entries = fetch_feed(url)
    if not entries:
        log(f"[{name}] Feed is EMPTY (no posts found).")
        return

    log(f"[{name}] Feed OK: found {len(entries)} posts.")

    first_run = name not in seen  # new feed: save existing posts, don't send them
    ids = list(seen.get(name, []))
    known = set(ids)
    new_count = 0

    try:
        for entry in reversed(entries):  # oldest first
            uid = entry.get("id") or entry.get("link")
            if not uid or uid in known:
                continue
            if not first_run:
                send_to_discord(to_embed_link(entry.get("link") or uid))
                log(f"[{name}] Sent new post: {entry.get('link', uid)}")
                time.sleep(1)
            ids.append(uid)
            known.add(uid)
            new_count += 1
    finally:
        if ids or not first_run:
            seen[name] = ids[-KEEP_LAST:]

    if first_run:
        log(f"[{name}] First run: saved {new_count} existing posts (not sent).")
    elif new_count == 0:
        log(f"[{name}] No new posts.")


def main():
    if not WEBHOOK_URL:
        log("ERROR: the WEBHOOK_URL secret is missing.")
        sys.exit(1)

    feeds = parse_feeds(FEEDS_TEXT)
    if not feeds:
        log("ERROR: the FEEDS secret is missing or empty.")
        sys.exit(1)

    seen = load_seen()
    try:
        for name, url in feeds:
            try:
                check_feed(name, url, seen)
            except Exception as e:
                log(f"[{name}] Error: {safe(e, url, WEBHOOK_URL)}")
            time.sleep(1)
    finally:
        save_seen(seen)


if __name__ == "__main__":
    main()
