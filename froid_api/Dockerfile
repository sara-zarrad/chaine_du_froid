FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Dépendances d'abord : cette couche est mise en cache tant que requirements.txt ne change pas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code de l'API (le modèle d'IA risk_model.json est dans app/)
COPY app ./app

# Exécution sans les droits root
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
