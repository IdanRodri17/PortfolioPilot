# Backend image — FastAPI + LangGraph (PortfolioPilot).
#
# Dev-oriented: dependencies are baked into the image, the app source is
# bind-mounted by docker-compose, and `uvicorn --reload` picks up edits live
# (watchfiles polling is enabled in compose so changes on a Windows-host bind
# mount are detected inside this Linux container).
FROM python:3.12-slim

# No .pyc files; unbuffered stdout/stderr so logs stream to `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first so this layer is cached unless requirements.txt changes.
# psycopg[binary] bundles libpq, so no apt packages are required. The generous
# timeout/retries keep the build resilient to slow PyPI mirrors.
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements.txt

# Copy the app so the image also works without the bind mount (e.g. a prod run).
# In dev, compose bind-mounts ./backend/app over this for hot reload.
COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
