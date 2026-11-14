# Roadmap Core V2

| Priorité | Étape | Dépend de | Critère d'acceptation | État au 14 novembre 2026 |
|---|---|---|---|---|
| P0 | Audit et conception | Révision de départ | Causes et impacts vérifiés dans le code | Réalisé |
| P0 | Docker, paramètres, CI | Dépendances | Image et Chromium démarrés, PostgreSQL sain, suite hors ligne | Vérifié localement, réseau Compose testé en mode hôte |
| P0 | Sécurité HTTP, export et découverte | Audit | TLS, redirections et IP privées bloquées, chemins et cellules neutralisés | Vérifié par tests |
| P0 | Identité et provenance | Source publique, modèle | SIRET distincts, ambiguïtés préservées, preuves exportables | Vérifié sur fixtures et avec DINUM |
| P1 | Persistance et reprise | Modèle | Migrations, transactions, interruption et opposition testées | Vérifié sur PostgreSQL 16 |
| P1 | Benchmarks et optimisation | Référence historique | Comparatif reproductible sans fournisseurs externes | Mesuré dans [BENCHMARKS.md](BENCHMARKS.md) |
| P1 | Profil agences web | Observations web | Score explicable, présence officielle et absence traitées selon les preuves | Vérifié sur HTML local, validation terrain ouverte |
| P1 | API et worker | Reprise | Créer, suivre, filtrer et paginer une recherche hors requête HTTP | Vérifié par intégration |
| P2 | Évaluation terrain | Jeu annoté représentatif | Mesurer les objectifs d'identité, de faux rapprochements et de latence | À faire |


## Suite vers un SaaS

1. Constituer un échantillon annoté et stratifié par secteur, géographie et chaînes à plusieurs sites. Mesurer erreurs de fusion, rappel des sites et couverture de la source publique.
2. Évaluer une source autorisée pour élargir la découverte de sites candidats. La DINUM alimente surtout l'identité et la géographie. Le catalogue local fournit déjà des URL à vérifier.
3. Ajouter une politique de rafraîchissement planifiée, la gestion des exports et sauvegardes lors des oppositions, ainsi que des limites globales de débit pour des workers multiples.
4. Ajouter une authentification et des droits par espace de travail, puis tester l'isolation des données. Évaluer `pg_trgm`, PostGIS ou une autre file uniquement sur des mesures représentatives.
