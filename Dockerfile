FROM --platform=linux/amd64 debian:bookworm-slim AS veo-tool

ARG VEO_VERSION=v0.6.4-demo
ARG VEO_ARCHIVE=GeminiWatermarkTool-Linux-x64-Video.zip
ARG VEO_SHA256=dd6d27547cee59555a87e720c8ef41c68373d78f94356cca31ab817b43d74f9b

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl --fail --location --retry 3 \
      "https://github.com/allenk/VeoWatermarkRemover/releases/download/${VEO_VERSION}/${VEO_ARCHIVE}" \
      --output "/tmp/${VEO_ARCHIVE}" \
    && echo "${VEO_SHA256}  /tmp/${VEO_ARCHIVE}" | sha256sum --check - \
    && unzip -q "/tmp/${VEO_ARCHIVE}" -d /tmp/veo \
    && install -m 0755 /tmp/veo/GeminiWatermarkTool-Video /veo-watermark-remover

FROM --platform=linux/amd64 python:3.12-slim-bookworm

ARG GFLOW_VERSION=0.43.0
ARG REMOVE_AI_WATERMARKS_VERSION=0.19.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DISPLAY=:99 \
    GFLOW_CLI_HOME=/data/gflow \
    GFLOW_CLI_OUTPUT_DIR=/data/outputs/flow \
    GFLOW_CLI_HEADLESS=true \
    GEMINI_COOKIE_PATH=/data/auth/gemini/cache \
    GEMINI_COOKIE_FILE=/data/auth/gemini/cookies.json \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_GEMINI_WEBAPI=2.0.0 \
    PYTHONPATH=/opt/Gemini-API/src:/app \
    MEDIA_OUTPUT_ROOT=/data/outputs

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates chromium curl ffmpeg fluxbox fonts-noto-cjk fonts-liberation \
      libdbus-1-3 libgl1 libgomp1 libstdc++6 novnc procps tini websockify \
      x11vnc xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/google/chrome \
    && ln -sf /usr/bin/chromium /opt/google/chrome/chrome \
    && python -m venv /opt/gflow-venv \
    && /opt/gflow-venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/gflow-venv/bin/pip install --no-cache-dir "gflow-cli==${GFLOW_VERSION}" \
    && python -m venv /opt/gemini-venv \
    && /opt/gemini-venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/gemini-venv/bin/pip install --no-cache-dir \
      "remove-ai-watermarks[migan]==${REMOVE_AI_WATERMARKS_VERSION}"

COPY --from=veo-tool /veo-watermark-remover /usr/local/bin/veo-watermark-remover
COPY vendor/Gemini-API /opt/Gemini-API
RUN /opt/gemini-venv/bin/pip install --no-cache-dir /opt/Gemini-API

WORKDIR /app

COPY run_gemini.py /app/run_gemini.py
COPY media_cleanup.py /app/media_cleanup.py
COPY suite_cli.py /app/suite_cli.py
COPY sync_auth.py /app/sync_auth.py
COPY start-desktop.sh /app/start-desktop.sh
COPY sitecustomize.py /tmp/gflow-container-hooks.py
COPY gflow_container_hooks.pth /tmp/gflow_container_hooks.pth

RUN site_packages="$(/opt/gflow-venv/bin/python -c 'import site; print(site.getsitepackages()[0])')" \
    && install -m 0644 /tmp/gflow-container-hooks.py "${site_packages}/gflow_container_hooks.py" \
    && install -m 0644 /tmp/gflow_container_hooks.pth "${site_packages}/gflow_container_hooks.pth" \
    && chmod 0755 /app/start-desktop.sh \
    && ln -s /opt/gflow-venv/bin/gflow /usr/local/bin/gflow \
    && printf '#!/bin/sh\nexec /opt/gflow-venv/bin/python /app/suite_cli.py "$@"\n' > /usr/local/bin/media-suite \
    && chmod 0755 /usr/local/bin/media-suite \
    && mkdir -p /data/auth/gemini /data/gflow /data/outputs /workspace

EXPOSE 7900

HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
  CMD curl -fsS http://127.0.0.1:7900/vnc.html >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/start-desktop.sh"]
