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
ENSAIO = "replay-t1-2026"
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
  @media (max-width: 640px) { .ap-duelo { grid-template-columns: 1fr; } .ap-card.l { text-align: left; } }
</style>
""")


# ================================================================ formatação =

def br(x: float, d: int = 1) -> str:
    """Número no formato brasileiro (vírgula decimal, ponto de milhar)."""
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(p: float, d: int = 0) -> str:
    return br(100 * p, d) + "%"


def vantagem(m: float | None, d: int = 1, dir_nome: str = "Flávio") -> str:
    """Margem (direita − Lula) em pontos, escrita com o nome de quem está à frente."""
    if m is None or (isinstance(m, float) and np.isnan(m)):
        return "—"
    if abs(m) < 0.05:
        return "empate"
    return f"{dir_nome if m > 0 else 'Lula'} +{br(abs(m), d)}"


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
    return [json.loads((Path(root) / nome / "projecao.json").read_text()) for nome in assinatura]


def historico(fonte: str) -> list[dict]:
    root = SNAPS / fonte
    if not root.exists():
        return []
    snaps = sorted(p for p in root.iterdir() if p.is_dir() and (p / "uf.csv").exists())
    prontos = tuple(s.name for s in snaps if garantir_projecao(s, root))
    return ler_historico(str(root), prontos)


def fonte_domingo() -> str:
    """Usa o coletor; se a entrada manual tiver dado mais recente (coletor caiu), usa a manual."""
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


def aba_ao_vivo():
    escolha = st.radio("O que mostrar", ["Apuração de domingo (25/10)", "Ensaio: o 1º turno (4/10) de novo"],
                       horizontal=True, label_visibility="collapsed")
    ensaio = escolha.startswith("Ensaio")
    fonte = ENSAIO if ensaio else fonte_domingo()

    @st.fragment(run_every=None if ensaio else 60)
    def corpo():
        hist = historico(fonte)
        if ensaio:
            st.caption("Ensaio com os dados reais da apuração do 1º turno, como se fosse ao vivo, só Flávio x Lula. "
                       "Arraste para ver o que o painel mostraria em cada horário. Resultado final real: "
                       "Flávio 2 pontos à frente de Lula.")
            if not hist:
                st.info("O ensaio ainda não foi gerado no servidor.")
                return
            padrao = next((i for i, h in enumerate(hist) if h["pct_apurado"] >= 10), 0)
            i = st.select_slider("Horário (4/10/2026, Brasília)", options=list(range(len(hist))), value=padrao,
                                 format_func=lambda k: hist[k]["tse_ht"][:5])
            hist = hist[: i + 1]
        if not hist or hist[-1]["pct_apurado"] == 0:
            duelo(0.5, 0.5, "—", "—", "aguardando a apuração", "aguardando a apuração")
            st.info("A divulgação do TSE começa às **17h (Brasília)** de domingo. Esta página se atualiza sozinha a cada "
                    "minuto. Enquanto isso, veja o **Ensaio** acima ou a aba **Antes da apuração**.")
            with st.expander("Como ler este painel", expanded=True):
                st.markdown(COMO_LER)
            return
        r = hist[-1]
        manchete(r, ensaio)
        with st.expander("Como ler estes números"):
            st.markdown(COMO_LER)
        graficos(hist)
        estados(r)

    corpo()


def manchete(r: dict, ensaio: bool):
    a = r["pct_apurado"]
    hora = (r.get("tse_ht") or "")[:5]
    st.html(f'<span class="ap-chip">{br(a)}% das urnas apuradas</span>'
            f'<span class="ap-chip">{"horário simulado" if ensaio else "atualizado às"} {hora}</span>')
    duelo(r["p_flavio"], r["p_lula"], pct(r["p_flavio"]), pct(r["p_lula"]), "chance de vencer", "chance de vencer")
    if r.get("origem") == "manual":
        st.info("Os números desta atualização foram digitados à mão a partir do app oficial do TSE, porque o site de "
                "resultados não respondeu. Podem ter pequenas diferenças.")
    if r["decidido"]:
        st.success(f"**Matematicamente decidido.** A vantagem de {r['lider_atual']} já é maior que o número de "
                   f"eleitores que faltam apurar: nem se todos votassem no outro candidato o resultado mudaria.")

    lo, hi = r["margem_80"]
    st.markdown(
        f"#### Resultado projetado: {placar(r['margem_mediana'])}\n"
        f"Faixa provável (8 em cada 10 simulações): de **{vantagem(lo)}** a **{vantagem(hi)}** pontos. "
        f"Diferença final estimada: cerca de **{milhoes(r['votos_mediana'])}** de votos para "
        f"{'Flávio' if r['votos_mediana'] > 0 else 'Lula'}."
    )
    if r.get("margem_atual") is not None:
        st.markdown(
            f"Contagem do TSE até agora: **{placar(r['margem_atual'])}**. É o número que aparece na TV, e ainda vai mudar: "
            f"{'faltam muitas urnas de regiões que votam diferente das já contadas.' if a < 90 else 'faltam poucas urnas.'}"
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


def estados(r: dict):
    st.subheader("Estado por estado")
    t = pd.DataFrame(r["uf"])
    mapa(t.rename(columns={"margem_proj": "margem", "pct_apurado": "apurado"}),
         "Quem deve vencer em cada estado (projeção)")
    t["Estado"] = t.uf.map(nomes_uf())
    t["Apurado"] = t.pct_apurado
    t["Na contagem"] = t.margem_atual.map(vantagem)
    t["Projeção"] = t.margem_proj.map(vantagem)
    t["Faixa provável"] = [f"{vantagem(a)} a {vantagem(b)}" for a, b in zip(t.p10, t.p90)]
    t["Chance de Flávio no estado"] = t.p_flavio
    with st.expander("Ver a tabela de todos os estados"):
        st.dataframe(
            t.sort_values("margem_proj", ascending=False)[
                ["Estado", "Apurado", "Na contagem", "Projeção", "Faixa provável", "Chance de Flávio no estado"]],
            hide_index=True, width="stretch", height=420,
            column_config={
                "Apurado": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                "Chance de Flávio no estado": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
            },
        )
        st.caption("Vantagem em pontos percentuais dos votos válidos. A chance de Lula no estado é 100% menos a de Flávio. "
                   "O exterior conta como um estado a mais.")


# ================================================================ Como funciona

ORDENS = {
    "real": ("Ordem real", "As zonas eleitorais entram na ordem em que o TSE de fato terminou de contá-las naquela noite. "
             "É o teste mais parecido com domingo."),
    "aleatoria": ("Ordem sorteada (5 sorteios)", "As urnas chegam em ordem aleatória. É o caso fácil: o que chega é uma "
                  "amostra parecida com o todo, como numa pesquisa."),
    "porte_desc": ("Cidades grandes primeiro", "Capitais e metrópoles chegam antes do interior."),
    "porte_asc": ("Cidades pequenas primeiro", "O interior pequeno chega antes, parecido com o começo de uma noite real."),
    "pior_F_primeiro": ("Redutos da direita primeiro (teste extremo)", "Todas as zonas mais favoráveis a {dir} chegam antes "
                        "de qualquer outra. Não acontece na vida real: serve para ver até onde o modelo aguenta."),
    "pior_L_primeiro": ("Redutos de Lula primeiro (teste extremo)", "Todas as zonas mais favoráveis a Lula chegam antes de "
                        "qualquer outra. Também não acontece na vida real."),
}
CASOS = {
    "t2_2022": {"titulo": "2º turno de 2022: Lula x Bolsonaro", "dir": "Bolsonaro",
                "ponto": "Demos ao modelo um ponto de partida **errado de propósito**: a mesma suposição que usamos "
                         "para 2026 (46% dos eleitores dos outros candidatos para a direita, 32% para Lula). Aplicada a "
                         "2022, ela dizia **Lula +{prior}**; o resultado real foi **Lula +{final}**."},
    "t1_2026": {"titulo": "1º turno de 2026: Flávio x Lula", "dir": "Flávio",
                "ponto": "O ponto de partida foi o resultado do 2º turno de 2022 em cada cidade, que apontava "
                         "**{lider_prior} +{prior}**. O resultado real foi **Flávio +{final}**: o ponto de partida "
                         "apontava o vencedor errado, e a ordem de chegada foi muito torta (o Sul chegou primeiro)."},
}


@st.cache_data
def backtest_df() -> pd.DataFrame | None:
    f = ROOT / "data" / "backtest" / "resultados.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f)
    d["grupo"] = np.where(d.ordem.str.startswith("aleatoria"), "aleatoria", d.ordem)
    d["tipo"] = np.where(d.ordem.str.startswith("pior"), "extrema", "realista")
    return d


@st.cache_data
def prior_backtest() -> dict[str, float]:
    """Margem nacional (direita − Lula) que o ponto de partida de cada teste previa."""
    import backtest
    out = {}
    for nome, f in (("t2_2022", backtest.caso_t2_2022), ("t1_2026", backtest.caso_t1_2026)):
        u = f()
        fp = (u.p0 * u.V0).sum() / u.V0.sum()
        out[nome] = 100 * (2 * fp - 1)
    return out


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
   cada parte tem, e conta em quantos cada candidato vence. Daí sai a **chance de vitória**.
6. **Ficar mais seguro com o tempo.** Quanto mais urnas contadas, menos sobra para adivinhar e mais estreita fica a
   faixa provável. No comecinho da noite o modelo é cauteloso de propósito.
""")
    d = backtest_df()
    if d is not None:
        testes(d)
    st.markdown("""
### Limites (leia antes de apostar alguma coisa)
- **Não é pesquisa nem resultado oficial.** Só o TSE declara o resultado.
- **Pode errar.** No teste extremo em que todas as urnas de Lula chegavam antes, o modelo chegou a apontar o favorito
  errado com até 60% das urnas apuradas. Na vida real as urnas não chegam desse jeito, mas isso mostra que ele não é infalível.
- **Só duas eleições de teste.** Os testes acima são bons sinais, não garantia.
- **Antes das 17h**, a aba *Antes da apuração* é só um exercício com suposições, não uma previsão.
- **Se o site do TSE falhar**, os números podem ser digitados à mão a partir do app oficial, e o painel avisa quando isso acontecer.

### Glossário
- **Votos válidos**: todos os votos menos brancos e nulos. É sobre eles que se calcula quem ganha.
- **Ponto percentual**: diferença entre duas porcentagens. 51% contra 49% são 2 pontos de vantagem.
- **Chance de vitória**: em quantas de 100 repetições da mesma situação o candidato venceria.
- **Faixa provável**: onde o resultado final cai em 8 de cada 10 simulações.
- **Apurado**: parte do eleitorado cujas urnas o TSE já contou.
- **Zona eleitoral**: um conjunto de seções de votação de uma cidade. Cidades grandes têm várias zonas.

*Projeto pessoal, sem vínculo com partidos, institutos ou com o TSE. Dados oficiais do TSE
(resultados.tse.jus.br e dadosabertos.tse.jus.br).*
""")


def testes(d: pd.DataFrame):
    st.markdown("""
### Já testamos com eleições de verdade
Pegamos apurações passadas e fizemos o modelo "assistir" de novo, como se fosse ao vivo, sem saber o final.
Em cada teste, as urnas chegam em **seis jeitos diferentes**, do mais realista ao mais maldoso, e anotamos o que o
modelo dizia com 5%, 10%, 20%… até 95% das urnas.
""")
    caso = st.radio("Escolha o teste", list(CASOS), format_func=lambda c: CASOS[c]["titulo"], horizontal=True)
    info = CASOS[caso]
    g = d[d.caso == caso]
    final = g.final.iloc[0]
    prior = prior_backtest()[caso]
    st.markdown(info["ponto"].format(prior=br(abs(prior)), final=br(abs(final)),
                                     lider_prior="Lula" if prior < 0 else info["dir"]))
    dirn = info["dir"]
    vant = lambda m, d_=1: vantagem(m, d_, dirn)  # noqa: E731

    # 1) O filme da noite, na ordem real
    rr = g[g.ordem == "real"].sort_values("pct")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pd.concat([rr.pct, rr.pct[::-1]]), y=pd.concat([rr.hi80, rr.lo80[::-1]]), fill="toself",
                             fillcolor="rgba(107,107,102,0.16)", line=dict(width=0), hoverinfo="skip", name="faixa provável"))
    fig.add_trace(go.Scatter(x=rr.pct, y=rr.ingenua, mode="lines+markers", line=dict(color=NEUTRO, width=2, dash="dot"),
                             name="contagem do TSE naquela hora", customdata=[vant(v) for v in rr.ingenua],
                             hovertemplate="contagem: %{customdata}<extra></extra>"))
    fig.add_trace(go.Scatter(x=rr.pct, y=rr.proj, mode="lines+markers", line=dict(color=TINTA, width=3),
                             name="projeção do modelo", customdata=[vant(v) for v in rr.proj],
                             hovertemplate="modelo: %{customdata}<extra></extra>"))
    fig.add_hline(y=final, line_width=2, line_dash="dash", line_color=FLAVIO if final > 0 else LULA,
                  annotation_text=f"resultado final: {vant(final)}", annotation_position="top right")
    fig.add_hline(y=0, line_width=1, line_color="#d8d6d0")
    layout(fig, h=380, title="O filme da noite (ordem real de chegada)", xaxis_title="% das urnas apuradas",
           yaxis_title=f"vantagem de {dirn} (pontos)", legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, width="stretch")
    r10 = rr[rr.pct == 10].iloc[0]
    st.caption(f"Com 10% das urnas, a contagem dizia **{vant(r10.ingenua)}**; o modelo dizia **{vant(r10.proj)}**. "
               f"A linha tracejada é onde a noite terminou. Quanto mais perto dela, melhor.")

    # 2) Erro do modelo x erro da contagem
    real_ = g[g.tipo == "realista"]
    e = real_.groupby("pct").agg(modelo=("erro", lambda x: x.abs().mean()),
                                 contagem=("erro_ingenuo", lambda x: x.abs().mean())).reset_index()
    e = e[e.pct.isin([10, 30, 50, 70, 90])]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[f"{p}%" for p in e.pct], y=e.contagem, name="olhar só a contagem do TSE", marker_color="#b9b7b0",
                         text=[br(v) for v in e.contagem], textposition="outside", hovertemplate="%{y:.1f} pontos<extra></extra>"))
    fig.add_trace(go.Bar(x=[f"{p}%" for p in e.pct], y=e.modelo, name="projeção do modelo", marker_color=TINTA,
                         text=[br(v) for v in e.modelo], textposition="outside", hovertemplate="%{y:.1f} pontos<extra></extra>"))
    layout(fig, h=340, title="Quanto cada um errou o resultado final (média, em pontos)", barmode="group", bargap=0.3,
           xaxis_title="% das urnas apuradas", yaxis_title="erro (pontos)", legend=dict(orientation="h", y=-0.25),
           hovermode="closest")
    fig.update_traces(marker_line_width=0)
    st.plotly_chart(fig, width="stretch")
    st.caption("Média das ordens realistas (real, sorteadas, por tamanho de cidade). Barra menor = erro menor.")

    # 3) Cada jeito de chegada, destrinchado
    st.markdown("#### Cada jeito de as urnas chegarem")
    grupos = ["real", "aleatoria", "porte_asc", "porte_desc", "pior_F_primeiro", "pior_L_primeiro"]
    cols = st.columns(2)
    for i, gname in enumerate(grupos):
        gg = g[g.grupo == gname]
        nome, desc = ORDENS[gname]
        agg = gg.groupby("pct").agg(proj=("proj", "median"), lo=("lo80", "min"), hi=("hi80", "max"),
                                    pv=("p_vencedor", "min"), ing=("ingenua", "median")).reset_index()
        firme = next((p for p in agg.pct if (agg[agg.pct >= p].pv >= 0.95).all()), None)
        errado = agg[agg.pv <= 0.05].pct.tolist()
        e50 = (gg[gg.pct == 50].erro.abs().mean())
        with cols[i % 2]:
            classe = "real" if gname == "real" else ("extrema" if gname.startswith("pior") else "")
            veredito = (f'<span class="ap-ok">Acertou o vencedor com segurança (95%+) a partir de {firme}% apurado.</span>'
                        if firme else '<span class="ap-ruim">Não chegou a 95% de segurança no vencedor certo.</span>')
            if errado:
                veredito += (f' <span class="ap-ruim">Ficou confiante no lado errado até {max(errado)}% apurado.</span>')
            st.html(f'<div class="ap-ordem {classe}"><b>{nome}</b><br><span style="color:#3d3d3a">{desc.format(dir=dirn)}</span>'
                    f'<br>{veredito} Erro com metade das urnas: <b>{br(e50, 1)} ponto{"s" if e50 >= 2 else ""}</b>.</div>')
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pd.concat([agg.pct, agg.pct[::-1]]), y=pd.concat([agg.hi, agg.lo[::-1]]),
                                     fill="toself", fillcolor="rgba(107,107,102,0.16)", line=dict(width=0), hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=agg.pct, y=agg.ing, mode="lines", line=dict(color=NEUTRO, width=1.5, dash="dot"),
                                     customdata=[vant(v) for v in agg.ing], hovertemplate="contagem: %{customdata}<extra></extra>"))
            fig.add_trace(go.Scatter(x=agg.pct, y=agg.proj, mode="lines",
                                     line=dict(color=LARANJA if classe == "extrema" else TINTA, width=2.5),
                                     customdata=[vant(v) for v in agg.proj], hovertemplate="modelo: %{customdata}<extra></extra>"))
            fig.add_hline(y=final, line_width=1.5, line_dash="dash", line_color=FLAVIO if final > 0 else LULA)
            fig.add_hline(y=0, line_width=1, line_color="#d8d6d0")
            vals = pd.concat([agg.lo, agg.hi, agg[agg.pct >= 20].ing, pd.Series([final, 0.0])])
            layout(fig, h=220, showlegend=False, xaxis=dict(ticksuffix="%"),
                   yaxis=dict(range=[vals.min() - 1, vals.max() + 1]))
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Em cada gráfico: linha cheia = projeção do modelo; pontilhada = contagem do TSE; faixa cinza = faixa provável; "
               "tracejada colorida = resultado final.")

    # 4) Chance que o modelo deu ao vencedor real
    piv = (g.groupby(["grupo", "pct"]).p_vencedor.min().unstack("pct").reindex(grupos))
    vencedor = dirn if final > 0 else "Lula"
    fig = go.Figure(go.Heatmap(
        z=100 * piv.values, x=[f"{c}%" for c in piv.columns], y=[ORDENS[k][0].split(" (")[0] for k in piv.index],
        zmin=0, zmax=100, colorscale=[[0, "#c98a3a"], [0.5, "#f0efec"], [1, "#0c7a0c"]],
        text=[[br(v, 0) for v in row] for row in 100 * piv.values], texttemplate="%{text}",
        hovertemplate="%{y}<br>%{x} apurado: chance dada ao vencedor real = %{z:.0f}%<extra></extra>",
        colorbar=dict(title="chance (%)", thickness=10), xgap=2, ygap=2))
    layout(fig, h=330, title=f"Chance que o modelo dava a {vencedor} (o vencedor real) a cada momento",
           hovermode="closest", xaxis_title="% das urnas apuradas")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")
    st.caption("Verde = o modelo apostava certo; laranja = apostava no perdedor; cinza claro = em dúvida (perto de 50%). "
               "Nas ordens sorteadas, mostramos o pior dos 5 sorteios.")

    # 5) A faixa provável acerta?
    cob = g[g.tipo == "realista"].groupby("pct").cob80.mean().reset_index()
    fig = go.Figure(go.Bar(x=[f"{p}%" for p in cob.pct], y=100 * cob.cob80, marker_color="#8f8d86",
                           text=[br(100 * v, 0) + "%" for v in cob.cob80], textposition="outside",
                           hovertemplate="%{y:.0f}% das vezes<extra></extra>"))
    fig.add_hline(y=80, line_dash="dash", line_color=TINTA, annotation_text="ideal: 80%", annotation_position="top left")
    layout(fig, h=280, title="O resultado final ficou dentro da faixa provável?", yaxis=dict(range=[0, 115], ticksuffix="%"),
           xaxis_title="% das urnas apuradas", hovermode="closest", showlegend=False)
    fig.update_traces(marker_line_width=0)
    st.plotly_chart(fig, width="stretch")
    st.caption("A faixa provável promete acertar 8 em cada 10 vezes. Bem acima de 80%, o modelo foi cauteloso demais; "
               "bem abaixo, confiante demais. Ordens realistas.")


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
                f"Faixa provável: de **{vantagem(r['margem_80'][0])}** a **{vantagem(r['margem_80'][1])}** pontos.")

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


# ================================================================ página ====

st.html("""
<div class="ap-hero">
  <div class="ap-over">Estimativa não oficial · 2º turno · domingo, 25 de outubro de 2026</div>
  <h1><span class="f">Flávio</span> x <span class="l">Lula</span></h1>
  <p>A chance de vitória de cada candidato, atualizada minuto a minuto durante a apuração. Projeto pessoal com
  dados públicos do TSE: não é pesquisa e não substitui o resultado oficial.</p>
</div>""")

nomes = ["Ao vivo", "Como funciona", "Antes da apuração"] + (["Administração"] if ADMIN else [])
tabs = st.tabs(nomes)
with tabs[0]:
    aba_ao_vivo()
with tabs[1]:
    aba_como_funciona()
with tabs[2]:
    aba_antes()
if ADMIN:
    with tabs[3]:
        aba_admin()
