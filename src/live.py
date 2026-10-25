"""Parte B: atualização ao vivo a partir de parciais por unidade (município ou zona).

Cada unidade i tem um prior p0_i (share de Flávio entre os 2) e V0_i (válidos esperados F+L).
Com o que já foi contado, mede o swing em logit:  s_i = logit(p_obs_i) − logit(p0_i)
e ajusta um modelo hierárquico gaussiano (empirical Bayes):

  s_i = β0 + β1·lean_i + β2·porte_i + u_regiao + v_uf + ε_i

  lean_i  = logit(p0_i) − logit(p0 nacional)  → corrige o viés de ordem de chegada
  porte_i = log(aptos) padronizado             → idem (capitais chegam em outro ritmo)
  u, v    = efeitos aleatórios (encolhimento para a média nacional)
  ε_i     = ruído próprio da unidade, σe estimado dos resíduos
  + choque comum em todo o resto (sd_resto): o que falta não é amostra aleatória do que chegou

O que falta é projetado com Monte Carlo: posterior de (β,u,v), ε de cada unidade restante e
incerteza de comparecimento. NUNCA extrapola a proporção nacional parcial.

  python src/live.py --watch data/snapshots/e6258     # processa snapshots novos
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGIOES = model.REGIOES


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def expit(x):
    return 1 / (1 + np.exp(-x))


@dataclass
class Hiper:
    sd_b0: float = 0.05      # intercepto (logit; 0,02 ≈ 1 p.p. de margem)
    sd_b: float = 0.05       # inclinações (lean, porte)
    tau_reg: float = 0.03    # efeito regional
    tau_ex: float = 0.30     # efeito do exterior: chega primeiro (fuso) e tem swing próprio; amplo para
                             # não contaminar o intercepto nacional (replay t1_2026: 118 de 267 unidades às 18h10)
    tau_uf: float = 0.03     # efeito por UF
    sd_turn: float = 0.02    # incerteza log do comparecimento (nacional e por UF)
    sd_resto: float = 0.05   # choque comum no que falta (logit; ≈2,5 p.p. de margem). Backtest t1_2026:
                             # erro RMS ≈ 2 p.p. nas ordens realistas (0,04). Subido para 0,05 no dia 25/10: com a
                             # votação prorrogada até as 19h, a projeção oscilou ~5 p.p. em minutos (ordem bem torta)
    f_min: float = 0.30      # abaixo disso o choque do resto cresce com sqrt(f_min/f): poucas unidades (era 0,10;
                             # subido no dia 25/10 pelo mesmo motivo: 100% para Lula com 7,7% apurado era exagero)
                             # iniciais não representam o resto (replay t1_2026: +7,7 projetado com 1,7%, final +2,0)
    k_turn: float = 2e5      # votos de "pseudo-contagem" no encolhimento do comparecimento por UF
    inflar: float = 1.0      # multiplica a covariância posterior (calibrado no backtest)
    n_sim: int = 2000
    seed: int = 11
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- priors ----

def prior_parte_a(base_mun: pd.DataFrame, preset: str = "Base") -> pd.DataFrame:
    """Prior por município para o 2º turno 2026: médias da Parte A (sem ruído)."""
    m = model.medias(preset)
    b = base_mun.copy()
    VL, VF, VO = b.lula.astype(float), b.flavio.astype(float), b.outros.astype(float)
    BN = (b.brancos + b.nulos).astype(float)
    g = b.groupby("uf")[["lula", "flavio"]].sum()
    nat = 100 * (g.flavio.sum() - g.lula.sum()) / (g.flavio.sum() + g.lula.sum())
    lean_uf = (100 * (g.flavio - g.lula) / (g.flavio + g.lula) - nat).reindex(b.uf).to_numpy()
    tF = np.clip(m["tF"] + m["kappa"] * lean_uf / 200, 0, 1)
    tL = np.clip(m["tL"] - m["kappa"] * lean_uf / 200, 0, 1)
    F2 = m["rF"] * VF + m["dLF"] * VL + tF * VO + m["bF"] * BN
    L2 = m["rL"] * VL + m["dFL"] * VF + tL * VO + m["bL"] * BN
    return pd.DataFrame({"uid": b.cd_tse.astype(str), "uf": b.uf, "nome": b.nome,
                         "p0": F2 / (F2 + L2), "V0": F2 + L2, "aptos": b.te.astype(float)})


def unidades_de_snapshot(snap_mun: pd.DataFrame, prior: pd.DataFrame) -> pd.DataFrame:
    """Junta prior e contagem do coletor (mun.csv). frac = eleitorado das seções totalizadas / total."""
    s = snap_mun.assign(uid=snap_mun.cd_tse.astype(str).str.zfill(5))
    u = prior.merge(s[["uid", "flavio", "lula", "est", "te", "st", "ts"]], on="uid", how="left")
    u[["flavio", "lula", "est", "st"]] = u[["flavio", "lula", "est", "st"]].fillna(0)
    u["ts"] = u.ts.fillna(0)
    u["frac"] = np.where(u.te > 0, u.est / u.te.where(u.te > 0, 1), 0.0)
    return u


def prior_uf(prior_mun: pd.DataFrame) -> pd.DataFrame:
    """Agrega o prior por UF (para o plano B manual, que só tem parciais por UF)."""
    g = prior_mun.assign(F0=prior_mun.p0 * prior_mun.V0).groupby("uf").agg(F0=("F0", "sum"), V0=("V0", "sum"),
                                                                           aptos=("aptos", "sum")).reset_index()
    return pd.DataFrame({"uid": g.uf, "uf": g.uf, "nome": g.uf.str.upper(), "p0": g.F0 / g.V0, "V0": g.V0, "aptos": g.aptos})


def unidades_de_uf(snap_uf: pd.DataFrame, prior_mun: pd.DataFrame) -> pd.DataFrame:
    u = prior_uf(prior_mun).merge(snap_uf[["uf", "flavio", "lula", "est", "te"]], on="uf", how="left")
    u[["flavio", "lula", "est"]] = u[["flavio", "lula", "est"]].fillna(0)
    u["frac"] = np.where(u.te > 0, u.est / u.te.where(u.te > 0, 1), 0.0)
    return u


# ---------------------------------------------------------------- motor -----

def estimar(u: pd.DataFrame, h: Hiper = Hiper()) -> dict:
    """u: uid, uf, p0, V0, aptos, flavio, lula, frac (0..1). Retorna projeção nacional e por UF."""
    u = u.reset_index(drop=True).copy()
    u["regiao"] = u.uf.map(model.REGIAO)
    # cidades do exterior sem voto no 1º turno: prior neutro e nenhum voto esperado
    u["p0"] = u.p0.fillna(0.5)
    u["V0"] = u.V0.fillna(0)
    c = (u.flavio + u.lula).to_numpy(float)
    frac = np.clip(u.frac.to_numpy(float), 0, 1)
    p0 = u.p0.to_numpy(float)
    V0 = u.V0.to_numpy(float)
    lg0 = logit(p0)
    nat0 = logit((p0 * V0).sum() / V0.sum())
    lean = lg0 - nat0
    porte = np.log(np.maximum(u.aptos.to_numpy(float), 1))
    porte = (porte - porte.mean()) / porte.std()

    ufs = sorted(model.REGIAO)
    iu = u.uf.map({x: i for i, x in enumerate(ufs)}).to_numpy()
    ir = u.regiao.map({x: i for i, x in enumerate(REGIOES)}).to_numpy()
    nb, nr, nu = 3, len(REGIOES), len(ufs)
    P = nb + nr + nu

    obs = (c > 0) & (frac > 0)
    tau_r = [h.tau_ex if r == "EX" else h.tau_reg for r in REGIOES]
    prior_var = np.r_[[h.sd_b0 ** 2, h.sd_b ** 2, h.sd_b ** 2], np.square(tau_r), [h.tau_uf ** 2] * nu]

    def desenho(idx):
        Z = np.zeros((idx.sum() if idx.dtype == bool else len(idx), P))
        Z[:, 0] = 1
        Z[:, 1] = lean[idx]
        Z[:, 2] = porte[idx]
        rows = np.arange(Z.shape[0])
        Z[rows, nb + ir[idx]] = 1
        Z[rows, nb + nr + iu[idx]] = 1
        return Z

    mean = np.zeros(P)
    cov = np.diag(prior_var)
    sig_e = 0.10
    if obs.sum() >= 5:
        pobs = (u.flavio.to_numpy(float)[obs] + 0.5) / (c[obs] + 1)
        s = logit(pobs) - lg0[obs]
        Z = desenho(obs)
        amostral = 1 / (c[obs] * pobs * (1 - pobs))
        for _ in range(3):  # alterna estimativa de σe e da posterior
            w = 1 / (sig_e ** 2 + amostral)
            A = Z.T @ (Z * w[:, None]) + np.diag(1 / prior_var)
            cov = np.linalg.inv(A)
            mean = cov @ (Z.T @ (w * s))
            r = s - Z @ mean
            ww = c[obs] / c[obs].sum()
            sig_e = float(np.sqrt(max((ww * (r ** 2 - amostral)).sum(), 1e-4)))
        resid = np.zeros(len(u))
        resid[obs] = s - Z @ mean
    else:
        resid = np.zeros(len(u))
    cov = cov * h.inflar

    # Comparecimento: válidos contados / esperados na parte contada, por UF com encolhimento.
    esp_cont = V0 * frac
    cont_uf = np.bincount(iu, weights=c, minlength=nu)
    esp_uf = np.bincount(iu, weights=esp_cont, minlength=nu)
    rho_nat = c.sum() / esp_cont.sum() if esp_cont.sum() > 0 else 1.0
    rho_uf = (cont_uf + h.k_turn * rho_nat) / (esp_uf + h.k_turn)

    rest = V0 * (1 - frac)
    falta = rest > 0
    Zf = desenho(falta)
    rng = np.random.default_rng(h.seed)
    n = h.n_sim
    L = np.linalg.cholesky(cov + 1e-12 * np.eye(P))
    theta = mean + rng.standard_normal((n, P)) @ L.T
    # unidade parcialmente contada: metade do próprio resíduo vale para o resto dela
    eta = (lg0[falta][:, None] + Zf @ theta.T).T + 0.5 * resid[falta]
    f_apur = (u.aptos.to_numpy(float) * frac).sum() / u.aptos.sum()
    sd_resto = h.sd_resto * max(1.0, np.sqrt(h.f_min / max(f_apur, 1e-3)))
    eta = eta + rng.normal(0, sd_resto, (n, 1)) + rng.normal(0, sig_e, (n, falta.sum())).astype(np.float32)
    pf = expit(eta)
    turn = np.exp(rng.normal(0, h.sd_turn, (n, 1)) + rng.normal(0, h.sd_turn, (n, nu))[:, iu[falta]])
    R = rest[falta] * rho_uf[iu[falta]] * turn

    Fc, Lc = u.flavio.to_numpy(float), u.lula.to_numpy(float)
    F_fin = Fc.sum() + (R * pf).sum(1)
    L_fin = Lc.sum() + (R * (1 - pf)).sum(1)
    marg = 100 * (F_fin - L_fin) / (F_fin + L_fin)
    votos = F_fin - L_fin

    # Por estado e por região: as mesmas simulações, só agrupadas de outro jeito (a incerteza
    # dos estados de uma região anda junta, por isso a região não é a soma das chances dos estados).
    aptos_u = u.aptos.to_numpy(float)

    def agrupar(idx: np.ndarray, nomes: list, chave: str) -> list[dict]:
        rows = []
        idx_f = idx[falta]
        for k, x in enumerate(nomes):
            sel = idx == k
            if not sel.any():
                continue
            mk = idx_f == k
            Fu = Fc[sel].sum() + (R[:, mk] * pf[:, mk]).sum(1)
            Lu = Lc[sel].sum() + (R[:, mk] * (1 - pf[:, mk])).sum(1)
            mu = 100 * (Fu - Lu) / (Fu + Lu)
            cont = Fc[sel].sum() + Lc[sel].sum()
            apt = aptos_u[sel]
            rows.append({
                chave: x, "pct_apurado": 100 * (apt * frac[sel]).sum() / apt.sum(),
                "margem_atual": 100 * (Fc[sel].sum() - Lc[sel].sum()) / cont if cont else np.nan,
                "flavio_contado": float(Fc[sel].sum()), "lula_contado": float(Lc[sel].sum()),
                "margem_proj": float(np.median(mu)), "p10": float(np.percentile(mu, 10)),
                "p90": float(np.percentile(mu, 90)), "p_flavio": float((mu > 0).mean()),
            })
        return rows

    uf_rows = agrupar(iu, ufs, "uf")
    reg_rows = agrupar(ir, REGIOES, "regiao")

    aptos = u.aptos.to_numpy(float)
    restante_aptos = float((aptos * (1 - frac)).sum())
    lead = float(Fc.sum() - Lc.sum())
    rest_med = float(np.median(R.sum(1))) if falta.any() else 0.0
    atr = "Lula" if lead > 0 else "Flávio"
    precisa = 0.5 + abs(lead) / (2 * rest_med) if rest_med > 0 else np.nan
    q = lambda p: float(np.percentile(marg, p))
    return {
        "pct_apurado": float(100 * (aptos * frac).sum() / aptos.sum()),
        "p_flavio": float((marg > 0).mean()), "p_lula": float((marg < 0).mean()),
        "margem_mediana": q(50), "margem_80": [q(10), q(90)], "margem_95": [q(2.5), q(97.5)],
        "votos_mediana": float(np.median(votos)), "votos_80": [float(np.percentile(votos, 10)), float(np.percentile(votos, 90))],
        "margem_atual": 100 * lead / (Fc.sum() + Lc.sum()) if (Fc.sum() + Lc.sum()) else None,
        "votos_atual": lead, "restante_aptos": restante_aptos, "restante_validos_proj": rest_med,
        "decidido": bool(abs(lead) > restante_aptos), "lider_atual": "Flávio" if lead > 0 else "Lula",
        "atrasado": atr, "atrasado_precisa": precisa,
        "sigma_e": sig_e, "sd_resto": float(sd_resto), "swing_nacional_logit": float(mean[0]), "inclinacao_lean": float(mean[1]),
        "uf": uf_rows, "regioes": reg_rows,
    }


# ---------------------------------------------------------------- execução --

def processar(snap: Path, prior: pd.DataFrame, h: Hiper = Hiper()) -> dict:
    """Projeta um snapshot e grava projecao.json. Sem mun.csv (plano B manual), roda por UF."""
    if (snap / "mun.csv").exists():
        mun = pd.read_csv(snap / "mun.csv", dtype={"cd_tse": str})
        res = estimar(unidades_de_snapshot(mun, prior), h)
    else:
        res = estimar(unidades_de_uf(pd.read_csv(snap / "uf.csv"), prior), h)
    meta = json.loads((snap / "meta.json").read_text())
    res["snapshot"] = snap.name
    res["coletado_em"] = meta.get("coletado_em")
    res["tse_ht"] = meta.get("tse_ht")
    res["origem"] = meta.get("origem", "tse")
    (snap / "projecao.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def prior_para(snap_root: Path) -> pd.DataFrame:
    """Replays do 1º turno 2026 usam o 2º turno de 2022 como prior; o resto usa a Parte A."""
    cfg = snap_root / "prior.json"
    tipo = json.loads(cfg.read_text())["prior"] if cfg.exists() else "parte_a"
    if tipo == "t2_2022":
        import backtest
        return backtest.prior_mun_t2_2022()
    return prior_parte_a(pd.read_csv(ROOT / "data" / "base" / "t1_2026_mun.csv", dtype={"cd_tse": str}))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", default="data/snapshots/e6258", help="pasta com snapshots")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=15)
    a = ap.parse_args(argv)
    root = ROOT / a.watch
    prior = prior_para(root)
    while True:
        for snap in sorted(p for p in root.iterdir() if p.is_dir()):
            if (snap / "uf.csv").exists() and not (snap / "projecao.json").exists():
                r = processar(snap, prior)
                print(f"{snap.name} | apurado {r['pct_apurado']:.1f}% | P(F) {r['p_flavio']:.3f} | "
                      f"margem {r['margem_mediana']:+.2f} ({r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f})", flush=True)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
