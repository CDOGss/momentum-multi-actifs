"""Génération du graphique de performance et du rapport quotidien markdown."""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config


def _charger(chemin, defaut):
    if chemin.exists():
        try:
            return json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:
            pass
    return defaut


def generer_graphique():
    """Courbes base 100 : stratégie momentum vs SPY vs 60/40."""
    historique = _charger(config.FICHIER_HISTORIQUE, [])
    if not historique:
        return

    capital = config.CAPITAL_INITIAL
    dates = [s["date"][5:] for s in historique]  # MM-DD
    base100 = lambda cle: [s[cle] / capital * 100 for s in historique]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(dates, base100("nav"), label="Rotation momentum (bot)",
            color="royalblue", linewidth=2.2, marker="o", markersize=3)
    ax.plot(dates, base100("bench_spy"), label="S&P 500 (SPY)",
            color="darkorange", linewidth=1.8, linestyle="--")
    ax.plot(dates, base100("bench_6040"), label="60/40 (SPY/IEF)",
            color="seagreen", linewidth=1.8, linestyle=":")
    ax.axhline(100, color="grey", linewidth=0.8, alpha=0.6)

    # Marqueurs des rotations mensuelles.
    for i, s in enumerate(historique):
        if s.get("rebalance"):
            ax.axvline(i, color="crimson", alpha=0.25, linewidth=1)

    ax.set_title("Momentum multi-actifs — performance base 100 (marche à blanc)")
    ax.set_ylabel("Base 100")
    ax.legend()
    ax.grid(True, linestyle=":", alpha=0.6)
    if len(dates) > 20:
        pas = max(1, len(dates) // 20)
        ax.set_xticks(range(0, len(dates), pas))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(config.FICHIER_GRAPHIQUE, dpi=110)
    plt.close()


def generer_rapport_markdown():
    historique = _charger(config.FICHIER_HISTORIQUE, [])
    if not historique:
        return
    s = historique[-1]
    capital = config.CAPITAL_INITIAL
    perf = lambda v: (v / capital - 1) * 100

    lignes = [f"# 🧭 Rotation momentum multi-actifs — {s['date']}", ""]

    lignes += [
        "## 💼 Situation",
        f"- **Valeur du portefeuille : {s['nav']:,.2f} $** ({perf(s['nav']):+.2f}% depuis le départ)",
        f"- Benchmark S&P 500 : {perf(s['bench_spy']):+.2f}% — Benchmark 60/40 : {perf(s['bench_6040']):+.2f}%",
        f"- Régime mécanique : **{s['regime_strategie']}** — VIX : {s.get('vix') or '?'}",
        f"- Frais cumulés depuis le départ : {s.get('frais_cumules', 0):,.2f} $",
        "",
    ]

    if s.get("rebalance"):
        lignes.append("## 🔄 Rotation mensuelle exécutée")
        if s["trades"]:
            for t in s["trades"]:
                emoji = "🟢" if t["sens"] == "achat" else "🔴"
                lignes.append(f"- {emoji} **{t['sens'].capitalize()} {t['ticker']}** : "
                              f"{t['montant']:,.2f} $ à {t['prix']:.2f} $ (frais {t['frais']:.2f} $)")
        else:
            lignes.append("- Aucun ordre : le portefeuille collait déjà à la cible.")
        lignes.append("")

    lignes.append("## 📌 Positions")
    if s["positions"]:
        lignes.append("| ETF | Nom | Valeur | Prix | Prix de revient |")
        lignes.append("|---|---|---:|---:|---:|")
        for p in s["positions"]:
            lignes.append(f"| **{p['ticker']}** | {p['nom']} | {p['valeur']:,.2f} $ "
                          f"| {p['prix']:.2f} $ | {p['prix_revient']:.2f} $ |")
    else:
        lignes.append("*100 % cash (régime défensif).*")
    lignes.append("")

    lignes.append("## 📊 Classement momentum du jour")
    lignes.append("| Rang | ETF | Score | 3 mois | 6 mois | 12 mois | Momentum absolu |")
    lignes.append("|---|---|---:|---:|---:|---:|:---:|")
    tries = sorted(s["momentum"], key=lambda l: (l["rang"] is None, l["rang"] or 0))
    for l in tries:
        rang = f"#{l['rang']}" if l["rang"] else "refuge"
        detenu = " 📌" if l["selectionne"] else ""
        absolu = "✅" if l["excess"] > 0 else "❌"
        lignes.append(f"| {rang} | **{l['ticker']}**{detenu} | {l['score']*100:+.1f}% "
                      f"| {l['r3m']*100:+.1f}% | {l['r6m']*100:+.1f}% | {l['r12m']*100:+.1f}% | {absolu} |")
    lignes += ["", "📌 = détenu — ✅/❌ = momentum absolu vs T-Bills (BIL)", ""]

    ia = s.get("ia")
    if ia:
        lignes += [
            "## 🧠 L'œil de l'analyste (IA)",
            f"**{ia.get('titre', '')}** — régime perçu : `{ia.get('regime', '?')}`",
            "",
            ia.get("commentaire", ""),
            "",
            "**Risques :**",
        ]
        lignes += [f"- ⚠️ {r}" for r in ia.get("risques", [])]
        lignes.append("")
        lignes.append("**À surveiller :**")
        lignes += [f"- 👁️ {r}" for r in ia.get("a_surveiller", [])]
        lignes.append("")

    lignes.append("---")
    lignes.append("*Rapport généré automatiquement — expérience à blanc, aucun argent réel, "
                  "ceci n'est pas un conseil en investissement.*")

    config.FICHIER_RAPPORT.write_text("\n".join(lignes), encoding="utf-8")


if __name__ == "__main__":
    generer_graphique()
    generer_rapport_markdown()
