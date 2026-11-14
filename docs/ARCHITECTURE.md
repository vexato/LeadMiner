# Architecture Core V2

```mermaid
flowchart LR
    CLI --> M[Moteur asynchrone]
    API --> B[(PostgreSQL)]
    W[Worker] --> M
    W --> B
    M --> D[Adaptateurs de découverte]
    M --> I[Rapprochement des établissements]
    I --> E[Collecte web bornée]
    E --> Q[Qualification et preuves]
    Q --> B
    M --> X[Adaptateur CSV et JSON]
```

Le moteur réutilise le contrat `BaseSource`, les extracteurs et les filtres de la CLI. Chaque recherche garde l'ordre demandé des sources même si elles terminent à des moments différents. Les erreurs attendues ont un état explicite. Un résultat sans site connu est exploitable si l'établissement a une identité certaine.

`Company` reste le modèle échangé avec la CLI. Il représente une fiche établissement avec SIRET, entreprise juridique (SIREN), éventuelle enseigne, site candidat, contacts et observations. Les sources de référence peuvent déclarer une valeur vérifiée au registre. Le succès HTTP confirme l'accès à une page. L'attribution officielle exige une preuve d'identité distincte. L'historique et les conflits sont portés par des observations datées.

PostgreSQL porte les recherches, les exécutions, les résultats de recherche et les identités légales. Les observations, états d'enrichissement, sites, contacts et scores sont versionnés par résultat dans une projection JSONB. Les checkpoints par source et par fiche permettent la reprise sous le même identifiant. Une transaction enregistre chaque checkpoint. Le worker traite les recherches hors du processus HTTP. La CLI peut exécuter le moteur avec ou sans PostgreSQL.

La frontière réseau vérifie les schémas, les utilisateurs et ports, les IP et chaque redirection. Un resolver filtre les réponses DNS utilisées pour la connexion. Les fetchs web ont des limites de taille, de temps et de concurrence. La découverte par navigateur historique relève de l'exploitation autorisée. L'API et le worker utilisent la source publique.

Le profil agences web évalue des signaux observables avec une explication et leurs pages d'origine. La complétude historique, la qualité, la pertinence commerciale et la confiance restent des valeurs distinctes.
