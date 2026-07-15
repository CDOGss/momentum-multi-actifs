"""Cœur systématique de la stratégie : données de marché et calcul du momentum.

Toutes les décisions d'allocation sortent d'ici, de façon purement mécanique.
L'IA (main.py) ne fait que commenter.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

import config


def telecharger_prix(tickers: list[str], periode: str = "2y") -> pd.DataFrame:
    """Clôtures quotidiennes ajustées (dividendes + splits) pour une liste de tickers.

    Retourne un DataFrame indexé par date, une colonne par ticker.
    """
    df = yf.download(
        tickers,
        period=periode,
        interval="1d",
        auto_adjust=True,  # prix ajustés → le momentum intègre les dividendes
        progress=False,
        threads=True,
    )
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(name=tickers[0])
    return closes.dropna(how="all")


def rendement_periode(serie: pd.Series, jours: int) -> float | None:
    """Rendement simple sur `jours` séances (None si historique insuffisant)."""
    s = serie.dropna()
    if len(s) <= jours:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - jours] - 1.0)


def score_momentum(serie: pd.Series) -> float | None:
    """Score = moyenne pondérée des rendements 3/6/12 mois (cf. config)."""
    total, poids_cumule = 0.0, 0.0
    for jours, poids in config.PERIODES_MOMENTUM.items():
        r = rendement_periode(serie, jours)
        if r is None:
            return None
        total += poids * r
        poids_cumule += poids
    return total / poids_cumule if poids_cumule else None


def table_momentum(prix: pd.DataFrame) -> list[dict]:
    """Table complète du classement momentum, prête pour le rapport et le dashboard.

    Une ligne par actif (risqués + refuge) avec rendements par horizon, score,
    excès vs T-Bills (momentum absolu) et rang parmi les actifs risqués.
    """
    score_sans_risque = score_momentum(prix[config.ACTIF_SANS_RISQUE])
    if score_sans_risque is None:
        raise RuntimeError(f"Historique insuffisant pour {config.ACTIF_SANS_RISQUE}")

    lignes = []
    for ticker in list(config.UNIVERS_RISQUE) + [config.ACTIF_REFUGE]:
        serie = prix[ticker]
        score = score_momentum(serie)
        if score is None:
            print(f"⚠️ Historique insuffisant pour {ticker} : exclu du classement.")
            continue
        lignes.append({
            "ticker": ticker,
            "nom": config.NOMS[ticker],
            "type": "refuge" if ticker == config.ACTIF_REFUGE else "risque",
            "r3m": rendement_periode(serie, 63),
            "r6m": rendement_periode(serie, 126),
            "r12m": rendement_periode(serie, 252),
            "score": score,
            "excess": score - score_sans_risque,  # momentum absolu
            "selectionne": False,
        })

    risques = sorted((l for l in lignes if l["type"] == "risque"),
                     key=lambda l: l["score"], reverse=True)
    for rang, ligne in enumerate(risques, start=1):
        ligne["rang"] = rang
    for ligne in lignes:
        ligne.setdefault("rang", None)
    return lignes


def portefeuille_cible(table: list[dict]) -> tuple[dict[str, float], str]:
    """Applique le dual momentum et retourne (poids cibles, régime stratégie).

    - momentum relatif : TOP_N meilleurs actifs risqués, poids égaux ;
    - momentum absolu  : tout sélectionné dont l'excès vs T-Bills est ≤ 0 cède
      son slot au refuge (IEF) ; si le refuge est lui-même ≤ 0 → cash.

    Régime : "offensif" (tous les slots risqués), "défensif" (aucun), "mixte" sinon.
    Marque `selectionne=True` dans la table pour les actifs réellement détenus.
    """
    risques = sorted((l for l in table if l["type"] == "risque"),
                     key=lambda l: l["score"], reverse=True)
    ligne_refuge = next(l for l in table if l["type"] == "refuge")

    poids_par_slot = 1.0 / config.TOP_N
    poids: dict[str, float] = {}
    slots_defensifs = 0

    for ligne in risques[:config.TOP_N]:
        if ligne["excess"] > 0:
            poids[ligne["ticker"]] = poids.get(ligne["ticker"], 0.0) + poids_par_slot
            ligne["selectionne"] = True
        else:
            slots_defensifs += 1

    if slots_defensifs:
        poids_defensif = slots_defensifs * poids_par_slot
        if ligne_refuge["excess"] > 0:
            poids[config.ACTIF_REFUGE] = poids.get(config.ACTIF_REFUGE, 0.0) + poids_defensif
            ligne_refuge["selectionne"] = True
        else:
            poids["CASH"] = poids.get("CASH", 0.0) + poids_defensif

    if slots_defensifs == 0:
        regime = "offensif"
    elif slots_defensifs == config.TOP_N:
        regime = "defensif"
    else:
        regime = "mixte"
    return poids, regime
