FROM python:3.12-slim

# Evitar prompts y bufferizado de logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependencias del sistema mínimas (build tools para compilar paquetes nativos
# como chromadb/onnxruntime, y curl para healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias primero (capa cacheada)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar el resto del código
COPY api.py .
COPY docs/ ./docs/

# El puerto que expone uvicorn dentro del contenedor
EXPOSE 8000

# Healthcheck para Dokploy/Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
