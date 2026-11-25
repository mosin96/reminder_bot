FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY run.py ./

RUN useradd --create-home --uid 1000 botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app

USER botuser

ENV DB_PATH=/app/data/bot.db
VOLUME ["/app/data"]

CMD ["python", "run.py"]
