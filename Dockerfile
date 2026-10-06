FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    VERAPOLITICA_WEB_HOST=0.0.0.0 \
    VERAPOLITICA_WEB_PORT=8000

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin verapolitica

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY backend /app/backend
COPY scripts /app/scripts
COPY frontend /app/frontend

RUN mkdir -p /app/data/raw \
    && chown -R verapolitica:verapolitica /app

USER verapolitica

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"

CMD ["python", "-m", "scripts.run_web"]
