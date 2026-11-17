# UofT Research Match

A website for University of Toronto students looking for a research supervisor: describe your interests in plain language, get professors whose **recent papers** match, with an explanation of each match, the papers behind it, public contact info, and a profile page listing all their recent work.

Current coverage (St. George): **Computer Science**, **Mathematics**, **Statistical Sciences**: 434 faculty, ~12.5k papers since 2020.

```
department directories ─► scrape_directories.py ─► SQLite (faculty)
OpenAlex API           ─► link_openalex.py      ─► SQLite (author links, works)   + review_matches.csv
sentence-transformers  ─► build_embeddings.py   ─► SQLite (vectors)
                                                    │
                       serve_api.py (FastAPI) ◄─────┘  ──►  web/ (Next.js + Tailwind)
                       Claude API writes "why this match" (template fallback without a key)
```

## Setup

Requirements: Python 3.11+, Node 20+.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env              # then fill it in (see below)

cd web && npm install && cd ..
```

`.env`:

| Variable | Needed for | Notes |
|---|---|---|
| `OPENALEX_API_KEY` | refreshing publication data | Free at https://openalex.org/settings/api. Without it the shared keyless budget (~100 author searches/day) is too small for a full refresh. |
| `ANTHROPIC_API_KEY` | "why this match" sentences | Optional. Without it the site uses template sentences. The student's query and the matched professors' public research info are sent to the Claude API. |
| `CONTACT_EMAIL` | optional | Added to the scraper User-Agent and sent to OpenAlex as `mailto`. |
| `EXPLAIN_MODEL` | optional | Defaults to `claude-opus-5-5`. |
| `NEXT_PUBLIC_API_URL` (in `web/.env.local`) | frontend | Defaults to `http://localhost:8000`. |
| `ALLOWED_ORIGINS` | API CORS | Comma-separated; defaults to `http://localhost:3000`. |

## Run locally

```bash
python serve_api.py          # API on http://localhost:8000  (interactive docs at /docs)
cd web && npm run dev        # site on http://localhost:3000
```

Command-line search without the website:

```bash
python search.py "causal inference in healthcare data" --dept stats --dept cs -k 10
```

## Refreshing the data

Run in order. Every step caches its inputs, so re-runs only do new work.

1. **Directories.** CS is downloaded automatically. Math and Stats sites block automated access with a bot check, so save them from a browser first:
   - open `https://www.mathematics.utoronto.ca/people/directories/all-faculty?sort_by=ppl_last_name_value&items_per_page=All` → *Save page as…* → put the `.html` in `data/manual_html/math/`
   - same for `https://www.statistics.utoronto.ca/...` → `data/manual_html/stats/`

   ```bash
   python scrape_directories.py             # --refresh to re-download CS instead of using the cache
   ```
   The summary warns `INCOMPLETE` if a saved page has fewer people than the site says it lists.

2. **Publications.**
   ```bash
   python link_openalex.py --max-cost 1.0
   ```
   Low-confidence or ambiguous matches are **not** merged; they are written to `review_matches.csv`. To resolve one, add a row to `match_overrides.csv` and re-run:
   ```csv
   faculty_id,openalex_ids,note
   stats:lei-sun,A5012345678,checked against her homepage
   cs:some-person,NONE,no OpenAlex record
   ```
   Several ids can be joined with `|` when OpenAlex splits one person into several records.

3. **Embeddings.**
   ```bash
   python build_embeddings.py
   ```
   Then restart `serve_api.py`.

## Adding a department

1. Add an entry to `departments.yaml`: `id`, `name`, `directory_url`, `parser`, and the `openalex_fields` / `openalex_related_fields` used for topic overlap when linking authors. If the site blocks automated access, set `source: manual` and save the pages into `data/manual_html/<id>/`.
2. If no existing parser fits, add one in `researchmatch/parsers/` that returns `FacultyRecord`s (see `cs_squarespace.py` or `artsci_drupal.py`) and register it in `researchmatch/parsers/__init__.py`. Other Arts & Science departments on the same Drupal template can probably reuse `artsci_drupal`.
3. Save a copy of the page into `tests/fixtures/` and add parser tests.
4. Run the three refresh steps above.

## Tuning

`departments.yaml` → `ranking:` holds the knobs: the weight of profile vs. paper similarity, how the profile vector mixes department-page text, OpenAlex topics and recency-weighted papers, the emeritus multiplier, etc. `embedding.model` swaps the sentence-transformers model (re-run `build_embeddings.py`).

## Tests

```bash
python -m pytest -q
```
Parsers run against saved copies of the real directory pages; linking, ranking and the API use small synthetic data, so no model download or network is needed.

## Data and privacy notes

- Emails are shown only when printed on the department page. They are never guessed. (The Arts & Science sites write `name[at]utoronto.ca`; that is converted back to `@`.)
- "Not accepting new graduate students" is shown only when the department page says so. Silence means *unknown*, not *yes*.
- OpenAlex sometimes attributes a paper to the wrong person. Users are told to verify on the official page.
- Scraping: robots.txt is respected, requests are ≥1 s apart with a descriptive User-Agent, and pages are cached. Sites that block bots are never worked around.
