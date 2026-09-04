# ============================================================
# zhycms Dockerfile（多阶段构建）
# 用法：docker build -t zhycms .
# 运行：docker compose --profile mysql up -d
# ============================================================

# ---- Stage 1: Builder ----
FROM python:3.12-slim AS builder

# pip 镜像源（默认官方 PyPI；国内构建可覆盖：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple -t zhycms .）
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# apt 镜像源（默认官方 deb.debian.org；国内构建可覆盖，例：
#   --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
# 兼容 bookworm 的 sources.list 与 trixie 的 deb822 debian.sources 两种格式）
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
      for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        [ -f "$f" ] && sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" "$f"; \
      done; \
    fi

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libmagic-dev libpq-dev default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境并安装依赖
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt requirements-prod.txt ./
# 核心依赖 + 生产依赖（gunicorn / gevent，Docker 运行时需要）
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt

# ---- Stage 2: Runtime ----
FROM python:3.12-slim

# apt 镜像源（同 builder，国内构建：--build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn）
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
      for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        [ -f "$f" ] && sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" "$f"; \
      done; \
    fi

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 libpq5 default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# 复制虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV ZHYCMS_ENV=production

WORKDIR /app

# 复制应用代码
COPY . /app/

# 演示图片暂存（volume 挂载 uploads/ 时会遮盖，entrypoint 负责拷回）
RUN cp -r /app/app/static/uploads/demo /opt/demo-stash

# 创建非 root 用户
RUN groupadd -r zhycms && useradd -r -g zhycms -u 1000 -s /sbin/nologin zhycms \
    && mkdir -p /app/instance/cache /app/instance/backups /app/instance/image_cache \
       /app/instance/search_index \
    && chown -R zhycms:zhycms /app/instance /app/app/static/uploads

# 编译翻译文件（.po → .mo）
RUN python -m babel.messages.frontend compile -d app/translations || true \
    && for d in plugins/*/translations; do \
        [ -d "$d" ] && python -m babel.messages.frontend compile -d "$d" || true; \
    done

EXPOSE 5000

USER zhycms

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz').read()" || exit 1

ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--timeout", "120", "wsgi:app"]
