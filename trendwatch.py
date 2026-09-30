#!/usr/bin/env python3
"""trendwatch — a tiny stdlib-only GitHub discovery CLI.

Scrapes GitHub's trending pages and topic pages (plain HTML, no API key
needed for discovery) and prints a markdown digest a human or agent can
scan before starring/forking. Optionally enriches each entry with the
GitHub API via the `gh` CLI (description, stars, language, last push).

Commands:
    trendwatch trending [--lang LANG] [--since daily|weekly|monthly]
    trendwatch topics TOPIC [--limit N]
    trendwatch digest                      # preset: trending + agent topics

Flags:
    --no-enrich    skip `gh api` enrichment (HTML data only)
    --limit N      cap rows per section (default 15)
    --md FILE      also write markdown to FILE

Stdlib only: urllib + html.parser + subprocess (for gh) + json.
"""
import argparse
import html as _html
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (trendwatch)"
BASE = "https://github.com"

ARTICLE_RE = re.compile(r'<article class="Box-row">(.*?)</article>', re.S)
REPO_HREF_RE = re.compile(r'href="(/[^/"]+/[^/"]+)"[^>]*class="[^"]*\bLink\b', re.S)
TOPICS_CARD_RE = re.compile(
    r'href="(/[^/"]+/[^/"]+)"[^>]*class="Link text-bold wb-break-word"', re.S)
DESC_RE = re.compile(r'<p class="col-9 color-fg-muted my-1[^"]*">(.*?)</p>', re.S)
LANG_RE = re.compile(r'<span itemprop="programmingLanguage">(.*?)</span>')
STARGAZERS_RE = re.compile(
    r'href="(/[^/"]+/[^/"]+/stargazers)"[^>]*>.*?([\d,]+)</a>', re.S)
STARS_TODAY_RE = re.compile(r'float-sm-right[^>]*>.*?([\d,]+)\s+stars today', re.S)
COUNTER_RE = re.compile(r'title="([\d,]+)"[^>]*class="Counter')
TAG_RE = re.compile(r"<[^>]+>")


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _clean(text):
    text = TAG_RE.sub("", text or "")
    return _html.unescape(re.sub(r"\s+", " ", text)).strip()


def _slug(href):
    return href.strip("/")


def parse_trending(page_html):
    """Return list of dicts in rank order from a /trending page."""
    rows = []
    for art in ARTICLE_RE.findall(page_html):
        art = re.sub(r"\s+", " ", art)
        m = re.search(r'<h2 class="h3 lh-condensed">(.*?)</h2>', art)
        href = None
        if m:
            h = re.search(r'href="(/[^/"]+/[^/"]+)"', m.group(1))
            if h:
                href = h.group(1)
        if not href:
            continue
        desc = DESC_RE.search(art)
        lang = LANG_RE.search(art)
        stars = STARGAZERS_RE.search(art)
        today = STARS_TODAY_RE.search(art)
        rows.append({
            "repo": _slug(href),
            "description": _clean(desc.group(1)) if desc else "",
            "language": _clean(lang.group(1)) if lang else "",
            "stars": _clean(stars.group(2)) if stars else "",
            "stars_today": _clean(today.group(1)) if today else "",
        })
    return rows


def parse_topics(page_html):
    """Return list of {repo, stars} from a /topics/<topic> page (name+stars only)."""
    rows = []
    for m in TOPICS_CARD_RE.finditer(page_html):
        slug = _slug(m.group(1))
        tail = page_html[m.end():m.end() + 3000]
        c = COUNTER_RE.search(tail)
        rows.append({
            "repo": slug,
            "description": "",
            "language": "",
            "stars": _clean(c.group(1)) if c else "",
            "stars_today": "",
        })
    # topics pages can list the same repo twice (grid duplicates); dedupe, keep order
    seen, out = set(), []
    for r in rows:
        if r["repo"] not in seen:
            seen.add(r["repo"])
            out.append(r)
    return out


def enrich(rows):
    """Fill description/stars/language/pushed_at via `gh api` (best effort)."""
    gh = shutil.which("gh")
    if not gh:
        return rows
    for r in rows:
        try:
            p = subprocess.run(
                [gh, "api", f"repos/{r['repo']}",
                 "-q", "{description: .description, stars: (.stargazers_count|tostring), "
                       "language: .language, pushed: .pushed_at}"],
                capture_output=True, text=True, timeout=25)
            if p.returncode != 0:
                continue
            d = json.loads(p.stdout)
        except Exception:
            continue
        if d.get("description"):
            r["description"] = d["description"].strip()
        if d.get("stars"):
            r["stars"] = d["stars"]
        if d.get("language"):
            r["language"] = d["language"]
        if d.get("pushed"):
            r["pushed_at"] = d["pushed"][:10]
    return rows


def to_md(title, rows):
    lines = [f"## {title}", "",
             "| # | Repo | Lang | Stars | Δ today | Description |",
             "|---|------|------|-------|---------|-------------|"]
    for i, r in enumerate(rows, 1):
        repo = r["repo"]
        link = f"[{repo}]({BASE}/{repo})"
        desc = (r.get("description") or "").replace("|", "\\|").replace("\n", " ")
        pushed = r.get("pushed_at", "")
        extra = f" · pushed {pushed}" if pushed else ""
        lines.append(
            f"| {i} | {link} | {r.get('language','')} | {r.get('stars','')}{extra} "
            f"| {r.get('stars_today','')} | {desc} |")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trendwatch",
                                 description="GitHub discovery digest CLI")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-enrich", action="store_true")
    common.add_argument("--limit", type=int, default=15)
    common.add_argument("--md", default="", help="also write markdown to FILE")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trending", parents=[common], help="github.com/trending")
    t.add_argument("--lang", default="", help="e.g. python, go, rust")
    t.add_argument("--since", default="daily", choices=["daily", "weekly", "monthly"])

    tp = sub.add_parser("topics", parents=[common], help="github.com/topics/<topic>")
    tp.add_argument("topic")

    sub.add_parser("digest", parents=[common], help="trending + agent-relevant topics")
    args = ap.parse_args(argv)

    sections = []
    if args.cmd == "trending":
        q = urllib.parse.urlencode({k: v for k, v in
                                    (("language", args.lang), ("since", args.since)) if v})
        url = f"{BASE}/trending?{q}" if q else f"{BASE}/trending"
        rows = parse_trending(_get(url))[:args.limit]
        title = f"Trending {args.lang or 'all'} ({args.since})"
        sections.append((title, url, rows))
    elif args.cmd == "topics":
        url = f"{BASE}/topics/{args.topic}"
        rows = parse_topics(_get(url))[:args.limit]
        sections.append((f"Topic: {args.topic}", url, rows))
    else:  # digest
        plan = [
            ("Trending (daily)", f"{BASE}/trending", parse_trending),
            ("Trending python (daily)", f"{BASE}/trending/python?since=daily", parse_trending),
            ("Trending go (daily)", f"{BASE}/trending/go?since=daily", parse_trending),
        ] + [(f"Topic: {t}", f"{BASE}/topics/{t}", parse_topics)
             for t in ["agents", "personal-ai", "ai", "llm", "cli",
                       "automation", "developer-tools"]]
        for title, url, parser in plan:
            try:
                rows = parser(_get(url))[:args.limit]
            except Exception as e:  # one failed page shouldn't kill the digest
                print(f"! skipped {title}: {e}", file=sys.stderr)
                continue
            sections.append((title, url, rows))

    out = []
    for title, url, rows in sections:
        if not args.no_enrich:
            rows = enrich(rows)
        out.append(f"<!-- source: {url} -->")
        out.append(to_md(title, rows))
    md = "\n".join(out)
    sys.stdout.write(md + "\n")
    if args.md:
        with open(args.md, "w") as f:
            f.write(md + "\n")
        print(f"wrote {args.md}", file=sys.stderr)


if __name__ == "__main__":
    main()
