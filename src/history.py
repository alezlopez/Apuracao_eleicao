"""Histórico de Presidente (2018, 2022, 2026-1T) por município/zona, dos dados abertos do TSE.

Baixa só o necessário:
  detalhe_votacao_munzona_{ano}.zip        aptos, comparecimento, brancos, nulos, hora da última totalização
  votacao_candidato_munzona_{ano}_BR.csv   votos por candidato a Presidente (extraído do zip por range request)

Saída: data/hist/munzona_{ano}.csv.gz, uma linha por (turno, uf, cd_mun, zona) com
esq (PT) e dir (candidato da direita que foi ao 2º turno), outros, brancos, nulos etc.

  python src/history.py
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests
from remotezip import RemoteZip

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "tse"
OUT = ROOT / "data" / "hist"
CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"

# Número do candidato de cada lado do 2º turno.
LADOS = {2018: {"esq": 13, "dir": 17}, 2022: {"esq": 13, "dir": 22}, 2026: {"esq": 13, "dir": 22}}
KEY = ["turno", "uf", "cd_mun", "zona"]


def _download(ano: int) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    det = RAW / f"detalhe_votacao_munzona_{ano}.zip"
    if not det.exists():
        r = requests.get(f"{CDN}/detalhe_votacao_munzona/{det.name}", timeout=300)
        r.raise_for_status()
        det.write_bytes(r.content)
    cand = RAW / f"votacao_candidato_munzona_{ano}_BR.csv"
    if not cand.exists():
        with RemoteZip(f"{CDN}/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip") as z:
            z.extract(cand.name, RAW)


def _read(f, cols) -> pd.DataFrame:
    return pd.read_csv(f, sep=";", encoding="latin1", usecols=cols, dtype={"CD_MUNICIPIO": str, "SG_UF": str})


def detalhe(ano: int) -> pd.DataFrame:
    cols = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "CD_CARGO", "QT_APTOS",
            "QT_TOTAL_SECOES", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_BRANCOS",
            "QT_TOTAL_VOTOS_NULOS", "HH_ULTIMA_TOTALIZACAO", "DT_ULTIMA_TOTALIZACAO"]
    frames = []
    with zipfile.ZipFile(RAW / f"detalhe_votacao_munzona_{ano}.zip") as z:
        for n in z.namelist():
            if n.endswith(".csv") and "BRASIL" not in n:  # o zip traz também o consolidado
                frames.append(_read(io.BytesIO(z.read(n)), cols))
    d = pd.concat(frames)
    d = d[d.CD_CARGO == 1]
    d = d.rename(columns={"NR_TURNO": "turno", "SG_UF": "uf", "CD_MUNICIPIO": "cd_mun", "NM_MUNICIPIO": "nome",
                          "NR_ZONA": "zona", "QT_APTOS": "aptos", "QT_TOTAL_SECOES": "secoes",
                          "QT_COMPARECIMENTO": "comp", "QT_ABSTENCOES": "abst", "QT_VOTOS_BRANCOS": "brancos",
                          "QT_TOTAL_VOTOS_NULOS": "nulos"})
    d["uf"] = d.uf.str.lower()
    d["cd_mun"] = d.cd_mun.str.zfill(5)
    d["ult_tot"] = pd.to_datetime(d.DT_ULTIMA_TOTALIZACAO + " " + d.HH_ULTIMA_TOTALIZACAO,
                                  format="%d/%m/%Y %H:%M:%S", errors="coerce")
    # Voto em trânsito vem em linha separada: soma, e fica com a última totalização.
    agg = {c: "sum" for c in ["aptos", "secoes", "comp", "abst", "brancos", "nulos"]}
    agg.update(nome="first", ult_tot="max")
    return d.groupby(KEY, as_index=False).agg(agg)


def candidatos(ano: int) -> pd.DataFrame:
    cols = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "CD_CARGO", "NR_CANDIDATO", "QT_VOTOS_NOMINAIS_VALIDOS"]
    c = _read(RAW / f"votacao_candidato_munzona_{ano}_BR.csv", cols)
    c = c[c.CD_CARGO == 1].rename(columns={"NR_TURNO": "turno", "SG_UF": "uf", "CD_MUNICIPIO": "cd_mun", "NR_ZONA": "zona"})
    c["uf"] = c.uf.str.lower()
    c["cd_mun"] = c.cd_mun.str.zfill(5)
    lado = {v: k for k, v in LADOS[ano].items()}
    c["lado"] = c.NR_CANDIDATO.map(lado).fillna("outros")
    w = c.pivot_table(index=KEY, columns="lado", values="QT_VOTOS_NOMINAIS_VALIDOS", aggfunc="sum", fill_value=0)
    w = w.reindex(columns=["esq", "dir", "outros"], fill_value=0).reset_index()
    w.columns.name = None
    return w


def build(ano: int) -> pd.DataFrame:
    _download(ano)
    df = detalhe(ano).merge(candidatos(ano), on=KEY, how="outer", indicator=True)
    # 2018 tem seções do exterior sem nenhum comparecimento: só elas ficam sem par.
    bad = df[(df._merge != "both") & (df.comp > 0)]
    if len(bad):
        raise ValueError(f"{ano}: {len(bad)} zonas com votos sem par entre detalhe e candidatos")
    df = df.drop(columns="_merge").fillna({"esq": 0, "dir": 0, "outros": 0})
    df["validos"] = df.esq + df.dir + df.outros
    df.insert(0, "ano", ano)
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ano in (2018, 2022, 2026):
        df = build(ano)
        df.to_csv(OUT / f"munzona_{ano}.csv.gz", index=False)
        for t, g in df.groupby("turno"):
            v = g.validos.sum()
            print(f"{ano} T{t}: zonas {len(g):5d} aptos {g.aptos.sum():,} abst {100 * g.abst.sum() / g.aptos.sum():.2f}% "
                  f"esq {100 * g.esq.sum() / v:.2f}% dir {100 * g.dir.sum() / v:.2f}% outros {100 * g.outros.sum() / v:.2f}%")


if __name__ == "__main__":
    main()
