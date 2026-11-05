FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 国内网络默认走阿里云镜像，可用 build arg 覆盖
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY app ./app

# 非 root 运行（design §15.5；M4 挂 docker.sock 前必须到位）
RUN useradd --uid 1000 --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 独立运行时的安全默认：只信任本机直连的 XFF。
# compose 里由 caddy 的固定 IP 覆盖此参数（见 docker-compose.yml）。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
