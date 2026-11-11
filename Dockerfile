FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY reports/qwen35-4b-live-v1.json reports/qwen35-4b-live-v02.json reports/challenge-v1-before.json reports/challenge-v1-after.json reports/independent-verification-v1.json ./reports/
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/web/dist
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
USER app
ENV AGENTPROOF_DB=/data/agentproof.sqlite
EXPOSE 8010
CMD ["/app/.venv/bin/uvicorn", "agentproof.api:app", "--host", "0.0.0.0", "--port", "8010"]
