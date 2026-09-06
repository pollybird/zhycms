#!/bin/bash
# ============================================================
# zhycms Docker 一键安装脚本
# 用法：bash docker/install.sh
# 功能：交互式配置 → 生成 .env → 拉取基础镜像 → 构建启动
# ============================================================
set -euo pipefail

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ---- 工具函数 ----
info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
prompt()  { echo -en "${BLUE}${1}${NC}"; read -r "$2"; }
prompt_default() {
    local question="$1" default="$2" varname="$3"
    echo -en "${BLUE}${question}${NC}"
    read -r -p " [${default}]" input
    eval "${varname}=\"${input:-${default}}\""
}
confirm() {
    local question="$1" default="${2:-y}"
    local hint; [ "$default" = "y" ] && hint="[Y/n]" || hint="[y/N]"
    echo -en "${BLUE}${question}${NC} ${hint} "
    read -r answer
    [ -z "$answer" ] && answer="$default"
    [[ "$answer" =~ ^[Yy] ]]
}

# 生成随机密码（32 字符，字母+数字）
gen_random() {
    head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32
}

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"

# ============================================================
# 欢迎界面
# ============================================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          zhycms Docker 一键安装                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  本脚本将引导你完成 Docker 部署的全部配置。"
echo "  所有信息只需在此输入，无需手动编辑任何文件。"
echo ""

# 检查 Docker 环境
if ! command -v docker &>/dev/null; then
    error "未检测到 docker 命令，请先安装 Docker。"
    echo "  安装指引：https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker info &>/dev/null 2>&1; then
    error "Docker 守护进程未运行，或当前用户无 docker 权限。"
    echo "  请启动 Docker 服务：sudo systemctl start docker"
    echo "  或将用户加入 docker 组：sudo usermod -aG docker \$USER（需重新登录）"
    exit 1
fi

HAS_COMPOSE_V2=$(docker compose version 2>/dev/null | head -1 || true)
HAS_COMPOSE_V1=$(command -v docker-compose 2>/dev/null || true)
if [ -z "$HAS_COMPOSE_V2" ] && [ -z "$HAS_COMPOSE_V1" ]; then
    error "未检测到 docker compose，请安装 Docker Compose。"
    echo "  Ubuntu/Debian: sudo apt install docker-compose-v2"
    echo "  或参考：https://docs.docker.com/compose/install/"
    exit 1
fi

# 统一 compose 命令（优先 v2；v1 在 docker-py>=6.0 时不兼容）
if [ -n "$HAS_COMPOSE_V2" ]; then
    COMPOSE_CMD=(docker compose)
else
    # docker-compose v1（Python 版）与 docker-py >= 6.0 不兼容
    # 检测：docker-compose version 如果报 URLSchemeUnknown 则 v1 已损坏
    if ! docker-compose version &>/dev/null 2>&1; then
        error "docker-compose v1 已损坏（docker-py 版本不兼容）"
        echo "  请安装 Docker Compose v2 插件："
        echo "    Ubuntu/Debian:  sudo apt install docker-compose-v2"
        echo "    或手动安装："
        echo "      mkdir -p ~/.docker/cli-plugins"
        echo "      curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose"
        echo "      chmod +x ~/.docker/cli-plugins/docker-compose"
        exit 1
    fi
    COMPOSE_CMD=(docker-compose)
fi

info "Docker 环境检查通过"
echo ""

# ============================================================
# 步骤 1：数据库选择
# ============================================================
echo -e "${GREEN}━━━ 步骤 1/5：选择数据库 ━━━${NC}"
echo "  1) MySQL 8.4（推荐，功能最全）"
echo "  2) PostgreSQL 16（轻量替代）"
echo ""
prompt "请选择 [1-2]" DB_CHOICE
DB_CHOICE="${DB_CHOICE:-1}"

case "$DB_CHOICE" in
    1) DB_PROFILE="mysql";   DB_NAME="MySQL" ;;
    2) DB_PROFILE="postgres"; DB_NAME="PostgreSQL" ;;
    *) error "无效选择"; exit 1 ;;
esac
info "已选择：${DB_NAME}"
echo ""

# ============================================================
# 步骤 2：密钥与密码
# ============================================================
echo -e "${GREEN}━━━ 步骤 2/5：安全配置 ━━━${NC}"

# SECRET_KEY
DEFAULT_SECRET=$(gen_random)
echo "  应用密钥（SECRET_KEY）用于会话加密，自动生成："
echo "  ${DEFAULT_SECRET:0:8}...${DEFAULT_SECRET: -8}"
if confirm "使用此自动生成的密钥？" "y"; then
    SECRET_KEY="$DEFAULT_SECRET"
else
    prompt "  请输入自定义密钥（32+ 字符）" SECRET_KEY
    [ ${#SECRET_KEY} -lt 16 ] && warn "密钥过短，安全性不足"
fi
echo ""

# 数据库密码
DEFAULT_DB_PASS=$(gen_random)
echo "  数据库密码自动生成："
echo "  ${DEFAULT_DB_PASS:0:8}...${DEFAULT_DB_PASS: -8}"
if confirm "使用此自动生成的密码？" "y"; then
    DB_PASSWORD="$DEFAULT_DB_PASS"
else
    # 密码会拼入数据库连接 URI，特殊字符（@ / : # 等）会破坏连接
    while true; do
        prompt "  请输入自定义密码（仅字母数字）" DB_PASSWORD
        if [[ "$DB_PASSWORD" =~ ^[A-Za-z0-9]+$ ]]; then
            break
        fi
        warn "密码含特殊字符，会导致数据库连接失败，请仅使用字母数字"
    done
fi

MYSQL_ROOT_PASSWORD=$(gen_random)
POSTGRES_PASSWORD="$DB_PASSWORD"
MYSQL_PASSWORD="$DB_PASSWORD"
info "安全配置完成"
echo ""

# ============================================================
# 步骤 3：镜像源加速
# ============================================================
echo -e "${GREEN}━━━ 步骤 3/5：镜像源加速 ━━━${NC}"
echo "  国内网络建议启用加速，否则 Docker 构建可能非常慢。"
echo "  启用后：apt 用清华源、pip 用清华源、基础镜像走镜像站。"
echo ""
if confirm "是否在中国 / 需要国内镜像加速？" "y"; then
    USE_MIRROR="yes"
    APT_MIRROR="mirrors.tuna.tsinghua.edu.cn"
    PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
    info "已启用国内镜像加速（清华源）"
else
    USE_MIRROR="no"
    APT_MIRROR=""
    PIP_INDEX_URL="https://pypi.org/simple"
    info "使用官方源"
fi
echo ""

# ============================================================
# 步骤 4：Meilisearch 搜索引擎
# ============================================================
echo -e "${GREEN}━━━ 步骤 4/5：搜索引擎（可选）━━━${NC}"
echo "  Meilisearch 提供全文搜索（比默认的 Whoosh 更快）。"
echo "  不启用则使用内置 Whoosh 引擎，功能完整。"
echo ""
if confirm "是否启用 Meilisearch？" "n"; then
    USE_MEILI="yes"
    MEILI_MASTER_KEY=$(gen_random)
    info "Meilisearch 已配置（master key 自动生成）"
else
    USE_MEILI="no"
    MEILI_MASTER_KEY=""
fi
echo ""

# ============================================================
# 步骤 5：端口与 Worker
# ============================================================
echo -e "${GREEN}━━━ 步骤 5/5：运行参数 ━━━${NC}"
prompt_default "  Web 端口" "5000" WEB_PORT
prompt_default "  Gunicorn Worker 数量" "4" GUNICORN_WORKERS
echo ""

# ============================================================
# 配置确认
# ============================================================
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   配置确认                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  数据库：          $DB_NAME"
echo "  应用密钥：        ${SECRET_KEY:0:8}...（已隐藏）"
echo "  数据库密码：      ${DB_PASSWORD:0:4}****（已隐藏）"
echo "  镜像加速：        ${USE_MIRROR}"
echo "  Meilisearch：     ${USE_MEILI}"
echo "  Web 端口：        $WEB_PORT"
echo "  Worker 数量：     $GUNICORN_WORKERS"
echo ""

if ! confirm "确认以上配置，开始部署？" "y"; then
    warn "已取消部署"
    exit 0
fi
echo ""

# ============================================================
# 生成 .env
# ============================================================
info "生成 .env 配置文件..."

cat > "$ENV_FILE" <<EOF
# zhycms Docker 环境变量（由 docker/install.sh 自动生成）
# 生成时间：$(date '+%Y-%m-%d %H:%M:%S')

# 应用密钥
SECRET_KEY=${SECRET_KEY}

# 数据库密码
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
MYSQL_PASSWORD=${MYSQL_PASSWORD}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# Web 端口
WEB_PORT=${WEB_PORT}

# Gunicorn
GUNICORN_WORKERS=${GUNICORN_WORKERS}

# Meilisearch
MEILI_MASTER_KEY=${MEILI_MASTER_KEY}

# 镜像源加速
APT_MIRROR=${APT_MIRROR}
PIP_INDEX_URL=${PIP_INDEX_URL}
EOF

info ".env 已生成：$ENV_FILE"
echo ""

# ============================================================
# 宿主机数据目录准备（容器内应用以 uid 1000 运行）
# ============================================================
info "准备数据目录..."
mkdir -p "$PROJECT_DIR/instance" "$PROJECT_DIR/app/static/uploads"

fix_ownership() {
    local dir="$1"
    local owner
    owner=$(stat -c %u "$dir" 2>/dev/null || echo "?")
    [ "$owner" = "1000" ] && return 0
    if [ "$(id -u)" = "0" ]; then
        chown -R 1000:1000 "$dir" && info "  已修正属主: $dir → 1000:1000"
    elif sudo -n chown -R 1000:1000 "$dir" 2>/dev/null; then
        info "  已通过 sudo 修正属主: $dir → 1000:1000"
    else
        warn "  $dir 属主为 uid $owner，容器内进程 (uid 1000) 可能无权写入"
        echo "    如启动失败请执行: sudo chown -R 1000:1000 $dir"
    fi
}

fix_ownership "$PROJECT_DIR/instance"
fix_ownership "$PROJECT_DIR/app/static/uploads"
info "数据目录就绪"
echo ""

# ============================================================
# 基础镜像加速（国内网络）
# ============================================================
if [ "$USE_MIRROR" = "yes" ]; then
    info "检查基础镜像加速..."

    # 检查 daemon.json 是否已配 registry-mirrors
    DAEMON_JSON="/etc/docker/daemon.json"
    NEED_PULL_RETAG=false

    if [ -f "$DAEMON_JSON" ] && grep -q "registry-mirrors" "$DAEMON_JSON" 2>/dev/null; then
        info "已检测到 Docker 守护进程镜像加速配置，跳过手动 retag"
    else
        warn "Docker 守护进程未配置 registry-mirrors"
        echo "  建议配置 /etc/docker/daemon.json 实现全局加速："
        echo '    {"registry-mirrors":["https://docker.m.daocloud.io","https://docker.1ms.run"]}'
        echo "  配置后执行：sudo systemctl restart docker"
        echo ""
        if confirm "是否现在通过镜像站手动拉取并 retag 基础镜像？" "y"; then
            NEED_PULL_RETAG=true
        fi
    fi

    if [ "$NEED_PULL_RETAG" = "true" ]; then
        info "通过镜像站拉取基础镜像（daocloud）..."

        MIRROR_PREFIX="docker.m.daocloud.io"

        # 基础镜像列表
        [ "$DB_PROFILE" = "mysql" ] && DB_NAME_IMAGE="mysql:8.4"
        [ "$DB_PROFILE" = "postgres" ] && DB_NAME_IMAGE="postgres:16-alpine"

        for img in "python:3.12-slim" "$DB_NAME_IMAGE"; do
            # 判断是否 library 镜像
            if [[ "$img" != */* ]]; then
                PULL_URL="${MIRROR_PREFIX}/library/${img}"
            else
                PULL_URL="${MIRROR_PREFIX}/${img}"
            fi

            info "拉取 $PULL_URL ..."
            if docker pull "$PULL_URL" 2>/dev/null; then
                docker tag "$PULL_URL" "$img"
                info "  → retag 为 $img ✓"
            else
                warn "  拉取失败，将使用 Docker 默认源（可能较慢）"
            fi
        done

        if [ "$USE_MEILI" = "yes" ]; then
            MEILI_IMG="getmeili/meilisearch:v1.8"
            PULL_URL="${MIRROR_PREFIX}/${MEILI_IMG}"
            info "拉取 $PULL_URL ..."
            if docker pull "$PULL_URL" 2>/dev/null; then
                docker tag "$PULL_URL" "$MEILI_IMG"
                info "  → retag 为 $MEILI_IMG ✓"
            else
                warn "  拉取失败，将使用 Docker 默认源"
            fi
        fi
        echo ""
    fi
fi

# ============================================================
# 构建镜像
# ============================================================
info "构建 zhycms 镜像（首次构建约 3-5 分钟）..."
echo ""

cd "$PROJECT_DIR"

COMPOSE_PROFILES="--profile ${DB_PROFILE}"
[ "$USE_MEILI" = "yes" ] && COMPOSE_PROFILES="$COMPOSE_PROFILES --profile search"

# 构建时覆盖端口（通过 --build-arg 不需要改端口，端口在 compose 层）
if ! "${COMPOSE_CMD[@]}" $COMPOSE_PROFILES build --build-arg APT_MIRROR="${APT_MIRROR}" --build-arg PIP_INDEX_URL="${PIP_INDEX_URL}" 2>&1 | tee /tmp/zhycms_build.log; then
    error "镜像构建失败，请检查上方日志"
    exit 1
fi
echo ""
info "镜像构建完成 ✓"
echo ""

# ============================================================
# 启动服务
# ============================================================
info "启动服务..."
"${COMPOSE_CMD[@]}" $COMPOSE_PROFILES up -d 2>&1 | tail -10
echo ""

# 等待健康检查
info "等待服务就绪..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:${WEB_PORT}/healthz 2>/dev/null | grep -q "200"; then
        info "服务已就绪 ✓"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo -ne "  等待中... ${WAITED}s\r"
done
echo ""

if [ $WAITED -ge $MAX_WAIT ]; then
    warn "服务未在 ${MAX_WAIT}s 内就绪，可能仍在启动中"
    echo "  查看日志：${COMPOSE_CMD[*]} $COMPOSE_PROFILES logs -f"
else
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                  部署成功！                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  访问地址：    http://localhost:${WEB_PORT}"
    echo "  健康检查：    http://localhost:${WEB_PORT}/healthz"
    echo ""
    echo "  常用命令："
    echo "    查看日志：  ${COMPOSE_CMD[*]} $COMPOSE_PROFILES logs -f"
    echo "    停止服务：  ${COMPOSE_CMD[*]} $COMPOSE_PROFILES down"
    echo "    重启服务：  ${COMPOSE_CMD[*]} $COMPOSE_PROFILES restart"
    echo "    卸载：      bash docker/uninstall.sh"
    echo ""
    echo -e "  ${YELLOW}首次访问需通过初始化向导创建管理员账号。${NC}"
    echo ""
fi
