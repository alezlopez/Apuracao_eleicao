# Painel da apuração: coletor do TSE + painel Streamlit no mesmo contêiner.
FROM python:3.13-slim

ENV TZ=America/Sao_Paulo \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501 \
    INTERVALO=60

RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x start.sh

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD curl -fs http://localhost:${PORT}/_stcore/health || exit 1

CMD ["./start.sh"]
