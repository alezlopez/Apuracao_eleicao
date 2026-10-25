"""Coletor de boletins de urna do exterior, para antes das 17h.

O TSE só divulga o total às 17h (Brasília), mas publica o boletim de cada urna do exterior assim que ela
chega (arquivo-urna/). Este coletor lê esses boletins e grava um snapshot no formato do coletor oficial
(data/snapshots/e6258-bu/), com só o exterior contado. Quando o total oficial começa, o painel passa a
usar o coletor oficial (src/collector.py) e este para sozinho.

  python src/coletor_bu.py --interval 120          # domingo, até a divulgação oficial
  python src/coletor_bu.py --pleito 3220 --ele 6257 --once --validar   # confere contra o 1º turno
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bu import ler_bu  # noqa: E402

BASE = "https://resultados.tse.jus.br/oficial/ele2026"
ROOT = Path(__file__).resolve().parent.parent
BASE_MUN = ROOT / "data" / "base" / "t1_2026_mun.csv"
LULA, FLAVIO = "13", "22"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "apuracao-eleicao/0.1 (projeto pessoal, estimativa nao oficial)"


def _get(url: str, binario: bool = False, tentativas: int = 3):
    for i in range(tentativas):
        try:
            r = SESSION.get(url, timeout=20)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return r.content if binario else r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1 + i)
    raise RuntimeError(f"falha em {url}")


def secoes(pleito: str, uf: str = "zz") -> list[tuple[str, str, str]]:
    cs = _get(f"{BASE}/arquivo-urna/{pleito}/config/{uf}/{uf}-p{int(pleito):06d}-cs.json")
    return [(m["cd"], z["cd"], s["ns"]) for a in cs["abr"] for m in a["mu"] for z in m["zon"] for s in z["sec"]]


class ColetorBU:
    def __init__(self, pleito: str, ele: str, uf: str = "zz", workers: int = 16):
        self.pleito, self.ele, self.uf, self.workers = pleito, ele, uf, workers
        self.cache = ROOT / "data" / "cache" / f"bu-p{pleito}-{uf}"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.secoes = secoes(pleito, uf)

    def _secao(self, mun: str, zona: str, sec: str) -> dict | None:
        """Lê (com cache) o BU de uma seção. None se ainda não chegou."""
        f = self.cache / f"{mun}-{zona}-{sec}.json"
        if f.exists():
            return json.loads(f.read_text())
        pasta = f"{BASE}/arquivo-urna/{self.pleito}/dados/{self.uf}/{mun}/{zona}/{sec}"
        aux = _get(f"{pasta}/p{int(self.pleito):06d}-{self.uf}-m{mun}-z{zona}-s{sec}-aux.json")
        if not aux:
            return None
        recebidos = [h for h in aux.get("hashes", []) if h.get("st") in ("Recebido", "Totalizado")]
        if not recebidos:
            return None
        h = recebidos[-1]
        nome = next((a["nm"] for a in h["arq"] if a["tp"] == "bu"), None)
        if not nome:
            return None
        b = _get(f"{pasta}/{h['hash']}/{nome}", binario=True)
        if not b:
            return None
        r = ler_bu(b, int(self.ele))
        r.update(mun=mun, zona=zona, secao=sec, recebido=f"{h.get('dr', '')} {h.get('hr', '')}".strip())
        f.write_text(json.dumps(r))
        return r

    def ciclo(self) -> pd.DataFrame:
        with ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(lambda s: self._secao(*s), self.secoes))
        rows = []
        for r in res:
            if r:
                rows.append({"mun": r["mun"], "zona": r["zona"], "secao": r["secao"], "aptos": r["aptos"],
                             "comp": r["comp"], "lula": r["votos"].get(LULA, 0), "flavio": r["votos"].get(FLAVIO, 0),
                             "outros": sum(v for k, v in r["votos"].items() if k not in (LULA, FLAVIO)),
                             "brancos": r["brancos"], "nulos": r["nulos"], "recebido": r["recebido"]})
        return pd.DataFrame(rows, columns=["mun", "zona", "secao", "aptos", "comp", "lula", "flavio", "outros",
                                           "brancos", "nulos", "recebido"])


def gravar_snapshot(sec: pd.DataFrame, total_secoes: pd.Series) -> Path | None:
    """Snapshot no formato do coletor oficial: todos os municípios, só o exterior com votos."""
    base = pd.read_csv(BASE_MUN, dtype={"cd_tse": str})
    base["cd_tse"] = base.cd_tse.str.zfill(5)
    por_mun = sec.groupby("mun").agg(st=("secao", "size"), est=("aptos", "sum"), comp=("comp", "sum"),
                                     lula=("lula", "sum"), flavio=("flavio", "sum"), outros=("outros", "sum"),
                                     brancos=("brancos", "sum"), nulos=("nulos", "sum"))
    m = base[["uf", "cd_tse", "cd_ibge", "nome", "te"]].join(por_mun, on="cd_tse")
    m["ts"] = m.cd_tse.map(total_secoes).fillna(base.ts).astype(int)
    for c in ["st", "est", "comp", "lula", "flavio", "outros", "brancos", "nulos"]:
        m[c] = m[c].fillna(0).astype(int)
    m["validos"] = m.lula + m.flavio + m.outros
    m["abst"] = 0
    m["dt"] = m["ht"] = ""

    root = ROOT / "data" / "snapshots" / "e6258-bu"
    ult = sorted(root.glob("*/meta.json")) if root.exists() else []
    assinatura = [int(m.st.sum()), int(m.lula.sum()), int(m.flavio.sum())]
    if ult and json.loads(ult[-1].read_text())["assinatura"] == assinatura:
        return None
    out = root / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    cols = ["uf", "cd_tse", "cd_ibge", "nome", "ts", "st", "te", "est", "comp", "abst", "validos", "brancos", "nulos",
            "dt", "ht", "lula", "flavio", "outros"]
    m[cols].to_csv(out / "mun.csv", index=False)
    m.groupby("uf")[["ts", "st", "te", "est", "comp", "validos", "brancos", "nulos", "lula", "flavio", "outros"]] \
        .sum().reset_index().to_csv(out / "uf.csv", index=False)
    sec.to_csv(out / "secoes.csv", index=False)
    ultimo = sec.recebido.max() if len(sec) else ""
    meta = {"ele": "6258", "origem": "bu", "coletado_em": datetime.now().isoformat(timespec="seconds"),
            "tse_ht": ultimo[-8:] if ultimo else "", "ultimo_bu": ultimo, "assinatura": assinatura,
            "br": {k: int(m[k].sum()) for k in ["ts", "st", "te", "est", "validos", "lula", "flavio"]}}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    try:
        import live
        live.processar(out, live.prior_para(root))
    except Exception as exc:  # o painel tenta de novo se faltar a projeção
        print(f"projeção falhou: {exc}", file=sys.stderr, flush=True)
    return out


def oficial_comecou() -> bool:
    d = _get(f"{BASE}/6258/dados/br/br-c0001-e006258-u.json")
    return bool(d) and int(d["s"]["st"] or 0) > 0


def validar(sec: pd.DataFrame) -> None:
    """Compara a soma dos BUs do 1º turno com o resultado oficial de cada cidade do exterior."""
    base = pd.read_csv(BASE_MUN, dtype={"cd_tse": str})
    base["cd_tse"] = base.cd_tse.str.zfill(5)
    of = base[base.uf == "zz"].set_index("cd_tse")
    bu = sec.groupby("mun")[["comp", "lula", "flavio", "brancos", "nulos"]].sum()
    j = bu.join(of[["nome", "comp", "lula", "flavio", "brancos", "nulos"]], rsuffix="_of", how="left")
    dif = j[[c for c in ["comp", "lula", "flavio", "brancos", "nulos"]]].values - \
        j[[c + "_of" for c in ["comp", "lula", "flavio", "brancos", "nulos"]]].values
    j["bate"] = (dif == 0).all(axis=1)
    print(f"cidades: {len(j)} | batem exatamente: {int(j.bate.sum())}")
    print(j[~j.bate].head(10).to_string() if (~j.bate).any() else "todas batem")
    tot = j[["comp", "comp_of", "lula", "lula_of", "flavio", "flavio_of", "brancos", "brancos_of", "nulos", "nulos_of"]].sum()
    print(tot.to_string())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="3221")
    ap.add_argument("--ele", default="6258")
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--validar", action="store_true")
    a = ap.parse_args(argv)

    col = None
    while True:
        try:
            if a.pleito == "3221" and not a.once and oficial_comecou():
                print("divulgação oficial começou; coletor de boletins encerrado", flush=True)
                return 0
            if col is None:
                col = ColetorBU(a.pleito, a.ele)
                print(f"{len(col.secoes)} seções no exterior", flush=True)
            t0 = time.time()
            sec = col.ciclo()
            if a.validar:
                validar(sec)
                return 0
            tot_secoes = pd.Series([s[0] for s in col.secoes]).value_counts()
            out = gravar_snapshot(sec, tot_secoes)
            v = sec.lula.sum() + sec.flavio.sum()
            print(f"[{datetime.now():%H:%M:%S}] BUs do exterior: {len(sec)}/{len(col.secoes)} seções | "
                  f"Lula {sec.lula.sum():,} x Flávio {sec.flavio.sum():,}"
                  + (f" ({100 * sec.lula.sum() / v:.1f}% x {100 * sec.flavio.sum() / v:.1f}%)" if v else "")
                  + f" | {time.time() - t0:.0f}s | " + (f"-> {out.relative_to(ROOT)}" if out else "sem novidade"),
                  flush=True)
        except Exception as exc:
            print(f"[{datetime.now():%H:%M:%S}] ciclo falhou: {exc}", file=sys.stderr, flush=True)
            if a.once:
                return 1
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
