FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 walnuts && useradd --uid 10001 --gid 10001 --no-create-home walnuts
WORKDIR /app
COPY server ./server
COPY static ./static
COPY migrations ./migrations
COPY scripts ./scripts
RUN mkdir -p /data && chown walnuts:walnuts /data
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/session', timeout=3)"
ENTRYPOINT ["python", "/app/scripts/container_start.py"]
CMD ["python", "-m", "server.app", "--host", "0.0.0.0", "--port", "8765", "--db", "/data/production.sqlite"]
