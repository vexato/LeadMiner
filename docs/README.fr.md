# Guide de démarrage LeadMiner Core V2

[README en anglais](../README.md) · [Architecture](ARCHITECTURE.md) · [Audit](AUDIT_TECHNIQUE.md) · [Roadmap](ROADMAP.md) · [Décisions techniques](DECISIONS_TECHNIQUES.md)

## Docker et PostgreSQL

Docker avec Compose v2 est nécessaire. Générer les secrets une fois par installation et conserver le mot de passe associé au volume PostgreSQL. Les fichiers doivent être lisibles par les UID des services. Le répertoire local `.secrets` est privé et exclu de Git et du contexte de build.

```bash
cp .env.example .env
mkdir -m 700 .secrets
secret="$(openssl rand -hex 24)"
install -m 644 /dev/null .secrets/db-password
install -m 644 /dev/null .secrets/db-url
printf '%s' "$secret" > .secrets/db-password
printf 'postgresql+psycopg://leadminer:%s@db:5432/leadminer' "$secret" > .secrets/db-url
unset secret

docker compose build migrate
docker compose --profile cli run --rm cli python main.py \
  -q 96.02A -l Bordeaux --radius-km 20 -n 20
```

Compose démarre la base, attend son healthcheck puis applique Alembic. Les exports se trouvent dans le volume `results` du service CLI. Pour les copier vers le répertoire hôte, utiliser le service éphémère suivant.

```bash
mkdir -p exports
docker compose --profile cli run --rm -T cli tar -C /data/results -cf - . | tar -x -C exports
```

Les exports peuvent contenir des données professionnelles. PostgreSQL n'a aucun port publié par Compose. Les services tournent avec rotation des journaux.

## CLI directe

```bash
python -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements.txt
python main.py -q "salons de coiffure" -l Bordeaux --radius-km 20 -n 20
python main.py --help
```

Les options historiques de volume, format, filtrage, score minimal et Groq sont disponibles. Plusieurs sources peuvent être séparées par des virgules. La limite vaut par source. Les codes de sortie sont 0 si des résultats sont exportés avec succès, 1 pour une recherche terminée sans résultat, 2 en cas d'erreur de paramètres ou d'échec total ou partiel d'une source, et 130 pour une interruption clavier. Les résultats valides d'une recherche partielle sont exportés.

La source par défaut `sirene` utilise la recherche publique DINUM et contrôle le SIRET, l'activité de l'établissement, sa géographie et ses indicateurs de diffusion. Les synonymes intégrés couvrent coiffure et boulangerie. Un code NAF comme `96.02A` est recommandé pour les autres recherches sectorielles. Le texte libre utilise l'index de dénomination et d'adresse de la DINUM, avec statut d'activité inconnu. Le rayon autour du centre communal accepte de 0 à 50 km, requiert une commune unique et une activité NAF explicite ou reconnue, et contrôle les coordonnées retournées. La couverture dépend des établissements indexés et filtrables chez le fournisseur. [Contrat API DINUM](https://recherche-entreprises.api.gouv.fr/docs/)

La source `catalog` lit un fichier JSON fourni par l'opérateur. Exemple d'une ligne fictive.

```json
[
  {
    "company_name": "Atelier des Quais",
    "siret": "11111111100010",
    "address": "12 rue des Quais 33000 Bordeaux",
    "location": "Bordeaux",
    "postal_code": "33000",
    "activity": "coiffure",
    "activity_code": "96.02A",
    "website": "https://salon.example"
  }
]
```

```bash
python main.py -q 96.02A -l Bordeaux -s sirene,catalog --catalog ./catalogue-autorise.json
python main.py -q coiffure -l Bordeaux -s catalog \
  --catalog tests/fixtures/catalog.json --metrics /tmp/leadminer-metrics.json
```

Le rapprochement accepte les SIRET concordants ou un nom compatible à une adresse suffisamment structurée. L'enrichissement valide un site candidat dont la page d'accueil affiche un nom compatible dans son titre ou un titre principal et dont les pages examinées publient le seul SIRET exact de la fiche. Une page joignable sans cette preuve reste candidate. Les descriptions et signaux techniques candidats restent des observations attribuées à leurs pages. L'enrichissement conserve les emails de même domaine extraits d'un site rattaché. La délivrabilité d'une adresse reste inconnue. Le bloc `qualification` contient qualité des données, score commercial éventuel, confiance et preuves. Le champ `score` historique sur 11 reste disponible pour `--min-score`.

Les adaptateurs historiques `maps`, `pj` et `google` exigent `--allow-legacy-sources`, un Chromium installé et un proxy sortant autorisé qui filtre les adresses internes et les ports, y compris après résolution DNS. Ils sont réservés aux déploiements isolés avec droits d'usage vérifiés. L'adresse du premier résultat Maps et le site du premier résultat Google ne sont plus utilisés pour combler les valeurs manquantes. L'option Groq est réservée à une exécution explicitement demandée et nécessite votre compte `GROQ_API_KEY`. Les erreurs et réponses inconnues conservent la fiche. [Conditions Google Maps](https://maps.google.com/help/terms_maps/)

## Reprise et opposition

Pour une CLI directe, définir `DATABASE_URL` ou `DATABASE_URL_FILE` puis exécuter `alembic upgrade head`. La CLI donne un identifiant UUID avant les appels externes. Les sources terminées et les établissements déjà enrichis sont repris à partir de leurs checkpoints.

```bash
python main.py --resume UUID
python main.py --suppress SIREN_OU_SIRET
python main.py --delete-search UUID
```

Une reprise sur catalogue demande le même fichier et les mêmes permissions que l'exécution initiale, tant que le checkpoint de découverte reste absent. Une erreur de source produit un état terminal `partial` ou `failed`. Une nouvelle recherche relance alors la collecte. Une interruption s'arrête à la dernière transaction validée.

Les oppositions par identifiant purgent les fiches et leurs snapshots et empêchent leur réinsertion. Les oppositions commerciales observées via DINUM bloquent le SIREN. Les exports déjà copiés, sauvegardes et fiches sans identifiant nécessitent une gestion par l'opérateur. Définir la durée de conservation, le traitement des demandes d'opposition et le renouvellement des statuts de diffusion avant mise à disposition. [Réutilisation des données selon la CNIL](https://www.cnil.fr/fr/reutilisation-de-vos-donnees-publiees-sur-internet-des-fins-commerciales-quels-sont-vos-droits) · [Statut de diffusion Sirene](https://www.insee.fr/fr/information/7456564)

## API et worker

```bash
docker compose --profile api up --wait
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/searches \
  -H 'Content-Type: application/json' \
  -d '{"query":"96.02A","location":"Bordeaux","limit":10,"radius_km":20}'
```

`POST /searches` retourne 202 et un identifiant. Le worker récupère les recherches depuis PostgreSQL. Consulter `GET /searches/{id}`, `GET /searches/{id}/results?limit=25&offset=0` et `GET /establishments/{siret}`. Les résultats acceptent également `min_score` et `website_status`. La documentation OpenAPI est disponible sur `/docs`. Le port Compose écoute uniquement sur l'interface locale. Une mise à disposition multi-utilisateurs demande une couche d'authentification et d'isolation.

## Vérifications et mesures

```bash
pip install --require-hashes -r requirements-dev.txt
ruff check .
python -m pytest -q
python benchmarks/compare.py
```

Pour intégrer PostgreSQL aux tests, définir `LEADMINER_TEST_DATABASE_URL` sur une base strictement jetable. La suite exécute `upgrade`, `downgrade base`, `upgrade` et vérifie l'absence de dérive. La CI inclut Python 3.11 et 3.12 ainsi qu'un démarrage Compose. [Mesures](BENCHMARKS.md)
