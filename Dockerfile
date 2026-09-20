# syntax=docker/dockerfile:1
FROM node:22-alpine AS console
WORKDIR /build/console
COPY console/package*.json ./
RUN npm ci
COPY console/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY --from=console /build/console/dist ./console/dist
RUN pip install --no-cache-dir .[postgres]
RUN useradd --create-home --uid 10001 eivon && mkdir -p /app/var && chown -R eivon:eivon /app
USER eivon
EXPOSE 8787
ENTRYPOINT ["eivon"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8787"]
