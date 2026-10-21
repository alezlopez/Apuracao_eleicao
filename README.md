# Apuração 2º turno 2026: painel de probabilidade (ESTIMATIVA NÃO OFICIAL)

Projeto pessoal. Lula (13) x Flávio Bolsonaro (22), domingo 25/10/2026.

## Status

| Passo | Estado |
|---|---|
| 1. Coletor do TSE | **feito**: testado no 1º turno (100%) e no 2º turno (arquivos já publicados, zerados) |
| 2. Base 1º turno 2026 por município | **feito** (`data/base/`). 2018/2022/2026 por zona em `data/hist/` |
| 3. Parte A + Monte Carlo + sliders | **feito**: `src/model.py`, calibração em `src/calibrate.py`, painel `app.py` |
| 4. Parte B + backtest | pendente |
| 5. Ensaio geral | pendente |

## Coletor (`src/collector.py`)

Endpoints verificados em 21/10/2026 (base `https://resultados.tse.jus.br/oficial/ele2026/`):

| Arquivo | Conteúdo |
|---|---|
| `{ele}/config/mun-e{ele:06}-cm.json` | 5.757 municípios (27 UFs + exterior `zz`), código TSE e IBGE |
| `{ele}/dados/{uf}/{uf}-e{ele:06}-ab.json` | seções totalizadas e eleitorado por município (sem votos) |
| `{ele}/dados/{abr}/{abr}-c0001-e{ele:06}-u.json` | resultado de Presidente: seções, aptos, comparecimento, abstenção, válidos, brancos, nulos e votos por candidato. `abr` = `br`, `{uf}` ou `{uf}{cd_mun}` |

Eleições: **6257** = Presidente 1º turno, **6258** = Presidente 2º turno (tirado de `comum/config/ele-c.json`).

Cada ciclo baixa br + 28 UFs + 28 índices `-ab`. O `-u` de um município só é baixado quando
o número de seções totalizadas mudou. Medido aqui: carga inicial de 5.757 municípios em ~45–60 s,
ciclo sem mudança em ~3–4 s, 0 erros.

```bash
pip install -r requirements.txt
python src/collector.py --ele 6257 --once          # 1º turno
python src/collector.py --ele 6258 --interval 60   # domingo, a partir das 16h50
```

Saída: `data/snapshots/e{ele}/{AAAAMMDD-HHMMSS}/{uf.csv, mun.csv, meta.json}`.

**Plano B** (`src/manual.py`): preencher `data/manual/parciais_uf.csv` e rodar o script; ele grava o
snapshot por UF no mesmo formato.

## Reconciliação do briefing com o TSE (1º turno, 100%)

Fonte: snapshot oficial em `data/base/t1_2026_uf.csv`.

- Totais nacionais batem: Flávio 56.104.503 (47,03%), Lula 53.879.538 (45,16%), outros 9.316.747 (7,81%).
  Aptos 158.745.502, comparecimento 78,92%, **abstenção 21,08%** (não 21,07%).
- Todos os valores da tabela por UF do briefing batem.
- Flávio lidera 15 (14 UFs + DF) e Lula 12. O exterior (`zz`, 916 mil aptos, 62,7% de abstenção) dá Lula 47,6 x 43,5,
  e entra no total nacional.
- **MG 22,81% / RJ 23,32%** de abstenção (aptos totais como denominador). A fonte que dizia MG 23,32 trocou as UFs.
- MS 23,87% (maior), CE 15,52% (menor), BA 19,97%, SP 22,54%: batem.
- Abstenção por região (calculada): N 19,43 · NE 18,39 · CO 21,70 · SE 22,70 · S 20,46.
  O NE dá 18,39 e não 18,36 como no briefing. A diferença provavelmente vem do denominador (aptos x outra base).

## Dados abertos (para o backtest)

Acessíveis daqui via `cdn.tse.jus.br/estatistica/sead/odsele/`: `votacao_secao_2022_BR.zip` (271 MB),
`votacao_candidato_munzona_2022.zip` (580 MB), `detalhe_votacao_munzona_2022.zip`, e os de 2026
(`votacao_secao_2026_BR.zip`, `votacao_candidato_munzona_2026.zip`). Os arquivos de 2022 **não** estão mais no portal
Resultados (`ele2022/544|545` dá 404).

## Histórico (`src/history.py`)

Gera `data/hist/munzona_{2018,2022,2026}.csv.gz`: Presidente por município e zona, nos dois turnos,
com aptos, comparecimento, abstenção, brancos, nulos, votos do PT (`esq`), da direita do 2º turno (`dir`),
outros e a hora da última totalização da zona (`ult_tot`, que serve de aproximação da ordem de chegada para o
backtest). Do zip de 580 MB de votos por candidato, extrai só o arquivo `_BR` (Presidente, ~2 MB) por range request.
Os totais batem com os resultados oficiais (2022: 48,43/43,20 → 50,90/49,10; 2018: 29,28/46,03 → 44,87/55,13).

## Parte A (`src/model.py`, `src/calibrate.py`, `app.py`)

```bash
python src/calibrate.py   # fluxos 1T->2T de 2018 e 2022
python src/model.py       # presets, tabela por UF e tornado no terminal
streamlit run app.py      # painel com sliders
```

O que a calibração mostrou (regressão ecológica de Goodman por zona; ordem de grandeza, não fluxo individual):

| | 2018 | 2022 |
|---|---|---|
| Retenção PT / direita | 0,997 / 1,000 | 0,990 / 1,000 |
| Outros → PT / direita / branco+nulo | 0,57 / 0,26 / 0,14 | 0,33 / 0,55 / 0,12 |
| Branco+nulo do 1T → PT / direita | 0,11 / 0,15 | 0,08 / 0,15 |
| Δ comparecimento 1T→2T (p.p.) | −0,97 | +0,36 |
| Erro por UF com fluxo nacional uniforme (DP) | 6,4 p.p. | 2,1 p.p. |
| Idem, com o termo de polarização κ | 4,0 p.p. (κ=0,57) | 1,1 p.p. (κ=0,85) |

- **Polarização local (κ)**, que não estava no plano original: no 2º turno os votos que mudam de dono vão mais para
  quem já lidera na UF. A correlação entre o erro por UF e o lean do 1T foi de 0,73 (2018) e 0,88 (2022).
  O modelo usa `tF_s = tF + κ·lean_s/200`.
- **σ nacional = 2,0 p.p., e não 1,0.** Uma transferência fixa 46/32 (estilo Datafolha) aplicada a 2022 erra a margem
  em +2,1 p.p. a favor da direita. Fluxos de outro ano erram de 6 a 14 p.p., então não se transportam.
- Matrizes regionais de Goodman são instáveis e contraditórias com o resíduo por UF. Não são usadas.
- Retenção: os dados dizem 0,99–1,00. O default ficou em 0,99, e não nos 0,98 do plano.

Resultado com os priors atuais, que ainda não passaram por backtest: Base P(Flávio) ≈ 94%, margem mediana +3,5 p.p.
(80%: +0,6 a +6,4). A Quaest (46 x 44) implica cerca de +2,2 p.p. nos válidos. O modelo é mais pró-Flávio que a
pesquisa porque parte do +1,87 do 1º turno e soma a transferência 46/32 da terceira via. O tornado mostra que
viés nacional, σ nacional, retenções e terceira via dominam. Comparecimento regional quase não move P(F).
