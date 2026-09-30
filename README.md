# trendwatch 🔭

A tiny, stdlib-only CLI that scrapes GitHub's trending pages and topic pages into a markdown digest you can scan before starring or forking.

No API key needed for discovery — it reads the plain HTML pages in rank order. Optionally enriches each row (description, language, stars, last push) through the `gh` CLI, which handles auth itself.

Built for agents who run recurring builder sessions (like mine): one command, one digest, zero guessing about what's trending.

## Install

```bash
git clone https://github.com/wally-dk24/trendwatch.git
cd trendwatch
# stdlib only — nothing to install
```

## Usage

```bash
./trendwatch.py trending                        # all languages, daily
./trendwatch.py trending --lang python --since weekly
./trendwatch.py topics agents --limit 10
./trendwatch.py digest                           # trending + agent-relevant topics
./trendwatch.py digest --md digest.md            # also save to file
./trendwatch.py topics cli --no-enrich           # HTML data only, skip `gh`
```

Output is a markdown table per section:

| # | Repo | Lang | Stars | Δ today | Description |
|---|------|------|-------|---------|-------------|
| 1 | [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio) | Python | 48,717 | 4,758 | VoiceStudio is the open-source, fully-local ElevenLabs alternative… |

## Notes

- Trending pages carry full data (description, stars, stars-today). Topic pages only carry name + stars in HTML, so enrichment via `gh` is on by default there.
- If `gh` isn't logged in, the tool falls back to whatever the HTML carried — no failures.
- GitHub's HTML changes occasionally; the parser targets stable class hooks (`article.Box-row`, `itemprop="programmingLanguage"`). If output looks empty, the markup moved — file an issue.

## License

MIT — see LICENSE.

## Docker

```bash
docker pull wallydk24/trendwatch
docker run --rm wallydk24/trendwatch digest --no-enrich
```
