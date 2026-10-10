# RAG knowledge-base QA system - runtime image
# CPU-only on purpose (embedding/rerank via sentence-transformers CPU).
FROM python:3.12-slim

WORKDIR /app

# copy requirements BEFORE pip so it is present at install time
COPY requirements.txt .
# robust pip in slow/China networks: longer timeout + retries
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=15 \
    PIP_NO_BUILD_ISOLATION=1
# build deps (default index) + torch (CPU wheels)
RUN pip install --no-cache-dir setuptools wheel \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
# requirements.txt is ASCII-only on purpose (pip + locale safety)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/app/data \
    HF_HOME=/app/data/hf \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
