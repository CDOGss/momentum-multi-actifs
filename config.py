"""Paramètres de la stratégie de rotation momentum multi-actifs (marche à blanc).

Stratégie « dual momentum » (Antonacci) :
  - momentum RELATIF  : chaque mois, classement des actifs risqués par performance
    passée (moyenne 3/6/12 mois), on garde les TOP_N meilleurs ;
  - momentum ABSOLU   : un actif n'est retenu que si sa performance dépasse celle
    des T-Bills (BIL). Sinon son slot bascule sur l'actif refuge (IEF), et si le
    refuge lui-même est en momentum négatif → cash. C'est la protection anti-krach.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Chemins -----------------------------------------------------------------
RACINE = Path(__file__).resolve().parent
FICHIER_PORTEFEUILLE = RACINE / "portfolio.json"
FICHIER_HISTORIQUE = RACINE / "history.json"
FICHIER_ANALYSE = RACINE / "latest_analysis.json"
FICHIER_RAPPORT = RACINE / "daily_report.md"
FICHIER_GRAPHIQUE = RACINE / "performance_chart.png"

# --- Univers d'ETF (tickers Yahoo Finance, cotations US en USD) ---------------
# Actifs RISQUÉS : classés entre eux par momentum relatif.
# TLT (duration longue) est traité comme actif risqué : il monte dans les krachs
# déflationnistes mais peut lourdement chuter quand les taux montent (2022).
UNIVERS_RISQUE = {
    "SPY": "S&P 500 (actions US)",
    "QQQ": "Nasdaq 100 (tech US)",
    "EFA": "Actions internationales développées",
    "EEM": "Actions émergentes",
    "GLD": "Or",
    "DBC": "Matières premières (panier large)",
    "VNQ": "Immobilier coté US (REITs)",
    "TLT": "Obligations US 20+ ans",
}

# Actif REFUGE : reçoit les slots des actifs recalés par le momentum absolu.
ACTIF_REFUGE = "IEF"
NOM_REFUGE = "Obligations US 7-10 ans (refuge)"

# Taux « sans risque » : seuil du momentum absolu (T-Bills 1-3 mois).
ACTIF_SANS_RISQUE = "BIL"
NOM_SANS_RISQUE = "T-Bills 1-3 mois (seuil momentum absolu)"

TICKER_VIX = "^VIX"

NOMS = {**UNIVERS_RISQUE, ACTIF_REFUGE: NOM_REFUGE, ACTIF_SANS_RISQUE: NOM_SANS_RISQUE}

# --- Règles de la stratégie ----------------------------------------------------
TOP_N = 3  # nombre d'actifs détenus (poids égaux)

# Score momentum = moyenne pondérée des rendements sur ~3, 6 et 12 mois de bourse
# (63/126/252 jours ouvrés). Le mélange de plusieurs horizons rend le score plus
# stable qu'un 12 mois sec, sans en changer la nature.
PERIODES_MOMENTUM = {63: 1 / 3, 126: 1 / 3, 252: 1 / 3}

CAPITAL_INITIAL = 10_000.0  # USD (virtuel)

# Frais estimés par ORDRE (achat ou vente), en % du montant traité. Les ETF de
# l'univers sont très liquides (spread ~1-2 pb) : 0.05 % est déjà conservateur.
COUT_TRANSACTION_PCT = float(os.getenv("COUT_TRANSACTION_PCT", "0.05"))

# En-dessous de ce montant, un ajustement de position n'est pas exécuté
# (évite les micro-ordres sans intérêt lors des rebalancements).
SEUIL_ORDRE_USD = 50.0

# --- Benchmarks (sans frais, buy & hold / rebalancé mensuellement) -------------
BENCH_ACTIONS = "SPY"                # 100 % actions US
BENCH_6040 = {"SPY": 0.60, "IEF": 0.40}  # portefeuille 60/40 classique

# --- IA (Gemini : rôle d'ANALYSTE, jamais de décideur) --------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")

# --- Flux d'actualité macro (RSS gratuits, sans clé) ----------------------------
FLUX_ACTU = [
    "https://news.google.com/rss/search?q=Fed+taux+inflation+when:2d&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=march%C3%A9s+actions+Wall+Street+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=or+p%C3%A9trole+mati%C3%A8res+premi%C3%A8res+when:2d&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=obligations+taux+souverains+when:2d&hl=fr&gl=FR&ceid=FR:fr",
    "https://www.lesechos.fr/rss/bourse",
]
TITRES_PAR_FLUX = 6
