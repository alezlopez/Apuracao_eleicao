"""Painel local: ao vivo (Parte B), cenário (Parte A), backtest e entrada manual.

  python src/collector.py --ele 6258 --interval 60   # em outro terminal, domingo
  streamlit run app.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
import live  # noqa: E402
import model  # noqa: E402

FLAVIO, LULA = "#2a78d6", "#d64545"   # validados (light e dark) com o validador de paleta
NEUTRO, NEUTRO_CLARO = "#6b6b66", "rgba(107,107,102,0.18)"
SNAPS = ROOT / "data" / "snapshots"
FONTES = {
    "2º turno ao vivo (coletor TSE)": "e6258",
    "2º turno manual (plano B)": "e6258-manual",
    "Ensaio: replay do 1º turno 2026": "replay-t1-2026",
}
N_SIM = 20000

st.set_page_config(page_title="Apuração 2º turno 2026", layout="wide")
st.markdown("**ESTIMATIVA NÃO OFICIAL** · projeto pessoal · fonte dos dados: TSE")


def fmt_votos(v: float) -> str:
    return f"{v:+,.0f}".replace(",", ".")


def layout(fig, h=300, **kw):
    kw.setdefault("hovermode", "x unified")
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=40, b=10), **kw)
    return fig


# ============================================================ Ao vivo =======

@st.cache_resource
def prior_cache(fonte: str) -> pd.DataFrame:
    return live.prior_para(SNAPS / fonte)


def projecoes(fonte: str) -> list[dict]:
    """Processa snapshots novos (grava projecao.json) e devolve o histórico em ordem."""
    root = SNAPS / fonte
    if not root.exists():
        return []
    out = []
    for snap in sorted(p for p in root.iterdir() if p.is_dir() and (p / "uf.csv").exists()):
        f = snap / "projecao.json"
        if not f.exists():
            live.processar(snap, prior_cache(fonte))
        r = json.loads(f.read_text())
        r["_dir"] = str(snap)
        out.append(r)
    return out


def aba_ao_vivo():
    c1, c2 = st.columns([2, 1])
    nome = c1.radio("Fonte", list(FONTES), horizontal=True)
    fonte = FONTES[nome]
    auto = c2.toggle("Atualizar a cada 60 s", value=fonte != "replay-t1-2026")

    @st.fragment(run_every=60 if auto else None)
    def corpo():
        hist = projecoes(fonte)
        if not hist:
            st.info(f"Nenhum snapshot em data/snapshots/{fonte}. "
                    + ("Rode `python src/collector.py --ele 6258 --interval 60`." if fonte == "e6258" else
                       "Use a aba Entrada manual." if fonte == "e6258-manual" else
                       "Rode `python src/backtest.py --replay`."))
            return
        if fonte == "replay-t1-2026":
            i = st.select_slider("Horário do replay (4/10/2026)", options=list(range(len(hist))), value=len(hist) // 3,
                                 format_func=lambda k: hist[k]["tse_ht"][:5])
            hist = hist[: i + 1]
            st.caption("Replay do 1º turno 2026, só Flávio x Lula, com o 2º turno de 2022 como prior. "
                       "Resultado real: Flávio +2,02 p.p. sobre Lula.")
        r = hist[-1]
        mostrar_topo(r)
        mostrar_historico(hist)
        mostrar_ufs(r)

    corpo()


def mostrar_topo(r: dict):
    a = r["pct_apurado"]
    if a == 0:
        st.info("Nada apurado ainda (a divulgação começa às 17h de Brasília). Até lá, o cenário está na aba "
                "**Cenário pré-apuração (Parte A)**.")
        return
    k = st.columns(5)
    k[0].metric("P(Flávio vence)", f"{100 * r['p_flavio']:.1f}%")
    k[1].metric("P(Lula vence)", f"{100 * r['p_lula']:.1f}%")
    k[2].metric("Margem projetada (F−L)", f"{r['margem_mediana']:+.2f} p.p.",
                help=f"80%: {r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f} · 95%: {r['margem_95'][0]:+.2f} a {r['margem_95'][1]:+.2f}")
    k[3].metric("Apurado (eleitorado)", f"{a:.1f}%")
    k[4].metric("Último snapshot", (r.get("tse_ht") or "-")[:8], help=f"coletado em {r.get('coletado_em')}")

    st.markdown(
        f"Intervalo da margem final: **80% de {r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f} p.p.**, "
        f"95% de {r['margem_95'][0]:+.2f} a {r['margem_95'][1]:+.2f} p.p. · em votos (mediana) "
        f"{fmt_votos(r['votos_mediana'])}, 80% de {fmt_votos(r['votos_80'][0])} a {fmt_votos(r['votos_80'][1])}."
    )
    if r.get("margem_atual") is not None:
        st.markdown(
            f"Parcial agora: **{r['lider_atual']} {abs(r['margem_atual']):.2f} p.p. à frente** "
            f"({fmt_votos(abs(r['votos_atual']))[1:]} votos). A parcial NÃO é amostra aleatória: "
            "não leia como projeção."
        )
    if r["decidido"]:
        st.success(f"MATEMATICAMENTE DECIDIDO: a vantagem de {r['lider_atual']} "
                   f"({fmt_votos(abs(r['votos_atual']))[1:]}) é maior que todo o eleitorado ainda não apurado "
                   f"({r['restante_aptos']:,.0f}).".replace(",", "."))
    elif r["restante_validos_proj"] > 0 and r.get("margem_atual") is not None:
        p = r["atrasado_precisa"]
        txt = (f"**O que precisa acontecer:** {r['atrasado']} precisa de **{100 * p:.1f}%** dos votos válidos "
               f"restantes (≈{r['restante_validos_proj']:,.0f} projetados) para virar.").replace(",", ".")
        st.markdown(txt + (" Impossível na prática (> 100%)." if p > 1 else ""))
    if a < 10:
        st.warning("Menos de 10% apurado: as primeiras urnas (exterior, municípios pequenos) não representam o resto. "
                   "A incerteza está ampliada de propósito.")
    elif a >= 70 and r["margem_80"][0] < 0 < r["margem_80"][1]:
        st.warning(f"Com {a:.0f}% apurado o intervalo de 80% ainda cruza zero: a disputa está apertada demais "
                   "para cravar.")


def mostrar_historico(hist: list[dict]):
    df = pd.DataFrame([{
        "t": h.get("tse_ht") or h["snapshot"], "apurado": h["pct_apurado"], "pf": 100 * h["p_flavio"],
        "proj": h["margem_mediana"], "lo": h["margem_80"][0], "hi": h["margem_80"][1],
        "atual": h["margem_atual"],
    } for h in hist])
    c1, c2 = st.columns(2)
    f1 = go.Figure(go.Scatter(x=df.apurado, y=df.pf, mode="lines+markers", line=dict(color=NEUTRO, width=2),
                              marker=dict(size=6), customdata=df.t,
                              hovertemplate="%{customdata} · %{x:.1f}% apurado<br>P(Flávio) %{y:.1f}%<extra></extra>"))
    f1.add_hline(y=50, line_width=1, line_dash="dot", line_color="gray")
    layout(f1, title="P(Flávio vence) ao longo da apuração", xaxis_title="% apurado",
           yaxis=dict(range=[0, 100], ticksuffix="%"), hovermode="closest")
    c1.plotly_chart(f1, width="stretch")

    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=pd.concat([df.apurado, df.apurado[::-1]]), y=pd.concat([df.hi, df.lo[::-1]]),
                            fill="toself", fillcolor=NEUTRO_CLARO, line=dict(width=0), hoverinfo="skip",
                            name="intervalo 80%"))
    f2.add_trace(go.Scatter(x=df.apurado, y=df.proj, mode="lines", line=dict(color="#3d3d3a", width=2),
                            name="margem projetada", hovertemplate="projetada %{y:+.2f}<extra></extra>"))
    f2.add_trace(go.Scatter(x=df.apurado, y=df.atual, mode="lines", line=dict(color=NEUTRO, width=2, dash="dot"),
                            name="parcial (não é projeção)", hovertemplate="parcial %{y:+.2f}<extra></extra>"))
    f2.add_hline(y=0, line_width=1, line_color="gray")
    # As primeiras urnas (0,1%) dão parciais de ±40 p.p. e achatariam a escala.
    ok = df[df.apurado >= 1] if (df.apurado >= 1).any() else df
    vals = pd.concat([ok.lo, ok.hi, ok.atual.dropna(), pd.Series([0.0])])
    layout(f2, title="Margem F−L (p.p.): projetada x parcial", xaxis_title="% apurado",
           yaxis=dict(range=[vals.min() - 1, vals.max() + 1]), legend=dict(orientation="h", y=-0.25))
    c2.plotly_chart(f2, width="stretch")


def mostrar_ufs(r: dict):
    st.subheader("Por UF")
    t = pd.DataFrame(r["uf"])
    t["lidera"] = np.where(t.margem_proj > 0, "Flávio", "Lula")
    t["uf"] = t.uf.str.upper().replace({"ZZ": "Exterior"})
    st.dataframe(
        t[["uf", "pct_apurado", "margem_atual", "margem_proj", "p10", "p90", "p_flavio", "lidera"]].rename(columns={
            "uf": "UF", "pct_apurado": "% apurado", "margem_atual": "Margem atual", "margem_proj": "Margem projetada",
            "p10": "P10", "p90": "P90", "p_flavio": "P(Flávio)", "lidera": "Lidera (proj.)"}),
        hide_index=True, width="stretch", height=420,
        column_config={
            "% apurado": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
            "P(Flávio)": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
            **{c: st.column_config.NumberColumn(format="%+.2f") for c in ["Margem atual", "Margem projetada", "P10", "P90"]},
        },
    )
    st.caption("Margens em p.p. de F−L (positivo = Flávio). P10/P90 = intervalo de 80% da margem final da UF.")


# ============================================================ Parte A =======

@st.cache_data
def base_uf() -> pd.DataFrame:
    return model.carregar_base()


@st.cache_data
def rodar_a(params: tuple) -> dict:
    return model.simular(base_uf(), dict(params), N_SIM)


@st.cache_data
def rodar_tornado(params: tuple) -> pd.DataFrame:
    return model.tornado(base_uf(), dict(params))


def aba_parte_a():
    c = st.columns([1, 3])
    with c[0]:
        preset = st.selectbox("Preset", list(model.PRESETS))
        if st.session_state.get("_preset") != preset:
            for k, v in model.medias(preset).items():
                st.session_state[k] = float(v)
            st.session_state["_preset"] = preset
        grupos = {
            "Choques": ["vies_nac", "sigma_nac", "sigma_reg", "sigma_uf"],
            "Terceira via e brancos/nulos": ["tF", "tL", "t_reg_dp", "kappa", "bF", "bL"],
            "Retenção e defecção": ["rL", "rF", "dLF", "dFL"],
            "Comparecimento por região": [f"dA_{r}" for r in model.REGIOES] + ["mL_dp"],
        }
        for g, ks in grupos.items():
            with st.expander(g, expanded=g == "Choques"):
                for k in ks:
                    p = model.PARAMS[k]
                    st.slider(p.rotulo, float(p.lo), float(p.hi), step=0.005 if p.hi - p.lo <= 1 else 0.05,
                              key=k, help=p.origem)
        sens = st.checkbox("Calcular sensibilidade (~10 s)")

    params = tuple(sorted((k, float(st.session_state[k])) for k in model.PARAMS))
    sim = rodar_a(params)
    r = model.resumo(sim)
    with c[1]:
        k = st.columns(4)
        k[0].metric("P(Flávio vence)", f"{100 * r['p_flavio']:.1f}%")
        k[1].metric("P(Lula vence)", f"{100 * r['p_lula']:.1f}%")
        k[2].metric("Margem mediana (F−L)", f"{r['margem_mediana']:+.2f} p.p.")
        k[3].metric("Votos (F−L), mediana", fmt_votos(r["votos_mediana"]))
        st.caption(f"80%: {r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f} p.p.; 95%: {r['margem_95'][0]:+.2f} a "
                   f"{r['margem_95'][1]:+.2f} p.p. · {N_SIM:,} simulações. Pré-apuração: priors com [suposição]; "
                   "passe o mouse nos sliders para ver a origem.")
        m = sim["margem"]
        bins = np.linspace(np.floor(m.min()), np.ceil(m.max()), 61)
        cont, bordas = np.histogram(m, bins)
        centro = (bordas[:-1] + bordas[1:]) / 2
        fig = go.Figure(go.Bar(x=centro, y=100 * cont / len(m), marker_color=[FLAVIO if x > 0 else LULA for x in centro],
                               marker_line_width=0,
                               hovertemplate="margem %{x:+.2f} p.p.<br>%{y:.2f}% das simulações<extra></extra>"))
        fig.add_vline(x=0, line_width=1, line_color="gray")
        fig.add_annotation(x=bordas[-1], y=1, yref="paper", xanchor="right", showarrow=False, text="Flávio vence →")
        fig.add_annotation(x=bordas[0], y=1, yref="paper", xanchor="left", showarrow=False, text="← Lula vence")
        layout(fig, title="Distribuição da margem nacional (F−L, p.p.)", bargap=0.08, yaxis_title="% das simulações",
               showlegend=False, hovermode="closest")
        st.plotly_chart(fig, width="stretch")

        t = model.tabela_uf(base_uf(), sim)
        t["uf"] = t.uf.str.upper().replace({"ZZ": "Exterior"})
        st.dataframe(t.rename(columns={"uf": "UF", "margem_1T": "Margem 1T", "margem_proj": "Margem proj.",
                                       "p10": "P10", "p90": "P90", "p_flavio": "P(Flávio)"}),
                     hide_index=True, width="stretch", height=300,
                     column_config={"P(Flávio)": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
        if sens:
            tor = rodar_tornado(params).head(10).iloc[::-1]
            pb = tor.attrs.get("p_base", r["p_flavio"])
            f2 = go.Figure()
            for col, nome, cor in (("p_lo", "parâmetro baixo", "#a8a8a3"), ("p_hi", "parâmetro alto", "#3d3d3a")):
                f2.add_trace(go.Bar(y=tor.rotulo, x=100 * (tor[col] - pb), orientation="h", name=nome, marker_color=cor,
                                    customdata=np.c_[tor["valor_lo" if col == "p_lo" else "valor_hi"], 100 * tor[col]],
                                    hovertemplate="%{y}<br>valor %{customdata[0]:.3f}<br>P(F) %{customdata[1]:.1f}%<extra></extra>"))
            layout(f2, h=380, barmode="overlay", title="Sensibilidade: o que mais move P(Flávio)",
                   xaxis_title=f"variação de P(Flávio) em p.p. (base {100 * pb:.1f}%)", hovermode="closest",
                   legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(f2, width="stretch")


# ============================================================ Backtest ======

def aba_backtest():
    f = ROOT / "data" / "backtest" / "resultados.csv"
    if not f.exists():
        st.info("Rode `python src/backtest.py`.")
        return
    d = pd.read_csv(f)
    d["tipo"] = np.where(d.ordem.str.startswith("pior"), "adversária", "realista")
    nomes = {"t2_2022": "2º turno 2022 (prior ruim de propósito)", "t1_2026": "1º turno 2026 (prior = 2º turno 2022)"}
    caso = st.radio("Caso", list(nomes), format_func=nomes.get, horizontal=True)
    g = d[d.caso == caso]
    final = g.final.iloc[0]
    st.markdown(f"Margem final real (F−L): **{final:+.2f} p.p.** "
                f"({'Bolsonaro' if caso == 't2_2022' else 'Flávio'} = F). Unidade: zona eleitoral.")
    fig = go.Figure()
    for o, gg in g.groupby("ordem"):
        real = o == "real"
        fig.add_trace(go.Scatter(x=gg.pct, y=gg.proj, mode="lines", name=o,
                                 line=dict(width=3 if real else 1.5, color="#1f1f1d" if real else
                                           ("#c98a3a" if o.startswith("pior") else "#a8a8a3")),
                                 hovertemplate=f"{o}<br>%{{x}}% apurado · projeção %{{y:+.2f}}<extra></extra>"))
    rr = g[g.ordem == "real"]
    fig.add_trace(go.Scatter(x=rr.pct, y=rr.ingenua, mode="lines", name="parcial (ordem real)",
                             line=dict(width=2, dash="dot", color=NEUTRO),
                             hovertemplate="parcial %{y:+.2f}<extra></extra>"))
    fig.add_hline(y=final, line_width=1, line_dash="dash", line_color="gray",
                  annotation_text="resultado final", annotation_position="top left")
    layout(fig, h=380, title="Margem projetada por ordem de chegada (preto = ordem real; laranja = adversárias)",
           xaxis_title="% das seções apuradas", yaxis_title="margem F−L (p.p.)", hovermode="closest")
    st.plotly_chart(fig, width="stretch")

    t = g.groupby(["tipo", "pct"]).agg(
        erro_abs=("erro", lambda x: x.abs().mean()), erro_max=("erro", lambda x: x.abs().max()),
        ingenuo_abs=("erro_ingenuo", lambda x: x.abs().mean()), cob80=("cob80", "mean"), cob95=("cob95", "mean"),
        acerto=("acertou", "mean"), p_vencedor_min=("p_vencedor", "min"), brier=("brier", "mean")).reset_index()
    st.dataframe(t.round(3), hide_index=True, width="stretch", column_config={
        "erro_abs": "erro médio |p.p.|", "erro_max": "erro máx |p.p.|", "ingenuo_abs": "erro da parcial |p.p.|",
        "cob80": "cobertura 80%", "cob95": "cobertura 95%", "acerto": "acertou vencedor",
        "p_vencedor_min": "menor P(vencedor real)"})
    st.caption("Realista = ordem real + 5 aleatórias + por porte. Adversária = redutos de um lado primeiro "
               "(ordenadas pelo resultado real, impossível na prática; teste de estresse).")


# ============================================================ Manual ========

def aba_manual():
    st.markdown("Plano B: se o coletor falhar, digite os parciais por UF (do app Resultados) e salve. "
                "O snapshot aparece na fonte **2º turno manual** da aba Ao vivo.")
    f = ROOT / "data" / "manual" / "parciais_uf.csv"
    df = pd.read_csv(f)
    ed = st.data_editor(df, hide_index=True, width="stretch", num_rows="fixed", column_config={
        "uf": st.column_config.TextColumn(disabled=True),
        "pct_secoes": st.column_config.NumberColumn("% seções", min_value=0, max_value=100),
        "lula": st.column_config.NumberColumn("Lula", min_value=0, step=1),
        "flavio": st.column_config.NumberColumn("Flávio", min_value=0, step=1),
        "brancos": st.column_config.NumberColumn("Brancos", min_value=0, step=1),
        "nulos": st.column_config.NumberColumn("Nulos", min_value=0, step=1)})
    if st.button("Salvar e gerar snapshot"):
        ed.to_csv(f, index=False)
        p = subprocess.run([sys.executable, str(ROOT / "src" / "manual.py")], capture_output=True, text=True)
        (st.success if p.returncode == 0 else st.error)(p.stdout + p.stderr)


tabs = st.tabs(["Ao vivo (Parte B)", "Cenário pré-apuração (Parte A)", "Backtest", "Entrada manual"])
with tabs[0]:
    aba_ao_vivo()
with tabs[1]:
    aba_parte_a()
with tabs[2]:
    aba_backtest()
with tabs[3]:
    aba_manual()
