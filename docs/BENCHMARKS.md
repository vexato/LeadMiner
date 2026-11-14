# Mesures reproductibles

```bash
python benchmarks/compare.py --baseline 8c687f6 --sites 40 --latency-ms 3 --repeats 5
```

Le script charge les modules d'origine directement depuis la révision Git et exécute les deux versions dans des processus séparés. Les cinq passages utilisent 40 visites simulées, une concurrence de cinq et une latence fixe de 3 ms par requête. Les délais aléatoires de la version initiale sont désactivés pour comparer le nombre de requêtes et le travail local. Un lien de contact hors des chemins historiques est présent dans chaque page. Le cache de moteur reste en dehors de ce comparatif centré sur la collecte d'un site. Mesures locales sous Linux avec Python 3.14.10.

| Indicateur | Initial | Core V2 |
|---|---:|---:|
| Durée médiane du lot | 0,560 s | 0,323 s |
| Durée moyenne d'une visite, médiane des passages | 69,8 ms | 39,4 ms |
| Requêtes simulées par lot | 760 | 200 |
| Visites réussies par minute en simulation | 4 282 | 7 433 |
| Pages de contact retrouvées | 0/40 | 40/40 |
| Échecs de chargement de la page principale | 0/40 | 0/40 |
| Pic RSS des processus de mesure | 44,4 Mio | 54,1 Mio |

Sur un jeu synthétique distinct de 100 lignes et 50 établissements partageant un nom et un domaine, la version initiale a conservé une seule adresse et Core V2 en a conservé 50. Aucun doublon ne subsiste sur ce jeu. Le rapprochement a pris 1,25 ms puis 2,89 ms. Ce scénario mesure précisément l'erreur de fusion par nom ou domaine. Une évaluation par cas annotés de terrain reste nécessaire pour estimer rappel, précision et coût au volume attendu.

Un essai réel de la CLI sur l'API publique a trouvé trois établissements pour « salons de coiffure », dans un rayon de 20 km autour de Bordeaux, et produit CSV et JSON. L'exécution a duré environ 1,49 s. Les trois fiches avaient un SIRET et une adresse de registre. Le fournisseur n'a livré aucun site dans cet essai. Ce résultat mesure la découverte sur une requête, avec un coût facturé nul.

Les cibles de 95 % d'identités correctes et de moins de 2 % de faux rapprochements sur données réelles restent à mesurer. Les chiffres simulés dépendent des fixtures, de la durée imposée et de la machine. Le test réel de découverte ne fournit aucune comparaison avec les fournisseurs historiques.
