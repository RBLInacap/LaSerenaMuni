FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/

ENV SECRET_KEY=build-only-key \
    DEBUG=False \
    ALLOWED_HOSTS=localhost \
    USE_MYSQL=False

RUN mkdir -p /app/staticfiles \
    && python manage.py collectstatic --noinput \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/media \
    && chown app:app /app/media

USER app

EXPOSE 8000

CMD ["gunicorn", "sgr_backend.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-"]
