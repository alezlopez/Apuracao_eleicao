"""Calibração dos priors da Parte A com 2018 e 2022 (1º -> 2º turno).

1. Variação de abstenção 1T -> 2T por região.
2. Matriz de transição por regressão ecológica de Goodman (zona eleitoral como unidade,
   proporções dos aptos, linhas somando 1, sem negativos). É inferência ecológica: dá a
   ordem de grandeza dos fluxos, não o fluxo individual. Resultado [provável], não [certo].
3. Erro por UF ao aplicar a matriz nacional a cada UF: estima o choque regional/UF.

  python src/calibrate.py   -> imprime e grava data/hist/calibracao.json
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "hist"

REGIAO = {
    **dict.fromkeys(["ac", "am", "ap", "pa", "ro", "rr", "to"], "N"),
    **dict.fromkeys(["al", "ba", "ce", "ma", "pb", "pe", "pi", "rn", "se"], "NE"),
    **dict.fromkeys(["df", "go", "ms", "mt"], "CO"),
    **dict.fromkeys(["es", "mg", "rj", "sp"], "SE"),
    **dict.fromkeys(["pr", "rs", "sc"], "S"),
    "zz": "EX",
}
ORIG = ["esq", "dir", "outros", "bn", "abst"]   # 1º turno
DEST = ["esq", "dir", "bn", "abst"]             # 2º turno


def pares(ano: int) -> pd.DataFrame:
    d = pd.read_csv(HIST / f"munzona_{ano}.csv.gz", dtype={"cd_mun": str})
    d["bn"] = d.brancos + d.nulos
    k = ["uf", "cd_mun", "zona"]
    t1 = d[d.turno == 1].set_index(k)
    t2 = d[d.turno == 2].set_index(k)
    m = t1[["aptos", *ORIG]].join(t2[DEST], rsuffix="2", how="inner")
    m = m[m.aptos > 0].reset_index()
    m["regiao"] = m.uf.map(REGIAO)
    return m


def goodman(m: pd.DataFrame) -> pd.DataFrame:
    X = m[ORIG].to_numpy(float) / m.aptos.to_numpy()[:, None]
    Y = m[[f"{c}2" for c in DEST]].to_numpy(float) / m.aptos.to_numpy()[:, None]
    w = m.aptos.to_numpy(float)
    w = w / w.sum()
    n, k = len(ORIG), len(DEST)

    def loss(t):
        r = Y - X @ t.reshape(n, k)
        return float((w[:, None] * r * r).sum()) * 1e4

    cons = [{"type": "eq", "fun": lambda t, i=i: t.reshape(n, k)[i].sum() - 1} for i in range(n)]
    t0 = np.full(n * k, 1 / k)
    res = minimize(loss, t0, method="SLSQP", bounds=[(0, 1)] * (n * k), constraints=cons,
                   options={"maxiter": 500, "ftol": 1e-12})
    return pd.DataFrame(res.x.reshape(n, k), index=ORIG, columns=DEST)


def residuo_uf(m: pd.DataFrame, T: pd.DataFrame) -> pd.DataFrame:
    g = m.groupby("uf")[[*ORIG, *[f"{c}2" for c in DEST]]].sum()
    pred = g[ORIG].to_numpy(float) @ T.to_numpy()
    p_marg = 100 * (pred[:, 1] - pred[:, 0]) / (pred[:, 0] + pred[:, 1])
    r_marg = 100 * (g.dir2 - g.esq2) / (g.dir2 + g.esq2)
    out = pd.DataFrame({"margem_prev": p_marg, "margem_real": r_marg}, index=g.index)
    out["erro"] = out.margem_real - out.margem_prev
    out["regiao"] = out.index.map(REGIAO)
    return out


def main() -> None:
    cal = {}
    pd.set_option("display.width", 160)
    for ano in (2018, 2022):
        m = pares(ano)
        print(f"\n===== {ano} =====")
        g = m.groupby("regiao")[["aptos", "abst", "abst2"]].sum()
        g.loc["BR"] = g.sum()
        g["dA_pp"] = -100 * (g.abst2 - g.abst) / g.aptos   # + = mais gente votou no 2T
        print("Variação de comparecimento 1T->2T (p.p. dos aptos):")
        print(g.dA_pp.round(2).to_string())

        T = goodman(m)
        print("\nMatriz de transição nacional (linha = voto no 1T, coluna = destino no 2T):")
        print(T.round(3).to_string())
        reg = {}
        for r, mr in m.groupby("regiao"):
            if r == "EX":
                continue
            Tr = goodman(mr)
            reg[r] = Tr.round(4).to_dict()
            o = Tr.loc["outros"]
            print(f"  {r}: outros -> esq {o.esq:.2f} dir {o.dir:.2f} bn {o.bn:.2f} abst {o.abst:.2f}")

        res = residuo_uf(m, T)
        res_ex = res.drop(index="zz", errors="ignore")
        reg_err = res_ex.groupby("regiao").erro.mean()
        print("\nErro da margem por UF usando a matriz nacional (real - previsto, p.p.):")
        print(res_ex.erro.round(2).sort_values().to_string())
        print(f"DP do erro por UF: {res_ex.erro.std():.2f} p.p. | média por região: {reg_err.round(2).to_dict()}")
        cal[ano] = {"dA_pp": g.dA_pp.round(3).to_dict(), "T_nacional": T.round(4).to_dict(),
                    "T_regional": reg, "erro_uf_dp": round(float(res_ex.erro.std()), 3),
                    "erro_regiao": reg_err.round(3).to_dict(),
                    "erro_uf": res_ex.erro.round(3).to_dict()}
    (HIST / "calibracao.json").write_text(json.dumps(cal, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
