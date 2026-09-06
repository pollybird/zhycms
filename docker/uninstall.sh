#!/bin/bash
# ============================================================
# zhycms Docker 卸载脚本
# 用法：bash docker/uninstall.sh
# 功能：停止容器 → 删除容器/卷/镜像 → 可选删除 .env
# ============================================================
set -euo pipefail

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
confirm() {
    local question="$1" default="${2:-y}"
    local hint; [ "$default" = "y" ] && hint="[Y/n]" || hint="[y/N]"
    echo -en "${BLUE}${question}${NC} ${hint} "
    read -r answer
    [ -z "$answer" ] && answer="$default"
    [[ "$answer" =~ ^[Yy] ]]
}

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# 检测 compose 命令（优先 v2）
if docker compose version &>/dev/null; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose &>/dev/null && docker-compose version &>/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    error "未检测到可用的 docker compose"
    echo "  请安装 Docker Compose v2 插件"
    exit 1
fi

echo ""
echo -e "${YELLOW}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║              zhycms Docker 卸载                   ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  本脚本将停止并删除 zhycms 的 Docker 容器、卷和镜像。"
echo "  数据（数据库、上传文件、配置）将根据你的选择保留或删除。"
echo ""

# ---- 确认 ----
if ! confirm "确定要卸载 zhycms Docker 部署？" "n"; then
    info "已取消"
    exit 0
fi
echo ""

# ---- 步骤 1：停止并删除容器 ----
info "停止并删除容器..."
for profile in mysql postgres search; do
    "${COMPOSE_CMD[@]}" --profile "$profile" down --remove-orphans 2>/dev/null || true
done
"${COMPOSE_CMD[@]}" down --remove-orphans 2>/dev/null || true
info "容器已清理 ✓"
echo ""

# ---- 步骤 2：删除 Docker 卷（数据库数据 + 上传文件） ----
echo -e "${YELLOW}Docker 卷包含数据库数据和上传文件：${NC}"
docker volume ls --filter "name=zhycms" --format "{{.Name}}" 2>/dev/null | while read -r vol; do
    echo "  - $vol"
done
echo ""
if confirm "是否删除所有 Docker 卷（数据将永久丢失）？" "n"; then
    info "删除卷..."
    docker volume ls --filter "name=zhycms" --format "{{.Name}}" 2>/dev/null | while read -r vol; do
        docker volume rm "$vol" 2>/dev/null && info "  已删除：$vol ✓" || warn "  删除失败：$vol"
    done
    info "卷已清理 ✓"
else
    warn "卷已保留（下次安装可复用数据）"
fi
echo ""

# ---- 步骤 3：删除镜像 ----
if confirm "是否删除 zhycms 构建镜像？" "n"; then
    info "删除镜像..."
    docker images --filter "reference=zhycms*" --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | while read -r img; do
        docker rmi "$img" 2>/dev/null && info "  已删除：$img ✓" || true
    done
    # 兼容 compose 自动命名的镜像
    docker images --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | grep -i "zhycms" | while read -r img; do
        docker rmi "$img" 2>/dev/null && info "  已删除：$img ✓" || true
    done
    info "镜像已清理 ✓"
else
    warn "镜像已保留"
fi
echo ""

# ---- 步骤 4：删除 .env ----
ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    if confirm "是否删除 .env 配置文件？" "n"; then
        rm -f "$ENV_FILE"
        info ".env 已删除 ✓"
    else
        warn ".env 已保留"
    fi
fi
echo ""

# ---- 步骤 5：提示残留目录 ----
echo -e "${YELLOW}注意：以下目录为宿主机挂载卷，需手动删除（如需）：${NC}"
[ -d "$PROJECT_DIR/instance" ]         && echo "  - $PROJECT_DIR/instance/        （数据库配置、备份）"
[ -d "$PROJECT_DIR/app/static/uploads" ] && echo "  - $PROJECT_DIR/app/static/uploads/  （上传文件）"
echo ""

# ---- 完成 ----
echo -e "${GREEN}卸载完成。${NC}"
echo ""
