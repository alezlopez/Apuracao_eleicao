"""Exporta os resultados do modelo em CSV para o painel publicado (data/painel/).

  python src/export_painel.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "painel"


def replay() -> None:
    serie, ufs = [], []
    root = ROOT / "data" / "snapshots" / "replay-t1-2026"
    for snap in sorted(p for p in root.iterdir() if p.is_dir()):
        r = json.loads((snap / "projecao.json").read_text())
        hora = r["tse_ht"][:5]
        serie.append({
            "hora": hora, "apurado": round(r["pct_apurado"], 2), "p_flavio": round(r["p_flavio"], 4),
            "margem_proj": round(r["margem_mediana"], 2), "lo80": round(r["margem_80"][0], 2),
            "hi80": round(r["margem_80"][1], 2), "lo95": round(r["margem_95"][0], 2), "hi95": round(r["margem_95"][1], 2),
            "margem_parcial": None if r["margem_atual"] is None else round(r["margem_atual"], 2),
            "lula_precisa": None if not np.isfinite(r["atrasado_precisa"] or np.nan) else round(r["atrasado_precisa"], 4),
        })
        for u in r["uf"]:
            ufs.append({"hora": hora, "uf": "EX" if u["uf"] == "zz" else u["uf"].upper(),
                        "apurado": round(u["pct_apurado"], 1),
                        "margem_parcial": None if pd.isna(u["margem_atual"]) else round(u["margem_atual"], 2),
                        "margem_proj": round(u["margem_proj"], 2), "p10": round(u["p10"], 2), "p90": round(u["p90"], 2),
                        "p_flavio": round(u["p_flavio"], 3)})
    s = pd.DataFrame(serie)
    s = s.drop_duplicates("hora", keep="last")   # o último snapshot (02:58) tem hora única; garante chave
    s.to_csv(OUT / "replay_serie.csv", index=False)
    pd.DataFrame(ufs).drop_duplicates(["hora", "uf"], keep="last").to_csv(OUT / "replay_uf.csv", index=False)


def backtest() -> None:
    d = pd.read_csv(ROOT / "data" / "backtest" / "resultados.csv")
    d["tipo"] = np.where(d.ordem.str.startswith("pior"), "adversaria", "realista")
    d[["caso", "ordem", "tipo", "pct", "final", "proj", "lo80", "hi80", "ingenua", "p_flavio"]].round(3).to_csv(
        OUT / "backtest_curvas.csv", index=False)
    r = d.groupby(["caso", "tipo", "pct"]).agg(
        erro_abs=("erro", lambda x: x.abs().mean()), erro_max=("erro", lambda x: x.abs().max()),
        erro_parcial=("erro_ingenuo", lambda x: x.abs().mean()), cob80=("cob80", "mean"), cob95=("cob95", "mean"),
        acerto=("acertou", "mean"), p_venc_min=("p_vencedor", "min")).reset_index()
    r.round(3).to_csv(OUT / "backtest_resumo.csv", index=False)


def parte_a() -> None:
    base = model.carregar_base()
    rows = []
    for nome in model.PRESETS:
        sim = model.simular(base, model.medias(nome))
        r = model.resumo(sim)
        rows.append({"preset": nome, "p_flavio": round(r["p_flavio"], 3), "margem": round(r["margem_mediana"], 2),
                     "lo80": round(r["margem_80"][0], 2), "hi80": round(r["margem_80"][1], 2),
                     "lo95": round(r["margem_95"][0], 2), "hi95": round(r["margem_95"][1], 2),
                     "votos": round(r["votos_mediana"])})
        if nome == "Base":
            t = model.tabela_uf(base, sim)
            t["uf"] = t.uf.str.upper().replace({"ZZ": "EX"})
            t.to_csv(OUT / "parte_a_uf.csv", index=False)
            m = sim["margem"]
            cont, bordas = np.histogram(m, np.arange(np.floor(m.min()), np.ceil(m.max()) + 0.25, 0.25))
            pd.DataFrame({"margem": ((bordas[:-1] + bordas[1:]) / 2).round(3),
                          "pct_sim": (100 * cont / len(m)).round(3)}).to_csv(OUT / "parte_a_hist.csv", index=False)
    pd.DataFrame(rows).to_csv(OUT / "parte_a_presets.csv", index=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    replay()
    backtest()
    parte_a()
    for f in sorted(OUT.glob("*.csv")):
        print(f.name, len(pd.read_csv(f)), "linhas")


if __name__ == "__main__":
    main()
