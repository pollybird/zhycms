#!/bin/bash
# ============================================================
# zhycms Docker 一键安装脚本
# 用法：bash docker/install.sh
# 功能：交互式配置 → 生成 .env → 拉取基础镜像 → 本地构建并启动
#
# 提示：官方镜像已发布到 Docker Hub（pollybird/zhycms），
# 若不想本地构建，可直接用独立 compose 文件拉取预构建镜像：
#   docker compose -f docker-compose.mysql.yml up -d       # MySQL
#   docker compose -f docker-compose.postgresql.yml up -d  # PostgreSQL
# 三个 tag（mysql/postgresql/latest）指向同一镜像。
# 本脚本走本地构建路径，适合需要定制 Dockerfile 的场景。
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

# ---- 国内 Docker 镜像加速站 ----
# 说明：以下均为「前缀替换式」镜像服务，拉取时把原镜像名改写为 <host>/<原路径>，
#       例如 redis:7-alpine → docker.m.daocloud.io/library/redis:7-alpine。
#       配置到 daemon.json 的 registry-mirrors 后，dockerd 会自动按序尝试，
#       原镜像名无需改动（compose / build 均透明生效）。
CN_REGISTRY_MIRRORS=(
    "https://docker.m.daocloud.io"
    "https://docker.1ms.run"
    "https://docker.xuanyuan.me"
    "https://hub.rat.dev"
)
# 仅保留 host（去掉 https://），用于 docker pull 前缀替换
CN_MIRROR_HOSTS=("${CN_REGISTRY_MIRRORS[@]#https://}")

# 判断 dockerd 是否已配置任意 registry mirror
daemon_has_mirror() {
    docker info 2>/dev/null | grep -A15 'Registry Mirrors:' \
        | grep -Eq 'https?://[0-9a-zA-Z.-]+'
}

# 合并写入 registry-mirrors 到 /etc/docker/daemon.json（保留已有其它字段），
# 然后重启 docker。需要 root 或 sudo。返回 0 表示成功。
configure_daemon_mirrors() {
    local target="/etc/docker/daemon.json"
    local tmp
    tmp="$(mktemp)"

    # 用 python3 或 jq 做 JSON 合并；二者皆无则放弃（避免手写 JSON 破坏配置）
    if command -v python3 >/dev/null 2>&1; then
        local mirrors_json
        mirrors_json=$(printf '%s\n' "${CN_REGISTRY_MIRRORS[@]}" \
            | python3 -c 'import sys,json;print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')
        python3 - "$target" "$mirrors_json" "$tmp" <<'PY'
import json, os, shutil, sys
target, mirrors_json, tmp = sys.argv[1], sys.argv[2], sys.argv[3]
mirrors = json.loads(mirrors_json)
data = {}
if os.path.exists(target):
    try:
        with open(target, encoding='utf-8') as f:
            data = json.load(f) or {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        # 原文件损坏：备份后从空对象开始，不直接丢弃
        shutil.copy2(target, target + '.corrupt.bak')
        data = {}
    else:
        shutil.copy2(target, target + '.bak')
merged = []
for m in list(data.get('registry-mirrors', [])) + mirrors:
    if m not in merged:
        merged.append(m)
data['registry-mirrors'] = merged
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
PY
    elif command -v jq >/dev/null 2>&1; then
        if [ -f "$target" ]; then
            jq -s --argjson m "$(printf '%s\n' "${CN_REGISTRY_MIRRORS[@]}" | jq -R . | jq -s .)" \
                '.[0] * {"registry-mirrors": ((.[0]["registry-mirrors"] // []) + $m | unique)}' \
                "$target" > "$tmp"
            cp -a "$target" "$target.bak"
        else
            jq -n --argjson m "$(printf '%s\n' "${CN_REGISTRY_MIRRORS[@]}" | jq -R . | jq -s .)" \
                '{"registry-mirrors": $m}' > "$tmp"
        fi
    else
        rm -f "$tmp"
        warn "未找到 python3 或 jq，无法安全合并 $target"
        return 1
    fi

    # 提权安装：root 直接写；否则用 sudo（交互终端会提示输入密码，sudo -v 先验密）
    if [ "$(id -u)" = "0" ]; then
        SUDO=""
    elif sudo -v 2>/dev/null; then
        SUDO="sudo"
    else
        warn "需要 root 权限写入 $target（当前非 root 且 sudo 不可用 / 已取消）"
        echo "  可手动执行以下命令完成配置（已生成好的内容如下）："
        echo "    sudo mkdir -p /etc/docker && sudo tee $target >/dev/null <<'JSON'"
        sed 's/^/    /' "$tmp"
        echo "    JSON"
        echo "    sudo systemctl restart docker"
        rm -f "$tmp"
        return 1
    fi
    $SUDO mkdir -p /etc/docker
    $SUDO sh -c "cat '$tmp' > '$target'"
    rm -f "$tmp"

    info "已写入 registry-mirrors 到 $target（原配置已备份为 .bak）"
    info "重启 Docker 守护进程使配置生效..."
    $SUDO systemctl restart docker 2>/dev/null || $SUDO service docker restart 2>/dev/null || true

    # 等待 dockerd 恢复
    local i
    for i in $(seq 1 30); do
        if docker info >/dev/null 2>&1; then
            info "Docker 已恢复，镜像加速器生效 ✓"
            return 0
        fi
        sleep 1
    done
    warn "Docker 重启后 30s 内未恢复，请手动检查：systemctl status docker"
    return 1
}

# 通过镜像站前缀拉取单个镜像并 retag 为官方名（多源回退 + 每源 2 次重试）。
# 用法：pull_image_via_mirror <官方镜像名>
pull_image_via_mirror() {
    local img="$1" path host url attempt
    # 本地已存在则跳过
    if docker image inspect "$img" >/dev/null 2>&1; then
        info "  $img 本地已存在，跳过拉取"
        return 0
    fi
    if [[ "$img" != */* ]]; then
        path="library/$img"        # 官方镜像（mysql/redis/python 等）
    else
        path="$img"                # 带命名空间（getmeili/meilisearch 等）
    fi
    for host in "${CN_MIRROR_HOSTS[@]}"; do
        url="${host}/${path}"
        for attempt in 1 2; do
            info "  拉取 ${url}（第 ${attempt} 次）"
            if docker pull "$url"; then
                docker tag "$url" "$img"
                info "  → 已 retag 为 $img ✓"
                return 0
            fi
            sleep 2
        done
        warn "  $host 拉取失败，尝试下一镜像站..."
    done
    error "  所有镜像站均无法拉取 $img"
    return 1
}

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
echo -e "${GREEN}━━━ 步骤 1/6：选择数据库 ━━━${NC}"
echo "  1) MySQL 8.4（推荐，功能最全）"
echo "  2) PostgreSQL 16（高并发性能更强）"
echo "  3) MariaDB 11.4（MySQL 协议兼容，开源社区维护）"
echo ""
prompt "请选择 [1-3]" DB_CHOICE
DB_CHOICE="${DB_CHOICE:-1}"

case "$DB_CHOICE" in
    1) DB_PROFILE="mysql";    DB_NAME="MySQL 8.4" ;;
    2) DB_PROFILE="postgres"; DB_NAME="PostgreSQL 16" ;;
    3) DB_PROFILE="mariadb";  DB_NAME="MariaDB 11.4" ;;
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

# 已有数据卷检测：MySQL/PostgreSQL 仅在首次初始化空数据卷时应用密码，
# 若数据卷已存在（此前部署过），新密码不会同步到数据库，会导致 Access denied
EXISTING_VOL=""
case "$DB_PROFILE" in
    mysql)    EXISTING_VOL=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E '_mysql_data$' | head -1 || true) ;;
    mariadb)  EXISTING_VOL=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E '_mariadb_data$' | head -1 || true) ;;
    postgres) EXISTING_VOL=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E '_pg_data$' | head -1 || true) ;;
esac

REUSE_DB=false
if [ -n "$EXISTING_VOL" ]; then
    warn "检测到已有数据库数据卷：$EXISTING_VOL"
    echo "  数据库仅在首次初始化空数据卷时应用密码，"
    echo "  若该数据卷由其它密码初始化，输入新密码将无法登录（Access denied）。"
    echo ""
    echo "  1) 沿用已有数据（输入此前初始化时的密码）"
    echo "  2) 删除数据卷重新初始化（数据库数据将全部清空！）"
    prompt "请选择 [1-2]" VOL_CHOICE
    VOL_CHOICE="${VOL_CHOICE:-1}"
    if [ "$VOL_CHOICE" = "2" ] && confirm "确认删除数据卷 $EXISTING_VOL？数据不可恢复！" "n"; then
        info "停止容器并删除数据卷..."
        "${COMPOSE_CMD[@]}" --profile "$DB_PROFILE" down -v 2>/dev/null || true
        info "数据卷已删除，将使用新密码全新初始化"
    else
        REUSE_DB=true
        [ "$VOL_CHOICE" = "2" ] && warn "已取消删除，将沿用已有数据"
    fi
fi
echo ""

# 数据库密码
if [ "$REUSE_DB" = "true" ]; then
    # 沿用已有数据卷：必须输入库内当前生效的密码，否则应用连接失败
    while true; do
        prompt "  请输入该数据库当前生效的密码（仅字母数字）" DB_PASSWORD
        if [[ "$DB_PASSWORD" =~ ^[A-Za-z0-9]+$ ]]; then
            break
        fi
        warn "密码含特殊字符，请仅使用字母数字"
    done
else
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
fi

MYSQL_ROOT_PASSWORD=$(gen_random)
MYSQL_PASSWORD="$DB_PASSWORD"
# MariaDB 复用同一组生成的密码（compose 中按 profile 各取所需）
MARIADB_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD"
MARIADB_PASSWORD="$DB_PASSWORD"
POSTGRES_PASSWORD="$DB_PASSWORD"
info "安全配置完成"
echo ""

# ============================================================
# 步骤 3：镜像源加速
# ============================================================
echo -e "${GREEN}━━━ 步骤 3/6：镜像源加速 ━━━${NC}"
echo "  国内网络建议启用加速，否则 Docker 拉取镜像/构建可能超时失败。"
echo "  启用后：Docker 镜像走国内加速站、apt 用清华源、pip 用清华源。"
echo ""

# daemon 加速器是否就绪（国内模式下使用，决定后续是否需要手动 retag 兜底）
DAEMON_MIRROR_READY=false

if confirm "是否在中国 / 需要国内镜像加速？" "y"; then
    USE_MIRROR="yes"
    APT_MIRROR="mirrors.tuna.tsinghua.edu.cn"
    PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
    info "已启用国内镜像加速（apt/pip 用清华源）"
    echo ""

    # 推荐方式：写入 dockerd 的 registry-mirrors（对 build 与 compose up 全透明生效）
    if daemon_has_mirror; then
        info "检测到 Docker 守护进程已配置镜像加速器，镜像拉取将自动加速 ✓"
        DAEMON_MIRROR_READY=true
    else
        echo "  Docker 守护进程当前未配置 registry-mirrors。"
        echo "  配置后，所有镜像（含数据库 / Redis / 搜索引擎）拉取均自动走国内加速站："
        printf '    - %s\n' "${CN_REGISTRY_MIRRORS[@]}"
        echo ""
        echo "  该操作会【合并】写入 /etc/docker/daemon.json（保留已有配置并备份），"
        echo "  然后重启 Docker（运行中容器会短暂中断后自动恢复）。"
        if confirm "是否现在自动配置 Docker 守护进程加速器？" "y"; then
            if configure_daemon_mirrors; then
                DAEMON_MIRROR_READY=true
            else
                warn "守护进程加速器未配置成功，稍后将改用「镜像站前缀拉取 + retag」兜底"
            fi
        else
            info "已跳过守护进程配置，稍后使用镜像站前缀拉取 + retag 兜底（无需重启 Docker）"
        fi
    fi
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
echo -e "${GREEN}━━━ 步骤 4/6：搜索引擎（可选）━━━${NC}"
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
# 步骤 5：Redis 缓存与 Session（可选）
# ============================================================
echo -e "${GREEN}━━━ 步骤 5/6：Redis 缓存与 Session（可选）━━━${NC}"
echo "  启用 Redis 后，页面缓存与登录 Session 存入 Redis，支持多实例负载均衡。"
echo "  不启用则使用内置 SimpleCache + Cookie Session（单机部署零依赖）。"
echo ""
if confirm "是否启用 Redis？" "n"; then
    USE_REDIS="yes"
    REDIS_URL="redis://redis:6379/0"
    info "Redis 已配置（将自动启动 redis 容器）"
else
    USE_REDIS="no"
    REDIS_URL=""
    info "使用内置 SimpleCache + Cookie Session"
fi
echo ""

# ============================================================
# 步骤 6：端口与 Worker
# ============================================================
echo -e "${GREEN}━━━ 步骤 6/6：运行参数 ━━━${NC}"
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
echo "  Redis：           ${USE_REDIS}"
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
MARIADB_ROOT_PASSWORD=${MARIADB_ROOT_PASSWORD}
MARIADB_PASSWORD=${MARIADB_PASSWORD}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# Web 端口
WEB_PORT=${WEB_PORT}

# Gunicorn
GUNICORN_WORKERS=${GUNICORN_WORKERS}

# Meilisearch
MEILI_MASTER_KEY=${MEILI_MASTER_KEY}

# Redis（可选，启用后缓存与 Session 走 Redis）
REDIS_URL=${REDIS_URL}

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
# ------------------------------------------------------------
# 若 dockerd 已配置 registry-mirrors（步骤 3 自动配置或原本就有），
# build 与 compose up 拉镜像会自动走加速器，此处无需任何处理。
# 否则用「镜像站前缀拉取 + retag 为官方名」兜底，覆盖本次部署
# 所需的【全部】镜像：构建基础镜像(python) + 数据库 + 搜索 + Redis。
# ============================================================
if [ "$USE_MIRROR" = "yes" ]; then
    # 重新探测一次（步骤 3 可能刚重启过 docker）
    if daemon_has_mirror; then
        DAEMON_MIRROR_READY=true
    fi

    if [ "$DAEMON_MIRROR_READY" = "true" ]; then
        info "Docker 守护进程加速器已就绪，所有镜像将自动走国内加速站，跳过手动拉取 ✓"
    else
        info "未启用守护进程加速器，改用镜像站前缀拉取 + retag 兜底..."
        echo "  将依次尝试：${CN_MIRROR_HOSTS[*]}"
        echo ""

        # 组装本次部署需要的全部镜像（必须与 docker-compose.yml / Dockerfile 一致）
        REQUIRED_IMAGES=("python:3.12-slim")   # 多阶段构建的基础镜像
        OPTIONAL_IMAGES=()
        case "$DB_PROFILE" in
            mysql)    REQUIRED_IMAGES+=("mysql:8.4") ;;
            mariadb)  REQUIRED_IMAGES+=("mariadb:11.4") ;;
            postgres) REQUIRED_IMAGES+=("postgres:16-alpine") ;;
        esac
        [ "$USE_MEILI" = "yes" ] && OPTIONAL_IMAGES+=("getmeili/meilisearch:v1.8")
        [ "$USE_REDIS" = "yes" ] && OPTIONAL_IMAGES+=("redis:7-alpine")

        PULL_FAILED=()
        info "拉取必需镜像（构建 / 数据库）..."
        for img in "${REQUIRED_IMAGES[@]}"; do
            if ! pull_image_via_mirror "$img"; then
                PULL_FAILED+=("$img")
            fi
        done

        if [ ${#OPTIONAL_IMAGES[@]} -gt 0 ]; then
            info "拉取可选服务镜像（搜索引擎 / Redis）..."
            for img in "${OPTIONAL_IMAGES[@]}"; do
                if ! pull_image_via_mirror "$img"; then
                    PULL_FAILED+=("$img")
                fi
            done
        fi
        echo ""

        if [ ${#PULL_FAILED[@]} -gt 0 ]; then
            error "以下镜像经所有国内镜像站均拉取失败："
            printf '    - %s\n' "${PULL_FAILED[@]}"
            echo ""
            echo "  建议（任选其一）："
            echo "    A. 配置守护进程加速器后重试：重跑本脚本并在步骤 3 选择「自动配置」"
            echo "    B. 若主机可访问外网，可直接让 Docker 走默认源（耗时可能较长）"
            echo "    C. 检查网络/代理后手动拉取：docker pull <镜像名>"
            exit 1
        fi
        info "全部基础镜像拉取完成 ✓"
    fi
    echo ""
fi

# ============================================================
# 构建镜像
# ============================================================
info "构建 zhycms 镜像（首次构建约 3-5 分钟）..."
echo ""

cd "$PROJECT_DIR"

COMPOSE_PROFILES="--profile ${DB_PROFILE}"
[ "$USE_MEILI" = "yes" ] && COMPOSE_PROFILES="$COMPOSE_PROFILES --profile search"
[ "$USE_REDIS" = "yes" ] && COMPOSE_PROFILES="$COMPOSE_PROFILES --profile redis"

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

# 数据库凭据校验（数据卷由旧密码初始化时快速给出明确指引，而非等应用超时）
info "校验数据库连接..."
CREDS_OK=false
for _ in $(seq 1 30); do
    if [ "$DB_PROFILE" = "mysql" ]; then
        if "${COMPOSE_CMD[@]}" --profile mysql exec -T db-mysql mysql -uzhycms "-p${MYSQL_PASSWORD}" -e "SELECT 1" &>/dev/null; then
            CREDS_OK=true
            break
        fi
    elif [ "$DB_PROFILE" = "mariadb" ]; then
        if "${COMPOSE_CMD[@]}" --profile mariadb exec -T db-mariadb mariadb -uzhycms "-p${MARIADB_PASSWORD}" -e "SELECT 1" &>/dev/null; then
            CREDS_OK=true
            break
        fi
    else
        if "${COMPOSE_CMD[@]}" --profile postgres exec -T db-pg env PGPASSWORD="${POSTGRES_PASSWORD}" psql -U zhycms -d zhycms -tAc "SELECT 1" &>/dev/null; then
            CREDS_OK=true
            break
        fi
    fi
    sleep 2
done

if [ "$CREDS_OK" = "true" ]; then
    info "数据库连接验证通过 ✓"
else
    error "数据库密码验证失败（Access denied）"
    echo "  原因：数据卷由旧密码初始化，当前 .env 中的密码无法登录。"
    echo "  处理方式二选一："
    echo "    A. 保留数据：重跑安装脚本，选择「沿用已有数据」并输入旧密码"
    echo "    B. 清空重建（数据丢失）：${COMPOSE_CMD[*]} --profile $DB_PROFILE down -v"
    exit 1
fi
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
