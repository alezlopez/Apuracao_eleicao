#!/bin/sh
# Sobe o coletor (com reinício automático) e o painel.
set -e
mkdir -p data/snapshots data/cache

# Boletins de urna do exterior, antes da divulgação oficial das 17h. Sai sozinho quando o total oficial começa;
# se falhar por outro motivo, tenta de novo em 30 s.
(
  until python src/coletor_bu.py --interval "${INTERVALO_BU:-30}"; do
    echo "coletor de boletins parou; reiniciando em 30 s"
    sleep 30
  done
) &

# Coletor do 2º turno. Se cair (TSE fora do ar, rede), volta em 30 s.
(
  while true; do
    python src/collector.py --ele 6258 --interval "${INTERVALO}" || true
    echo "coletor parou; reiniciando em 30 s"
    sleep 30
  done
) &

exec streamlit run app.py --server.port "${PORT}" --server.address 0.0.0.0
