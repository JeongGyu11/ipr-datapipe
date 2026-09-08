FROM mcr.microsoft.com/playwright/python:v1.55.0-noble@sha256:640d578aae63cfb632461d1b0aecb01414e4e020864ac3dd45a868dc0eff3078

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=ko_KR.UTF-8 \
    LC_ALL=ko_KR.UTF-8 \
    PYTHONPATH=/app

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        locales \
        xauth \
        xvfb \
    && sed -i 's/^# *ko_KR.UTF-8 UTF-8/ko_KR.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version ./
# uv.lock을 유일한 설치 기준으로 사용한다. Playwright Python client 1.55.0은
# base image에 포함된 Chromium과 같은 검증 버전이다.
RUN install -d -m 0755 /opt/uv/python \
    && uv sync --locked --no-dev --no-install-project \
    && chmod -R a+rX /opt/uv/python

COPY . /app
RUN sed -i 's/\r$//' /app/docker/entrypoints/*.sh \
    && chmod +x /app/docker/entrypoints/*.sh \
    && mkdir -p /var/lib/insurance-document-crawler/staging \
        /var/lib/insurance-document-crawler/state \
    && chown -R pwuser:pwuser /app /var/lib/insurance-document-crawler

USER pwuser

ENTRYPOINT ["/app/docker/entrypoints/api.sh"]
