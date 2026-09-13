FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/mcp/server.py /app/server.py

USER 65532:65532

ENTRYPOINT ["python", "/app/server.py"]
