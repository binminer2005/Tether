FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TETHER_DATA_DIR=/app/data \
    TETHER_UPLOAD_DIR=/app/data/uploads \
    TETHER_PICS_DIR=/app/data/Pics \
    USERS_FILE=/app/data/users.json \
    TRUST_PROXY=1

WORKDIR /app

RUN groupadd --system tether && useradd --system --gid tether --home-dir /app tether

COPY Tether/requirements.txt /app/Tether/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/Tether/requirements.txt

COPY Tether/ /app/Tether/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data/uploads /app/data/Pics && chown -R tether:tether /app

USER tether
WORKDIR /app/Tether
EXPOSE 8000

CMD ["/app/entrypoint.sh"]
