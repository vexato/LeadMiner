# LeadMiner Core V2

LeadMiner discovers B2B establishments, reconciles their identities, collects evidence about candidate websites and exports CSV and JSON. The Python engine can run from the CLI or from a PostgreSQL-backed worker with a private FastAPI interface.

[Guide de démarrage en français](docs/README.fr.md) · [Architecture](docs/ARCHITECTURE.md) · [Audit](docs/AUDIT_TECHNIQUE.md) · [Roadmap](docs/ROADMAP.md) · [Technical decisions](docs/DECISIONS_TECHNIQUES.md)

## Quick start

Use Python 3.11+ and the locked requirements.

```bash
python -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements.txt
python main.py -q "salons de coiffure" -l Bordeaux --radius-km 20 -n 20
```

The default source is the French public Recherche d'entreprises API. Use a NAF code for exact activity selection. The location is a commune or postal code. The public registry can provide identity, activity and address. An authorized catalog can add website candidates. Each export includes source and verification metadata. [Provider documentation](https://recherche-entreprises.api.gouv.fr/docs/)

```bash
python main.py -q coiffure -l Bordeaux -s sirene,catalog --catalog ./authorized-catalog.json
python main.py --help
```

The [French guide](docs/README.fr.md) includes a reproducible Docker startup, the catalog schema, database migrations and resume, the worker and API, and the test procedure.

## License

[MIT](LICENSE)
