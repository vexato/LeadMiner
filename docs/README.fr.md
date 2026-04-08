# LeadMiner

Langue: FR | [EN](README.md)

LeadMiner est un outil CLI Python de generation de leads B2B multi-sources.
Il decouvre des entreprises, deduplique les fiches, enrichit les donnees depuis les sites web, attribue un score de qualite, puis exporte les resultats en JSON et CSV.

## Sommaire

- [Fonctionnalites](#fonctionnalites)
- [Pipeline](#pipeline)
- [Prerequis](#prerequis)
- [Installation](#installation)
- [Demarrage rapide](#demarrage-rapide)
- [Options CLI](#options-cli)
- [Filtre IA (optionnel)](#filtre-ia-optionnel)
- [Score qualite](#score-qualite)
- [Champs exportes](#champs-exportes)
- [Nommage des fichiers](#nommage-des-fichiers)
- [Exemples utiles](#exemples-utiles)
- [Structure du projet](#structure-du-projet)
- [Depannage](#depannage)
- [Bonnes pratiques legales](#bonnes-pratiques-legales)
- [Licence](#licence)

## Fonctionnalites

- Discovery multi-sources: `maps`, `pj`, `google`
- Deduplication des doublons (nom + domaine)
- Enrichissement via website (email, page contact, description)
- Scoring de qualite des leads
- Filtres par champs obligatoires et score minimal
- Export en `JSON`, `CSV` ou les deux
- Filtre final IA (Groq) en option

## Prévisualisation (durée réelle : 9 min)

<img src="./Animation.gif"/>

## Pipeline

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
- Playwright Chromium

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

Important: `--limit` est applique par source. Avec `maps,pj,google`, le volume brut peut depasser la limite avant deduplication et filtrage.

## Options CLI

### Obligatoires

| Option | Raccourci | Description |
|---|---|---|
| `--query` | `-q` | Activite recherchee (ex: `agence web`) |
| `--location` | `-l` | Ville/zone (ex: `Bordeaux`) |

### Sources, volume, sortie

| Option | Defaut | Description |
|---|---|---|
| `--source` (`-s`) | `maps` | Sources separees par virgule: `maps`, `pj`, `google` |
| `--limit` (`-n`) | `20` | Nombre max d'entreprises par source |
| `--format` (`-f`) | `both` | `json`, `csv` ou `both` |
| `--output-dir` (`-o`) | `results` | Dossier d'export |

### Filtrage qualite

| Option | Defaut | Description |
|---|---|---|
| `--only` | none | Garde les entreprises ayant TOUS les champs demandes (`email`, `contact`, `website`, `address`, `description`) |
| `--min-score` | `0` | Garde les entreprises avec `score >= N` |
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
| `--scroll-count` | `6` | Nombre de scrolls Maps |
| `--concurrency` | `5` | Nombre de scrapers website en parallele |
| `--no-headless` | off | Affiche le navigateur (debug/CAPTCHA) |
| `--verbose` (`-v`) | off | Active les logs debug |

## Filtre IA (optionnel)

| Option | Defaut | Description |
|---|---|---|
| `--ai` | off | Filtre final de pertinence via Groq. Exporte aussi les entreprises refusees dans des fichiers `*_refused.*` |

Creer un fichier `.env` a la racine:

```bash
GROQ_API_KEY=your_api_key_here
```

Puis lancer:

```bash
python main.py -q "agence web" -l "Bordeaux" --ai
```

## Score qualite

Le score est calcule sur un maximum de `11` points:

- `+2` website present
- `+2` adresse presente
- `+1` page contact presente
- `+1` description presente
- `+3` email professionnel
- `-2` email de provider gratuit (gmail, outlook, etc.)
- `+2` entreprise vue sur plusieurs sources

Les resultats sont tries par score descendant.

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

# Leads plus qualifies
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

### Peu de resultats

- Augmenter `--limit`
- Activer plusieurs sources avec `-s maps,pj,google`
- Utiliser `--no-headless` pour verifier visuellement les pages

### Pas d'emails

C'est frequent: de nombreux sites n'affichent pas d'email direct.

Pistes:

- Utiliser `--only contact` pour garder les entreprises avec page contact
- Combiner plusieurs sources pour trouver plus de websites

### Erreurs Playwright / navigateur

Reinstaller Chromium:

```bash
playwright install chromium
```

### CAPTCHA / blocages

- Relancer avec `--no-headless`
- Reduire `--concurrency`
- Augmenter les delais dans `config/settings.py`

## Bonnes pratiques legales

- Respecter les CGU des sites cibles.
- Respecter la legislation locale (scraping, protection des donnees, prospection).
- Prevoir de maintenir les selecteurs: les structures HTML changent regulierement.

## Licence

Ce projet est distribue sous licence MIT. Voir [LICENSE](../LICENSE).
