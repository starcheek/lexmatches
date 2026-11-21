FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pytest.ini .
COPY app ./app
COPY seed ./seed
COPY tests ./tests

# Unprivileged user. An existing piper-voices volume made by the old root image needs a one-time
#   docker run --rm -v lexmatches_piper-voices:/d alpine chown -R 10001:10001 /d
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/piper && chown -R app:app /data/piper
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
