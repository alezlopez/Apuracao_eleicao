# Apuração 2º turno 2026: painel de probabilidade (ESTIMATIVA NÃO OFICIAL)

Projeto pessoal. Lula (13) x Flávio Bolsonaro (22), domingo 25/10/2026.

## Status

| Passo | Estado |
|---|---|
| 1. Coletor do TSE | **feito**: testado no 1º turno (100%) e no 2º turno (arquivos já publicados, zerados) |
| 2. Base 1º turno 2026 por município | **feito** (`data/base/`). 2018/2022/2026 por zona em `data/hist/` |
| 3. Parte A + Monte Carlo + sliders | **feito**: `src/model.py`, calibração em `src/calibrate.py`, painel `app.py` |
| 4. Parte B + backtest | **feito**: `src/live.py`, `src/backtest.py` |
| 5. Ensaio geral | replay do 1º turno 2026 pronto (`python src/backtest.py --replay`); falta rodar com o coletor de ponta a ponta |

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

## Parte B (`src/live.py`)

Unidade = município (ao vivo) ou zona (backtest). Swing em logit contra o prior de cada unidade, modelo hierárquico
gaussiano (intercepto + lean + porte + efeito por região + efeito por UF), projeção do que falta por Monte Carlo.
Nunca extrapola a parcial nacional.

Incertezas que o backtest obrigou a incluir:
- **Choque comum no que falta (`sd_resto` = 2 p.p.)**: sem ele, os intervalos de 80% cobriam o resultado só 10–20%
  das vezes no 1º turno 2026. O erro RMS da margem da parte não apurada foi ~2 p.p. nas ordens realistas.
- **Pouco apurado (`f_min` = 10%)**: abaixo disso o choque cresce com √(10%/apurado). No replay, com 1,7% apurado,
  o modelo projetava +7,7 com P(F) ≈ 1 (final: +2,0).
- **Exterior (`tau_ex`)**: chega primeiro por causa do fuso (118 de 267 unidades às 18h10 no replay) e tem swing próprio.

## Backtest (`src/backtest.py`) e resultados

Zona eleitoral como unidade, contada inteira no horário da sua última totalização (aproximação da ordem real;
para o 2º turno de 2022 ela comprime a virada que houve na apuração). 10 ordens: real, 5 aleatórias, por porte e
2 adversárias (redutos de um lado primeiro, ordenadas pelo resultado real, ou seja, impossíveis na prática).

| | 2º turno 2022 (prior 46/32, errado de propósito) | 1º turno 2026 (prior = 2º turno 2022) |
|---|---|---|
| Erro médio da margem com 30% / 50% / 70% (ordens realistas) | 0,15 / 0,14 / 0,05 p.p. | 1,1 / 0,6 / 0,45 p.p. |
| Erro da parcial ingênua com 50% | 7,2 p.p. | 8,2 p.p. |
| Cobertura do intervalo de 80% (realistas) | 100% (conservador) | 75–88% |
| P(vencedor real) ≥ 99% a partir de | 60–70% apurado em todas as ordens | 20–60% nas realistas |
| Confiante (≥95%) no lado errado | nunca | ordem "redutos do Lula primeiro", até 60% |

O caso de domingo (prior = 1º turno 2026 nas mesmas unidades) tem a mesma estrutura do 2º turno de 2022, que foi o caso robusto.
Mas são só duas eleições, e a unidade do backtest (zona inteira) é mais grossa que a do ao vivo (município parcial).

## Painel

```bash
python src/collector.py --ele 6258 --interval 60   # terminal 1, domingo a partir das 16h50
streamlit run app.py                               # terminal 2
```

Abas: **Ao vivo** (fonte: coletor, manual ou replay), **Cenário pré-apuração** (Parte A com sliders), **Backtest** e
**Entrada manual** (plano B). O painel processa cada snapshot novo sozinho e atualiza a cada 60 s.
`python src/export_painel.py` exporta os CSVs da versão publicada (somente leitura) do painel.

## Publicar no Easypanel

O contêiner (`Dockerfile` + `start.sh`) roda tudo sozinho: gera o ensaio na primeira subida, mantém o coletor do TSE
rodando (reinicia em 30 s se cair), calcula a projeção uma vez por atualização do TSE e serve o painel na porta 8501.
Testado aqui subindo de uma cópia limpa: painel no ar em ~40 s, primeira coleta completa em ~50 s.
(Não deu para construir a imagem Docker neste ambiente; o `start.sh` foi testado direto.)

1. **Projeto → + Serviço → App.**
2. **Fonte:** GitHub, repositório `alezlopez/apuracao_eleicao`, branch `ccr-82f4e1c3-h0zfwi` (ou `main`, depois do merge).
   Se o repositório for privado, o Easypanel precisa ter acesso ao GitHub.
3. **Build:** Dockerfile (caminho `Dockerfile`).
4. **Ambiente:**
   ```
   ADMIN_TOKEN=<uma senha longa>
   INTERVALO=60
   ```
5. **Volumes (Mounts):** volume `snapshots` em `/app/data/snapshots` e volume `cache` em `/app/data/cache`.
   Sem eles, um reinício apaga o histórico do gráfico da noite.
6. **Domínio:** aponte para a porta **8501**. O HTTPS o Easypanel faz sozinho.
7. **Recursos:** 2 GB de RAM recomendados (cálculo da projeção: pico de ~300 MB; mínimo 1 GB).
8. **Deploy** e confira os logs. O certo é aparecer
   `TSE - | seções 0.00% | ... mun baixados 5757 | erros 0` e depois `sem novidade no TSE` a cada minuto.

**Confira no seu servidor antes de domingo:** que os logs mostram `erros 0` (o servidor alcança `resultados.tse.jus.br`).
Se o TSE recusar o IP do servidor, o coletor vai registrar `ciclo falhou`, e aí o plano B é a entrada manual.

**Administração (plano B):** abra `https://seu-dominio/?admin=<ADMIN_TOKEN>`. Aparece a aba *Administração*, onde
você digita os números por estado. Os visitantes não veem essa aba. Sem `ADMIN_TOKEN` definido, ela não aparece para ninguém.

Para os amigos: mande só o link do domínio. O painel abre em *Ao vivo*. Antes das 17h de domingo ele mostra o aviso
de espera e o **Ensaio** (o 1º turno reapresentado). A aba *Como funciona* explica o método em linguagem simples.

## Painel público (design e textos)

- Azul = Flávio, vermelho = Lula em todo o site (par validado para daltonismo). Títulos em Archivo e texto em Source Sans 3 (Google Fonts).
- **Ao vivo:** os cartões de chance dos dois candidatos lado a lado, o placar projetado em % dos válidos, a contagem do TSE
  separada da projeção e um mapa do Brasil por estado (malha do IBGE em `data/geo/br_uf.geojson`, gerada a partir
  da API de malhas do IBGE).
- **Como funciona:** o método em 6 passos e os testes ilustrados: o filme da noite, o erro do modelo contra o erro da
  contagem, cada uma das 6 ordens de chegada explicada e com seu gráfico, o mapa de calor da chance dada ao vencedor real
  e a cobertura da faixa provável. Todos os números desses textos são calculados de `data/backtest/resultados.csv`.
- **Antes da apuração:** os 6 cenários num gráfico só, cada um explicado (o que muda em relação ao Base e de onde veio),
  com os controles avançados escondidos. Nomes: Base, Vento a favor de Flávio, Vento a favor de Lula,
  Nordeste vai mais às urnas, Sudeste falta mais, Repete 2022.
- Regiões e estados aparecem sempre por extenso.
