"""Bot de rotation momentum multi-actifs — marche à blanc quotidienne.

Déroulé d'un passage (chaque soir de bourse US, après la clôture) :
  1. téléchargement des prix de l'univers (10 ETF) ;
  2. calcul du classement momentum et du portefeuille cible du moment ;
  3. si premier passage du mois → rotation (rebalancement mensuel) ;
  4. valorisation du portefeuille et des deux benchmarks (SPY, 60/40) ;
  5. analyse de Gemini (rôle : ANALYSTE — il explique, il ne décide rien) ;
  6. snapshot dans history.json + rapport markdown + graphique.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

# La console Windows par défaut (cp1252) ne sait pas encoder les emoji des logs.
# GitHub Actions (Linux) est déjà en UTF-8 ; ceci sécurise l'exécution locale.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import feedparser

import config
import momentum
import report

FUSEAU_NY = ZoneInfo("America/New_York")


# --- Utilitaires -----------------------------------------------------------------

def charger_json(chemin, defaut):
    if chemin.exists():
        try:
            return json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:
            return defaut
    return defaut


def sauvegarder_json(chemin, donnees):
    chemin.write_text(json.dumps(donnees, indent=2, ensure_ascii=False), encoding="utf-8")


def dernier_prix(prix, ticker) -> float:
    return float(prix[ticker].dropna().iloc[-1])


def premier_jour_bourse_mois_suivant(date: datetime.date) -> datetime.date:
    """Premier jour OUVRÉ du mois suivant (approximation hors jours fériés US)."""
    annee, mois = (date.year + 1, 1) if date.month == 12 else (date.year, date.month + 1)
    jour = datetime.date(annee, mois, 1)
    while jour.weekday() >= 5:
        jour += datetime.timedelta(days=1)
    return jour


# --- Portefeuille ------------------------------------------------------------------

def initialiser_portefeuille(prix, date_str: str) -> dict:
    """Crée le portefeuille virtuel et les deux benchmarks (même capital, sans frais)."""
    capital = config.CAPITAL_INITIAL
    prix_spy = dernier_prix(prix, "SPY")
    prix_ief = dernier_prix(prix, config.ACTIF_REFUGE)
    return {
        "date_creation": date_str,
        "capital_initial": capital,
        "cash": capital,
        "positions": {},          # ticker -> {"parts": float, "prix_revient": float, "date_achat": str}
        "poids_cible": {},
        "dernier_rebalancement": None,   # "YYYY-MM"
        "frais_cumules": 0.0,
        "benchmarks": {
            "spy": {"parts": capital / prix_spy},
            "b6040": {
                "parts_spy": capital * config.BENCH_6040["SPY"] / prix_spy,
                "parts_ief": capital * config.BENCH_6040["IEF"] / prix_ief,
            },
        },
    }


def valeur_positions(ptf, prix) -> dict[str, float]:
    return {t: pos["parts"] * dernier_prix(prix, t) for t, pos in ptf["positions"].items()}


def nav_portefeuille(ptf, prix) -> float:
    return ptf["cash"] + sum(valeur_positions(ptf, prix).values())


def nav_benchmarks(ptf, prix) -> tuple[float, float]:
    b = ptf["benchmarks"]
    nav_spy = b["spy"]["parts"] * dernier_prix(prix, "SPY")
    nav_6040 = (b["b6040"]["parts_spy"] * dernier_prix(prix, "SPY")
                + b["b6040"]["parts_ief"] * dernier_prix(prix, config.ACTIF_REFUGE))
    return nav_spy, nav_6040


def executer_rotation(ptf, cible: dict[str, float], prix, date_str: str) -> list[dict]:
    """Ajuste les positions vers les poids cibles (ordres sur les écarts uniquement).

    Trader seulement les deltas évite de payer des frais sur les lignes conservées
    d'un mois sur l'autre — la rotation réelle du dual momentum est faible.
    """
    nav = nav_portefeuille(ptf, prix)
    valeurs = valeur_positions(ptf, prix)

    # Les frais sont provisionnés AVANT de dimensionner les ordres : sans cela, un
    # portefeuille investi à 100 % finirait avec un cash légèrement négatif.
    def valeurs_cibles(montant):
        return {t: p * montant for t, p in cible.items() if t != "CASH"}

    brut = valeurs_cibles(nav)
    frais_estimes = sum(abs(brut.get(t, 0.0) - valeurs.get(t, 0.0))
                        for t in set(valeurs) | set(brut)) * config.COUT_TRANSACTION_PCT / 100.0
    cible_valeurs = valeurs_cibles(nav - frais_estimes)
    trades = []

    for ticker in sorted(set(valeurs) | set(cible_valeurs)):
        delta = cible_valeurs.get(ticker, 0.0) - valeurs.get(ticker, 0.0)
        if abs(delta) < config.SEUIL_ORDRE_USD:
            continue
        prix_actuel = dernier_prix(prix, ticker)
        frais = abs(delta) * config.COUT_TRANSACTION_PCT / 100.0
        parts_delta = delta / prix_actuel

        position = ptf["positions"].setdefault(
            ticker, {"parts": 0.0, "prix_revient": prix_actuel, "date_achat": date_str})
        if parts_delta > 0:  # achat → mise à jour du prix de revient moyen
            anciennes = position["parts"]
            position["prix_revient"] = (
                (anciennes * position["prix_revient"] + parts_delta * prix_actuel)
                / (anciennes + parts_delta))
            if anciennes == 0:
                position["date_achat"] = date_str
        position["parts"] += parts_delta
        if position["parts"] * prix_actuel < 1.0:  # ligne soldée
            del ptf["positions"][ticker]

        ptf["cash"] -= delta + frais
        ptf["frais_cumules"] += frais
        trades.append({
            "ticker": ticker,
            "sens": "achat" if delta > 0 else "vente",
            "montant": round(abs(delta), 2),
            "prix": round(prix_actuel, 2),
            "parts": round(abs(parts_delta), 4),
            "frais": round(frais, 2),
        })
        signe = "🟢 Achat" if delta > 0 else "🔴 Vente"
        print(f"{signe} {ticker} : {abs(delta):,.2f} $ à {prix_actuel:.2f} $ (frais {frais:.2f} $)")

    # Benchmark 60/40 : rebalancé aux mêmes dates, sans frais.
    nav_spy, nav_6040 = nav_benchmarks(ptf, prix)
    b = ptf["benchmarks"]["b6040"]
    b["parts_spy"] = nav_6040 * config.BENCH_6040["SPY"] / dernier_prix(prix, "SPY")
    b["parts_ief"] = nav_6040 * config.BENCH_6040["IEF"] / dernier_prix(prix, config.ACTIF_REFUGE)

    ptf["poids_cible"] = cible
    ptf["dernier_rebalancement"] = date_str[:7]
    return trades


# --- Actualités & IA ----------------------------------------------------------------

def recuperer_actus() -> str:
    titres = []
    for url in config.FLUX_ACTU:
        try:
            flux = feedparser.parse(url)
            for entree in flux.entries[: config.TITRES_PAR_FLUX]:
                titres.append(f"- {entree.title}")
        except Exception as e:
            print(f"Flux RSS illisible ({url}) : {e}")
    return "\n".join(titres) if titres else "Aucune actualité disponible."


def formater_table_momentum(table) -> str:
    lignes = []
    for l in sorted(table, key=lambda x: (x["rang"] is None, x["rang"] or 0)):
        rang = f"#{l['rang']}" if l["rang"] else "réf."
        absolu = "POSITIF" if l["excess"] > 0 else "NÉGATIF"
        statut = " ← DÉTENU" if l["selectionne"] else ""
        lignes.append(
            f"{rang} {l['ticker']} ({l['nom']}) : score {l['score']*100:+.1f}% "
            f"[3m {l['r3m']*100:+.1f}%, 6m {l['r6m']*100:+.1f}%, 12m {l['r12m']*100:+.1f}%] "
            f"— momentum absolu vs T-Bills : {absolu}{statut}")
    return "\n".join(lignes)


def analyser_avec_gemini(contexte: dict) -> dict | None:
    """Demande à Gemini un commentaire d'analyste sur la situation. Facultatif :
    sans clé API (ou en cas d'erreur), le bot continue sans analyse."""
    if not config.GEMINI_API_KEY:
        print("⚠️ GEMINI_API_KEY absente : passage sans analyse IA.")
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("⚠️ Paquet google-genai absent : passage sans analyse IA.")
        return None

    bloc_rotation = ""
    if contexte["trades"]:
        lignes = "\n".join(
            f"- {t['sens'].upper()} {t['ticker']} pour {t['montant']:,.0f} $"
            for t in contexte["trades"])
        bloc_rotation = (
            "\nROTATION EXÉCUTÉE AUJOURD'HUI (rebalancement mensuel) :\n"
            f"{lignes}\n"
            "Explique dans ton commentaire ce que cette rotation dit du marché.\n")

    prompt = f"""
Tu es un analyste quantitatif senior. Tu commentes chaque jour un portefeuille géré par une
règle SYSTÉMATIQUE de dual momentum (Antonacci) sur 10 ETF multi-actifs : classement par
performance 3/6/12 mois, détention des {config.TOP_N} meilleurs, et bascule vers les
obligations ({config.ACTIF_REFUGE}) puis le cash si le momentum absolu (vs T-Bills) devient négatif.

IMPORTANT : tu ne décides RIEN. Les allocations sont mécaniques. Ton rôle est celui de
l'analyste : expliquer ce que le classement momentum dit du régime de marché, détecter les
changements de régime qui se préparent (actifs proches d'un basculement de rang ou d'un
momentum absolu négatif), et signaler les risques macro visibles dans l'actualité.

DATE : {contexte['date']}
VIX : {contexte['vix']}
RÉGIME MÉCANIQUE DE LA STRATÉGIE : {contexte['regime_strategie']}
(offensif = tous les slots en actifs risqués, mixte = partiellement replié, défensif = tout en refuge/cash)

CLASSEMENT MOMENTUM DU JOUR :
{contexte['table']}

PORTEFEUILLE (marche à blanc, départ {contexte['capital_initial']:,.0f} $) :
- Valeur actuelle : {contexte['nav']:,.2f} $ ({contexte['perf_totale']:+.2f}% depuis le départ)
- Benchmark S&P 500 (SPY) : {contexte['perf_spy']:+.2f}% | Benchmark 60/40 : {contexte['perf_6040']:+.2f}%
- Positions : {contexte['positions']}
- Prochaine rotation mensuelle : {contexte['prochaine_rotation']}
{bloc_rotation}
ACTUALITÉS MACRO RÉCENTES (titres bruts) :
{contexte['actus']}

Réponds en français, au format JSON strict :
{{
  "regime": "risk_on" | "neutre" | "risk_off",   // TON diagnostic macro (peut différer du régime mécanique)
  "titre": "une phrase d'accroche (max 12 mots)",
  "commentaire": "ton analyse du jour en 120 à 200 mots : ce que dit le classement momentum, cohérence avec l'actualité macro, tensions ou divergences notables",
  "risques": ["2 à 4 risques concrets pour le portefeuille actuel"],
  "a_surveiller": ["2 à 3 signaux précis à surveiller (seuils de bascule momentum, événements macro datés)"]
}}
"""
    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        reponse = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        analyse = json.loads(reponse.text)
        analyse["modele"] = config.GEMINI_MODEL
        return analyse
    except Exception as e:
        print(f"⚠️ Analyse Gemini indisponible : {e}")
        return None


# --- Passage quotidien ----------------------------------------------------------------

def executer_passage():
    maintenant_ny = datetime.datetime.now(FUSEAU_NY)
    force = os.environ.get("FORCE_RUN") == "1"

    print("Téléchargement des données de marché...")
    tickers = (list(config.UNIVERS_RISQUE) + [config.ACTIF_REFUGE, config.ACTIF_SANS_RISQUE,
                                              config.TICKER_VIX])
    prix = momentum.telecharger_prix(tickers)

    # La journée traitée est celle de la dernière clôture disponible pour SPY.
    date_seance = prix["SPY"].dropna().index[-1].date()
    date_str = date_seance.isoformat()

    # Garde-fous : ne traiter que la clôture FRAÎCHE du jour (sauf FORCE_RUN=1).
    if not force:
        if date_seance != maintenant_ny.date():
            print(f"⛔ Pas de séance aujourd'hui ({maintenant_ny:%Y-%m-%d}) : dernière clôture "
                  f"connue le {date_str}. Marché fermé, exécution annulée.")
            return
        if (maintenant_ny.hour, maintenant_ny.minute) < (16, 10):
            print(f"⛔ Il est {maintenant_ny:%H:%M} à New York : le bot doit tourner après la "
                  "clôture (16h10). Exécution annulée (FORCE_RUN=1 pour outrepasser).")
            return

    historique = charger_json(config.FICHIER_HISTORIQUE, [])
    if any(s["date"] == date_str for s in historique):
        print(f"⛔ La séance du {date_str} est déjà dans l'historique. Rien à faire.")
        return

    # Portefeuille (créé au premier passage).
    ptf = charger_json(config.FICHIER_PORTEFEUILLE, None)
    if ptf is None:
        print(f"🚀 Premier passage : création du portefeuille ({config.CAPITAL_INITIAL:,.0f} $ virtuels).")
        ptf = initialiser_portefeuille(prix, date_str)

    # Classement momentum + cible du jour.
    table = momentum.table_momentum(prix)
    cible, regime_strategie = momentum.portefeuille_cible(table)
    print(f"Régime mécanique : {regime_strategie} | Cible : "
          + ", ".join(f"{t} {p:.0%}" for t, p in cible.items()))

    # Rotation si premier passage du mois (rattrape automatiquement un cron manqué).
    trades = []
    rebalance = ptf["dernier_rebalancement"] != date_str[:7]
    if rebalance:
        print(f"🔄 Rebalancement mensuel ({date_str[:7]})...")
        trades = executer_rotation(ptf, cible, prix, date_str)
        if not trades:
            print("Aucun ordre nécessaire : le portefeuille collait déjà à la cible.")
    else:
        # Hors rotation, on marque quand même les actifs détenus dans la table.
        for ligne in table:
            ligne["selectionne"] = ligne["ticker"] in ptf["positions"]

    # Valorisation.
    nav = nav_portefeuille(ptf, prix)
    nav_spy, nav_6040 = nav_benchmarks(ptf, prix)
    capital = ptf["capital_initial"]
    perf = (nav / capital - 1) * 100
    perf_spy = (nav_spy / capital - 1) * 100
    perf_6040 = (nav_6040 / capital - 1) * 100
    print(f"💼 Valeur : {nav:,.2f} $ ({perf:+.2f}%) | SPY {perf_spy:+.2f}% | 60/40 {perf_6040:+.2f}%")

    try:
        vix = round(dernier_prix(prix, config.TICKER_VIX), 1)
    except Exception:
        vix = None

    positions_detail = [
        {"ticker": t, "nom": config.NOMS.get(t, t), "parts": round(pos["parts"], 4),
         "prix": round(dernier_prix(prix, t), 2),
         "valeur": round(pos["parts"] * dernier_prix(prix, t), 2),
         "prix_revient": round(pos["prix_revient"], 2), "date_achat": pos["date_achat"]}
        for t, pos in sorted(ptf["positions"].items())]

    prochaine_rotation = premier_jour_bourse_mois_suivant(date_seance).isoformat()

    # Analyse IA.
    print("Analyse par l'IA (Gemini)...")
    analyse = analyser_avec_gemini({
        "date": date_str,
        "vix": vix if vix is not None else "indisponible",
        "regime_strategie": regime_strategie,
        "table": formater_table_momentum(table),
        "capital_initial": capital,
        "nav": nav,
        "perf_totale": perf,
        "perf_spy": perf_spy,
        "perf_6040": perf_6040,
        "positions": ", ".join(f"{p['ticker']} ({p['valeur']:,.0f} $)"
                               for p in positions_detail) or "100 % cash",
        "prochaine_rotation": prochaine_rotation,
        "trades": trades,
        "actus": recuperer_actus(),
    })
    if analyse:
        print(f"🧠 {analyse.get('titre', '')} [{analyse.get('regime', '?')}]")

    # Snapshot du jour.
    arrondi = lambda v: round(v, 4) if isinstance(v, float) else v
    historique.append({
        "date": date_str,
        "nav": round(nav, 2),
        "bench_spy": round(nav_spy, 2),
        "bench_6040": round(nav_6040, 2),
        "cash": round(ptf["cash"], 2),
        "frais_cumules": round(ptf["frais_cumules"], 2),
        "vix": vix,
        "regime_strategie": regime_strategie,
        "rebalance": rebalance,
        "trades": trades,
        "positions": positions_detail,
        "momentum": [{k: arrondi(v) for k, v in ligne.items()} for ligne in table],
        "ia": analyse,
    })
    sauvegarder_json(config.FICHIER_HISTORIQUE, historique)
    sauvegarder_json(config.FICHIER_PORTEFEUILLE, ptf)
    sauvegarder_json(config.FICHIER_ANALYSE, {
        "date": date_str,
        "prochaine_rotation": prochaine_rotation,
        "regime_strategie": regime_strategie,
        "ia": analyse,
    })

    print("Génération du rapport et du graphique...")
    report.generer_graphique()
    report.generer_rapport_markdown()


if __name__ == "__main__":
    print(f"--- BOT MOMENTUM MULTI-ACTIFS ({datetime.datetime.now(FUSEAU_NY):%Y-%m-%d %H:%M} NY) ---")
    executer_passage()
    print("--- FIN DE L'EXÉCUTION ---")
