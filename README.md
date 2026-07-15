# 🧭 Momentum Multi-Actifs — rotation mensuelle avec analyse IA

Expérience de **marche à blanc** (aucun argent réel) : un bot applique chaque mois une
stratégie systématique de **dual momentum** (Antonacci) sur un univers de 10 ETF
multi-actifs, et une IA (Gemini) commente chaque soir le régime de marché. Le tout
tourne automatiquement sur GitHub Actions et publie un dashboard sur GitHub Pages.

## La stratégie

Le momentum est l'anomalie la mieux documentée de la finance empirique
(Jegadeesh & Titman 1993, confirmée hors échantillon depuis, sur toutes les classes
d'actifs). La version implémentée ici est une rotation « dual momentum » :

1. **Momentum relatif** — chaque premier jour de bourse du mois, les 8 actifs risqués
   de l'univers sont classés par leur score momentum (moyenne des performances sur
   3, 6 et 12 mois, dividendes inclus). Les **3 meilleurs** sont détenus à poids égaux.
2. **Momentum absolu** (le filtre anti-krach) — un actif n'est éligible que si son
   momentum dépasse celui des T-Bills (BIL). Sinon son slot bascule vers l'actif
   refuge **IEF** (obligations US 7-10 ans) ; et si IEF est lui-même en momentum
   négatif, le slot reste en **cash**.

### L'univers

| Bloc | ETF |
|---|---|
| Actions US | SPY, QQQ |
| International & émergents | EFA, EEM |
| Or & matières premières | GLD, DBC |
| Immobilier | VNQ |
| Obligations longues | TLT |
| Refuge (momentum absolu) | IEF |
| Seuil sans risque | BIL |

- **Capital virtuel : 10 000 $** — frais simulés : 0,05 % par ordre.
- **Benchmarks** : SPY (100 % actions US) et un 60/40 (SPY/IEF) rebalancé mensuellement, sans frais.
- Les ordres ne portent que sur les **écarts** à la cible (pas de vente/rachat inutile
  des lignes conservées) : la rotation réelle du dual momentum est faible, c'est ce qui
  lui permet de survivre aux frais.

### Le rôle de l'IA

Gemini **ne décide rien** : les allocations sont mécaniques. Il joue le rôle de
l'analyste — chaque soir il explique ce que dit le classement momentum, détecte les
changements de régime qui se préparent (bascule de rang, momentum absolu proche de
zéro), et signale les risques macro visibles dans l'actualité. Les jours de rotation,
il commente les ordres exécutés.

## Architecture

```
main.py            Passage quotidien : données → cible momentum → rotation éventuelle
                   → valorisation → analyse Gemini → snapshot
momentum.py        Cœur systématique : téléchargement des prix, scores, portefeuille cible
config.py          Univers, paramètres de la stratégie, flux RSS
report.py          Graphique PNG + rapport markdown quotidien
backtest.py        Backtest local (~18 ans) réutilisant le même code que la production
web/index.html     Dashboard GitHub Pages (autonome, lit les JSON du dépôt)
portfolio.json     État du portefeuille virtuel (créé au premier passage)
history.json       Un snapshot par séance : NAV, benchmarks, classement, analyse IA
```

Chaque soir de bourse (après la clôture de Wall Street, ~22h07 UTC), GitHub Actions :
1. exécute `main.py` (le rebalancement n'a lieu qu'au premier passage du mois — un
   cron manqué est donc rattrapé automatiquement le lendemain) ;
2. commit les résultats ;
3. redéploie le dashboard sur GitHub Pages.

## Installation

1. **Créer le dépôt GitHub** (public pour GitHub Pages gratuit) et pousser ce code.
2. **Secret API** : dans *Settings → Secrets and variables → Actions*, créer
   `GEMINI_API_KEY` (clé [Google AI Studio](https://aistudio.google.com/apikey)).
   Sans clé, le bot fonctionne quand même — simplement sans commentaire d'analyste.
3. **GitHub Pages** : dans *Settings → Pages*, choisir **Source : GitHub Actions**.
4. Premier lancement : onglet *Actions* → workflow **Bot Momentum Multi-Actifs** →
   *Run workflow*. Le portefeuille virtuel est créé à la première clôture disponible.

### En local

```bash
pip install -r requirements.txt

# Backtest de la stratégie (~18 ans, aucune clé nécessaire)
python backtest.py

# Passage du bot hors horaires de bourse (traite la dernière clôture disponible)
FORCE_RUN=1 python main.py           # PowerShell : $env:FORCE_RUN="1"; python main.py

# Prévisualiser le dashboard
python -m http.server 8000           # puis ouvrir http://localhost:8000/web/
```

## Garde-fous

- **Cron best-effort** : 4 créneaux étalés + garde-fou « déjà tourné aujourd'hui ».
- **Idempotence** : une séance déjà présente dans `history.json` n'est jamais retraitée.
- **Marché fermé** : si la dernière clôture SPY n'est pas du jour (week-end, jour férié),
  le passage s'annule proprement.
- **IA facultative** : toute erreur Gemini est non bloquante.

---

*Projet pédagogique de suivi de stratégie en marche à blanc. Rien ici ne constitue un
conseil en investissement.*
