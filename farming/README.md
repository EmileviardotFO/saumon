# Suivi salmonicole : Canada, Australie, douanes

## Contenu
| Chemin | Rôle |
|---|---|
| `farming_canada_australie.xlsx` | Classeur unique (onglets Canada + `AU_`). Remplace `farming_canada.xlsx`, à supprimer du dépôt. |
| `farming/scripts/maj_australie.py` | Australie : page EPA (mortalités, pas d'API) et portail NRE (production). |
| `farming/scripts/ingest_bc.py` | Canada / BC : adresses et dates lues dans le catalogue open.canada.ca ; `COLS` à renseigner après `inspect`. |
| `farming/scripts/maj_douanes.py` + `douanes_config.json` | Douanes par API : États-Unis (Census), Norvège, Islande, Féroé (PxWeb). |
| `donnees_au/`, `donnees_douanes/`, `donnees_ca/` | CSV datés (historique, révisions) + journaux. `donnees_douanes/fraicheur.csv` = dernier mois réellement disponible par source. |
| `.github/workflows/*.yml` | Trois passages quotidiens automatiques, commit si quelque chose change. |

## Ce qui reste manuel
1. **Une fois** : `python scripts/maj_douanes.py --decouvrir <source>` pour chaque table PxWeb, puis remplir `selection` dans `douanes_config.json` (sans sélection, la source donne déjà sa fraîcheur).
2. **Une fois** : `COLS` dans `farming/scripts/ingest_bc.py` (Canada), puis décommenter l'étape *build* du workflow.
3. **Facultatif** : clé gratuite du Census en secret GitHub `CENSUS_KEY`.
4. **Au fil de l'eau** : lire les courriels GitHub. `--strict` fait échouer un passage en cas de retard, de révision ou de lecture anormale.
5. **Chine et Chili** : hors automatisation pour l'instant (voir la clé `manuel` de la configuration).

## Si une source casse
- Australie : la page EPA est lue comme du texte ; un changement de mise en page donne « aucune ligne trouvée » dans le journal.
- PxWeb : une erreur 404 veut dire que le chemin de la table a changé ; copier l'adresse « API » affichée sous la table sur le site.
- Les serveurs de GitHub peuvent être refusés par certains sites gouvernementaux : lancer alors le script depuis un poste (cron).

## Intégration dans le dépôt existant
Tout le projet vit dans `farming/` ; seuls les trois workflows sont à la racine, dans `.github/workflows/farming_*.yml`
(GitHub n'exécute les workflows que depuis cet endroit). Ils travaillent dans `farming/` et ne touchent à rien d'autre.
Les trois passages partagent un verrou (`concurrency: farming-commit`) et récupèrent les derniers changements avant
d'enregistrer, pour ne pas entrer en conflit entre eux ni avec les autres workflows du dépôt.
