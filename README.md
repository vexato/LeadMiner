# internship

CLI tool that searches **Google Maps** for companies matching a domain and location, then enriches each result by visiting the company's website to extract an email address, a short description, and a contact page URL.

---

## Installation

**Requirements: Python 3.11+**

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Quick start

```bash
python main.py --query "agence web" --location "Bordeaux" --limit 20
```

Results are saved to `results/` as JSON and CSV.

---

## Pipeline

```
Google Maps search
      │
      ▼
 List of companies  (name, address, website)
      │
      ▼
 Website enrichment  (email, description, contact page)   ← async, concurrent
      │
      ▼
 --only filter  (optional)
      │
      ▼
 Export  →  results/<query>_<location>_<timestamp>.json / .csv
```

---

## Parameters

### Required

| Parameter | Short | Description |
|-----------|-------|-------------|
| `--query QUERY` | `-q` | Type of company to search for, e.g. `"agence web"`, `"cabinet comptable"`. |
| `--location LOCATION` | `-l` | City, region, or address to search in. |

### Volume & output

| Parameter | Short | Default | Description |
|-----------|-------|---------|-------------|
| `--limit N` | `-n` | `20` | Maximum number of companies to collect. The scraper stops as soon as it reaches this number **or** Google Maps has no more results. Most queries return 40–120 results for a given city. |
| `--format FORMAT` | `-f` | `both` | Output format: `json`, `csv`, or `both`. |
| `--output-dir DIR` | `-o` | `results/` | Directory where result files are written (created automatically). |

### Filtering

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--only FIELDS` | *(none)* | Keep only companies that have **all** listed fields populated after enrichment. Comma-separated combination of: `email`, `contact`, `website`, `address`, `description`. |

```bash
--only email                  # only companies with an email found
--only email,contact          # email + contact page both found
--only email,website,description
```

### Scraping behaviour

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--scroll-count N` | `6` | Minimum scroll iterations on Google Maps. Raised automatically to `max(N, limit // 3 + 10)` to reach the requested limit. |
| `--concurrency N` | `5` | Parallel website scrapers. Raise for speed, lower if you hit connection errors. |
| `--no-headless` | *(off)* | Show the Chromium browser window — useful for debugging selectors or solving a CAPTCHA manually. |
| `--verbose` / `-v` | *(off)* | Enable DEBUG logging. |

---

## Output fields

| Field | Description |
|-------|-------------|
| `company_name` | Name as shown on Google Maps. |
| `website` | Company website URL. |
| `email` | First valid email found on the contact page or homepage. |
| `description` | Short summary (≤ 300 chars) from the homepage meta description or main content. |
| `contact_page` | URL of the first reachable contact-like page (`/contact`, `/about`, `/mentions-legales`, …). |
| `address` | Street address from Google Maps. |

---

## Advanced configuration

Parameters not exposed on the CLI can be tweaked in `config/settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `scroll_delay` | `2.0 s` | Pause between each Google Maps scroll. |
| `result_click_delay` | `1.5 s` | Wait after navigating to a place detail page. |
| `min_delay` / `max_delay` | `1.0–3.0 s` | Random delay between place-page visits. |
| `website_min_delay` / `website_max_delay` | `0.5–1.5 s` | Random delay between contact-path probes. |
| `website_timeout` | `10 s` | HTTP timeout per website request. |
| `max_description_length` | `300` | Maximum characters in the description field. |
| `contact_paths` | see settings | URL paths probed to find a contact page. |

---

## Examples

```bash
# Basic search
python main.py -q "agence web" -l "Bordeaux"

# 50 results, CSV only
python main.py -q "agence digitale" -l "Paris" -n 50 -f csv

# Only companies with an email
python main.py -q "développement web" -l "Lyon" --only email

# Only companies with email + contact page
python main.py -q "startup tech" -l "Toulouse" -n 100 --only email,contact

# Debug with visible browser
python main.py -q "agence web" -l "Nantes" -n 10 --no-headless --verbose

# Custom output folder
python main.py -q "agence seo" -l "Marseille" -o ./exports
```

---

## Project structure

```
internship/
├── main.py                   CLI entry point
├── requirements.txt
├── config/
│   └── settings.py           All tuneable parameters
├── models/
│   └── company.py            Company dataclass
├── scrapers/
│   ├── base.py               BaseSource interface (add new sources here)
│   ├── registry.py           Source factory
│   ├── google_maps_scraper.py  Playwright — search & place extraction
│   └── website_scraper.py      aiohttp — homepage & contact pages
├── extractors/
│   ├── email_extractor.py    Regex-based email extraction
│   └── text_extractor.py     Description extraction from HTML
├── core/
│   ├── pipeline.py           Concurrent website enrichment
│   └── orchestrator.py       Wires all steps together
├── utils/
│   ├── filters.py            --only field filtering
│   ├── helpers.py            Retry decorators, delays
│   ├── logger.py             Logging setup
│   └── validators.py         URL & email validation
└── output/
    └── exporter.py           JSON & CSV export
```

---

## Troubleshooting

**Only 20–25 results with a high limit**
Google Maps may have fewer entries for that query + location. Try `--no-headless` to watch what the browser sees.

**No emails found**
Many French SMEs don't publish emails. Try `--only contact` to keep companies with a `/contact` page and prospect manually.

**Browser crashes or Playwright errors**
Run `playwright install chromium` again.

**Blocked by Google (CAPTCHA)**
Lower `--concurrency` and raise delays in `config/settings.py` (`scroll_delay`, `min_delay`). Use `--no-headless` to solve the CAPTCHA manually once.
