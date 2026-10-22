# CPU默认构建；GPU构建使用build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128。
FROM python:3.12-slim-bookworm
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 MPLCONFIGDIR=/app/.local/matplotlib \
    YOLO_CONFIG_DIR=/app/.local/ultralytics TORCH_HOME=/app/.local/torch-cache \
    GV_S3_DATA_DIR=/data GV_S3_DEVICE=cpu
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
    libglib2.0-0 libgl1 fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-stage3.txt requirements-build.txt ./
# pip 25.3支持大文件中断后的下载恢复；保留TLS及包哈希校验。
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8 PIP_RESUME_RETRIES=8 PIP_DISABLE_PIP_VERSION_CHECK=1
# 缓存位于Docker数据盘（本机配置为D盘），不复制进最终镜像。
# 分开安装，后续步骤失败时可复用已完成的安装层和已下载的包。
RUN --mount=type=cache,id=garbage-vision-pip,target=/root/.cache/pip,sharing=locked \
    unset PIP_NO_CACHE_DIR && python -m pip install --upgrade pip==25.3
RUN --mount=type=cache,id=garbage-vision-pip,target=/root/.cache/pip,sharing=locked \
    unset PIP_NO_CACHE_DIR && python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url ${TORCH_INDEX}
RUN --mount=type=cache,id=garbage-vision-pip,target=/root/.cache/pip,sharing=locked \
    unset PIP_NO_CACHE_DIR && python -m pip install -r requirements-stage3.txt -r requirements-build.txt
RUN --mount=type=cache,id=garbage-vision-pip,target=/root/.cache/pip,sharing=locked \
    unset PIP_NO_CACHE_DIR && python -m pip install --no-deps --no-build-isolation \
    'https://codeload.github.com/ultralytics/CLIP/zip/7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40#sha256=ea6799c740f2725175edee0881de9f354086e801dd33d4f43b17d18c8238fb54' \
    && python -m pip check
COPY garbage_vision ./garbage_vision
COPY config ./config
COPY prompts ./prompts
COPY pages ./pages
COPY data/manifests ./data/manifests
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY stage3_app.py ./
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data /app/weights /app/.local/ultralytics/Ultralytics /app/.local/matplotlib \
    && chown -R appuser:appuser /data /app/.local
USER appuser
EXPOSE 8000 8501
CMD ["python", "-m", "uvicorn", "garbage_vision.service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
