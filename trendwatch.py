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
import os
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


def run_sections(cmd, topic="", lang="", since="daily", limit=15, no_enrich=False):
    """Fetch and return [(title, url, rows)] for a digest/trending/topics run."""
    sections = []
    if cmd == "trending":
        q = urllib.parse.urlencode({k: v for k, v in
                                    (("language", lang), ("since", since)) if v})
        url = f"{BASE}/trending?{q}" if q else f"{BASE}/trending"
        rows = parse_trending(_get(url))[:limit]
        if not no_enrich:
            rows = enrich(rows)
        sections.append((f"Trending {lang or 'all'} ({since})", url, rows))
    elif cmd == "topics":
        url = f"{BASE}/topics/{topic}"
        rows = parse_topics(_get(url))[:limit]
        if not no_enrich:
            rows = enrich(rows)
        sections.append((f"Topic: {topic}", url, rows))
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
                rows = parser(_get(url))[:limit]
            except Exception as e:  # one failed page shouldn't kill the digest
                print(f"! skipped {title}: {e}", file=sys.stderr)
                continue
            if not no_enrich:
                rows = enrich(rows)
            sections.append((title, url, rows))
    return sections


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

    sv = sub.add_parser("serve", help="run the branded web UI")
    sv.add_argument("--host", default="0.0.0.0", help="bind host (default 0.0.0.0)")
    sv.add_argument("--port", type=int, default=8080, help="port (default 8080)")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        cmd_serve(args)
        return

    sections = run_sections(args.cmd, getattr(args, "topic", ""),
                            getattr(args, "lang", ""), args.since,
                            args.limit, args.no_enrich)

    out = []
    for title, url, rows in sections:
        out.append(f"<!-- source: {url} -->")
        out.append(to_md(title, rows))
    md = "\n".join(out)
    sys.stdout.write(md + "\n")
    if args.md:
        with open(args.md, "w") as f:
            f.write(md + "\n")
        print(f"wrote {args.md}", file=sys.stderr)


# ----------------------------------------------------------------------------
# Serve mode: a branded web UI over the digest engine.
#
#   python3 trendwatch.py serve --port 8080
#
#   GET  /         run form + last cached digest as cards
#   POST /run      fetch a fresh digest, cache it, redirect to /
#   GET  /healthz  "ok"
# ----------------------------------------------------------------------------

TW_STYLE = """<style>
.tw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.tw-repo{background:#1f1a15;border:1px solid #332b21;border-radius:12px;padding:14px 16px}
.tw-repo .tw-name{font-weight:700;overflow-wrap:anywhere}
.tw-repo .tw-name a{color:#f7c873;text-decoration:none}
.tw-repo .tw-name a:hover{text-decoration:underline}
.tw-repo .tw-desc{color:#a49176;font-size:14px;margin:.4em 0 .6em;line-height:1.5}
.tw-meta{font-size:13px;color:#a49176;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.tw-sec-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.tw-sec-head a{font-size:13px;color:#a49176}
</style>"""

CACHE_PATH = os.path.join(os.path.expanduser("~"), ".trendwatch", "cache.json")


def _load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_cache(payload):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(payload, f)
    except OSError as e:
        print(f"trendwatch: couldn't save cache: {e}", file=sys.stderr)


def _repo_card(r):
    e = _html.escape
    repo = e(r.get("repo", "?"))
    desc = e((r.get("description") or "").strip())
    lang = e(r.get("language") or "")
    stars = e(str(r.get("stars") or ""))
    today = e(str(r.get("stars_today") or ""))
    pushed = e(str(r.get("pushed_at") or ""))
    meta = []
    if lang:
        meta.append('<span class="wb-badge">%s</span>' % lang)
    if stars:
        meta.append("★ %s" % stars)
    if today:
        meta.append("+%s today" % today)
    if pushed:
        meta.append("pushed %s" % pushed)
    return ('<div class="tw-repo"><div class="tw-name">'
            '<a href="https://github.com/%s">%s</a></div>'
            '%s<div class="tw-meta">%s</div></div>'
            % (repo, repo,
               '<div class="tw-desc">%s</div>' % desc if desc else "",
               " · ".join(meta)))


def _serve_index(params, cached, err=None):
    e = _html.escape
    mode = params.get("mode", "digest")
    sel = lambda v: " selected" if mode == v else ""
    err_html = ""
    if err:
        err_html = ('<div class="wb-card"><span class="wb-badge b-red">error</span>'
                    '<p>%s</p></div>\n') % e(err)
    form = TW_STYLE + """
<div class="wb-card">
  <h2>Run a digest</h2>
  <p class="wb-sub">Scrapes GitHub's trending and topic pages (no API key needed)
  and renders the results as cards.</p>
  <form action="/run" method="post">
    <div class="wb-field">
      <label for="mode">What to fetch</label>
      <select class="wb-select" id="mode" name="mode">
        <option value="digest"%(digest)s>Digest — trending + agent topics</option>
        <option value="trending"%(trending)s>Trending</option>
        <option value="topics"%(topics)s>One topic</option>
      </select>
    </div>
    <div class="wb-field">
      <label for="topic">Topic (for "one topic")</label>
      <input class="wb-input" id="topic" name="topic" value="%(topic)s"
        placeholder="e.g. agents">
    </div>
    <div class="wb-field">
      <label for="lang">Language filter (for "trending")</label>
      <input class="wb-input" id="lang" name="lang" value="%(lang)s"
        placeholder="e.g. python">
    </div>
    <div class="wb-field">
      <label for="limit">Repos per section</label>
      <input class="wb-input" id="limit" name="limit" type="number" min="1" max="50"
        value="%(limit)s">
    </div>
    <div class="wb-btn-row">
      <button class="wb-btn wb-btn-primary" type="submit">Run</button>
    </div>
  </form>
</div>
""" % {"digest": sel("digest"), "trending": sel("trending"), "topics": sel("topics"),
       "topic": e(params.get("topic", "")), "lang": e(params.get("lang", "")),
       "limit": e(str(params.get("limit", 8)))}

    body = err_html + form
    if not cached or not cached.get("sections"):
        body += ('<div class="wb-card"><h2>No digest yet</h2>'
                 '<p class="wb-sub">Run one above — results are cached here '
                 'after each run.</p></div>')
        return body
    p = cached.get("params", {})
    when = e(cached.get("ts", ""))
    body += ('<div class="wb-card"><span class="wb-badge b-green">cached</span> '
             '<span style="color:var(--wb-muted);font-size:14px">%s · %s</span></div>\n'
             % (when, e(p.get("mode", "digest"))))
    for title, url, rows in cached["sections"]:
        cards = "\n".join(_repo_card(r) for r in rows)
        body += ('<div class="wb-card"><div class="tw-sec-head"><h2>%s</h2>'
                 '<a href="%s">source ↗</a></div>'
                 '<div class="tw-grid">\n%s\n</div></div>\n'
                 % (e(title), e(url), cards))
    return body


def cmd_serve(args):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    from datetime import datetime
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from brand.page import render, brand_asset

    state = {"cache": _load_cache(),
             "params": {"mode": "digest", "topic": "", "lang": "",
                        "limit": 8, "no_enrich": False}}

    def shell(title, content, code=200):
        return render("trendwatch", "GitHub discovery digest", title, content,
                      footer_extra="trendwatch")

    class TrendHandler(BaseHTTPRequestHandler):
        server_version = "trendwatch/serve"

        def log_message(self, fmt, *a):
            sys.stderr.write("trendwatch: %s\n" % (fmt % a))

        def _send(self, body, ctype="text/html; charset=utf-8", code=200):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            asset = brand_asset(path)
            if asset:
                ctype, data = asset
                return self._send(data, ctype)
            if path == "/healthz":
                return self._send("ok", "text/plain; charset=utf-8")
            if path in ("/", "/index.html"):
                return self._send(shell("Trendwatch",
                                        _serve_index(state["params"], state["cache"])))
            self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path != "/run":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 1024 * 1024:
                self.send_error(400, "bad form size")
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            mode = (form.get("mode", ["digest"])[0] or "digest").strip()
            topic = (form.get("topic", [""])[0] or "").strip()
            lang = (form.get("lang", [""])[0] or "").strip()
            try:
                limit = max(1, min(50, int(form.get("limit", ["8"])[0] or 8)))
            except ValueError:
                limit = 8
            params = {"mode": mode, "topic": topic, "lang": lang,
                      "limit": limit, "no_enrich": False}
            state["params"] = params
            if mode == "topics" and not topic:
                return self._send(shell("Trendwatch", _serve_index(
                    params, state["cache"], "pick a topic first")), code=400)
            if mode not in ("digest", "trending", "topics"):
                return self._send(shell("Trendwatch", _serve_index(
                    params, state["cache"], "unknown mode")), code=400)
            try:
                sections = run_sections(mode, topic, lang, "daily", limit, False)
            except Exception as ex:
                return self._send(shell("Trendwatch", _serve_index(
                    params, state["cache"], str(ex))), code=502)
            payload = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                       "params": params, "sections": sections}
            state["cache"] = payload
            _save_cache(payload)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    httpd = ThreadingHTTPServer((args.host, args.port), TrendHandler)
    httpd.daemon_threads = True
    host = "localhost" if args.host == "0.0.0.0" else args.host
    print("trendwatch: serving the digest UI at http://%s:%d/" % (host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
