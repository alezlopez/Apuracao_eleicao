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

FLAVIO, LULA = "#2a78d6", "#d64545"   # validados (claro e escuro) com o validador de paleta
TINTA, NEUTRO, NEUTRO_CLARO = "#3d3d3a", "#6b6b66", "rgba(107,107,102,0.18)"
SNAPS = ROOT / "data" / "snapshots"
DOMINGO = ["e6258", "e6258-manual"]   # coletor do TSE; entrada manual (plano B)
ENSAIO = "replay-t1-2026"
N_SIM = 20000

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN = bool(ADMIN_TOKEN) and st.query_params.get("admin") == ADMIN_TOKEN

st.set_page_config(page_title="Apuração 2º turno 2026", page_icon="🗳️", layout="wide")


# ================================================================ formatação =

def br(x: float, d: int = 1) -> str:
    """Número no formato brasileiro (vírgula decimal, ponto de milhar)."""
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(p: float, d: int = 0) -> str:
    return br(100 * p, d) + "%"


def vantagem(m: float | None, d: int = 1) -> str:
    """Margem F−L em p.p. escrita com o nome de quem está à frente."""
    if m is None or (isinstance(m, float) and np.isnan(m)):
        return "—"
    if abs(m) < 0.05:
        return "empate"
    return f"{'Flávio' if m > 0 else 'Lula'} +{br(abs(m), d)}"


def milhoes(v: float) -> str:
    x = abs(v) / 1e6
    return f"{br(x, 1)} {'milhão' if x < 2 else 'milhões'}" if x >= 1 else f"{br(abs(v) / 1e3, 0)} mil"


def placar(m: float) -> str:
    """Margem F−L em p.p. como porcentagem dos válidos de cada um."""
    f = 50 + m / 2
    return f"Flávio {br(f)}% x Lula {br(100 - f)}%"


def layout(fig, h=300, **kw):
    kw.setdefault("hovermode", "x unified")
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=40, b=10), separators=",.", **kw)
    return fig


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
        r = json.loads((Path(root) / nome / "projecao.json").read_text())
        out.append(r)
    return out


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

**Ponto percentual (p.p.)**: a diferença entre as porcentagens dos dois. *Flávio +2* quer dizer algo como
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
            st.caption("Ensaio com os dados reais da apuração do 1º turno, como se fosse ao vivo, mas só Flávio x Lula. "
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
            st.info("A divulgação do TSE começa às **17h (Brasília)** de domingo. Esta página se atualiza sozinha a cada "
                    "minuto. Enquanto isso, veja o **Ensaio** acima ou a aba **Antes da apuração**.")
            with st.expander("Como ler este painel", expanded=True):
                st.markdown(COMO_LER)
            return
        r = hist[-1]
        manchete(r, ensaio)
        with st.expander("Como ler estes números", expanded=False):
            st.markdown(COMO_LER)
        graficos(hist)
        tabela_ufs(r)

    corpo()


def manchete(r: dict, ensaio: bool):
    a = r["pct_apurado"]
    pf, pl = r["p_flavio"], r["p_lula"]
    hora = (r.get("tse_ht") or "")[:5]
    origem = " (dados digitados à mão: o site do TSE não respondeu)" if r.get("origem") == "manual" else ""

    c = st.columns(3)
    c[0].metric("Chance de Flávio vencer", pct(pf), help="Em quantas de 100 repetições desta situação Flávio venceria.")
    c[1].metric("Chance de Lula vencer", pct(pl), help="Em quantas de 100 repetições desta situação Lula venceria.")
    c[2].metric("Urnas apuradas", br(a) + "%", help=f"Parte do eleitorado já contada pelo TSE. Atualizado às {hora}{origem}.")

    if origem:
        st.info("Os números desta atualização foram digitados à mão a partir do app oficial do TSE, porque o site de "
                "resultados não respondeu. Podem ter pequenas diferenças.")
    if r["decidido"]:
        st.success(f"**Matematicamente decidido.** A vantagem de {r['lider_atual']} já é maior que o número de "
                   f"eleitores que faltam apurar: nem se todos votassem no outro candidato o resultado mudaria.")

    lo, hi = r["margem_80"]
    st.markdown(
        f"#### Resultado projetado: {placar(r['margem_mediana'])}\n"
        f"Faixa provável (8 em cada 10 simulações): de **{vantagem(lo)}** a **{vantagem(hi)}** pontos. "
        f"Em votos, a diferença final estimada é de cerca de **{milhoes(r['votos_mediana'])}** "
        f"para {'Flávio' if r['votos_mediana'] > 0 else 'Lula'}."
    )
    if r.get("margem_atual") is not None:
        st.markdown(
            f"Contagem do TSE até agora ({hora}): **{placar(r['margem_atual'])}**. "
            f"É o número que aparece na TV, e ele ainda vai mudar: "
            f"{'faltam muitas urnas de regiões que votam diferente das já contadas.' if a < 90 else 'faltam poucas urnas.'}"
        )
    if not r["decidido"] and r["restante_validos_proj"] > 0 and r.get("margem_atual") is not None:
        p = r["atrasado_precisa"]
        txt = (f"**Para virar**, {r['atrasado']} precisaria de **{br(100 * p)}%** dos votos que ainda faltam contar "
               f"(cerca de {br(r['restante_validos_proj'] / 1e6, 1)} milhões).")
        st.markdown(txt + (" Isso é impossível." if p > 1 else ""))
    if a < 10:
        st.warning("**Ainda é cedo.** Com menos de 10% das urnas, quem chegou primeiro (exterior, cidades pequenas) "
                   "não representa o resto do país. O modelo está sendo cauteloso de propósito.")
    elif a >= 70 and lo < 0 < hi:
        st.warning(f"**Disputa apertada.** Mesmo com {br(a, 0)}% apurado, a faixa provável ainda inclui vitória dos dois. "
                   "Nesse caso, não dá para cravar antes do fim.")
    if ensaio:
        st.caption(f"Ensaio: horário simulado {hora} de 4/10/2026.")


def graficos(hist: list[dict]):
    df = pd.DataFrame([{
        "t": (h.get("tse_ht") or h["snapshot"])[:5], "apurado": h["pct_apurado"], "pf": 100 * h["p_flavio"],
        "proj": h["margem_mediana"], "lo": h["margem_80"][0], "hi": h["margem_80"][1], "atual": h["margem_atual"],
    } for h in hist])
    c1, c2 = st.columns(2)
    f1 = go.Figure(go.Scatter(x=df.apurado, y=df.pf, mode="lines+markers", line=dict(color=FLAVIO, width=2),
                              marker=dict(size=6), customdata=np.c_[df.t, 100 - df.pf],
                              hovertemplate="%{customdata[0]} · %{x:.1f}% apurado<br>Flávio %{y:.0f}% · Lula %{customdata[1]:.0f}%<extra></extra>"))
    f1.add_hline(y=50, line_width=1, line_dash="dot", line_color="gray")
    f1.add_annotation(x=0, y=96, xref="paper", xanchor="left", showarrow=False, text="↑ Flávio favorito", font=dict(color=FLAVIO))
    f1.add_annotation(x=0, y=4, xref="paper", xanchor="left", showarrow=False, text="↓ Lula favorito", font=dict(color=LULA))
    layout(f1, title="Chance de Flávio vencer ao longo da noite", xaxis_title="% das urnas apuradas",
           yaxis=dict(range=[0, 100], ticksuffix="%"), hovermode="closest")
    c1.plotly_chart(f1, width="stretch")
    c1.caption("Acima da linha pontilhada, Flávio é o favorito; abaixo, Lula. Quanto mais longe da linha, mais clara a vantagem.")

    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=pd.concat([df.apurado, df.apurado[::-1]]), y=pd.concat([df.hi, df.lo[::-1]]),
                            fill="toself", fillcolor=NEUTRO_CLARO, line=dict(width=0), hoverinfo="skip",
                            name="faixa provável"))
    f2.add_trace(go.Scatter(x=df.apurado, y=df.proj, mode="lines", line=dict(color=TINTA, width=2),
                            name="projeção do modelo", hovertemplate="projeção %{y:+.1f}<extra></extra>"))
    f2.add_trace(go.Scatter(x=df.apurado, y=df.atual, mode="lines", line=dict(color=NEUTRO, width=2, dash="dot"),
                            name="contagem do TSE", hovertemplate="contagem %{y:+.1f}<extra></extra>"))
    f2.add_hline(y=0, line_width=1, line_color="gray")
    # As primeiras urnas (0,1%) dão contagens de ±40 pontos e achatariam a escala.
    ok = df[df.apurado >= 1] if (df.apurado >= 1).any() else df
    vals = pd.concat([ok.lo, ok.hi, ok.atual.dropna(), pd.Series([0.0])])
    lo_y, hi_y = vals.min() - 1, vals.max() + 1
    f2.add_annotation(x=1, y=hi_y, xref="paper", xanchor="right", yanchor="top", showarrow=False, text="Flávio à frente ↑", font=dict(color=FLAVIO))
    f2.add_annotation(x=1, y=lo_y, xref="paper", xanchor="right", yanchor="bottom", showarrow=False, text="Lula à frente ↓", font=dict(color=LULA))
    layout(f2, title="Vantagem em pontos: contagem do TSE x projeção", xaxis_title="% das urnas apuradas",
           yaxis=dict(range=[lo_y, hi_y]), legend=dict(orientation="h", y=-0.3))
    c2.plotly_chart(f2, width="stretch")
    c2.caption("A linha pontilhada é a contagem do TSE e costuma oscilar muito no começo. A linha cheia é a projeção "
               "do modelo para o resultado final; a faixa cinza é onde ele deve cair.")


def tabela_ufs(r: dict):
    st.subheader("Estado por estado")
    t = pd.DataFrame(r["uf"])
    t["Estado"] = t.uf.str.upper().replace({"ZZ": "Exterior"})
    t["Apurado"] = t.pct_apurado
    t["Na contagem"] = t.margem_atual.map(vantagem)
    t["Projeção"] = t.margem_proj.map(vantagem)
    t["Faixa provável"] = [f"{vantagem(a)} a {vantagem(b)}" for a, b in zip(t.p10, t.p90)]
    t["Chance de Flávio no estado"] = t.p_flavio
    t = t.sort_values("margem_proj", ascending=False)
    st.dataframe(
        t[["Estado", "Apurado", "Na contagem", "Projeção", "Faixa provável", "Chance de Flávio no estado"]],
        hide_index=True, width="stretch", height=420,
        column_config={
            "Apurado": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
            "Chance de Flávio no estado": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
        },
    )
    st.caption("Vantagem em pontos percentuais dos votos válidos. A chance de Lula no estado é 100% menos a de Flávio. "
               "O exterior conta como um estado a mais.")


# ================================================================ Como funciona

@st.cache_data
def backtest_df() -> pd.DataFrame | None:
    f = ROOT / "data" / "backtest" / "resultados.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f)
    d["tipo"] = np.where(d.ordem.str.startswith("pior"), "extrema", "realista")
    return d


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
        t2 = d[(d.caso == "t2_2022") & (d.tipo == "realista")]
        t1 = d[d.caso == "t1_2026"]
        e50 = t2[t2.pct == 50].erro.abs().mean()
        i50 = t2[t2.pct == 50].erro_ingenuo.abs().mean()
        r10 = t1[(t1.ordem == "real") & (t1.pct == 10)].iloc[0]
        nunca = (d[d.caso == "t2_2022"].p_vencedor >= 0.5).all()
        st.markdown(f"""
### Já testamos com eleições de verdade
Pegamos apurações passadas e fizemos o modelo "assistir" de novo, como se fosse ao vivo, sem saber o final.

- **2º turno de 2022 (Lula x Bolsonaro).** Demos ao modelo um ponto de partida *errado de propósito*. Mesmo assim,
  com metade das urnas ele errou o resultado final, em média, por **{br(e50, 1)} ponto**. A contagem parcial
  do TSE naquela hora errava por **{br(i50, 1)} pontos**. Em nenhuma das 10 ordens de chegada testadas ele apontou o
  perdedor como favorito{'.' if nunca else ' (com exceções).'}
- **1º turno de 2026 (só Flávio x Lula).** Com 10% das urnas, a contagem dava Flávio
  **+{br(r10.ingenua, 0)}** pontos. O modelo dizia **+{br(r10.proj, 0)}**. O resultado final foi
  **+{br(r10.final, 0)}**.
""")
        with st.expander("Ver os testes em detalhe (gráfico e tabela)"):
            detalhe_backtest(d)
    st.markdown("""
### Limites (leia antes de apostar alguma coisa)
- **Não é pesquisa nem resultado oficial.** Só o TSE declara o resultado.
- **Pode errar.** Num teste extremo, em que todas as urnas de um candidato chegavam antes das do outro, o modelo
  chegou a apontar o favorito errado com até 60% das urnas apuradas. Na vida real as urnas não chegam desse jeito,
  mas isso mostra que ele não é infalível.
- **Antes das 17h**, a aba *Antes da apuração* é só um exercício com suposições, não uma previsão.
- **Se o site do TSE falhar**, os números podem ser digitados à mão a partir do app oficial, e o painel avisa quando isso acontecer.

### Glossário
- **Votos válidos**: todos os votos menos brancos e nulos. É sobre eles que se calcula quem ganha.
- **Ponto percentual (p.p.)**: diferença entre duas porcentagens. 51% contra 49% são 2 pontos de vantagem.
- **Chance de vitória**: em quantas de 100 repetições da mesma situação o candidato venceria.
- **Faixa provável**: onde o resultado final cai em 8 de cada 10 simulações.
- **Apurado**: parte do eleitorado cujas urnas o TSE já contou.

*Projeto pessoal, sem vínculo com partidos, institutos ou com o TSE. Código aberto: dados oficiais do TSE
(resultados.tse.jus.br e dadosabertos.tse.jus.br).*
""")


def detalhe_backtest(d: pd.DataFrame):
    nomes = {"t2_2022": "2º turno 2022", "t1_2026": "1º turno 2026"}
    caso = st.radio("Eleição", list(nomes), format_func=nomes.get, horizontal=True)
    g = d[d.caso == caso]
    final = g.final.iloc[0]
    fig = go.Figure()
    for o, gg in g.groupby("ordem"):
        real = o == "real"
        fig.add_trace(go.Scatter(x=gg.pct, y=gg.proj, mode="lines", name=o,
                                 line=dict(width=3 if real else 1.5, color="#1f1f1d" if real else
                                           ("#c98a3a" if o.startswith("pior") else "#a8a8a3")),
                                 hovertemplate=f"{o}<br>%{{x}}% apurado · projeção %{{y:+.1f}}<extra></extra>"))
    rr = g[g.ordem == "real"]
    fig.add_trace(go.Scatter(x=rr.pct, y=rr.ingenua, mode="lines", name="contagem (ordem real)",
                             line=dict(width=2, dash="dot", color=NEUTRO), hovertemplate="contagem %{y:+.1f}<extra></extra>"))
    fig.add_hline(y=final, line_width=1, line_dash="dash", line_color="gray",
                  annotation_text="resultado final", annotation_position="top left")
    layout(fig, h=380, title="Projeção do modelo conforme as urnas chegam, em várias ordens de chegada",
           xaxis_title="% das urnas apuradas", yaxis_title="vantagem da direita (pontos)", hovermode="closest")
    st.plotly_chart(fig, width="stretch")
    st.caption("Linha preta: ordem real de chegada. Cinzas: ordens sorteadas e por tamanho de cidade. Laranja: ordens "
               "extremas (todas as urnas de um lado primeiro). Pontilhada: contagem parcial. Tracejada: resultado final. "
               "Quanto mais perto da tracejada, melhor.")
    t = g.groupby(["tipo", "pct"]).agg(
        erro=("erro", lambda x: x.abs().mean()), erro_contagem=("erro_ingenuo", lambda x: x.abs().mean()),
        dentro=("cob80", "mean"), acertou=("acertou", "mean")).reset_index()
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "tipo": "Ordem", "pct": st.column_config.NumberColumn("% apurado", format="%d%%"),
        "erro": st.column_config.NumberColumn("Erro do modelo (pontos)", format="%.2f"),
        "erro_contagem": st.column_config.NumberColumn("Erro da contagem (pontos)", format="%.2f"),
        "dentro": st.column_config.NumberColumn("Resultado dentro da faixa provável", format="percent"),
        "acertou": st.column_config.NumberColumn("Apontou o vencedor", format="percent")})
    st.caption("“Resultado dentro da faixa provável” deveria ficar perto de 80%. Bem acima disso, o modelo está sendo cauteloso demais; "
               "bem abaixo, confiante demais.")


# ================================================================ Antes =====

PRESET_TXT = {
    "Base": "Premissas centrais: retenção de 99%, terceira via 46% Flávio / 32% Lula (Datafolha).",
    "Flávio+": "Terceira via vai mais para Flávio (55/30), Lula perde um pouco mais de eleitores e as pesquisas subestimam Flávio em 1 ponto.",
    "Lula+": "Terceira via mais dividida (40/38), Flávio perde um pouco mais de eleitores e as pesquisas subestimam Lula em 1 ponto.",
    "Mobilização alta no NE": "2 pontos a mais de comparecimento no Nordeste.",
    "Abstenção alta no Sudeste": "2 pontos a menos de comparecimento no Sudeste.",
    "Repete 2022 (Goodman)": "Os votos de outros candidatos migram como em 2022 (55% para a direita, 33% para o PT).",
}


@st.cache_data
def base_uf() -> pd.DataFrame:
    return model.carregar_base()


@st.cache_data
def rodar_a(params: tuple) -> dict:
    return model.simular(base_uf(), dict(params), N_SIM)


@st.cache_data
def rodar_tornado(params: tuple) -> pd.DataFrame:
    return model.tornado(base_uf(), dict(params))


def aba_antes():
    st.markdown("""
Antes de abrir a primeira urna, dá para fazer contas com o resultado do 1º turno e com as pesquisas. **Isto é um
cenário, não uma previsão**: depende de suposições, como para onde vão os eleitores dos outros 10 candidatos,
quanta gente muda de lado e quanta gente deixa de votar. Escolha um cenário e veja o que acontece.
""")
    preset = st.radio("Cenário", list(model.PRESETS), horizontal=True)
    st.caption(PRESET_TXT.get(preset, ""))
    if st.session_state.get("_preset") != preset:
        for k, v in model.medias(preset).items():
            st.session_state[k] = float(v)
        st.session_state["_preset"] = preset

    with st.expander("Ajustes avançados (para quem quer mexer nas suposições)"):
        st.caption("Passe o mouse no ícone de cada controle para ver de onde veio o valor inicial.")
        grupos = {
            "Incerteza geral": ["vies_nac", "sigma_nac", "sigma_reg", "sigma_uf"],
            "Eleitores de outros candidatos e brancos/nulos": ["tF", "tL", "t_reg_dp", "kappa", "bF", "bL"],
            "Quem continua votando no mesmo candidato": ["rL", "rF", "dLF", "dFL"],
            "Comparecimento por região (pontos a mais ou a menos)": [f"dA_{r}" for r in model.REGIOES] + ["mL_dp"],
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
    c = st.columns(3)
    c[0].metric("Flávio vence em", f"{br(100 * r['p_flavio'], 0)} de 100", help="Simulações em que Flávio tem mais votos válidos.")
    c[1].metric("Lula vence em", f"{br(100 * r['p_lula'], 0)} de 100", help="Simulações em que Lula tem mais votos válidos.")
    c[2].metric("Resultado mais provável", placar(r["margem_mediana"]))
    st.markdown(f"Faixa provável: de **{vantagem(r['margem_80'][0])}** a **{vantagem(r['margem_80'][1])}** pontos.")

    m = sim["margem"]
    bins = np.linspace(np.floor(m.min()), np.ceil(m.max()), 61)
    cont, bordas = np.histogram(m, bins)
    centro = (bordas[:-1] + bordas[1:]) / 2
    fig = go.Figure(go.Bar(x=centro, y=100 * cont / len(m), marker_color=[FLAVIO if x > 0 else LULA for x in centro],
                           marker_line_width=0, customdata=[vantagem(x) for x in centro],
                           hovertemplate="%{customdata}<br>%{y:.1f}% das simulações<extra></extra>"))
    fig.add_vline(x=0, line_width=1, line_color="gray")
    fig.add_annotation(x=bordas[-1], y=1, yref="paper", xanchor="right", showarrow=False, text="Flávio vence →", font=dict(color=FLAVIO))
    fig.add_annotation(x=bordas[0], y=1, yref="paper", xanchor="left", showarrow=False, text="← Lula vence", font=dict(color=LULA))
    layout(fig, title=f"Os {br(N_SIM, 0)} resultados simulados", bargap=0.08, yaxis_title="% das simulações",
           xaxis_title="vantagem final em pontos (positivo = Flávio)", showlegend=False, hovermode="closest")
    st.plotly_chart(fig, width="stretch")
    st.caption("Cada barra é um resultado possível; quanto mais alta, mais vezes ele apareceu. Barras azuis: vitórias de "
               "Flávio. Vermelhas: de Lula.")

    with st.expander("Estado por estado neste cenário"):
        t = model.tabela_uf(base_uf(), sim)
        t["Estado"] = t.uf.str.upper().replace({"ZZ": "Exterior"})
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
        for col, nome, cor in (("p_lo", "suposição mais baixa", "#a8a8a3"), ("p_hi", "suposição mais alta", TINTA)):
            f2.add_trace(go.Bar(y=tor.rotulo, x=100 * (tor[col] - pb), orientation="h", name=nome, marker_color=cor,
                                customdata=np.c_[tor["valor_lo" if col == "p_lo" else "valor_hi"], 100 * tor[col]],
                                hovertemplate="%{y}<br>valor %{customdata[0]:.3f}<br>chance de Flávio %{customdata[1]:.0f}%<extra></extra>"))
        layout(f2, h=380, barmode="overlay", title="O que mais muda a chance de Flávio",
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
        "uf": st.column_config.TextColumn(disabled=True),
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

st.markdown("## Apuração do 2º turno 2026: Lula x Flávio")
st.markdown("Chance de vitória de cada candidato, atualizada durante a apuração. **Estimativa não oficial**, "
            "feita por um projeto pessoal com dados públicos do TSE. Não é pesquisa e não substitui o resultado oficial.")

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
