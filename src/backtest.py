"""Backtest da Parte B e gerador de replay para o ensaio geral.

Casos (unidade = zona eleitoral, contada inteira no horário da sua última totalização):
  t2_2022  2º turno 2022 (Bolsonaro = "F", Lula = "L"). Prior: 1º turno 2022 por zona com os
           fluxos da Parte A 2026 (46/32), que sabidamente erram 2022 em ~2 p.p.: teste de prior ruim.
  t1_2026  1º turno 2026, disputa Flávio x Lula (só os 2). Prior: 2º turno 2022 por município.
           Chegada muito enviesada (Flávio +23 com 10% apurado; final +2).

Ordens de chegada: real (horário da zona), aleatória (5 sementes), porte (maiores/menores primeiro),
pior_F (redutos do Flávio primeiro) e pior_L (redutos do Lula primeiro).

  python src/backtest.py               -> data/backtest/resultados.csv + resumo no terminal
  python src/backtest.py --replay      -> data/snapshots/replay-t1-2026/ (snapshots p/ o painel)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import live  # noqa: E402
import model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "hist"
OUT = ROOT / "data" / "backtest"
CHECK = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95]


def _hist(ano: int) -> pd.DataFrame:
    return pd.read_csv(HIST / f"munzona_{ano}.csv.gz", dtype={"cd_mun": str}, parse_dates=["ult_tot"])


def prior_mun_t2_2022() -> pd.DataFrame:
    """Prior por município 2026 = share da direita no 2º turno 2022; V0 = aptos 2026 × taxa de válidos (F+L) 2022."""
    base = pd.read_csv(ROOT / "data" / "base" / "t1_2026_mun.csv", dtype={"cd_tse": str})
    d = _hist(2022)
    g = d[d.turno == 2].groupby("cd_mun")[["esq", "dir", "aptos"]].sum()
    g["p0"] = g.dir / (g.esq + g.dir)
    g["taxa"] = (g.esq + g.dir) / g.aptos
    b = base.assign(uid=base.cd_tse.str.zfill(5)).join(g[["p0", "taxa"]], on="uid")
    uf_med = b.groupby("uf")[["p0", "taxa"]].transform("median")
    b[["p0", "taxa"]] = b[["p0", "taxa"]].fillna(uf_med)
    return pd.DataFrame({"uid": b.uid, "uf": b.uf, "nome": b.nome, "p0": b.p0,
                         "V0": b.te * b.taxa, "aptos": b.te.astype(float)})


def caso_t2_2022() -> pd.DataFrame:
    d = _hist(2022)
    k = ["uf", "cd_mun", "zona"]
    t1 = d[d.turno == 1].set_index(k)
    t2 = d[d.turno == 2].set_index(k)
    m = model.medias("Base")
    VL, VF, VO = t1.esq, t1.dir, t1.outros
    BN = t1.brancos + t1.nulos
    g = t1.groupby("uf")[["esq", "dir"]].sum()
    nat = 100 * (g.dir.sum() - g.esq.sum()) / g[["esq", "dir"]].to_numpy().sum()
    lean = (100 * (g.dir - g.esq) / (g.dir + g.esq) - nat).reindex(t1.index.get_level_values("uf")).to_numpy()
    tF = np.clip(m["tF"] + m["kappa"] * lean / 200, 0, 1)
    tL = np.clip(m["tL"] - m["kappa"] * lean / 200, 0, 1)
    F2 = m["rF"] * VF + m["dLF"] * VL + tF * VO + m["bF"] * BN
    L2 = m["rL"] * VL + m["dFL"] * VF + tL * VO + m["bL"] * BN
    u = pd.DataFrame({"p0": F2 / (F2 + L2), "V0": F2 + L2}).join(
        t2[["aptos", "secoes", "esq", "dir", "ult_tot"]], how="inner").reset_index()
    u["p0"] = u.p0.fillna(0.5)   # zonas do exterior sem voto no 1º turno
    u["V0"] = u.V0.fillna(0)
    return u.rename(columns={"dir": "F", "esq": "L"}).assign(uid=lambda x: x.cd_mun + "-" + x.zona.astype(str))


def caso_t1_2026() -> pd.DataFrame:
    d = _hist(2026)
    z = d[d.turno == 1].copy()
    pm = prior_mun_t2_2022().set_index("uid")
    z = z.join(pm[["p0"]], on="cd_mun")
    taxa = (pm.V0 / pm.aptos)
    z["V0"] = z.aptos * z.cd_mun.map(taxa)
    z["p0"] = z.p0.fillna(z.groupby("uf").p0.transform("median"))
    z["V0"] = z.V0.fillna(z.aptos * 0.85)
    z = z.rename(columns={"dir": "F", "esq": "L"})
    return z.assign(uid=lambda x: x.cd_mun + "-" + x.zona.astype(str))[
        ["uid", "uf", "cd_mun", "zona", "p0", "V0", "aptos", "secoes", "F", "L", "ult_tot"]]


def ordens(u: pd.DataFrame) -> dict[str, np.ndarray]:
    p = u.F / (u.F + u.L).where(u.F + u.L > 0, 1)
    o = {
        "real": np.argsort(u.ult_tot.to_numpy(), kind="stable"),
        "porte_desc": np.argsort(-u.aptos.to_numpy(), kind="stable"),
        "porte_asc": np.argsort(u.aptos.to_numpy(), kind="stable"),
        "pior_F_primeiro": np.argsort(-p.to_numpy(), kind="stable"),
        "pior_L_primeiro": np.argsort(p.to_numpy(), kind="stable"),
    }
    for s in range(5):
        o[f"aleatoria_{s}"] = np.random.default_rng(100 + s).permutation(len(u))
    return o


def rodar_caso(nome: str, u: pd.DataFrame, h: live.Hiper) -> pd.DataFrame:
    u = u.reset_index(drop=True)
    final = 100 * (u.F.sum() - u.L.sum()) / (u.F.sum() + u.L.sum())
    sec = u.secoes.to_numpy(float)
    rows = []
    for on, ordem in ordens(u).items():
        cs = np.cumsum(sec[ordem]) / sec.sum()
        for pct in CHECK:
            k = int(np.searchsorted(cs, pct / 100)) + 1
            chegou = np.zeros(len(u), bool)
            chegou[ordem[:k]] = True
            x = u.assign(flavio=np.where(chegou, u.F, 0), lula=np.where(chegou, u.L, 0), frac=chegou.astype(float))
            r = live.estimar(x, h)
            rows.append({
                "caso": nome, "ordem": on, "pct": pct, "final": final,
                "p_flavio": r["p_flavio"], "proj": r["margem_mediana"],
                "lo80": r["margem_80"][0], "hi80": r["margem_80"][1],
                "lo95": r["margem_95"][0], "hi95": r["margem_95"][1],
                "ingenua": r["margem_atual"], "decidido": r["decidido"],
            })
    df = pd.DataFrame(rows)
    df["erro"] = df.proj - df.final
    df["erro_ingenuo"] = df.ingenua - df.final
    df["cob80"] = (df.final >= df.lo80) & (df.final <= df.hi80)
    df["cob95"] = (df.final >= df.lo95) & (df.final <= df.hi95)
    venceu_f = final > 0
    df["acertou"] = (df.p_flavio > 0.5) == venceu_f
    df["brier"] = (df.p_flavio - float(venceu_f)) ** 2
    df["p_vencedor"] = df.p_flavio if venceu_f else 1 - df.p_flavio
    return df


def resumo(df: pd.DataFrame) -> None:
    pd.set_option("display.width", 200)
    for caso, g in df.groupby("caso"):
        print(f"\n=== {caso} (margem final F−L {g.final.iloc[0]:+.2f} p.p.) ===")
        t = g.groupby("pct").agg(
            erro_medio_abs=("erro", lambda x: x.abs().mean()), erro_max_abs=("erro", lambda x: x.abs().max()),
            ingenuo_abs=("erro_ingenuo", lambda x: x.abs().mean()), cob80=("cob80", "mean"),
            cob95=("cob95", "mean"), acerto=("acertou", "mean"), p_venc_min=("p_vencedor", "min"),
            brier=("brier", "mean"))
        print(t.round(3).to_string())
        r = g[g.ordem == "real"].set_index("pct")[["p_flavio", "proj", "lo80", "hi80", "ingenua"]]
        print("ordem real:\n" + r.round(3).to_string())


# ---------------------------------------------------------------- replay ----

def gerar_replay(passo_min: int = 10) -> Path:
    """Snapshots no formato do coletor, reproduzindo a chegada do 1º turno 2026 (Flávio x Lula)."""
    out = ROOT / "data" / "snapshots" / "replay-t1-2026"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "prior.json").write_text(json.dumps({"prior": "t2_2022", "obs": "replay do 1º turno 2026, só Flávio x Lula"}))
    z = caso_t1_2026()
    base = pd.read_csv(ROOT / "data" / "base" / "t1_2026_mun.csv", dtype={"cd_tse": str})
    muns = base[["uf", "cd_tse", "cd_ibge", "nome", "te", "ts"]].assign(cd_tse=lambda x: x.cd_tse.str.zfill(5))
    t0 = z.ult_tot.min().floor("10min")
    tempos = list(pd.date_range(t0, z.ult_tot.max().ceil("10min"), freq=f"{passo_min}min"))
    tempos = [t for t in tempos if t <= pd.Timestamp(t0.date()) + pd.Timedelta(hours=23, minutes=30)] + [z.ult_tot.max()]
    for t in tempos:
        c = z[z.ult_tot <= t].groupby("cd_mun").agg(flavio=("F", "sum"), lula=("L", "sum"), est=("aptos", "sum"),
                                                     st=("secoes", "sum"))
        m = muns.join(c, on="cd_tse").fillna({"flavio": 0, "lula": 0, "est": 0, "st": 0})
        m["validos"] = m.flavio + m.lula
        m = m.rename(columns={"te": "te"})
        snap = out / t.strftime("%Y%m%d-%H%M%S")
        snap.mkdir()
        m.to_csv(snap / "mun.csv", index=False)
        m.groupby("uf")[["ts", "st", "te", "est", "validos", "flavio", "lula"]].sum().reset_index().to_csv(snap / "uf.csv", index=False)
        br = {k: int(m[k].sum()) for k in ["ts", "st", "te", "est", "validos", "flavio", "lula"]}
        (snap / "meta.json").write_text(json.dumps({"ele": "replay", "coletado_em": t.isoformat(),
                                                   "tse_ht": t.strftime("%H:%M:%S"), "br": br}))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--inflar", type=float, default=live.Hiper.inflar)
    a = ap.parse_args(argv)
    if a.replay:
        out = gerar_replay()
        prior = live.prior_para(out)
        for snap in sorted(p for p in out.iterdir() if p.is_dir()):
            r = live.processar(snap, prior)
            print(f"{snap.name} apurado {r['pct_apurado']:5.1f}% P(F) {r['p_flavio']:.3f} "
                  f"proj {r['margem_mediana']:+.2f} ({r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f}) atual {r['margem_atual'] or 0:+.2f}")
        return 0
    h = live.Hiper(inflar=a.inflar)
    df = pd.concat([rodar_caso("t2_2022", caso_t2_2022(), h), rodar_caso("t1_2026", caso_t1_2026(), h)])
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "resultados.csv", index=False)
    resumo(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
