# Python 3.11 to match .python-version. slim rather than alpine: psycopg and
# pandas both ship manylinux wheels, so glibc avoids compiling either from
# source.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Dependencies are installed before the source is copied so that editing code
# does not invalidate the (slow) dependency layer.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install --requirement requirements.txt

COPY . .

# Static files are baked into the image: WhiteNoise's manifest storage refuses
# to serve anything collectstatic has not processed. SECRET_KEY is only needed
# for settings to import here, and is never written into the image; the real
# one arrives as an environment variable at run time.
RUN SECRET_KEY=build-time-only-not-a-real-secret \
    DEBUG=False \
    DATABASE_URL= \
    python manage.py collectstatic --noinput

# Run unprivileged. Done after collectstatic so the build can write staticfiles.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Container Apps injects PORT, so it is read at run time rather than baked in.
# Migrations deliberately do NOT run here: they run as a separate job before a
# new revision is promoted, so a failed migration cannot half-start the app.
CMD ["sh", "-c", "gunicorn wasel.wsgi --bind 0.0.0.0:${PORT} --workers 3 --timeout 60 --access-logfile - --error-logfile -"]
