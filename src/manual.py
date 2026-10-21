"""Plano B: transforma parciais digitados por UF em um snapshot no mesmo formato
do coletor (uf.csv + meta.json), para o modelo não precisar saber a origem.

Preencha data/manual/parciais_uf.csv (uf, pct_secoes, lula, flavio, brancos,
nulos; deixe em branco as UFs sem dado) e rode:
  python src/manual.py
Sem dado por município, a Parte B só roda no nível UF.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE_UF = ROOT / "data" / "base" / "t1_2026_uf.csv"
INPUT = ROOT / "data" / "manual" / "parciais_uf.csv"
OUT_DIR = ROOT / "data" / "snapshots" / "e6258-manual"


def main() -> int:
    base = pd.read_csv(BASE_UF)[["uf", "ts", "te"]]
    p = pd.read_csv(INPUT).dropna(subset=["pct_secoes", "lula", "flavio"])
    if p.empty:
        print("nenhuma UF preenchida em", INPUT.relative_to(ROOT))
        return 1
    df = base.merge(p, on="uf", how="left").fillna({"pct_secoes": 0, "lula": 0, "flavio": 0, "brancos": 0, "nulos": 0})
    # Seções totais do 2º turno ≈ 1º turno; o coletor usa o valor exato quando funciona.
    df["st"] = (df.ts * df.pct_secoes / 100).round().astype(int)
    for c in ["lula", "flavio", "brancos", "nulos"]:
        df[c] = df[c].astype(int)
    df["validos"] = df.lula + df.flavio
    df["outros"] = 0
    df["est"] = (df.te * df.pct_secoes / 100).round().astype(int)
    df["comp"] = df["abst"] = 0  # desconhecido na entrada manual
    df["dt"] = df["ht"] = ""

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / stamp
    out.mkdir(parents=True, exist_ok=True)
    cols = ["uf", "ts", "st", "te", "est", "comp", "abst", "validos", "brancos", "nulos", "dt", "ht", "lula", "flavio", "outros"]
    df[cols].to_csv(out / "uf.csv", index=False)
    br = {c: int(df[c].sum()) for c in ["ts", "st", "te", "est", "validos", "brancos", "nulos", "lula", "flavio"]}
    meta = {"ele": "6258", "origem": "manual", "coletado_em": datetime.now().isoformat(timespec="seconds"), "br": br}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"{len(p)} UFs | seções {100 * br['st'] / br['ts']:.2f}% | Lula {br['lula']:,} x Flávio {br['flavio']:,} -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
