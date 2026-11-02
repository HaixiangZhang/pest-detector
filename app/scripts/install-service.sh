#!/usr/bin/env bash
#
# 安装 systemd 服务（Linux 服务器常驻）— pest_detector Web 服务
#
# 用法（需 root）:
#   sudo ./scripts/install-service.sh
#   sudo ./scripts/install-service.sh --host 0.0.0.0 --port 8000
#   sudo ./scripts/install-service.sh --home /data/pest_detector --user pest
#   sudo ./scripts/install-service.sh --python /opt/conda/envs/yolo11/bin/python
#   sudo ./scripts/install-service.sh --name pestdet --no-start
#
# 说明:
#   - 生成 /etc/systemd/system/<name>.service，然后 daemon-reload + enable（默认立即启动）。
#   - 默认 PESTDET_HOME = 仓库根；用 --home 指向独立数据盘时会创建 data/uploads、runs、logs，
#     并把 web/dist 软链过去（代码从 PESTDET_HOME/web/dist 读前端产物）。
#   - 卸载: sudo ./scripts/uninstall-service.sh [--name pestdet]
#   - 本文件必须保持 LF 换行（见 .gitattributes: *.sh text eol=lf）。

set -uo pipefail

NAME="pestdet"
HOST="0.0.0.0"
PORT="8000"
HOME_DIR=""
RUN_USER=""
RUN_GROUP=""
PYTHON="${PESTDET_PYTHON:-}"
MAX_UPLOAD_MB=""
DO_START=1

usage() {
    cat <<'EOF'
安装 pest_detector Web 服务为 systemd 常驻服务（需 root）

用法:
  sudo ./scripts/install-service.sh [选项]

选项:
      --name <name>          服务名（默认 pestdet → /etc/systemd/system/pestdet.service）
      --host <addr>          监听地址（默认 0.0.0.0）
      --port <port>          监听端口（默认 8000）
      --home <dir>           工作根 PESTDET_HOME（默认仓库根）
      --python <path>        指定解释器（默认自动探测装有依赖的 Python）
      --user <user>          以该用户运行服务（默认 root）
      --group <group>        以该用户组运行服务
      --max-upload-mb <n>    上传大小上限 MB（默认不写，用代码默认 4096）
      --no-start             只安装并 enable，不立即启动
  -h, --help                 显示本帮助
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)          NAME="${2:-}"; shift 2 ;;
        --host)          HOST="${2:-}"; shift 2 ;;
        --port)          PORT="${2:-}"; shift 2 ;;
        --home)          HOME_DIR="${2:-}"; shift 2 ;;
        --python)        PYTHON="${2:-}"; shift 2 ;;
        --user)          RUN_USER="${2:-}"; shift 2 ;;
        --group)         RUN_GROUP="${2:-}"; shift 2 ;;
        --max-upload-mb) MAX_UPLOAD_MB="${2:-}"; shift 2 ;;
        --no-start)      DO_START=0; shift ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "未知参数: $1" >&2; echo "用 --help 查看用法" >&2; exit 2 ;;
    esac
done

if [ -z "$NAME" ] || [ -z "$HOST" ] || [ -z "$PORT" ]; then
    echo "参数错误: --name / --host / --port 不能为空" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
[ -n "$HOME_DIR" ] || HOME_DIR="$ROOT"

# --- 前置检查 ---------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行:  sudo $0 $*" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "未找到 systemctl，本脚本仅支持 systemd 系统（容器内通常不可用）" >&2
    exit 1
fi

# --- 解释器探测 -------------------------------------------------------------
PROBE='import importlib.metadata as m; [m.version(p) for p in ("torch","ultralytics","fastapi","uvicorn")]'

resolve_python() {
    local cand
    for cand in "$PYTHON" "$ROOT/.venv/bin/python" "${CONDA_PREFIX:-}/bin/python" "$(command -v python3 2>/dev/null || true)"; do
        [ -n "$cand" ] || continue
        if [[ "$cand" == */* ]]; then [ -x "$cand" ] || continue; fi
        if "$cand" -c "$PROBE" >/dev/null 2>&1; then
            printf '%s' "$cand"
            return 0
        fi
    done
    return 1
}

PY="$(resolve_python)" || {
    echo "未找到装有项目依赖的 Python（需 torch/ultralytics/fastapi/uvicorn）。" >&2
    echo "请用 --python /path/to/envs/yolo11/bin/python 指定。" >&2
    exit 1
}

# --- 目录与前端产物 ---------------------------------------------------------
mkdir -p "$HOME_DIR/data/uploads" "$HOME_DIR/runs" "$HOME_DIR/logs"

if [ ! -f "$HOME_DIR/configs.yaml" ]; then
    echo "[警告] $HOME_DIR/configs.yaml 不存在；服务启动后读取配置会失败。" >&2
    if [ "$HOME_DIR" != "$ROOT" ]; then
        echo "       可执行: cp \"$ROOT/configs.yaml\" \"$HOME_DIR/configs.yaml\"" >&2
    fi
fi

if [ "$HOME_DIR" != "$ROOT" ] && [ ! -e "$HOME_DIR/web/dist" ]; then
    mkdir -p "$HOME_DIR/web"
    if ln -sfn "$ROOT/web/dist" "$HOME_DIR/web/dist" 2>/dev/null; then
        echo "[前端] 已建立软链 $HOME_DIR/web/dist -> $ROOT/web/dist"
    fi
fi
if [ ! -f "$HOME_DIR/web/dist/index.html" ]; then
    echo "[警告] $HOME_DIR/web/dist/index.html 不存在；根路径将没有界面（仅 /api/docs 可用）。" >&2
    echo "       请先在仓库根执行: ./scripts/start.sh --build  （或 cd web && npm install && npm run build）" >&2
fi

# --- 生成单元文件 -----------------------------------------------------------
UNIT="/etc/systemd/system/${NAME}.service"

{
    echo "[Unit]"
    echo "Description=pest_detector Web 服务"
    echo "Documentation=file://$ROOT/README.md"
    echo "After=network-online.target"
    echo "Wants=network-online.target"
    echo
    echo "[Service]"
    echo "Type=simple"
    echo "WorkingDirectory=$ROOT"
    echo "Environment=PESTDET_HOME=$HOME_DIR"
    echo "Environment=PYTHONPATH=$ROOT/src"
    [ -n "$MAX_UPLOAD_MB" ] && echo "Environment=PESTDET_MAX_UPLOAD_MB=$MAX_UPLOAD_MB"
    [ -n "$RUN_USER" ] && echo "User=$RUN_USER"
    [ -n "$RUN_GROUP" ] && echo "Group=$RUN_GROUP"
    echo "ExecStart=$PY -m pestdet.server --host $HOST --port $PORT"
    echo "Restart=on-failure"
    echo "RestartSec=5"
    echo "KillMode=mixed"
    echo "TimeoutStopSec=30"
    echo "StandardOutput=journal"
    echo "StandardError=journal"
    echo
    echo "[Install]"
    echo "WantedBy=multi-user.target"
} > "$UNIT"

echo "[安装] 已写入 $UNIT"
echo "[安装] 解释器: $PY"
echo "[安装] 工作根: $HOME_DIR"
echo "[安装] 监听:   $HOST:$PORT"

# --- 生效 -------------------------------------------------------------------
systemctl daemon-reload || { echo "[错误] systemctl daemon-reload 失败" >&2; exit 1; }

if [ "$DO_START" = 1 ]; then
    systemctl enable --now "$NAME" || { echo "[错误] systemctl enable --now $NAME 失败" >&2; exit 1; }
else
    systemctl enable "$NAME" || { echo "[错误] systemctl enable $NAME 失败" >&2; exit 1; }
fi

echo
systemctl --no-pager --full status "$NAME" | head -n 15 || true
echo
echo "常用命令:"
echo "  systemctl status $NAME         # 查看状态"
echo "  systemctl restart $NAME        # 重启（改配置/换权重后）"
echo "  systemctl stop $NAME           # 停止"
echo "  journalctl -u $NAME -f         # 跟踪服务日志"