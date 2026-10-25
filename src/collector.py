"""Coletor do Portal Resultados do TSE (resultados.tse.jus.br).

Padrão de URL verificado em 21/10/2026 contra o 1º turno (eleição 6257) e os
arquivos já publicados (zerados) do 2º turno (eleição 6258):

  {ele}/config/mun-e{ele:06}-cm.json             lista de municípios por UF
  {ele}/dados/{uf}/{uf}-e{ele:06}-ab.json        seções/eleitorado por município (sem votos)
  {ele}/dados/{abr}/{abr}-c0001-e{ele:06}-u.json resultado completo de Presidente
                                         abr = br | {uf} | {uf}{cd_mun_tse}

Estratégia incremental: a cada ciclo baixa br + 28 UFs (-u) e os 28 índices
(-ab). Só baixa o -u de um município quando o número de seções totalizadas
mudou desde o último ciclo. Cada ciclo grava um snapshot em
data/snapshots/e{ele}/{AAAAMMDD-HHMMSS}/ com uf.csv, mun.csv e meta.json.

Uso:
  python src/collector.py --ele 6257 --once        # snapshot do 1º turno
  python src/collector.py --ele 6258 --interval 60 # ao vivo no domingo

Sem novidade no TSE, não grava snapshot. A cada 20 ciclos baixa todos os municípios de novo
(pega correções que não mudam o número de seções). Depois de gravar, calcula a projeção
(projecao.json, via src/live.py), para o painel só ler, por mais gente que esteja olhando.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = "https://resultados.tse.jus.br/oficial/ele2026"
ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "snapshots"
CACHE_DIR = ROOT / "data" / "cache"

LULA, FLAVIO = "13", "22"
RECARGA_TOTAL = 20   # ciclos entre recargas completas

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "apuracao-eleicao/0.1 (projeto pessoal, estimativa nao oficial)"


FREIOS: list[float] = []   # horários dos HTTP 429 (TSE pedindo para ir mais devagar)


def get_json(ele: str, path: str, retries: int = 4) -> dict:
    """path usa {e} como marcador do código da eleição com zeros (e006257)."""
    url = f"{BASE}/{ele}/" + path.format(e=f"e{int(ele):06d}")
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                raise FileNotFoundError(url)
            if r.status_code == 429:
                FREIOS.append(time.time())
                if i == retries - 1:
                    break
                time.sleep(10 * (i + 1))
                continue
        except (requests.RequestException, ValueError) as exc:
            if i == retries - 1:
                raise RuntimeError(f"falha em {url}: {exc}") from exc
        time.sleep(2 ** i)
    raise RuntimeError(f"falha em {url}: HTTP {r.status_code}")


def _int(x) -> int:
    return int(x) if x not in (None, "") else 0


def parse_result(d: dict) -> dict:
    """Achata um arquivo -u em uma linha: seções, eleitorado, votos e candidatos."""
    s, e, v = d["s"], d["e"], d["v"]
    row = {
        "ts": _int(s["ts"]),          # seções totais
        "st": _int(s["st"]),          # seções totalizadas
        "te": _int(e["te"]),          # eleitorado apto total
        "est": _int(e["est"]),        # eleitorado das seções totalizadas
        "comp": _int(e["c"]),         # comparecimento (nas seções totalizadas)
        "abst": _int(e["a"]),         # abstenção (nas seções totalizadas)
        "validos": _int(v["vv"]),
        "brancos": _int(v["vb"]),
        "nulos": _int(v["tvn"]),      # nulos + nulos técnicos
        "dt": d.get("dt", ""),
        "ht": d.get("ht", ""),
    }
    cands = {}
    for agr in d["carg"][0].get("agr", []):
        for par in agr.get("par", []):
            for c in par.get("cand", []):
                cands[c["n"]] = _int(c.get("vap"))
    row["lula"] = cands.get(LULA, 0)
    row["flavio"] = cands.get(FLAVIO, 0)
    row["outros"] = row["validos"] - row["lula"] - row["flavio"]
    row["_cands"] = cands
    return row


def municipios(ele: str) -> pd.DataFrame:
    cm = get_json(ele, "config/mun-{e}-cm.json")
    rows = [
        {"uf": a["cd"], "cd_tse": m["cd"], "cd_ibge": m["cdi"], "nome": m["nm"], "capital": m["c"] == "s"}
        for a in cm["abr"] for m in a["mu"]
    ]
    return pd.DataFrame(rows)


def secoes_por_municipio(ele: str, uf: str) -> dict[str, int]:
    ab = get_json(ele, f"dados/{uf}/{uf}-{{e}}-ab.json")
    return {a["cdabr"]: _int(a["s"]["st"]) for a in ab["abr"] if a["tpabr"] == "mun"}


class Collector:
    def __init__(self, ele: str, workers: int = 6, max_mun: int = 1200):
        self.ele = ele
        self.workers = workers
        self.cache_dir = CACHE_DIR / f"e{ele}"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.muns = municipios(ele)
        self.ufs = sorted(self.muns["uf"].unique())
        self.n = 0
        self.prior = None
        # Teto de municípios baixados por ciclo: o resto fica para o ciclo seguinte. Cai pela metade se o TSE
        # frear (HTTP 429) e sobe aos poucos se não. Os totais por UF (28 arquivos) vêm em todo ciclo.
        self.max_mun = max_mun
        self.pendentes = 0

    def _cache_path(self, uf: str, cd: str) -> Path:
        return self.cache_dir / f"{uf}{cd}.json"

    def _fetch_mun(self, uf: str, cd: str) -> None:
        # Arquivo de cidade: uma tentativa só; se o TSE frear, fica para o próximo ciclo.
        d = get_json(self.ele, f"dados/{uf}/{uf}{cd}-c0001-{{e}}-u.json", retries=1)
        self._cache_path(uf, cd).write_text(json.dumps(d, ensure_ascii=False))

    def _ultimo(self) -> dict | None:
        root = SNAP_DIR / f"e{self.ele}"
        snaps = sorted(p for p in root.glob("*/meta.json")) if root.exists() else []
        return json.loads(snaps[-1].read_text()) if snaps else None

    def cycle(self) -> Path | None:
        """Grava um snapshot e devolve a pasta, ou None quando nada mudou desde o último."""
        t0 = time.time()
        self.n += 1
        recarga = self.n % RECARGA_TOTAL == 0
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        with ThreadPoolExecutor(self.workers) as ex:
            br_f = ex.submit(get_json, self.ele, "dados/br/br-c0001-{e}-u.json")
            uf_f = {uf: ex.submit(get_json, self.ele, f"dados/{uf}/{uf}-c0001-{{e}}-u.json") for uf in self.ufs}
            ab_f = {uf: ex.submit(secoes_por_municipio, self.ele, uf) for uf in self.ufs}
            br = parse_result(br_f.result())
            uf_rows = {uf: parse_result(f.result()) for uf, f in uf_f.items()}
            st_now = {(uf, cd): st for uf, f in ab_f.items() for cd, st in f.result().items()}

        # Baixa só o que mudou (ou ainda não está em cache).
        st_mun = {}
        mudou, resto = [], []
        for (uf, cd), st in st_now.items():
            p = self._cache_path(uf, cd)
            cached_st = None
            if p.exists():
                cached_st = _int(json.loads(p.read_text())["s"]["st"])
            if cached_st != st:
                mudou.append((abs(st - (cached_st or 0)), uf, cd))
            elif recarga:
                resto.append((uf, cd))
            st_mun[(uf, cd)] = st
        # Primeiro quem mais mudou; a recarga completa (correções) só entra quando sobra espaço no teto.
        mudou.sort(reverse=True)
        fila = [(uf, cd) for _, uf, cd in mudou] + resto
        todo = fila[: self.max_mun]
        self.pendentes = len(mudou) - min(len(mudou), self.max_mun)
        n_freios = len(FREIOS)
        errors = []
        with ThreadPoolExecutor(self.workers) as ex:
            futs = {ex.submit(self._fetch_mun, uf, cd): (uf, cd) for uf, cd in todo}
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception as exc:  # um município falhar não derruba o snapshot
                    errors.append(f"{futs[f]}: {exc}")

        freios = len(FREIOS) - n_freios
        self.max_mun = max(200, self.max_mun // 2) if freios else min(3000, int(self.max_mun * 1.5))
        self.freios = freios
        ult = self._ultimo()
        if not todo and not errors and ult and ult["br"].get("st") == br["st"] \
                and ult["br"].get("lula") == br["lula"] and ult["br"].get("flavio") == br["flavio"] \
                and ult.get("tse_ht") == br["ht"]:
            return None

        mun_rows = []
        for _, m in self.muns.iterrows():
            p = self._cache_path(m.uf, m.cd_tse)
            if not p.exists():
                continue
            r = parse_result(json.loads(p.read_text()))
            r.pop("_cands")
            mun_rows.append({"uf": m.uf, "cd_tse": m.cd_tse, "cd_ibge": m.cd_ibge, "nome": m.nome, **r})
        mun_df = pd.DataFrame(mun_rows)
        uf_df = pd.DataFrame([{"uf": uf, **{k: v for k, v in r.items() if k != "_cands"}} for uf, r in uf_rows.items()])

        out = SNAP_DIR / f"e{self.ele}" / stamp
        out.mkdir(parents=True, exist_ok=True)
        uf_df.to_csv(out / "uf.csv", index=False)
        mun_df.to_csv(out / "mun.csv", index=False)
        meta = {
            "ele": self.ele,
            "coletado_em": datetime.now().isoformat(timespec="seconds"),
            "tse_dt": br["dt"], "tse_ht": br["ht"],
            "br": {k: v for k, v in br.items() if k != "_cands"},
            "candidatos_br": br["_cands"],
            "mun_baixados": len(todo), "mun_total": len(st_now), "mun_no_snapshot": len(mun_df),
            "erros": errors, "segundos": round(time.time() - t0, 1),
        }
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        self.projetar(out)
        return out

    def projetar(self, out: Path) -> None:
        if self.ele != "6258":
            return
        try:
            import live
            if self.prior is None:
                self.prior = live.prior_para(out.parent)
            live.processar(out, self.prior)
        except Exception as exc:  # o painel tenta de novo se faltar a projeção
            print(f"projeção falhou em {out.name}: {exc}", file=sys.stderr, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ele", default="6258", help="6257 = 1º turno, 6258 = 2º turno (Presidente)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60, help="segundos entre ciclos")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args(argv)

    col = None
    while True:
        try:
            if col is None:
                col = Collector(a.ele, a.workers)
            out = col.cycle()
            if out is None:
                print(f"[{datetime.now():%H:%M:%S}] sem novidade no TSE", flush=True)
                if a.once:
                    return 0
                time.sleep(a.interval)
                continue
            meta = json.loads((out / "meta.json").read_text())
            br = meta["br"]
            pct = 100 * br["st"] / br["ts"] if br["ts"] else 0
            print(f"[{meta['coletado_em']}] TSE {meta['tse_ht'] or '-'} | seções {pct:.2f}% | "
                  f"Lula {br['lula']:,} x Flávio {br['flavio']:,} | mun baixados {meta['mun_baixados']} "
                  f"(faltam {col.pendentes}{', TSE freou ' + str(col.freios) if col.freios else ''}) "
                  f"| erros {len(meta['erros'])} | {meta['segundos']}s -> {out.relative_to(ROOT)}", flush=True)
        except Exception as exc:
            print(f"[{datetime.now():%H:%M:%S}] ciclo falhou: {exc}", file=sys.stderr, flush=True)
            if a.once:
                return 1
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
