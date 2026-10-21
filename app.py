"""Painel local. Por enquanto só a Parte A (cenário pré-apuração).

  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
import model  # noqa: E402

FLAVIO, LULA = "#2a78d6", "#d64545"   # validados (light e dark) com o validador de paleta
N_SIM = 20000

st.set_page_config(page_title="Apuração 2º turno 2026", layout="wide")
st.markdown("**ESTIMATIVA NÃO OFICIAL** · projeto pessoal · fonte dos dados: TSE")


@st.cache_data
def base() -> pd.DataFrame:
    return model.carregar_base()


@st.cache_data
def rodar(params: tuple, n: int) -> dict:
    return model.simular(base(), dict(params), n)


@st.cache_data
def rodar_tornado(params: tuple) -> pd.DataFrame:
    return model.tornado(base(), dict(params))


# ---- barra lateral: preset + sliders ---------------------------------------
with st.sidebar:
    st.header("Cenário (Parte A)")
    preset = st.selectbox("Preset", list(model.PRESETS))
    if st.session_state.get("_preset") != preset:
        for k, v in model.medias(preset).items():
            st.session_state[k] = float(v)
        st.session_state["_preset"] = preset
    grupos = {
        "Retenção e defecção": ["rL", "rF", "dLF", "dFL"],
        "Terceira via e brancos/nulos": ["tF", "tL", "t_reg_dp", "kappa", "bF", "bL"],
        "Comparecimento por região": [f"dA_{r}" for r in model.REGIOES] + ["mL_dp"],
        "Choques": ["vies_nac", "sigma_nac", "sigma_reg", "sigma_uf"],
    }
    for g, ks in grupos.items():
        with st.expander(g, expanded=g == "Choques"):
            for k in ks:
                p = model.PARAMS[k]
                step = 0.005 if p.hi - p.lo <= 1 else 0.05
                st.slider(p.rotulo, float(p.lo), float(p.hi), step=step, key=k, help=p.origem)
    rodar_sens = st.checkbox("Calcular sensibilidade (tornado, ~10 s)")

params = tuple(sorted((k, float(st.session_state[k])) for k in model.PARAMS))
sim = rodar(params, N_SIM)
r = model.resumo(sim)

# ---- topo -------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("P(Flávio vence)", f"{100 * r['p_flavio']:.1f}%")
c2.metric("P(Lula vence)", f"{100 * r['p_lula']:.1f}%")
lider = "Flávio" if r["margem_mediana"] > 0 else "Lula"
c3.metric("Margem mediana (F−L)", f"{r['margem_mediana']:+.2f} p.p.", help=f"{lider} à frente")
c4.metric("Votos (F−L), mediana", f"{r['votos_mediana']:+,.0f}".replace(",", "."))
st.caption(
    f"Intervalo da margem: 80% de {r['margem_80'][0]:+.2f} a {r['margem_80'][1]:+.2f} p.p.; "
    f"95% de {r['margem_95'][0]:+.2f} a {r['margem_95'][1]:+.2f} p.p. · {N_SIM:,} simulações. "
    "Pré-apuração: depende de priors marcados como [suposição]. Passe o mouse nos sliders para ver a origem de cada um."
)

# ---- distribuição da margem ------------------------------------------------
m = sim["margem"]
bins = np.linspace(np.floor(m.min()), np.ceil(m.max()), 61)
cont, bordas = np.histogram(m, bins)
centro = (bordas[:-1] + bordas[1:]) / 2
fig = go.Figure(go.Bar(
    x=centro, y=100 * cont / len(m), marker_color=[FLAVIO if x > 0 else LULA for x in centro],
    marker_line_width=0, hovertemplate="margem %{x:+.2f} p.p.<br>%{y:.2f}% das simulações<extra></extra>",
))
fig.add_vline(x=0, line_width=1, line_color="gray")
fig.add_annotation(x=bordas[-1], y=1, yref="paper", xanchor="right", showarrow=False, text="Flávio vence →")
fig.add_annotation(x=bordas[0], y=1, yref="paper", xanchor="left", showarrow=False, text="← Lula vence")
fig.update_layout(title="Distribuição da margem nacional (F−L, p.p. dos válidos)", bargap=0.08, height=320,
                  margin=dict(l=10, r=10, t=40, b=10), yaxis_title="% das simulações", showlegend=False)
st.plotly_chart(fig, width="stretch")

# ---- por UF -----------------------------------------------------------------
st.subheader("Por UF")
t = model.tabela_uf(base(), sim)
t["lidera"] = np.where(t.margem_proj > 0, "Flávio", "Lula")
t["uf"] = t.uf.str.upper().replace({"ZZ": "Exterior"})
st.dataframe(
    t.rename(columns={"margem_1T": "Margem 1T", "margem_proj": "Margem proj.", "p10": "P10", "p90": "P90",
                      "p_flavio": "P(Flávio)", "lidera": "Lidera"}),
    hide_index=True, width="stretch",
    column_config={"P(Flávio)": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")},
)
st.caption("Margens em p.p. de F−L (positivo = Flávio). P10/P90 = intervalo de 80% da simulação.")

# ---- sensibilidade -----------------------------------------------------------
if rodar_sens:
    st.subheader("Sensibilidade: o que mais move P(Flávio)")
    tor = rodar_tornado(params).head(10).iloc[::-1]
    pb = tor.attrs.get("p_base", r["p_flavio"])
    fig2 = go.Figure()
    for col, nome in (("p_lo", "parâmetro baixo"), ("p_hi", "parâmetro alto")):
        fig2.add_trace(go.Bar(
            y=tor.rotulo, x=100 * (tor[col] - pb), orientation="h", name=nome,
            marker_color="#8a8a86" if col == "p_lo" else "#3d3d3a",
            customdata=np.c_[tor["valor_lo" if col == "p_lo" else "valor_hi"], 100 * tor[col]],
            hovertemplate="%{y}<br>valor %{customdata[0]:.3f}<br>P(F) = %{customdata[1]:.1f}%<extra></extra>",
        ))
    fig2.update_layout(barmode="overlay", height=380, margin=dict(l=10, r=10, t=10, b=10),
                       xaxis_title=f"variação de P(Flávio) em p.p. (base {100 * pb:.1f}%)",
                       legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig2, width="stretch")
