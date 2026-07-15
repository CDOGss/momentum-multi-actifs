"""Backtest mensuel de la stratégie — outil local, jamais exécuté par le bot.

Réutilise exactement les mêmes fonctions que la production (momentum.py) :
à chaque fin de mois, le classement est calculé sur l'historique disponible à
cette date, puis les poids sont tenus jusqu'à la fin de mois suivante.

Usage :  python backtest.py
Sortie : métriques en console + backtest_chart.png
"""
from __future__ import annotations

import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config
import momentum


def fins_de_mois(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Dernière séance de chaque mois présent dans l'index."""
    serie = pd.Series(index, index=index)
    return list(serie.groupby([index.year, index.month]).last())


def rendement(prix: pd.DataFrame, ticker: str, debut, fin) -> float:
    s = prix[ticker].dropna()
    return float(s.asof(fin) / s.asof(debut) - 1.0)


def metriques(courbe: pd.Series) -> dict:
    rendements = courbe.pct_change().dropna()
    annees = (courbe.index[-1] - courbe.index[0]).days / 365.25
    cagr = (courbe.iloc[-1] / courbe.iloc[0]) ** (1 / annees) - 1
    vol = rendements.std() * math.sqrt(12)
    creux = (courbe / courbe.cummax() - 1).min()
    return {"CAGR": cagr, "Volatilité": vol,
            "Sharpe": cagr / vol if vol else float("nan"), "Max drawdown": creux}


def executer_backtest():
    tickers = list(config.UNIVERS_RISQUE) + [config.ACTIF_REFUGE, config.ACTIF_SANS_RISQUE]
    print(f"Téléchargement de l'historique complet ({len(tickers)} ETF)...")
    prix = momentum.telecharger_prix(tickers, periode="max")

    mois = fins_de_mois(prix.index)
    # Démarrage : première fin de mois où TOUS les tickers ont 12 mois d'historique.
    debut = next(d for d in mois
                 if all(prix[t].loc[:d].dropna().shape[0] > 252 for t in tickers))
    mois = [d for d in mois if d >= debut]
    print(f"Backtest de {mois[0]:%Y-%m} à {mois[-1]:%Y-%m} "
          f"({len(mois)} mois, frais {config.COUT_TRANSACTION_PCT}%/ordre)")

    valeurs = {"bot": [100.0], "spy": [100.0], "b6040": [100.0]}
    dates = [mois[0]]
    poids_precedents: dict[str, float] = {}
    regimes = []

    for d, d_suivant in zip(mois[:-1], mois[1:]):
        table = momentum.table_momentum(prix.loc[:d])
        poids, regime = momentum.portefeuille_cible(table)
        regimes.append(regime)

        # Frais sur les écarts de poids par rapport au mois précédent.
        rotation = sum(abs(poids.get(t, 0) - poids_precedents.get(t, 0))
                       for t in set(poids) | set(poids_precedents))
        frais = rotation * config.COUT_TRANSACTION_PCT / 100.0

        r_bot = sum(w * (rendement(prix, config.ACTIF_SANS_RISQUE, d, d_suivant) if t == "CASH"
                         else rendement(prix, t, d, d_suivant))
                    for t, w in poids.items())
        valeurs["bot"].append(valeurs["bot"][-1] * (1 + r_bot - frais))
        valeurs["spy"].append(valeurs["spy"][-1] * (1 + rendement(prix, "SPY", d, d_suivant)))
        r_6040 = sum(w * rendement(prix, t, d, d_suivant) for t, w in config.BENCH_6040.items())
        valeurs["b6040"].append(valeurs["b6040"][-1] * (1 + r_6040))
        dates.append(d_suivant)
        poids_precedents = poids

    courbes = {nom: pd.Series(v, index=dates) for nom, v in valeurs.items()}

    print(f"\nRépartition des régimes : offensif {regimes.count('offensif')} mois, "
          f"mixte {regimes.count('mixte')}, défensif {regimes.count('defensif')}")
    print(f"\n{'':<14}{'Momentum':>12}{'SPY':>12}{'60/40':>12}")
    m = {nom: metriques(c) for nom, c in courbes.items()}
    for cle in ["CAGR", "Volatilité", "Sharpe", "Max drawdown"]:
        fmt = (lambda v: f"{v:.2f}") if cle == "Sharpe" else (lambda v: f"{v*100:+.1f}%")
        print(f"{cle:<14}{fmt(m['bot'][cle]):>12}{fmt(m['spy'][cle]):>12}{fmt(m['b6040'][cle]):>12}")

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(courbes["bot"], label="Rotation momentum", color="royalblue", linewidth=2)
    ax.plot(courbes["spy"], label="S&P 500 (SPY)", color="darkorange", linewidth=1.5, linestyle="--")
    ax.plot(courbes["b6040"], label="60/40", color="seagreen", linewidth=1.5, linestyle=":")
    ax.set_yscale("log")
    ax.set_title("Backtest — rotation momentum multi-actifs vs benchmarks (échelle log)")
    ax.legend()
    ax.grid(True, linestyle=":", alpha=0.6)
    plt.tight_layout()
    plt.savefig("backtest_chart.png", dpi=110)
    print("\nGraphique : backtest_chart.png")


if __name__ == "__main__":
    executer_backtest()
