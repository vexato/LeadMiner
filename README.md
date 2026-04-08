# LeadMiner

LeadMiner est un outil CLI Python pour générer des leads B2B a partir de plusieurs sources web, puis enrichir automatiquement chaque entreprise.

Le projet:
- cherche des entreprises via `Google Maps`, `Pages Jaunes` et/ou `Google Search`
- deduplique les doublons (nom + domaine)
- enrichit via le site web (email, page contact, description)
- calcule un score qualite
- exporte en `JSON` et/ou `CSV`

## Fonctionnement global

```text
1) Discovery (sources: maps, pj, google)
2) Tagging de la source
3) Deduplication + fusion des champs
4) Enrichissement website (async/concurrent)
5) Scoring qualite
6) Filtres (junk, empty, --only, --min-score)
7) Tri par score descendant
8) Filtre IA optionnel (--ai, Groq)
9) Export JSON/CSV
```

## Prerequis

- Python `3.11+`
- Playwright Chromium (necessaire pour les sources navigateur)

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Demarrage rapide

```bash
python main.py -q "agence web" -l "Bordeaux"
```

Par defaut:
- source = `maps`
- limite = `20` entreprises par source
- format = `both` (JSON + CSV)
- dossier de sortie = `results/`

## Utilisation avec plusieurs sources

```bash
python main.py -q "societes de services numeriques" -l "Bordeaux" -s maps,pj,google -n 40
```

Important: `--limit` est applique par source. Avec 3 sources, le volume brut peut etre superieur a la limite avant deduplication/filtrage.

## Options CLI

### Obligatoires

| Option | Short | Description |
|---|---|---|
| `--query` | `-q` | Activite recherchee (ex: `agence web`) |
| `--location` | `-l` | Ville/zone (ex: `Bordeaux`) |

### Sources / volume / sortie

| Option | Defaut | Description |
|---|---|---|
| `--source` (`-s`) | `maps` | Sources separees par virgule: `maps`, `pj`, `google` |
| `--limit` (`-n`) | `20` | Nombre max d'entreprises par source |
| `--format` (`-f`) | `both` | `json`, `csv` ou `both` |
| `--output-dir` (`-o`) | `results` | Dossier d'export |

### Filtrage qualite

| Option | Defaut | Description |
|---|---|---|
| `--only` | none | Garde seulement les entreprises ayant TOUS les champs demandes (`email`, `contact`, `website`, `address`, `description`) |
| `--min-score` | `0` | Garde seulement les entreprises avec `score >= N` |
| `--no-filter` | off | Desactive le filtre anti-junk + anti-fiches vides |

Exemples `--only`:
```bash
--only email
--only email,contact
--only email,website,description
```

### Comportement scraping

| Option | Defaut | Description |
|---|---|---|
| `--scroll-count` | `6` | Nombre de scrolls Maps (impacte surtout la source `maps`) |
| `--concurrency` | `5` | Nombre de scrapers websites en parallele |
| `--no-headless` | off | Affiche le navigateur (debug/CAPTCHA) |
| `--verbose` (`-v`) | off | Active les logs debug |

### Filtre IA (optionnel)

| Option | Defaut | Description |
|---|---|---|
| `--ai` | off | Filtre final de pertinence via Groq. Exporte aussi les entreprises refusees dans des fichiers `*_refused.*` |

## Configuration `.env` (pour `--ai`)

Creer un fichier `.env` a la racine:

```bash
GROQ_API_KEY=your_api_key_here
```

Puis lancer:

```bash
python main.py -q "agence web" -l "Bordeaux" --ai
```

## Score qualite

Le score est calcule sur 11 points max:

- `+2` website present
- `+2` adresse presente
- `+1` page contact presente
- `+1` description presente
- `+3` email pro
- `-2` email provider gratuit (gmail, outlook, etc.)
- `+2` entreprise vue sur plusieurs sources

Le pipeline trie ensuite les resultats par score descendant.

## Champs exportes

| Champ | Description |
|---|---|
| `company_name` | Nom de l'entreprise |
| `website` | URL du site |
| `email` | Email detecte |
| `description` | Description courte |
| `contact_page` | URL de page contact detectee |
| `address` | Adresse postale |
| `sources` | Sources d'origine (`maps`, `pj`, `google`) |
| `score` | Score qualite final |

## Nommage des fichiers

Les exports sont ecrits dans `results/` (ou `--output-dir`) avec un format de type:

```text
<sources>_<query>_<location>_<timestamp>.json
<sources>_<query>_<location>_<timestamp>.csv
```

Si `--ai` est active, des fichiers supplementaires sont crees pour les refus:

```text
..._refused.json
..._refused.csv
```

## Exemples utiles

```bash
# Basique (Google Maps)
python main.py -q "agence web" -l "Bordeaux"

# Multi-sources + CSV uniquement
python main.py -q "agence digitale" -l "Paris" -s maps,pj,google -n 30 -f csv

# Leads avec email + page contact
python main.py -q "developpement web" -l "Lyon" --only email,contact

# Forcer des leads plus qualifies
python main.py -q "ssii" -l "Toulouse" -s maps,pj,google --min-score 5

# Debug navigateur visible
python main.py -q "agence seo" -l "Nantes" --no-headless --verbose
```

## Structure du projet

```text
.
├── main.py
├── requirements.txt
├── config/
│   └── settings.py
├── core/
│   ├── orchestrator.py
│   └── pipeline.py
├── scrapers/
│   ├── base.py
│   ├── registry.py
│   ├── google_maps_scraper.py
│   ├── pages_jaunes_scraper.py
│   ├── google_search_scraper.py
│   └── website_scraper.py
├── extractors/
│   ├── email_extractor.py
│   └── text_extractor.py
├── models/
│   └── company.py
├── utils/
│   ├── deduplicator.py
│   ├── filter.py
│   ├── filters.py
│   ├── scorer.py
│   ├── ai_filter.py
│   └── ...
└── output/
    └── exporter.py
```

## Depannage

### Je n'ai pas beaucoup de resultats

- augmenter `--limit`
- activer plusieurs sources avec `-s maps,pj,google`
- utiliser `--no-headless` pour verifier visuellement les pages

### Je n'ai pas d'emails

C'est frequent: beaucoup de sites n'affichent pas d'email direct.

Pistes:
- utiliser `--only contact` pour garder les entreprises avec page contact
- combiner plusieurs sources pour recuperer plus de websites

### Erreurs Playwright / navigateur

Reinstaller Chromium:

```bash
playwright install chromium
```

### CAPTCHA / blocages

- relancer avec `--no-headless`
- reduire `--concurrency`
- augmenter les delais dans `config/settings.py`

## Notes

- Utiliser ce projet en respectant les CGU des sites cibles et la legislation locale.
- Les structures HTML des moteurs changent regulierement: certains selecteurs peuvent necessiter des ajustements.
