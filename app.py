"""Painel público: chance de vitória durante a apuração do 2º turno 2026, explicado para leigos.

  streamlit run app.py

Variáveis de ambiente:
  ADMIN_TOKEN  senha da área de administração (entrada manual). Acesse com ?admin=<senha> na URL.
               Sem ela definida, a área de administração não aparece para ninguém.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
import live  # noqa: E402
import model  # noqa: E402

# Azul = Flávio, vermelho = Lula (par validado para daltonismo e contraste). Neutros levemente quentes.
FLAVIO, LULA = "#2a78d6", "#d64545"
FLAVIO_CLARO, LULA_CLARO = "rgba(42,120,214,0.10)", "rgba(214,69,69,0.10)"
TINTA, NEUTRO, MEIO = "#1f1f1d", "#6b6b66", "#ecebe7"
LARANJA = "#c98a3a"
FONTE = "Source Sans 3, Source Sans Pro, sans-serif"
SNAPS = ROOT / "data" / "snapshots"
DOMINGO = ["e6258", "e6258-manual"]   # coletor do TSE; entrada manual (plano B)
EXTERIOR_BU = "e6258-bu"              # boletins de urna do exterior, antes da divulgação oficial
REG_NOME = {"N": "Norte", "NE": "Nordeste", "CO": "Centro-Oeste", "SE": "Sudeste", "S": "Sul", "EX": "Exterior"}
REG_ORDEM = ["NE", "SE", "S", "N", "CO", "EX"]
FONTE_FORCADA = os.environ.get("PAINEL_FONTE", "")   # só para testes locais (ex.: replay-t1-2026)
N_SIM = 20000

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN = bool(ADMIN_TOKEN) and st.query_params.get("admin") == ADMIN_TOKEN

st.set_page_config(page_title="Lula x Flávio: apuração 2º turno 2026", page_icon="🗳️", layout="wide")

st.html("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Source+Sans+3:wght@400;600&display=swap');
  :root { --flavio:#2a78d6; --lula:#d64545; --tinta:#1f1f1d; --neutro:#6b6b66; --linha:#e3e1dc; --fundo2:#f7f6f3; }
  .stMarkdown p, .stMarkdown li, .stCaption p, .ap-hero p, .ap-card, .ap-box, .ap-ordem, .ap-chip, .ap-legbarra
    { font-family: 'Source Sans 3', 'Source Sans Pro', sans-serif; }
  h1, h2, h3, h4, .ap-num, .ap-hero b { font-family: 'Archivo', 'Source Sans 3', sans-serif !important; letter-spacing: -0.01em; }
  header[data-testid="stHeader"] { display: none; }
  .block-container { padding-top: 1.5rem; max-width: 1180px; }
  .ap-hero { border-bottom: 1px solid var(--linha); padding-bottom: 1rem; margin-bottom: .25rem; }
  .ap-over { font-size: .78rem; letter-spacing: .08em; text-transform: uppercase; color: var(--neutro); }
  .ap-hero h1 { font-size: clamp(2rem, 5vw, 3.1rem); font-weight: 800; margin: .15rem 0 .35rem; line-height: 1.05; }
  .ap-hero h1 .f { color: var(--flavio); } .ap-hero h1 .l { color: var(--lula); }
  .ap-hero p { margin: 0; color: #3d3d3a; max-width: 70ch; }
  .ap-duelo { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; margin: .5rem 0 .75rem; }
  .ap-card { border-radius: 10px; padding: .9rem 1.1rem; border: 1px solid var(--linha); }
  .ap-card.f { background: rgba(42,120,214,.08); border-color: rgba(42,120,214,.35); }
  .ap-card.l { background: rgba(214,69,69,.08); border-color: rgba(214,69,69,.35); text-align: right; }
  .ap-card .quem { font-weight: 600; font-size: .95rem; }
  .ap-card.f .quem, .ap-card.f .ap-num { color: var(--flavio); }
  .ap-card.l .quem, .ap-card.l .ap-num { color: var(--lula); }
  .ap-num { font-size: clamp(2.2rem, 6vw, 3.4rem); font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; }
  .ap-card .sub { color: var(--neutro); font-size: .85rem; }
  .ap-barra { display: flex; height: 14px; border-radius: 7px; overflow: hidden; background: #ecebe7; margin: .25rem 0 .2rem; }
  .ap-barra .f { background: var(--flavio); } .ap-barra .l { background: var(--lula); }
  .ap-barra span + span { border-left: 2px solid #fff; }
  .ap-legbarra { display: flex; justify-content: space-between; font-size: .8rem; color: var(--neutro); }
  .ap-chip { display: inline-block; font-size: .78rem; padding: 2px 8px; border-radius: 999px; background: var(--fundo2);
             border: 1px solid var(--linha); color: #3d3d3a; margin-right: .35rem; }
  .ap-box { background: var(--fundo2); border: 1px solid var(--linha); border-radius: 10px; padding: .9rem 1.1rem; }
  .ap-ordem { border-left: 4px solid var(--linha); padding: .2rem 0 .2rem .8rem; margin: .4rem 0; }
  .ap-ordem.real { border-left-color: var(--tinta); } .ap-ordem.extrema { border-left-color: #c98a3a; }
  .ap-ok { color: #0c7a0c; font-weight: 600; } .ap-ruim { color: #a35a00; font-weight: 600; }
  .stTabs [data-baseweb="tab-list"] { gap: .25rem; }
  .stTabs [data-baseweb="tab"] { font-family: 'Archivo', sans-serif; font-weight: 600; font-size: 1rem; }
  .ap-card .linha { display: flex; justify-content: space-between; gap: .5rem; font-size: .92rem; color: #3d3d3a;
                    border-top: 1px solid rgba(0,0,0,.06); padding-top: .35rem; margin-top: .45rem; }
  .ap-card.l .linha { flex-direction: row-reverse; }
  .ap-card .linha b { font-variant-numeric: tabular-nums; }
  .ap-prog { margin: .9rem 0 .4rem; }
  .ap-prog .rot { display: flex; justify-content: space-between; font-size: .85rem; color: var(--neutro); margin-bottom: .25rem; }
  .ap-prog .rot b { color: var(--tinta); font-family: 'Archivo', sans-serif; font-size: 1.05rem; }
  .ap-prog .trilho { height: 10px; border-radius: 5px; background: #ecebe7; overflow: hidden; }
  .ap-prog .trilho span { display: block; height: 100%; background: var(--tinta); border-radius: 5px; }
  .ap-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 250px), 1fr)); gap: .75rem; margin: .5rem 0 1rem; }
  .ap-grid.uf { grid-template-columns: repeat(auto-fill, minmax(min(100%, 210px), 1fr)); }
  .ap-rc { border: 1px solid var(--linha); border-left: 5px solid #c9c7c0; border-radius: 10px; padding: .75rem .9rem;
           background: #fff; display: flex; flex-direction: column; gap: .35rem; font-family: 'Source Sans 3', sans-serif; }
  .ap-rc.f { border-left-color: var(--flavio); } .ap-rc.l { border-left-color: var(--lula); }
  .ap-rc .topo { display: flex; justify-content: space-between; align-items: baseline; gap: .5rem; }
  .ap-rc .nome { font-family: 'Archivo', sans-serif; font-weight: 700; font-size: 1.05rem; color: var(--tinta); }
  .ap-rc .apu { font-size: .78rem; color: var(--neutro); white-space: nowrap; }
  .ap-rc .mini { height: 4px; border-radius: 2px; background: #ecebe7; overflow: hidden; }
  .ap-rc .mini span { display: block; height: 100%; background: var(--tinta); }
  .ap-rc .split { display: flex; height: 22px; border-radius: 5px; overflow: hidden; background: #ecebe7; font-size: .78rem;
                  font-weight: 600; color: #fff; line-height: 22px; }
  .ap-rc .split span { padding: 0 .4rem; white-space: nowrap; overflow: hidden; }
  .ap-rc .split .f { background: var(--flavio); } .ap-rc .split .l { background: var(--lula); text-align: right; }
  .ap-rc .split .vazio { color: var(--neutro); font-weight: 400; }
  .ap-rc .votos { display: flex; justify-content: space-between; font-size: .8rem; color: var(--neutro); font-variant-numeric: tabular-nums; }
  .ap-rc .proj { font-size: .92rem; color: #3d3d3a; }
  .ap-rc .proj b.f, .ap-rc .t1 b.f { color: var(--flavio); } .ap-rc .proj b.l, .ap-rc .t1 b.l { color: var(--lula); }
  .ap-rc .t1 { font-size: .8rem; color: var(--neutro); }
  .ap-sec { font-family: 'Archivo', sans-serif; font-weight: 800; font-size: 1.5rem; margin: 1.6rem 0 .1rem; color: var(--tinta); }
  .ap-secsub { color: var(--neutro); margin: 0 0 .4rem; font-size: .95rem; }
  .ap-det { border: 1px solid var(--linha); border-radius: 12px; padding: 1rem 1.1rem; background: var(--fundo2); }
  .ap-det h3 { margin: 0 0 .2rem; }
  .ap-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); gap: .6rem; margin-top: .6rem; }
  .ap-kpi { background: #fff; border: 1px solid var(--linha); border-radius: 10px; padding: .55rem .75rem; }
  .ap-kpi .k { font-size: .75rem; color: var(--neutro); text-transform: uppercase; letter-spacing: .05em; }
  .ap-kpi .v { font-family: 'Archivo', sans-serif; font-weight: 700; font-size: 1.15rem; font-variant-numeric: tabular-nums; }
  /* Faixa fixa no rodapé: apuração por região, sempre visível */
  .block-container { padding-bottom: 7.5rem; }
  .ap-fixo { position: fixed; left: 0; right: 0; bottom: 0; z-index: 999990; background: rgba(255,255,255,.97);
             border-top: 1px solid var(--linha); box-shadow: 0 -4px 16px rgba(0,0,0,.06);
             padding: .5rem max(12px, env(safe-area-inset-right, 0px)) calc(.5rem + env(safe-area-inset-bottom, 0px))
                      max(12px, env(safe-area-inset-left, 0px)); font-family: 'Source Sans 3', sans-serif; }
  .ap-fixo .lin { max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: repeat(7, 1fr); gap: .75rem; }
  .ap-fixo .c { min-width: 0; }
  .ap-fixo .t { font-size: .8rem; }
  .ap-fixo .t b { font-family: 'Archivo', sans-serif; font-weight: 700; color: var(--tinta); white-space: nowrap; }
  .ap-fixo .b { height: 7px; border-radius: 4px; background: #ecebe7; overflow: hidden; margin: .2rem 0 .15rem; }
  .ap-fixo .b i { display: block; height: 100%; background: var(--tinta); border-radius: 4px; }
  .ap-fixo .c.f .b i { background: var(--flavio); } .ap-fixo .c.l .b i { background: var(--lula); }
  .ap-fixo .v { display: flex; justify-content: space-between; gap: .25rem; font-size: .76rem; color: var(--neutro);
                white-space: nowrap; }
  .ap-fixo .v .p { font-variant-numeric: tabular-nums; font-weight: 700; color: var(--tinta); }
  .ap-fixo .v .q { overflow: hidden; text-overflow: ellipsis; }
  .ap-fixo .c.f .v .q { color: var(--flavio); font-weight: 600; } .ap-fixo .c.l .v .q { color: var(--lula); font-weight: 600; }
  .ap-fixo .c.br .t b { text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 3px; }
  @media (max-width: 640px) {
    .ap-duelo { grid-template-columns: 1fr; } .ap-card.l { text-align: left; } .ap-card.l .linha { flex-direction: row; }
    .block-container { padding-bottom: 9.5rem; }
    .ap-fixo .lin { grid-template-columns: repeat(4, 1fr); gap: .35rem .55rem; }
    .ap-fixo .t { font-size: .7rem; } .ap-fixo .v { font-size: .68rem; } .ap-fixo .b { height: 6px; }
  }
</style>
""")


# ================================================================ formatação =

def br(x: float, d: int = 1) -> str:
    """Número no formato brasileiro (vírgula decimal, ponto de milhar)."""
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(p: float, d: int = 0) -> str:
    return br(100 * p, d) + "%"


def chance(p: float) -> str:
    """Chance de vitória: nunca "100%" ou "0%" cravados, que nenhuma projeção merece."""
    if p >= 0.995:
        return "> 99%"
    if p <= 0.005:
        return "< 1%"
    return pct(p)


def vantagem(m: float | None, d: int = 1, dir_nome: str = "Flávio") -> str:
    """Margem (direita − Lula) em pontos, escrita com o nome de quem está à frente."""
    if m is None or (isinstance(m, float) and np.isnan(m)):
        return "—"
    if abs(m) < 0.05:
        return "empate"
    return f"{dir_nome if m > 0 else 'Lula'} +{br(abs(m), d)}"


def faixa(lo: float, hi: float) -> str:
    """Faixa provável escrita do menor para o maior lado a lado ("Lula +38,2 a Lula +41,8")."""
    if lo < 0 and hi < 0:
        lo, hi = hi, lo
    return f"{vantagem(lo)} a {vantagem(hi)}"


def placar(m: float) -> str:
    f = 50 + m / 2
    return f"Flávio {br(f)}% x Lula {br(100 - f)}%"


def milhoes(v: float) -> str:
    x = abs(v) / 1e6
    return f"{br(x, 1)} {'milhão' if x < 2 else 'milhões'}" if x >= 1 else f"{br(abs(v) / 1e3, 0)} mil"


def layout(fig, h=320, **kw):
    kw.setdefault("hovermode", "x unified")
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=48, b=10), separators=",.",
                      font=dict(family=FONTE, color=TINTA, size=13),
                      title_font=dict(family="Archivo, sans-serif", size=16),
                      plot_bgcolor="white", paper_bgcolor="white", **kw)
    fig.update_xaxes(gridcolor="#efeee9", zerolinecolor="#d8d6d0", linecolor="#d8d6d0")
    fig.update_yaxes(gridcolor="#efeee9", zerolinecolor="#d8d6d0", linecolor="#d8d6d0")
    return fig


def duelo(pf: float, pl: float, rot_f: str, rot_l: str, sub_f: str = "", sub_l: str = ""):
    """Os dois cartões de chance, lado a lado, com a barra dividida."""
    st.html(f"""
<div class="ap-duelo">
  <div class="ap-card f"><div class="quem">Flávio Bolsonaro (PL)</div><div class="ap-num">{rot_f}</div><div class="sub">{sub_f}</div></div>
  <div class="ap-card l"><div class="quem">Lula (PT)</div><div class="ap-num">{rot_l}</div><div class="sub">{sub_l}</div></div>
</div>
<div class="ap-barra" role="img" aria-label="Flávio {pct(pf)}, Lula {pct(pl)}">
  <span class="f" style="width:{100 * pf:.2f}%"></span><span class="l" style="width:{100 * pl:.2f}%"></span></div>
<div class="ap-legbarra"><span>Flávio {pct(pf)}</span><span>Lula {pct(pl)}</span></div>""")


# ================================================================ estados ===

@st.cache_data
def geo() -> dict:
    return json.loads((ROOT / "data" / "geo" / "br_uf.geojson").read_text())


@st.cache_data
def nomes_uf() -> dict[str, str]:
    n = {f["id"]: f["properties"]["nome"] for f in geo()["features"]}
    n["zz"] = "Exterior"
    return n


def mapa(t: pd.DataFrame, titulo: str, rot: str = "Projeção"):
    """t: colunas uf (minúscula), margem, e opcionais apurado, p_flavio."""
    t = t[t.uf != "zz"].copy()
    nomes = nomes_uf()
    lim = 30
    extra = []
    for _, r in t.iterrows():
        partes = [f"{rot}: {vantagem(r.margem)}"]
        if "apurado" in t and not pd.isna(r.get("apurado")):
            partes.append(f"Apurado: {br(r.apurado, 0)}%")
        if "p_flavio" in t:
            partes.append(f"Chance de Flávio no estado: {pct(r.p_flavio)}")
        extra.append("<br>".join(partes))
    fig = go.Figure(go.Choropleth(
        geojson=geo(), locations=t.uf, featureidkey="id", z=t.margem.clip(-lim, lim),
        zmin=-lim, zmax=lim, zmid=0,
        colorscale=[[0, LULA], [0.5, "#f0efec"], [1, FLAVIO]],
        marker_line_color="white", marker_line_width=0.8,
        customdata=np.c_[t.uf.map(nomes), extra],
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
        colorbar=dict(title=dict(text="Vantagem", side="top"), tickvals=[-30, -15, 0, 15, 30],
                      ticktext=["Lula +30", "Lula +15", "empate", "Flávio +15", "Flávio +30"],
                      thickness=12, len=0.7, outlinewidth=0),
    ))
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="white")
    layout(fig, h=460, title=titulo, hovermode="closest")
    fig.update_layout(margin=dict(l=0, r=0, t=48, b=0), dragmode=False)
    st.plotly_chart(fig, width="stretch", config={"scrollZoom": False, "displayModeBar": False})


# ================================================================ dados ======

def garantir_projecao(snap: Path, root: Path) -> bool:
    """O coletor já calcula a projeção; isto só cobre falhas, com trava para dois visitantes não calcularem juntos."""
    if (snap / "projecao.json").exists():
        return True
    trava = snap / ".calculando"
    try:
        if trava.exists() and time.time() - trava.stat().st_mtime > 300:
            trava.unlink()
        fd = os.open(trava, os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return False
    try:
        os.close(fd)
        live.processar(snap, prior_cache(root.name))
        return True
    finally:
        trava.unlink(missing_ok=True)


@st.cache_resource
def prior_cache(fonte: str) -> pd.DataFrame:
    return live.prior_para(SNAPS / fonte)


@st.cache_data(ttl=600)
def ler_historico(root: str, assinatura: tuple) -> list[dict]:
    out = []
    for nome in assinatura:
        try:
            out.append(json.loads((Path(root) / nome / "projecao.json").read_text()))
        except (OSError, ValueError):   # arquivo ruim: pula, o próximo snapshot cobre
            continue
    return out


def historico(fonte: str) -> list[dict]:
    root = SNAPS / fonte
    if not root.exists():
        return []
    snaps = sorted(p for p in root.iterdir() if p.is_dir() and (p / "uf.csv").exists())
    prontos = tuple(s.name for s in snaps if garantir_projecao(s, root))
    return ler_historico(str(root), prontos)


def _oficial_comecou() -> bool:
    snaps = sorted((SNAPS / DOMINGO[0]).glob("*/meta.json")) if (SNAPS / DOMINGO[0]).exists() else []
    return bool(snaps) and json.loads(snaps[-1].read_text())["br"].get("st", 0) > 0


def fonte_domingo() -> str:
    """Antes das 17h: boletins do exterior. Depois: o coletor oficial, ou a entrada manual se ela for mais recente."""
    if FONTE_FORCADA:
        return FONTE_FORCADA
    manual = SNAPS / DOMINGO[1]
    if not _oficial_comecou() and not (manual.exists() and any(manual.glob("*/uf.csv"))):
        if (SNAPS / EXTERIOR_BU).exists() and any((SNAPS / EXTERIOR_BU).glob("*/uf.csv")):
            return EXTERIOR_BU
    melhor, t = DOMINGO[0], -1.0
    for f in DOMINGO:
        root = SNAPS / f
        if root.exists():
            snaps = sorted(root.glob("*/uf.csv"))
            if snaps and snaps[-1].stat().st_mtime > t:
                melhor, t = f, snaps[-1].stat().st_mtime
    return melhor


# ================================================================ Ao vivo ===

COMO_LER = """
**Chance de vitória** não é porcentagem de votos. *Flávio 80%* quer dizer: se esta mesma situação da apuração
se repetisse 100 vezes, ele venceria em cerca de 80 e Lula em 20. Com 80%, o favorito ainda perde 1 em cada 5 vezes.

**Por que não basta olhar a contagem do TSE?** As urnas não chegam em ordem aleatória. Cidades pequenas, o Sul e o
Centro-Oeste costumam aparecer primeiro; o Nordeste e as capitais, depois. No 1º turno, às 18h50, a contagem
mostrava Flávio com **23 pontos** de vantagem sobre Lula. Ele terminou com **2**. O modelo existe para corrigir isso:
ele olha *quais* cidades já entraram e estima as que faltam.

**Faixa provável**: em 8 de cada 10 simulações, o resultado final fica dentro dela.

**Ponto percentual**: a diferença entre as porcentagens dos dois. *Flávio +2* quer dizer algo como
Flávio 51% x Lula 49% dos votos válidos (votos válidos = sem brancos e nulos).
"""


def estado_atual() -> tuple[dict | None, Path | None, list[dict]]:
    """Última projeção, a pasta do snapshot dela e o histórico da noite."""
    fonte = fonte_domingo()
    hist = historico(fonte)
    if not hist:
        return None, None, []
    r = hist[-1]
    return r, SNAPS / fonte / r["snapshot"], hist


@st.cache_data(ttl=120)
def contagem_uf(snap: str) -> pd.DataFrame:
    """Votos contados por estado, como o TSE informa (uf.csv do snapshot)."""
    t = pd.read_csv(Path(snap) / "uf.csv")
    for c in ["comp", "est", "brancos", "nulos", "lula", "flavio", "te", "st", "ts"]:
        if c not in t:
            t[c] = 0
    t["regiao"] = t.uf.map(model.REGIAO)
    return t


@st.cache_data
def base_t1() -> pd.DataFrame:
    """1º turno por estado (só Flávio x Lula), para comparar."""
    b = model.carregar_base()
    b["margem_1t"] = 100 * (b.flavio - b.lula) / (b.flavio + b.lula)
    b["comp_1t"] = 100 * b.comp / b.te
    return b


def t1_regiao() -> dict[str, float]:
    b = base_t1().groupby("regiao")[["flavio", "lula"]].sum()
    return (100 * (b.flavio - b.lula) / (b.flavio + b.lula)).to_dict()


def antes_das_17h(r: dict | None) -> bool:
    return r is None or r.get("origem") == "bu" or r["pct_apurado"] == 0


def cartao(nome: str, apurado: float, f: float, l: float, proj: dict | None, m1t: float | None) -> str:
    """Cartão de uma região ou de um estado: apuração, contagem, projeção e 1º turno."""
    v = f + l
    lider = (proj["margem_proj"] if proj else (m1t or 0))
    classe = "f" if lider > 0 else "l"
    if v > 0:
        pf = 100 * f / v
        split = (f'<span class="f" style="width:{pf:.2f}%">{br(pf)}%</span>'
                 f'<span class="l" style="width:{100 - pf:.2f}%">{br(100 - pf)}%</span>')
        votos = f'<div class="votos"><span>Flávio {br(f, 0)}</span><span>Lula {br(l, 0)}</span></div>'
    else:
        split = '<span class="vazio">aguardando a apuração</span>'
        votos = ""
    if proj:
        cls = "f" if proj["margem_proj"] > 0 else "l"
        pf_ = proj["p_flavio"]
        proj_html = (f'<div class="proj">Projeção: <b class="{cls}">{vantagem(proj["margem_proj"])}</b><br>'
                     f'<span class="t1">Chance: <b class="f">Flávio {chance(pf_)}</b> · <b class="l">Lula {chance(1 - pf_)}</b></span></div>')
    else:
        proj_html = ""
    t1 = f'<div class="t1">1º turno: {vantagem(m1t)}</div>' if m1t is not None else ""
    return (f'<div class="ap-rc {classe}"><div class="topo"><span class="nome">{nome}</span>'
            f'<span class="apu">{br(apurado, 0)}% apurado</span></div>'
            f'<div class="mini"><span style="width:{min(apurado, 100):.1f}%"></span></div>'
            f'<div class="split">{split}</div>{votos}{proj_html}{t1}</div>')


def aba_apuracao():
    @st.fragment(run_every=60)
    def corpo():
        r, snap, hist = estado_atual()
        if r is not None and r.get("origem") == "bu":
            painel_exterior(snap)
            return
        if antes_das_17h(r):
            duelo(0.5, 0.5, "—", "—", "aguardando a apuração", "aguardando a apuração")
            st.info("A divulgação do TSE começa às **17h (Brasília)**. Esta página se atualiza sozinha a cada minuto.")
            with st.expander("Como ler este painel", expanded=True):
                st.markdown(COMO_LER)
            return
        placar_nacional(r, snap)
        st.html('<div class="ap-sec">Por região</div><p class="ap-secsub">Contagem do TSE (barra), projeção do modelo e '
                'chance de cada candidato vencer na região. Detalhes por estado na aba <b>Regiões e estados</b>.</p>')
        grade_regioes(r, snap)
        st.html('<div class="ap-sec">A noite até agora</div>')
        graficos(hist)
        with st.expander("Como ler estes números"):
            st.markdown(COMO_LER)

    corpo()


@st.cache_data(ttl=60)
def total_oficial(snap: str) -> dict:
    """Total nacional como o TSE publica (o mesmo da TV). Os arquivos por estado e por cidade chegam depois."""
    return json.loads((Path(snap) / "meta.json").read_text()).get("br", {})


def placar_nacional(r: dict, snap: Path):
    tot = total_oficial(str(snap))
    a = 100 * tot["st"] / tot["ts"] if tot.get("ts") else r["pct_apurado"]
    hora = (r.get("tse_ht") or "")[:5]
    F, L = float(tot.get("flavio", 0)), float(tot.get("lula", 0))
    v = F + L
    proj_f = 50 + r["margem_mediana"] / 2
    status = "Decidido" if r["decidido"] else "Ao vivo"
    st.html(f'<span class="ap-chip">● {status}</span><span class="ap-chip">atualizado às {hora}</span>'
            + ('<span class="ap-chip">dados digitados à mão</span>' if r.get("origem") == "manual" else ""))
    st.html(f"""
<div class="ap-duelo">
  <div class="ap-card f"><div class="quem">Flávio Bolsonaro (PL)</div><div class="ap-num">{chance(r['p_flavio'])}</div>
    <div class="sub">chance de vencer</div>
    <div class="linha"><span>Contagem do TSE</span><b>{br(100 * F / v) if v else '—'}% · {br(F, 0)}</b></div>
    <div class="linha"><span>Projeção final</span><b>{br(proj_f)}%</b></div></div>
  <div class="ap-card l"><div class="quem">Lula (PT)</div><div class="ap-num">{chance(r['p_lula'])}</div>
    <div class="sub">chance de vencer</div>
    <div class="linha"><span>Contagem do TSE</span><b>{br(100 * L / v) if v else '—'}% · {br(L, 0)}</b></div>
    <div class="linha"><span>Projeção final</span><b>{br(100 - proj_f)}%</b></div></div>
</div>
<div class="ap-barra" role="img" aria-label="Chance: Flávio {pct(r['p_flavio'])}, Lula {pct(r['p_lula'])}">
  <span class="f" style="width:{100 * r['p_flavio']:.2f}%"></span><span class="l" style="width:{100 * r['p_lula']:.2f}%"></span></div>
<div class="ap-legbarra"><span>chance de Flávio</span><span>chance de Lula</span></div>
<div class="ap-prog"><div class="rot"><span>Seções apuradas (TSE)</span><b>{br(a, 2)}%</b></div>
  <div class="trilho"><span style="width:{min(a, 100):.2f}%"></span></div></div>""")

    if r.get("origem") == "manual":
        st.info("Os números desta atualização foram digitados à mão a partir do app oficial do TSE, porque o site de "
                "resultados não respondeu. Podem ter pequenas diferenças.")
    if r["decidido"]:
        st.success(f"**Matematicamente decidido.** A vantagem de {r['lider_atual']} já é maior que o número de "
                   f"eleitores que faltam apurar: nem se todos votassem no outro candidato o resultado mudaria.")
    lo, hi = r["margem_80"]
    st.markdown(
        f"#### Resultado projetado: {placar(r['margem_mediana'])}\n"
        f"Faixa provável (8 em cada 10 simulações): **{faixa(lo, hi)}** pontos. "
        f"Diferença final estimada: cerca de **{milhoes(r['votos_mediana'])}** de votos para "
        f"{'Flávio' if r['votos_mediana'] > 0 else 'Lula'}."
    )
    if not r["decidido"] and r["restante_validos_proj"] > 0 and r.get("margem_atual") is not None:
        p = r["atrasado_precisa"]
        txt = (f"**Para virar**, {r['atrasado']} precisaria de **{br(100 * p)}%** dos votos que ainda faltam contar "
               f"(cerca de {milhoes(r['restante_validos_proj'])}).")
        st.markdown(txt + (" Isso é impossível." if p > 1 else ""))
    if a < 10:
        st.warning("**Ainda é cedo.** Com menos de 10% das urnas, quem chegou primeiro (exterior, cidades pequenas) "
                   "não representa o resto do país. O modelo está sendo cauteloso de propósito.")
    elif a >= 70 and lo < 0 < hi:
        st.warning(f"**Disputa apertada.** Mesmo com {br(a, 0)}% apurado, a faixa provável ainda inclui vitória dos dois. "
                   "Nesse caso, não dá para cravar antes do fim.")


def grade_regioes(r: dict | None, snap: Path | None, so: list[str] | None = None):
    m1t = t1_regiao()
    proj = {g["regiao"]: g for g in (r or {}).get("regioes", [])} if not antes_das_17h(r) else {}
    if snap is not None and not antes_das_17h(r):
        c = contagem_uf(str(snap)).groupby("regiao")[["flavio", "lula"]].sum()
        apur = {g["regiao"]: g["pct_apurado"] for g in r.get("regioes", [])} or \
            {k: v for k, v in (100 * contagem_uf(str(snap)).groupby("regiao").est.sum()
                               / contagem_uf(str(snap)).groupby("regiao").te.sum()).items()}
    else:
        c, apur = pd.DataFrame(columns=["flavio", "lula"]), {}
    html = []
    for g in (so or REG_ORDEM):
        f = float(c.flavio.get(g, 0)) if len(c) else 0.0
        l = float(c.lula.get(g, 0)) if len(c) else 0.0
        html.append(cartao(REG_NOME[g], apur.get(g, 0.0), f, l, proj.get(g), m1t.get(g)))
    st.html('<div class="ap-grid">' + "".join(html) + "</div>")


def aba_regioes():
    @st.fragment(run_every=60)
    def corpo():
        r, snap, hist = estado_atual()
        cedo = antes_das_17h(r)
        if cedo:
            st.info("A apuração por estado começa às **17h (Brasília)**. Por enquanto, os cartões mostram o resultado do "
                    "1º turno de cada região e estado, só entre Flávio e Lula, para referência.")
        opcoes = ["Brasil"] + [REG_NOME[g] for g in REG_ORDEM if g != "EX"]
        escolha = st.segmented_control("Região", opcoes, default="Brasil", key="regiao_sel") or "Brasil"
        cod = {v: k for k, v in REG_NOME.items()}.get(escolha)

        st.html(f'<div class="ap-sec">{"Regiões" if escolha == "Brasil" else escolha}</div>')
        grade_regioes(r, snap, None if escolha == "Brasil" else [cod])

        b = base_t1()
        ufs = b[b.uf != "zz"] if escolha == "Brasil" else b[b.regiao == cod]
        proj = {} if cedo else {x["uf"]: x for x in r["uf"]}
        cont = contagem_uf(str(snap)).set_index("uf") if (snap is not None and not cedo) else None

        # Mapa
        if not cedo:
            modo = st.segmented_control("Colorir o mapa por", ["Projeção final", "Contagem do TSE"],
                                        default="Projeção final", key="mapa_modo") or "Projeção final"
            t = pd.DataFrame(r["uf"])
            t = t[t.uf.isin(ufs.uf)]
            t["apurado"] = t.pct_apurado
            t["margem"] = t.margem_proj if modo == "Projeção final" else t.margem_atual
            mapa(t[t.margem.notna()], f"{escolha}: {'projeção final' if modo == 'Projeção final' else 'contagem do TSE'} por estado",
                 rot="Projeção" if modo == "Projeção final" else "Contagem")
        else:
            t = ufs.rename(columns={"margem_1t": "margem"})[["uf", "margem"]]
            mapa(t, f"{escolha}: resultado do 1º turno por estado (só Flávio x Lula)", rot="1º turno")

        # Cartões dos estados (do mais Flávio ao mais Lula na projeção, ou no 1º turno)
        ordem = ufs.assign(chave=[(proj[u]["margem_proj"] if u in proj else m) for u, m in zip(ufs.uf, ufs.margem_1t)]) \
            .sort_values("chave", ascending=False)
        html = []
        for _, x in ordem.iterrows():
            f = float(cont.at[x.uf, "flavio"]) if cont is not None and x.uf in cont.index else 0.0
            l = float(cont.at[x.uf, "lula"]) if cont is not None and x.uf in cont.index else 0.0
            p = proj.get(x.uf)
            html.append(cartao(nomes_uf()[x.uf], p["pct_apurado"] if p else 0.0, f, l, p, x.margem_1t))
        st.html(f'<div class="ap-sec">{"Todos os estados" if escolha == "Brasil" else "Estados: " + escolha}</div>'
                '<p class="ap-secsub">Ordenados de onde Flávio está mais forte para onde Lula está mais forte.</p>'
                f'<div class="ap-grid uf">{"".join(html)}</div>')

        # Detalhe de um estado
        nomes = {nomes_uf()[u]: u for u in ordem.uf}
        sel = st.selectbox("Ver um estado em detalhe", ["—"] + sorted(nomes), key="uf_detalhe")
        if sel != "—":
            detalhe_estado(nomes[sel], r, snap, hist, cedo)

    corpo()


def detalhe_estado(uf: str, r: dict | None, snap: Path | None, hist: list[dict], cedo: bool):
    b = base_t1().set_index("uf").loc[uf]
    nome, reg = nomes_uf()[uf], REG_NOME[model.REGIAO[uf]]
    p = None if cedo else next((x for x in r["uf"] if x["uf"] == uf), None)
    c = None if cedo else contagem_uf(str(snap)).set_index("uf").loc[uf]
    F, L = (float(c.flavio), float(c.lula)) if c is not None else (0.0, 0.0)
    v = F + L
    kpis = []
    if p:
        kpis += [("Apurado", f"{br(p['pct_apurado'])}%"),
                 ("Projeção", vantagem(p["margem_proj"])),
                 ("Faixa provável", faixa(p["p10"], p["p90"])),
                 ("Chance de Flávio", chance(p["p_flavio"])), ("Chance de Lula", chance(1 - p["p_flavio"]))]
    if c is not None and c.est and c.comp:
        kpis.append(("Comparecimento até agora", f"{br(100 * c.comp / c.est)}%"))
        if c.comp:
            kpis.append(("Brancos e nulos", f"{br(100 * (c.brancos + c.nulos) / c.comp)}%"))
    kpis += [("Comparecimento no 1º turno", f"{br(b.comp_1t)}%"), ("1º turno (só os dois)", vantagem(b.margem_1t))]
    st.html(f'<div class="ap-det"><h3>{nome}</h3><span class="ap-secsub">{reg}</span>'
            + (f'<div class="ap-duelo" style="margin-top:.6rem"><div class="ap-card f"><div class="quem">Flávio</div>'
               f'<div class="ap-num" style="font-size:2rem">{br(F, 0)}</div><div class="sub">votos contados · {br(100 * F / v)}%</div></div>'
               f'<div class="ap-card l"><div class="quem">Lula</div><div class="ap-num" style="font-size:2rem">{br(L, 0)}</div>'
               f'<div class="sub">votos contados · {br(100 * L / v)}%</div></div></div>' if v else "")
            + '<div class="ap-kpis">' + "".join(f'<div class="ap-kpi"><div class="k">{k}</div><div class="v">{val}</div></div>'
                                                for k, val in kpis) + "</div></div>")

    # 1º turno x contagem x projeção, em barras de 100%
    linhas = [("1º turno", 50 + b.margem_1t / 2)]
    if v:
        linhas.append(("Contagem agora", 100 * F / v))
    if p:
        linhas.append(("Projeção final", 50 + p["margem_proj"] / 2))
    linhas = linhas[::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=[x[0] for x in linhas], x=[x[1] for x in linhas], orientation="h", name="Flávio",
                         marker_color=FLAVIO, text=[f"Flávio {br(x[1])}%" for x in linhas], textposition="inside",
                         insidetextanchor="start", hovertemplate="%{y}: Flávio %{x:.1f}%<extra></extra>"))
    fig.add_trace(go.Bar(y=[x[0] for x in linhas], x=[100 - x[1] for x in linhas], orientation="h", name="Lula",
                         marker_color=LULA, text=[f"Lula {br(100 - x[1])}%" for x in linhas], textposition="inside",
                         insidetextanchor="end", hovertemplate="%{y}: Lula %{x:.1f}%<extra></extra>"))
    fig.add_vline(x=50, line_color="white", line_width=2)
    layout(fig, h=90 + 48 * len(linhas), barmode="stack", showlegend=False, hovermode="closest",
           title=f"{nome}: votos entre os dois", xaxis=dict(range=[0, 100], ticksuffix="%", showgrid=False),
           bargap=0.35)
    fig.update_traces(marker_line_width=0, textfont=dict(color="white", size=13))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # Evolução no estado ao longo da noite
    if p and len(hist) > 1:
        ev = [{"apurado": h["pct_apurado"], **x} for h in hist for x in h.get("uf", []) if x["uf"] == uf]
        ev = pd.DataFrame(ev)
        if len(ev) > 1:
            f2 = go.Figure()
            f2.add_trace(go.Scatter(x=pd.concat([ev.apurado, ev.apurado[::-1]]), y=pd.concat([ev.p90, ev.p10[::-1]]),
                                    fill="toself", fillcolor="rgba(107,107,102,0.16)", line=dict(width=0),
                                    hoverinfo="skip", name="faixa provável"))
            f2.add_trace(go.Scatter(x=ev.apurado, y=ev.margem_proj, mode="lines", line=dict(color=TINTA, width=2.5),
                                    name="projeção", customdata=[vantagem(m) for m in ev.margem_proj],
                                    hovertemplate="projeção: %{customdata}<extra></extra>"))
            f2.add_trace(go.Scatter(x=ev.apurado, y=ev.margem_atual, mode="lines", line=dict(color=NEUTRO, width=2, dash="dot"),
                                    name="contagem do TSE", customdata=[vantagem(m) for m in ev.margem_atual],
                                    hovertemplate="contagem: %{customdata}<extra></extra>"))
            f2.add_hline(y=0, line_color=NEUTRO, line_width=1)
            layout(f2, h=300, title=f"{nome} ao longo da noite (vantagem em pontos)",
                   xaxis_title="% das urnas apuradas no país", legend=dict(orientation="h", y=-0.3))
            st.plotly_chart(f2, width="stretch", config={"displayModeBar": False})


def graficos(hist: list[dict]):
    df = pd.DataFrame([{
        "t": (h.get("tse_ht") or h["snapshot"])[:5], "apurado": h["pct_apurado"], "pf": 100 * h["p_flavio"],
        "proj": h["margem_mediana"], "lo": h["margem_80"][0], "hi": h["margem_80"][1], "atual": h["margem_atual"],
    } for h in hist])
    c1, c2 = st.columns(2)
    f1 = go.Figure()
    f1.add_trace(go.Scatter(x=df.apurado, y=df.pf, mode="lines", line=dict(color=FLAVIO, width=0), fill="tozeroy",
                            fillcolor=FLAVIO_CLARO, hoverinfo="skip", showlegend=False))
    f1.add_trace(go.Scatter(x=df.apurado, y=df.pf, mode="lines+markers", line=dict(color=FLAVIO, width=2.5),
                            marker=dict(size=6), customdata=np.c_[df.t, 100 - df.pf], showlegend=False,
                            hovertemplate="%{customdata[0]} · %{x:.1f}% apurado<br>Flávio %{y:.0f}% · Lula %{customdata[1]:.0f}%<extra></extra>"))
    f1.add_hline(y=50, line_width=1, line_dash="dot", line_color=NEUTRO)
    f1.add_annotation(x=0.01, y=97, xref="paper", xanchor="left", showarrow=False, text="↑ Flávio favorito", font=dict(color=FLAVIO))
    f1.add_annotation(x=0.01, y=3, xref="paper", xanchor="left", showarrow=False, text="↓ Lula favorito", font=dict(color=LULA))
    layout(f1, title="Chance de Flávio vencer ao longo da noite", xaxis_title="% das urnas apuradas",
           yaxis=dict(range=[0, 100], ticksuffix="%"), hovermode="closest")
    c1.plotly_chart(f1, width="stretch")
    c1.caption("Acima da linha pontilhada, Flávio é o favorito; abaixo, Lula.")

    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=pd.concat([df.apurado, df.apurado[::-1]]), y=pd.concat([df.hi, df.lo[::-1]]),
                            fill="toself", fillcolor="rgba(107,107,102,0.16)", line=dict(width=0), hoverinfo="skip",
                            name="faixa provável"))
    f2.add_trace(go.Scatter(x=df.apurado, y=df.proj, mode="lines", line=dict(color=TINTA, width=2.5),
                            name="projeção do modelo", hovertemplate="projeção %{y:+.1f}<extra></extra>"))
    f2.add_trace(go.Scatter(x=df.apurado, y=df.atual, mode="lines", line=dict(color=NEUTRO, width=2, dash="dot"),
                            name="contagem do TSE", hovertemplate="contagem %{y:+.1f}<extra></extra>"))
    f2.add_hline(y=0, line_width=1, line_color=NEUTRO)
    ok = df[df.apurado >= 1] if (df.apurado >= 1).any() else df   # as primeiras urnas (0,1%) achatariam a escala
    vals = pd.concat([ok.lo, ok.hi, ok.atual.dropna(), pd.Series([0.0])])
    lo_y, hi_y = vals.min() - 1, vals.max() + 1
    f2.add_hrect(y0=0, y1=hi_y, fillcolor=FLAVIO_CLARO, line_width=0, layer="below")
    f2.add_hrect(y0=lo_y, y1=0, fillcolor=LULA_CLARO, line_width=0, layer="below")
    f2.add_annotation(x=1, y=hi_y, xref="paper", xanchor="right", yanchor="top", showarrow=False, text="Flávio à frente ↑", font=dict(color=FLAVIO))
    f2.add_annotation(x=1, y=lo_y, xref="paper", xanchor="right", yanchor="bottom", showarrow=False, text="Lula à frente ↓", font=dict(color=LULA))
    layout(f2, title="Vantagem em pontos: contagem do TSE x projeção", xaxis_title="% das urnas apuradas",
           yaxis=dict(range=[lo_y, hi_y]), legend=dict(orientation="h", y=-0.3))
    c2.plotly_chart(f2, width="stretch")
    c2.caption("Pontilhada: a contagem do TSE, que oscila muito no começo. Cheia: a projeção do resultado final. "
               "Faixa cinza: onde o resultado deve cair.")


# ================================================================ Exterior (antes das 17h)

@st.cache_data(ttl=120)
def dados_exterior(snap: str) -> tuple[pd.DataFrame, dict]:
    sec = pd.read_csv(Path(snap) / "secoes.csv", dtype={"mun": str, "zona": str, "secao": str})
    meta = json.loads((Path(snap) / "meta.json").read_text())
    base = pd.read_csv(ROOT / "data" / "base" / "t1_2026_mun.csv", dtype={"cd_tse": str})
    base["cd_tse"] = base.cd_tse.str.zfill(5)
    zz = base[base.uf == "zz"].set_index("cd_tse")
    g = sec.groupby("mun").agg(secoes=("secao", "size"), comp=("comp", "sum"), lula=("lula", "sum"),
                               flavio=("flavio", "sum"), ultimo=("recebido", "max")).reset_index()
    g["cidade"] = g.mun.map(zz.nome).str.title()
    g["lula_1t"] = g.mun.map(100 * zz.lula / (zz.lula + zz.flavio))
    g["lula_2t"] = 100 * g.lula / (g.lula + g.flavio).where(g.lula + g.flavio > 0)
    info = {
        "secoes": int(len(sec)),
        "aptos_contados": int(sec.aptos.sum()), "aptos_exterior": int(zz.te.sum()), "aptos_brasil": int(base.te.sum()),
        "lula_1t_exterior": float(100 * zz.lula.sum() / (zz.lula + zz.flavio).sum()),
        "ultimo": meta.get("ultimo_bu", ""),
    }
    return g, info


def painel_exterior(snap: Path):
    g, i = dados_exterior(str(snap))
    L, F = int(g.lula.sum()), int(g.flavio.sum())
    v = L + F
    # O que as mesmas cidades deram no 1º turno, com o peso dos votos contados agora
    v_c = g.lula + g.flavio
    esperado = float((g.lula_1t * v_c).sum() / v_c.sum()) if v else float("nan")
    agora = 100 * L / v if v else float("nan")

    st.html(f'<span class="ap-chip">Antes das 17h</span><span class="ap-chip">último boletim: {i["ultimo"][-8:-3]}</span>'
            f'<span class="ap-chip">{i["secoes"]} urnas do exterior contadas</span>')
    st.markdown(
        "### Votos do exterior, urna por urna\n"
        "O TSE só soma e divulga o resultado às **17h de Brasília**. Mas, nos países onde a votação já acabou, "
        "o boletim de cada urna já está publicado no site do TSE. Este painel lê esses boletins oficiais e soma. "
        "**A chance de vitória nacional só aparece depois das 17h**: o exterior é menos de 1% do eleitorado e vota "
        "muito diferente do Brasil."
    )
    duelo(F / v if v else .5, L / v if v else .5, br(F, 0), br(L, 0),
          f"votos ({br(100 * F / v)}% dos dois)" if v else "votos", f"votos ({br(100 * L / v)}% dos dois)" if v else "votos")
    st.caption(f"Votos contados em {i['secoes']} urnas do exterior, com {br(i['aptos_contados'], 0)} eleitores aptos "
               f"({br(100 * i['aptos_contados'] / i['aptos_exterior'], 0)}% do exterior e "
               f"{br(100 * i['aptos_contados'] / i['aptos_brasil'], 2)}% do país).")

    if v:
        delta = agora - esperado
        quem = "Lula" if delta > 0 else "Flávio"
        st.markdown(
            f"#### O placar acima engana. Compare cidade com cidade.\n"
            f"As primeiras urnas vêm da Ásia e da Oceania, e as maiores são as do **Japão**, onde Flávio teve mais de "
            f"75% no 1º turno. No exterior inteiro, no 1º turno, Lula teve **{br(i['lula_1t_exterior'])}%** dos votos "
            f"dados aos dois.\n\n"
            f"Nas **mesmas cidades** que já foram contadas, Lula tinha **{br(esperado)}%** no 1º turno e agora tem "
            f"**{br(agora)}%**: {'uma diferença pequena' if abs(delta) < 1 else 'uma mudança'} de "
            f"**{br(abs(delta))} ponto{'s' if abs(delta) >= 2 else ''} a favor de {quem}**. Parte de qualquer mudança é "
            f"natural: no 2º turno, quem votou nos outros 10 candidatos precisa escolher entre os dois."
        )
        top = g.sort_values("comp", ascending=False).head(15).iloc[::-1]
        fig = go.Figure()
        for _, r in top.iterrows():
            fig.add_trace(go.Scatter(x=[r.lula_1t, r.lula_2t], y=[r.cidade] * 2, mode="lines",
                                     line=dict(color="#c9c7c0", width=3), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=top.lula_1t, y=top.cidade, mode="markers", name="1º turno",
                                 marker=dict(color="white", size=11, line=dict(color=NEUTRO, width=2)),
                                 hovertemplate="%{y}: Lula %{x:.1f}% no 1º turno<extra></extra>"))
        fig.add_trace(go.Scatter(x=top.lula_2t, y=top.cidade, mode="markers", name="agora (2º turno)",
                                 marker=dict(color=[LULA if x >= 50 else FLAVIO for x in top.lula_2t], size=12,
                                             line=dict(color="white", width=1.5)),
                                 customdata=np.c_[top.secoes, top.comp],
                                 hovertemplate="%{y}: Lula %{x:.1f}% agora<br>%{customdata[0]} urnas, %{customdata[1]} votantes<extra></extra>"))
        fig.add_vline(x=50, line_color=NEUTRO, line_width=1, line_dash="dot")
        fig.add_vrect(x0=0, x1=50, fillcolor=FLAVIO_CLARO, line_width=0, layer="below")
        fig.add_vrect(x0=50, x1=100, fillcolor=LULA_CLARO, line_width=0, layer="below")
        fig.add_annotation(x=2, y=1.04, yref="paper", xanchor="left", showarrow=False, text="← Flávio na frente", font=dict(color=FLAVIO))
        fig.add_annotation(x=98, y=1.04, yref="paper", xanchor="right", showarrow=False, text="Lula na frente →", font=dict(color=LULA))
        layout(fig, h=max(320, 34 * len(top) + 120), title="% de Lula entre os dois: 1º turno x agora",
               xaxis=dict(range=[0, 100], ticksuffix="%"), yaxis=dict(automargin=True), hovermode="closest",
               legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("As 15 cidades com mais votos contados. Se a bolinha cheia está à direita do círculo, Lula melhorou "
                   "naquela cidade em relação ao 1º turno; à esquerda, Flávio melhorou.")
        with st.expander("Ver todas as cidades contadas"):
            t = g.sort_values("comp", ascending=False)
            st.dataframe(pd.DataFrame({
                "Cidade": t.cidade, "Urnas": t.secoes, "Votantes": t.comp, "Flávio": t.flavio, "Lula": t.lula,
                "Lula agora (%)": t.lula_2t.round(1), "Lula no 1º turno (%)": t.lula_1t.round(1),
                "Chegada": t.ultimo.str[-8:-3]}), hide_index=True, width="stretch")
    st.info("Às 17h, o painel passa sozinho para a apuração oficial do TSE, com a chance de vitória de cada candidato. "
            "Esta página se atualiza a cada minuto.")


# ================================================================ Como funciona

def aba_como_funciona():
    st.markdown("""
### Em uma frase
O painel compara cada cidade já apurada com o que ela votou no 1º turno e usa essa mudança para estimar
as cidades que ainda faltam.

### Passo a passo
1. **Ponto de partida.** Para cada uma das 5.757 cidades (e para os votos do exterior), partimos do resultado oficial do
   1º turno e estimamos para onde vão os eleitores dos outros candidatos. A estimativa usa a pesquisa Datafolha:
   46% desses eleitores vão para Flávio, 32% para Lula e o resto vota branco, anula ou não vai votar.
2. **Dados oficiais a cada minuto.** O painel baixa do site de resultados do TSE os números de cada cidade.
3. **Medir a surpresa.** Em cada cidade já apurada, Flávio foi melhor ou pior do que o esperado? Por quanto?
4. **Aprender o padrão.** As surpresas se parecem dentro de um mesmo estado, de uma mesma região, entre cidades do mesmo
   tamanho? Cada cidade que falta recebe a surpresa típica das cidades parecidas com ela que já foram contadas.
5. **Simular.** O painel sorteia 2.000 resultados possíveis para as urnas que faltam, com a margem de incerteza que
   cada parte tem, e conta em quantos cada candidato vence. Daí sai a **chance de vitória**, no país, em cada região
   e em cada estado.
6. **Ficar mais seguro com o tempo.** Quanto mais urnas contadas, menos sobra para adivinhar e mais estreita fica a
   faixa provável. No comecinho da noite o modelo é cauteloso de propósito.

Antes de domingo, o modelo foi testado reapresentando as apurações do 2º turno de 2022 e do 1º turno de 2026 como se
fossem ao vivo.

### Limites (leia antes de apostar alguma coisa)
- **Não é pesquisa nem resultado oficial.** Só o TSE declara o resultado.
- **Pode errar.** A chance de vitória é uma estimativa; com 80%, o favorito ainda perde 1 em cada 5 vezes.
- **Se o site do TSE falhar**, os números podem ser digitados à mão a partir do app oficial, e o painel avisa quando isso acontecer.

### Glossário
- **Votos válidos**: todos os votos menos brancos e nulos. É sobre eles que se calcula quem ganha.
- **Ponto percentual**: diferença entre duas porcentagens. 51% contra 49% são 2 pontos de vantagem.
- **Chance de vitória**: em quantas de 100 repetições da mesma situação o candidato venceria.
- **Faixa provável**: onde o resultado final cai em 8 de cada 10 simulações.
- **Apurado**: parte do eleitorado cujas urnas o TSE já contou.
- **Projeção final**: a estimativa do modelo para o resultado quando todas as urnas forem contadas.

*Projeto pessoal, sem vínculo com partidos, institutos ou com o TSE. Dados oficiais do TSE
(resultados.tse.jus.br e dadosabertos.tse.jus.br).*
""")


# ================================================================ Antes =====

CENARIOS = {
    "Base": {
        "resumo": "As suposições centrais, tiradas dos dados.",
        "porque": "Retenção de 99% (o que as urnas de 2018 e 2022 mostram), eleitores dos outros candidatos divididos "
                  "como na pesquisa Datafolha (46% Flávio, 32% Lula), comparecimento igual ao do 1º turno.",
    },
    "Vento a favor de Flávio": {
        "resumo": "Tudo o que é incerto pende um pouco para Flávio.",
        "porque": "Os eleitores dos outros candidatos vão mais para Flávio (55%, como em 2022 para Bolsonaro), 2% dos "
                  "eleitores de Lula não repetem o voto e as pesquisas subestimam Flávio em 1 ponto, como aconteceu no "
                  "1º turno.",
    },
    "Vento a favor de Lula": {
        "resumo": "Tudo o que é incerto pende um pouco para Lula.",
        "porque": "Os eleitores dos outros candidatos se dividem quase igual (40% Flávio, 38% Lula), 2% dos eleitores de "
                  "Flávio não repetem o voto e as pesquisas subestimam Lula em 1 ponto.",
    },
    "Nordeste vai mais às urnas": {
        "resumo": "Mobilização forte no Nordeste, onde Lula tem mais votos.",
        "porque": "Comparecimento 2 pontos maior no Nordeste do que no 1º turno. Os novos eleitores votam parecido com a "
                  "própria cidade. Em 2022, o Nordeste subiu 0,2 ponto do 1º para o 2º turno.",
    },
    "Sudeste falta mais": {
        "resumo": "Mais gente deixa de votar no Sudeste, onde Flávio venceu o 1º turno.",
        "porque": "Comparecimento 2 pontos menor em São Paulo, Minas, Rio e Espírito Santo. Em 2018, o Sudeste caiu 0,5 "
                  "ponto do 1º para o 2º turno.",
    },
    "Repete 2022": {
        "resumo": "Os votos migram como migraram em 2022.",
        "porque": "Medimos nas urnas de 2022 para onde foram os eleitores dos outros candidatos: 55% para Bolsonaro, 33% "
                  "para Lula. Aqui aplicamos isso a 2026, incluindo o efeito “quem lidera no estado ganha mais”.",
    },
}


@st.cache_data
def base_uf() -> pd.DataFrame:
    return model.carregar_base()


@st.cache_data
def rodar_a(params: tuple) -> dict:
    return model.simular(base_uf(), dict(params), N_SIM)


@st.cache_data
def resumo_cenarios() -> pd.DataFrame:
    rows = []
    for nome in model.PRESETS:
        r = model.resumo(model.simular(base_uf(), model.medias(nome), N_SIM))
        rows.append({"cenario": nome, **{k: r[k] for k in ("p_flavio", "margem_mediana")},
                     "lo": r["margem_80"][0], "hi": r["margem_80"][1]})
    return pd.DataFrame(rows)


@st.cache_data
def rodar_tornado(params: tuple) -> pd.DataFrame:
    return model.tornado(base_uf(), dict(params))


def fmt_param(k: str, v: float) -> str:
    if k.startswith("dA_") or k in ("vies_nac", "sigma_nac", "sigma_reg", "sigma_uf"):
        return f"{'+' if v > 0 else ''}{br(v, 1)} ponto{'s' if abs(v) >= 2 else ''}"
    if k == "kappa":
        return br(v, 2)
    return br(100 * v, 0) + "%"


def aba_antes():
    st.markdown("""
Antes de abrir a primeira urna, dá para fazer contas com o resultado do 1º turno e com as pesquisas. **Isto é um
cenário, não uma previsão**: depende de suposições, como para onde vão os eleitores dos outros 10 candidatos,
quanta gente muda de lado e quanta gente deixa de votar. Abaixo, seis cenários lado a lado; depois, escolha um para
ver os detalhes ou mexa você mesmo nas suposições.
""")
    cen = resumo_cenarios()
    fig = go.Figure()
    for _, r in cen.iloc[::-1].iterrows():
        cor = FLAVIO if r.margem_mediana > 0 else LULA
        fig.add_trace(go.Scatter(x=[r.lo, r.hi], y=[r.cenario] * 2, mode="lines", line=dict(color=cor, width=8),
                                 opacity=0.35, hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=[r.margem_mediana], y=[r.cenario], mode="markers", showlegend=False,
                                 marker=dict(color=cor, size=13, line=dict(color="white", width=2)),
                                 customdata=[[placar(r.margem_mediana), vantagem(r.lo), vantagem(r.hi)]],
                                 hovertemplate="%{y}<br>mais provável: %{customdata[0]}<br>faixa: %{customdata[1]} a %{customdata[2]}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[r.hi], y=[r.cenario], mode="text", showlegend=False, hoverinfo="skip",
                                 text=[f"   Flávio vence em {br(100 * r.p_flavio, 0)} de 100"], textposition="middle right",
                                 textfont=dict(color=TINTA)))
    fig.add_vline(x=0, line_color=NEUTRO, line_width=1)
    xmin, xmax = min(cen.lo.min(), -1) - 1, max(cen.hi.max(), 1) + 8
    fig.add_vrect(x0=xmin, x1=0, fillcolor=LULA_CLARO, line_width=0, layer="below")
    fig.add_vrect(x0=0, x1=xmax, fillcolor=FLAVIO_CLARO, line_width=0, layer="below")
    fig.add_annotation(x=xmin, y=1.06, yref="paper", xanchor="left", showarrow=False, text="← Lula vence", font=dict(color=LULA))
    fig.add_annotation(x=xmax, y=1.06, yref="paper", xanchor="right", showarrow=False, text="Flávio vence →", font=dict(color=FLAVIO))
    layout(fig, h=380, title="Os seis cenários: resultado mais provável (bolinha) e faixa provável (barra)",
           xaxis=dict(range=[xmin, xmax], title="vantagem final em pontos", tickvals=list(range(-10, 15, 2)),
                      ticktext=[vantagem(v, 0) if v else "empate" for v in range(-10, 15, 2)]),
           yaxis=dict(automargin=True), hovermode="closest")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    preset = st.radio("Ver em detalhe", list(model.PRESETS), horizontal=True)
    c = CENARIOS[preset]
    base_m, mm = model.medias("Base"), model.medias(preset)
    mudou = [(model.PARAMS[k].rotulo, fmt_param(k, base_m[k]), fmt_param(k, mm[k])) for k in model.PARAMS if mm[k] != base_m[k]]
    linhas = "".join(f"<li>{rot}: <b>{v1}</b> (no Base: {v0})</li>" for rot, v0, v1 in mudou)
    st.html(f'<div class="ap-box"><b>{preset}.</b> {c["resumo"]}<br><span style="color:#3d3d3a">{c["porque"]}</span>'
            + (f"<ul style='margin:.5rem 0 0'>{linhas}</ul>" if linhas else "") + "</div>")

    if st.session_state.get("_preset") != preset:
        for k, v in mm.items():
            st.session_state[k] = float(v)
        st.session_state["_preset"] = preset

    with st.expander("Mexer nas suposições (para curiosos)"):
        st.caption("Passe o mouse no ícone ⓘ de cada controle para ver de onde veio o valor inicial.")
        grupos = {
            "Incerteza geral": ["vies_nac", "sigma_nac", "sigma_reg", "sigma_uf"],
            "Eleitores de outros candidatos e brancos/nulos": ["tF", "tL", "t_reg_dp", "kappa", "bF", "bL"],
            "Quem continua votando no mesmo candidato": ["rL", "rF", "dLF", "dFL"],
            "Comparecimento por região": [f"dA_{r}" for r in model.REGIOES] + ["mL_dp"],
        }
        cols = st.columns(2)
        for i, (g, ks) in enumerate(grupos.items()):
            with cols[i % 2]:
                st.markdown(f"**{g}**")
                for k in ks:
                    p = model.PARAMS[k]
                    st.slider(p.rotulo, float(p.lo), float(p.hi), step=0.005 if p.hi - p.lo <= 1 else 0.05,
                              key=k, help=p.origem)
        sens = st.checkbox("Mostrar o que mais muda o resultado (leva ~10 s)")

    params = tuple(sorted((k, float(st.session_state[k])) for k in model.PARAMS))
    sim = rodar_a(params)
    r = model.resumo(sim)
    duelo(r["p_flavio"], r["p_lula"], f"{br(100 * r['p_flavio'], 0)} em 100", f"{br(100 * r['p_lula'], 0)} em 100",
          "simulações em que vence", "simulações em que vence")
    st.markdown(f"#### Resultado mais provável: {placar(r['margem_mediana'])}\n"
                f"Faixa provável: **{faixa(r['margem_80'][0], r['margem_80'][1])}** pontos.")

    m = sim["margem"]
    bins = np.linspace(np.floor(m.min()), np.ceil(m.max()), 61)
    cont, bordas = np.histogram(m, bins)
    centro = (bordas[:-1] + bordas[1:]) / 2
    fig = go.Figure(go.Bar(x=centro, y=100 * cont / len(m), marker_color=[FLAVIO if x > 0 else LULA for x in centro],
                           marker_line_width=0, customdata=[vantagem(x) for x in centro],
                           hovertemplate="%{customdata}<br>%{y:.1f}% das simulações<extra></extra>"))
    fig.add_vline(x=0, line_width=1, line_color=NEUTRO)
    fig.add_annotation(x=bordas[-1], y=1.02, yref="paper", xanchor="right", showarrow=False, text="Flávio vence →", font=dict(color=FLAVIO))
    fig.add_annotation(x=bordas[0], y=1.02, yref="paper", xanchor="left", showarrow=False, text="← Lula vence", font=dict(color=LULA))
    layout(fig, title=f"Os {br(N_SIM, 0)} resultados simulados", bargap=0.08, yaxis_title="% das simulações",
           xaxis_title="vantagem final em pontos (à direita, Flávio; à esquerda, Lula)", showlegend=False, hovermode="closest")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Cada barra é um resultado possível; quanto mais alta, mais vezes ele apareceu.")

    t = model.tabela_uf(base_uf(), sim)
    mapa(t.rename(columns={"margem_proj": "margem"}), "Quem vence em cada estado neste cenário")
    with st.expander("Ver a tabela de todos os estados"):
        t["Estado"] = t.uf.map(nomes_uf())
        t["1º turno"] = t.margem_1T.map(vantagem)
        t["Projeção"] = t.margem_proj.map(vantagem)
        t["Chance de Flávio no estado"] = t.p_flavio
        st.dataframe(t.sort_values("margem_proj", ascending=False)[["Estado", "1º turno", "Projeção", "Chance de Flávio no estado"]],
                     hide_index=True, width="stretch", height=300,
                     column_config={"Chance de Flávio no estado": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
        st.caption("“1º turno” considera só os votos de Flávio e Lula.")

    if sens:
        tor = rodar_tornado(params).head(10).iloc[::-1]
        pb = tor.attrs.get("p_base", r["p_flavio"])
        f2 = go.Figure()
        for col, nome, cor in (("p_lo", "suposição mais baixa", "#b9b7b0"), ("p_hi", "suposição mais alta", TINTA)):
            f2.add_trace(go.Bar(y=tor.rotulo, x=100 * (tor[col] - pb), orientation="h", name=nome, marker_color=cor,
                                customdata=np.c_[tor["valor_lo" if col == "p_lo" else "valor_hi"], 100 * tor[col]],
                                hovertemplate="%{y}<br>valor %{customdata[0]:.3f}<br>chance de Flávio %{customdata[1]:.0f}%<extra></extra>"))
        layout(f2, h=420, barmode="overlay", title="O que mais muda a chance de Flávio",
               xaxis_title=f"mudança na chance de Flávio, em pontos (hoje {br(100 * pb, 0)}%)", hovermode="closest",
               legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(f2, width="stretch")
        st.caption("Barras longas = suposições que, se estiverem erradas, mudam muito a resposta.")


# ================================================================ Admin =====

def aba_admin():
    st.markdown("**Área restrita.** Use só se o coletor do TSE falhar: digite os números por estado do app "
                "Resultados e salve. O painel passa a usar estes dados enquanto forem os mais recentes.")
    st.caption(f"Fonte em uso agora: `{fonte_domingo()}`")
    f = ROOT / "data" / "manual" / "parciais_uf.csv"
    df = pd.read_csv(f)
    ed = st.data_editor(df, hide_index=True, width="stretch", num_rows="fixed", column_config={
        "uf": st.column_config.TextColumn("Estado", disabled=True),
        "pct_secoes": st.column_config.NumberColumn("% seções", min_value=0, max_value=100),
        "lula": st.column_config.NumberColumn("Lula", min_value=0, step=1),
        "flavio": st.column_config.NumberColumn("Flávio", min_value=0, step=1),
        "brancos": st.column_config.NumberColumn("Brancos", min_value=0, step=1),
        "nulos": st.column_config.NumberColumn("Nulos", min_value=0, step=1)})
    if st.button("Salvar e publicar"):
        ed.to_csv(f, index=False)
        p = subprocess.run([sys.executable, str(ROOT / "src" / "manual.py")], capture_output=True, text=True)
        (st.success if p.returncode == 0 else st.error)(p.stdout + p.stderr)


# ================================================================ faixa fixa =

def faixa_regioes():
    """Rodapé sempre visível: % apurado e quem lidera a contagem em cada região, no Brasil e no exterior."""
    r, snap, _ = estado_atual()
    celulas = []
    if snap is not None:
        c = contagem_uf(str(snap))
        g = c.groupby("regiao")[["est", "te", "flavio", "lula"]].sum()
        g.loc["BR"] = c[["est", "te", "flavio", "lula"]].sum()
        tot = total_oficial(str(snap))
        if tot.get("ts") and r is not None and r.get("origem") != "bu":
            # Brasil = total nacional do TSE (o da TV), que chega antes dos arquivos por estado
            g.loc["BR", ["est", "te", "flavio", "lula"]] = [tot["st"], tot["ts"], tot.get("flavio", 0), tot.get("lula", 0)]
    else:
        g = pd.DataFrame(columns=["est", "te", "flavio", "lula"])
    for cod, nome in [("BR", "Brasil"), ("NE", "Nordeste"), ("SE", "Sudeste"), ("S", "Sul"), ("N", "Norte"),
                      ("CO", "Centro-Oeste"), ("EX", "Exterior")]:
        if cod in g.index and g.at[cod, "te"]:
            apur = 100 * g.at[cod, "est"] / g.at[cod, "te"]
            f, l = float(g.at[cod, "flavio"]), float(g.at[cod, "lula"])
        else:
            apur, f, l = 0.0, 0.0, 0.0
        # Antes de haver voto apurado no Brasil, a soma do "Brasil" seria só o exterior: não mostra vantagem.
        domestico = cod == "BR" and (g.drop(index=["EX", "BR"], errors="ignore")[["flavio", "lula"]].to_numpy().sum() == 0)
        if f + l > 0 and not domestico:
            m = 100 * (f - l) / (f + l)
            classe, txt = ("f" if m > 0 else "l"), vantagem(m)
        else:
            classe, txt = "", "aguardando"
        celulas.append(f'<div class="c {classe} {"br" if cod == "BR" else ""}" title="{nome}: {br(apur)}% apurado; '
                       f'contagem do TSE: {txt}"><div class="t"><b>{nome}</b></div>'
                       f'<div class="b"><i style="width:{min(apur, 100):.1f}%"></i></div>'
                       f'<div class="v"><span class="p">{br(apur, 0)}%</span><span class="q">{txt}</span></div></div>')
    st.html('<div class="ap-fixo" role="region" aria-label="Apuração por região"><div class="lin">'
            + "".join(celulas) + "</div></div>")


@st.fragment(run_every=60)
def faixa_fixa():
    faixa_regioes()


# ================================================================ página ====

st.html("""
<div class="ap-hero">
  <div class="ap-over">Estimativa não oficial · 2º turno · domingo, 25 de outubro de 2026</div>
  <h1><span class="f">Flávio</span> x <span class="l">Lula</span></h1>
  <p>A chance de vitória de cada candidato, atualizada minuto a minuto durante a apuração. Projeto pessoal com
  dados públicos do TSE: não é pesquisa e não substitui o resultado oficial.</p>
</div>""")

faixa_fixa()
nomes = ["Apuração", "Regiões e estados", "Como funciona", "Cenários pré-apuração"] + (["Administração"] if ADMIN else [])
tabs = st.tabs(nomes)
with tabs[0]:
    aba_apuracao()
with tabs[1]:
    aba_regioes()
with tabs[2]:
    aba_como_funciona()
with tabs[3]:
    aba_antes()
if ADMIN:
    with tabs[4]:
        aba_admin()
