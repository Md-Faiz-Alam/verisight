# VeriSight website: FastAPI + static UI, one process.
# Uploaded datasets live in this container's memory and temp disk, so run a
# single instance (scale 1). See docs/deploy-azure.md.
# The official Python image via a public mirror (no Docker Hub pull limits).
FROM public.ecr.aws/docker/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[web]" \
    && useradd --create-home --uid 10001 verisight

USER verisight
# /api/health reports this, so a deploy can confirm which build is answering.
# The publish workflow passes the commit tag; set last to keep the cache above.
ARG VERISIGHT_BUILD=dev
ENV VERISIGHT_WEB_BUILD=$VERISIGHT_BUILD
# Behind a load balancer that appends the visitor address, set
# VERISIGHT_WEB_TRUST_FORWARDED_FOR=true where the container is deployed. Left
# off here, a container run without such a proxy cannot have its rate limits
# dodged with a forged X-Forwarded-For header.

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "verisight.web.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
