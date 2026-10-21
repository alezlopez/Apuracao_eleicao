"""Parte A: cenário pré-apuração por UF com Monte Carlo.

Para cada UF s (27 + exterior), com o 1º turno V_L, V_F, V_O (outros), V_BN (brancos+nulos), aptos A:

  L2 = rL·V_L + dFL·V_F + tL_s·V_O + bL·V_BN + mL_s·M_s
  F2 = rF·V_F + dLF·V_L + tF_s·V_O + bF·V_BN + (1−mL_s)·M_s

  tF_s = tF + dev_reg + κ·lean_s/200,  tL_s = tL + dev_reg' − κ·lean_s/200
  lean_s = margem F−L (2 candidatos) do 1T na UF menos a nacional, em p.p.
  M_s    = ΔA_regiao/100 · A_s · 0,95  (eleitor marginal; 0,95 = fração válida típica)
  mL_s   = share de Lula nos 2 finalistas do 1T na UF + ruído

Depois aplica choques na margem (p.p. de F−L): nacional + regional + UF.
Margem sempre = F − L em p.p. dos válidos; positivo = Flávio à frente.

Calibração: src/calibrate.py (2018 e 2022). Ver PARAMS para a origem de cada prior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE_UF = ROOT / "data" / "base" / "t1_2026_uf.csv"

REGIOES = ["N", "NE", "CO", "SE", "S", "EX"]
REGIAO = {
    **dict.fromkeys(["ac", "am", "ap", "pa", "ro", "rr", "to"], "N"),
    **dict.fromkeys(["al", "ba", "ce", "ma", "pb", "pe", "pi", "rn", "se"], "NE"),
    **dict.fromkeys(["df", "go", "ms", "mt"], "CO"),
    **dict.fromkeys(["es", "mg", "rj", "sp"], "SE"),
    **dict.fromkeys(["pr", "rs", "sc"], "S"),
    "zz": "EX",
}


@dataclass(frozen=True)
class P:
    media: float
    dp: float
    lo: float      # limite do slider
    hi: float
    rotulo: str
    origem: str    # [certo] / [provável] / [suposição] + fonte


PARAMS: dict[str, P] = {
    "rL": P(0.99, 0.01, 0.90, 1.00, "Eleitores de Lula no 1º turno que votam nele de novo",
            "[provável] Nas urnas de 2018 e 2022, praticamente 100% repetiram o voto (estimativa a partir das zonas eleitorais)."),
    "rF": P(0.99, 0.01, 0.90, 1.00, "Eleitores de Flávio no 1º turno que votam nele de novo",
            "[provável] Nas urnas de 2018 e 2022, praticamente 100% repetiram o voto (estimativa a partir das zonas eleitorais)."),
    "dLF": P(0.005, 0.005, 0.0, 0.05, "Eleitores de Lula que trocam para Flávio",
             "[suposição] Os dados das urnas não conseguem separar trocas nos dois sentidos; usamos um valor pequeno."),
    "dFL": P(0.005, 0.005, 0.0, 0.05, "Eleitores de Flávio que trocam para Lula",
             "[suposição] Os dados das urnas não conseguem separar trocas nos dois sentidos; usamos um valor pequeno."),
    "tF": P(0.46, 0.05, 0.20, 0.70, "Eleitores de outros candidatos que vão para Flávio",
            "[pesquisa] Datafolha de 6 e 7/10: 46%. Em 2022, as urnas indicam 55% para Bolsonaro."),
    "tL": P(0.32, 0.05, 0.10, 0.60, "Eleitores de outros candidatos que vão para Lula",
            "[pesquisa] Datafolha de 6 e 7/10: 32%. Em 2022, as urnas indicam 33% para Lula."),
    "t_reg_dp": P(0.03, 0.0, 0.0, 0.10, "Quanto esse destino varia de uma região para outra",
                  "[suposição] Variação típica entre regiões."),
    "kappa": P(0.70, 0.15, 0.0, 1.5, "Força do efeito “quem lidera no estado ganha mais”",
               "[provável] No 2º turno, os votos que mudam de dono vão mais para quem já lidera no estado. "
               "Medido em 2018 (0,57) e 2022 (0,85)."),
    "bF": P(0.14, 0.03, 0.0, 0.40, "Quem votou branco ou nulo e agora vota em Flávio",
            "[provável] Em 2018 e 2022, cerca de 15% dos brancos e nulos foram para a direita no 2º turno."),
    "bL": P(0.10, 0.03, 0.0, 0.40, "Quem votou branco ou nulo e agora vota em Lula",
            "[provável] Em 2018, cerca de 11%; em 2022, cerca de 8% foram para o PT no 2º turno."),
    "dA_N": P(0.0, 0.75, -4, 4, "Comparecimento no Norte (pontos a mais ou a menos)",
              "[provável] Do 1º para o 2º turno: 2018, −3,5; 2022, −2,0."),
    "dA_NE": P(0.0, 0.75, -4, 4, "Comparecimento no Nordeste (pontos a mais ou a menos)",
               "[provável] Do 1º para o 2º turno: 2018, −1,1; 2022, +0,2."),
    "dA_CO": P(0.0, 0.75, -4, 4, "Comparecimento no Centro-Oeste (pontos a mais ou a menos)",
               "[provável] Do 1º para o 2º turno: 2018, −1,3; 2022, +0,7."),
    "dA_SE": P(0.0, 0.75, -4, 4, "Comparecimento no Sudeste (pontos a mais ou a menos)",
               "[provável] Do 1º para o 2º turno: 2018, −0,5; 2022, +0,7."),
    "dA_S": P(0.0, 0.75, -4, 4, "Comparecimento no Sul (pontos a mais ou a menos)",
              "[provável] Do 1º para o 2º turno: 2018, −0,5; 2022, +0,7."),
    "dA_EX": P(0.0, 0.75, -4, 4, "Comparecimento no exterior (pontos a mais ou a menos)",
               "[provável] Do 1º para o 2º turno: 2018, −0,3; 2022, +0,9."),
    "mL_dp": P(0.05, 0.0, 0.0, 0.20, "Incerteza sobre o voto de quem passa a votar ou deixa de votar",
               "[suposição] Quem aparece só no 2º turno vota parecido com sua cidade, com essa margem de erro."),
    "vies_nac": P(0.0, 0.0, -5, 5, "Erro geral a favor de Flávio (pontos; negativo = a favor de Lula)",
                  "Cenário: 0 = sem erro sistemático. As pesquisas subestimaram a direita em 2022 e no 1º turno de 2026."),
    "sigma_nac": P(2.0, 0.0, 0.0, 5.0, "Incerteza nacional (pontos)",
                   "[provável] Aplicar a pesquisa de transferência a 2022 teria errado o resultado em 2,1 pontos."),
    "sigma_reg": P(0.8, 0.0, 0.0, 4.0, "Incerteza por região (pontos)",
                   "[provável] Em 2022, o erro típico por estado foi de 1,1 ponto."),
    "sigma_uf": P(0.8, 0.0, 0.0, 4.0, "Incerteza por estado (pontos)",
                  "[provável] Em 2022, o erro típico por estado foi de 1,1 ponto."),
}

PRESETS: dict[str, dict[str, float]] = {
    "Base": {},
    "Vento a favor de Flávio": {"tF": 0.55, "tL": 0.30, "rL": 0.98, "vies_nac": 1.0},
    "Vento a favor de Lula": {"tF": 0.40, "tL": 0.38, "rF": 0.98, "vies_nac": -1.0},
    "Nordeste vai mais às urnas": {"dA_NE": 2.0},
    "Sudeste falta mais": {"dA_SE": -2.0},
    "Repete 2022": {"tF": 0.55, "tL": 0.33, "bF": 0.15, "bL": 0.08, "kappa": 0.85},
}


def carregar_base(path: Path = BASE_UF) -> pd.DataFrame:
    """Tabela por UF do 1º turno no formato do coletor (lula, flavio, outros, brancos, nulos, te)."""
    u = pd.read_csv(path)
    u["regiao"] = u.uf.map(REGIAO)
    return u


def medias(preset: str = "Base", **override) -> dict[str, float]:
    m = {k: p.media for k, p in PARAMS.items()}
    m.update(PRESETS[preset])
    m.update(override)
    return m


def _draw(rng, mean, sd, n, lo=-np.inf, hi=np.inf):
    x = rng.normal(mean, sd, n) if sd > 0 else np.full(n, float(mean))
    return np.clip(x, lo, hi)


def simular(base: pd.DataFrame, m: dict[str, float], n: int = 20000, seed: int = 7,
            fixos: dict[str, float] | None = None) -> dict:
    """Roda o Monte Carlo. `m` = médias (veja medias()); `fixos` trava parâmetros sem ruído."""
    fixos = fixos or {}
    rng = np.random.default_rng(seed)
    dp = {k: (0.0 if k in fixos else p.dp) for k, p in PARAMS.items()}
    mm = {**m, **fixos}

    VL, VF, VO = (base[c].to_numpy(float) for c in ("lula", "flavio", "outros"))
    BN = (base.brancos + base.nulos).to_numpy(float)
    A = base.te.to_numpy(float)
    reg = base.regiao.map({r: i for i, r in enumerate(REGIOES)}).to_numpy()
    nat = 100 * (VF.sum() - VL.sum()) / (VF.sum() + VL.sum())
    lean = 100 * (VF - VL) / (VF + VL) - nat
    shareL = VL / (VL + VF)
    S, R = len(base), len(REGIOES)

    rL = _draw(rng, mm["rL"], dp["rL"], n, 0, 1)[:, None]
    rF = _draw(rng, mm["rF"], dp["rF"], n, 0, 1)[:, None]
    dLF = np.minimum(_draw(rng, mm["dLF"], dp["dLF"], n, 0, 1)[:, None], 1 - rL)
    dFL = np.minimum(_draw(rng, mm["dFL"], dp["dFL"], n, 0, 1)[:, None], 1 - rF)
    kappa = _draw(rng, mm["kappa"], dp["kappa"], n, 0)[:, None]
    tsd = mm["t_reg_dp"]
    tF = _draw(rng, mm["tF"], dp["tF"], n)[:, None] + rng.normal(0, tsd, (n, R))[:, reg] + kappa * lean / 200
    tL = _draw(rng, mm["tL"], dp["tL"], n)[:, None] + rng.normal(0, tsd, (n, R))[:, reg] - kappa * lean / 200
    tF, tL = np.clip(tF, 0, 1), np.clip(tL, 0, 1)
    excesso = np.maximum(tF + tL, 1)
    tF, tL = tF / excesso, tL / excesso
    bF = _draw(rng, mm["bF"], dp["bF"], n, 0, 1)[:, None]
    bL = np.minimum(_draw(rng, mm["bL"], dp["bL"], n, 0, 1)[:, None], 1 - bF)

    dA = np.column_stack([_draw(rng, mm[f"dA_{r}"], dp[f"dA_{r}"], n) for r in REGIOES])[:, reg]
    M = dA / 100 * A * 0.95
    mL = np.clip(shareL + rng.normal(0, mm["mL_dp"], (n, S)), 0, 1)

    L2 = rL * VL + dFL * VF + tL * VO + bL * BN + mL * M
    F2 = rF * VF + dLF * VL + tF * VO + bF * BN + (1 - mL) * M
    L2, F2 = np.maximum(L2, 0), np.maximum(F2, 0)
    V2 = L2 + F2

    choque = (mm["vies_nac"] + rng.normal(0, mm["sigma_nac"], (n, 1))
              + rng.normal(0, mm["sigma_reg"], (n, R))[:, reg]
              + rng.normal(0, mm["sigma_uf"], (n, S)))
    shift = choque / 200 * V2          # +x p.p. na margem = x/2 p.p. de cada lado
    F2, L2 = F2 + shift, L2 - shift

    margem_uf = 100 * (F2 - L2) / (F2 + L2)
    votos = F2.sum(1) - L2.sum(1)
    margem = 100 * votos / (F2.sum(1) + L2.sum(1))
    return {"margem": margem, "votos": votos, "margem_uf": margem_uf, "validos": V2.sum(1),
            "uf": base.uf.to_numpy()}


def resumo(sim: dict) -> dict:
    m, v = sim["margem"], sim["votos"]
    q = lambda x, p: float(np.percentile(x, p))
    return {
        "p_flavio": float((m > 0).mean()), "p_lula": float((m < 0).mean()),
        "margem_mediana": q(m, 50), "margem_80": (q(m, 10), q(m, 90)), "margem_95": (q(m, 2.5), q(m, 97.5)),
        "votos_mediana": q(v, 50), "votos_80": (q(v, 10), q(v, 90)),
    }


def tabela_uf(base: pd.DataFrame, sim: dict) -> pd.DataFrame:
    mu = sim["margem_uf"]
    t1 = 100 * (base.flavio - base.lula) / (base.flavio + base.lula)
    return pd.DataFrame({
        "uf": base.uf, "margem_1T": t1.round(2),
        "margem_proj": np.median(mu, 0).round(2),
        "p10": np.percentile(mu, 10, 0).round(2), "p90": np.percentile(mu, 90, 0).round(2),
        "p_flavio": (mu > 0).mean(0).round(3),
    })


def tornado(base: pd.DataFrame, m: dict[str, float], n: int = 8000, seed: int = 7) -> pd.DataFrame:
    """Quanto P(F) muda quando cada parâmetro vai a média ± 1 DP (ou ±25% da faixa se DP=0).
    Usa a mesma semente em todas as rodadas (números aleatórios comuns)."""
    base_p = resumo(simular(base, m, n, seed))["p_flavio"]
    rows = []
    for k, p in PARAMS.items():
        delta = p.dp if p.dp > 0 else 0.25 * (p.hi - p.lo) / 2
        lo, hi = max(p.lo, m[k] - delta), min(p.hi, m[k] + delta)
        pl = resumo(simular(base, {**m, k: lo}, n, seed))["p_flavio"]
        ph = resumo(simular(base, {**m, k: hi}, n, seed))["p_flavio"]
        rows.append({"param": k, "rotulo": p.rotulo, "valor_lo": lo, "valor_hi": hi,
                     "p_lo": pl, "p_hi": ph, "amplitude": abs(ph - pl)})
    out = pd.DataFrame(rows).sort_values("amplitude", ascending=False)
    out.attrs["p_base"] = base_p
    return out


def main() -> None:
    base = carregar_base()
    for nome in PRESETS:
        r = resumo(simular(base, medias(nome)))
        print(f"{nome:28s} P(F)={r['p_flavio']:.3f}  margem {r['margem_mediana']:+.2f} p.p. "
              f"(80%: {r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f}; 95%: {r['margem_95'][0]:+.2f} a {r['margem_95'][1]:+.2f}) "
              f"votos {r['votos_mediana']:+,.0f}")
    m = medias()
    print("\nPor UF (Base):")
    print(tabela_uf(base, simular(base, m)).to_string(index=False))
    t = tornado(base, m)
    print(f"\nTornado (P(F) base = {t.attrs['p_base']:.3f}):")
    print(t[["rotulo", "valor_lo", "valor_hi", "p_lo", "p_hi", "amplitude"]].round(3).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
