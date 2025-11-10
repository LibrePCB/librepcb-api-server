ARG ALPINE_TAG
FROM alpine:$ALPINE_TAG

# Install packages.
RUN apk add --no-cache \
  python3 \
  py3-flask \
  py3-flask-pyc \
  py3-gunicorn \
  py3-gunicorn-pyc \
  py3-requests \
  py3-requests-pyc

# Copy files.
COPY *.py app/
COPY static/ app/static/
WORKDIR app

# Set entrypoint.
ENTRYPOINT [ \
    "gunicorn", \
    "--access-logfile=-", \
    "--bind=0.0.0.0:8000", \
    "--forwarded-allow-ips=*", \
    "--workers=4", \
    "app:app" \
]
