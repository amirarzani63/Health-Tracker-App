FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEALTH_DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# exercise illustrations (RepDB free tier, used in-app with attribution; not stored in git)
COPY scripts ./scripts
RUN python scripts/fetch_exercise_library.py

RUN useradd --create-home appuser && mkdir -p /data
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
# The entrypoint makes the mounted data disk writable, then runs the app as a non-root user.
ENTRYPOINT ["docker-entrypoint.sh"]
# Hosts like Render set $PORT; --proxy-headers lets the app see it's served over HTTPS.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
