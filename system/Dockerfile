FROM node:22-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json vite.config.js ./
COPY frontend/ ./frontend/
COPY survey_definition*.json ./
RUN npm ci && npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt -r requirements-server.txt


COPY *.py ./
COPY personas/ ./personas/
COPY migrations/ ./migrations/
COPY survey_definition*.json privacy_settings.json ./
COPY --from=frontend /build/web-dist/ ./web-dist/
RUN groupadd --gid 10001 helena && useradd --uid 10001 --gid helena --no-create-home helena
USER helena
EXPOSE 5050
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:create_app()"]
