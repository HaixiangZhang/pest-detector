#!/usr/bin/env bash
#
# pest_detector Web 服务启动脚本（Linux / macOS）
#
# 用法:
#   ./scripts/start.sh                                  自检 + 启动；Ctrl+C 停止
#   ./scripts/start.sh --check                          只做环境自检，不启动（等价 scripts/check.sh）
#   ./scripts/start.sh --build                          强制重新构建前端后启动
#   ./scripts/start.sh --reload                         开发热重载（改后端代码自动重启）
#   ./scripts/start.sh --install                        依赖缺失时自动安装到当前解释器
#   ./scripts/start.sh --open                           启动后自动打开浏览器（需桌面环境）
#   ./scripts/start.sh --host 0.0.0.0 --port 8000       对外提供服务（服务器 / 局域网）
#   ./scripts/start.sh --python /path/to/python         显式指定解释器
#
# 说明:
#   - 自动探测"装有项目依赖"的 Python（torch / ultralytics / fastapi / uvicorn），无需手动 conda activate。
#   - 探测顺序: --python > $PESTDET_PYTHON > 缓存(.pestdet-python) > $CONDA_PREFIX
#               > PATH(python3/python) > .venv > 常见 conda 安装位置的 envs/*。
#   - 工作根 = $PESTDET_HOME（未设置时 = 仓库根）；configs.yaml / runs / data / web/dist
#     都相对它解析，与 src/pestdet/infra/paths.py 的 _resolve_root() 保持一致。
#   - 启动前自检: 解释器/依赖、configs.yaml、模型权重、前端产物、Node/npm、ffmpeg、端口、数据目录。
#   - web/dist 不存在时自动构建前端（需要 Node.js）。
#   - 推理在进程内单 worker 串行执行，请勿多 worker 启动。
#   - 本文件必须保持 LF 换行（见 .gitattributes: *.sh text eol=lf）。

set -uo pipefail

# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------
HOST="127.0.0.1"
PORT="8000"
PYTHON="${PESTDET_PYTHON:-}"
DO_BUILD=0
DO_RELOAD=0
DO_INSTALL=0
CHECK_ONLY=0
DO_OPEN=0

usage() {
    cat <<'EOF'
pest_detector Web 服务启动脚本（Linux / macOS）

用法:
  ./scripts/start.sh [选项]

选项:
  -H, --host <addr>    监听地址（默认 127.0.0.1；服务器用 0.0.0.0）
  -p, --port <port>    监听端口（默认 8000）
      --python <path>  指定 Python 解释器（优先于自动探测）
  -b, --build          强制重新构建前端（web/dist）
  -r, --reload         开发热重载（改后端代码自动重启）
  -i, --install        依赖缺失时自动安装到当前解释器（pip install -e ".[web]"）
  -c, --check          只做环境自检，不启动（退出码 0=通过 1=有错误）
  -o, --open           启动后自动打开浏览器（需桌面环境）
  -h, --help           显示本帮助

环境变量:
  PESTDET_PYTHON       默认 Python 解释器路径
  PESTDET_HOME         工作根（configs.yaml / runs / data / web/dist 所在目录），默认仓库根
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -H|--host)    HOST="${2:-}"; shift 2 ;;
        -p|--port)    PORT="${2:-}"; shift 2 ;;
        --python)     PYTHON="${2:-}"; shift 2 ;;
        -b|--build)   DO_BUILD=1; shift ;;
        -r|--reload)  DO_RELOAD=1; shift ;;
        -i|--install) DO_INSTALL=1; shift ;;
        -c|--check)   CHECK_ONLY=1; shift ;;
        -o|--open)    DO_OPEN=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "未知参数: $1" >&2; echo "用 --help 查看用法" >&2; exit 2 ;;
    esac
done

if [ -z "$HOST" ] || [ -z "$PORT" ]; then
    echo "参数错误: --host / --port 不能为空" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# 工作根与 src/pestdet/infra/paths.py 的 _resolve_root() 保持一致
if [ -n "${PESTDET_HOME:-}" ]; then
    HOME_DIR="$(cd "$PESTDET_HOME" 2>/dev/null && pwd || printf '%s' "$PESTDET_HOME")"
else
    HOME_DIR="$ROOT"
fi

# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_FAIL=$'\033[31m'
    C_DIM=$'\033[90m'; C_CYAN=$'\033[36m'; C_OFF=$'\033[0m'
else
    C_OK=''; C_WARN=''; C_FAIL=''; C_DIM=''; C_CYAN=''; C_OFF=''
fi

FAIL_COUNT=0
WARN_COUNT=0

ok()   { printf '  %s[OK]%s   %s' "$C_OK" "$C_OFF" "$1"; [ -n "${2:-}" ] && printf '  %s%s%s' "$C_DIM" "$2" "$C_OFF"; printf '\n'; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); printf '  %s[WARN]%s %s' "$C_WARN" "$C_OFF" "$1"; [ -n "${2:-}" ] && printf '  %s%s%s' "$C_DIM" "$2" "$C_OFF"; printf '\n'; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf '  %s[FAIL]%s %s' "$C_FAIL" "$C_OFF" "$1"; [ -n "${2:-}" ] && printf '  %s%s%s' "$C_DIM" "$2" "$C_OFF"; printf '\n'; }

# ---------------------------------------------------------------------------
# 解释器探测
# ---------------------------------------------------------------------------
# 判据: 同时具备 torch / ultralytics / fastapi / uvicorn 四个发行版。
# 用 importlib.metadata 查"已安装发行版"，不真正 import（快、不加载 CUDA）。
PROBE='import importlib.metadata as m; [m.version(p) for p in ("torch","ultralytics","fastapi","uvicorn")]'
CACHE_FILE="$ROOT/.pestdet-python"

read_cache() {
    [ -f "$CACHE_FILE" ] || return 0
    local p
    p="$(tr -d '\r\n' < "$CACHE_FILE" 2>/dev/null)"
    p="${p#$'\xef\xbb\xbf'}"   # 剥掉 PowerShell 写缓存时可能带上的 UTF-8 BOM
    [ -n "$p" ] && printf '%s' "$p"
}

write_cache() {
    [ -n "${1:-}" ] || return 0
    printf '%s' "$1" > "$CACHE_FILE" 2>/dev/null || true
}

test_python() {
    local exe="${1:-}"
    [ -n "$exe" ] || return 1
    if [[ "$exe" == */* ]]; then
        [ -x "$exe" ] || return 1
    else
        command -v "$exe" >/dev/null 2>&1 || return 1
    fi
    "$exe" -c "$PROBE" >/dev/null 2>&1
}

collect_candidates() {
    _cc_cached="$(read_cache)"
    _cc_venv="$ROOT/.venv/bin/python"
    {
        [ -n "$PYTHON" ] && printf '%s\n' "$PYTHON"
        [ -n "$_cc_cached" ] && printf '%s\n' "$_cc_cached"
        [ -n "${CONDA_PREFIX:-}" ] && printf '%s\n' "$CONDA_PREFIX/bin/python"
        command -v python3 2>/dev/null || true
        command -v python 2>/dev/null || true
        [ -x "$_cc_venv" ] && printf '%s\n' "$_cc_venv"
        for _cc_base in "${HOME:-}/miniconda3" "${HOME:-}/anaconda3" "${HOME:-}/miniforge3" "${HOME:-}/mambaforge" /opt/conda /opt/miniconda3; do
            [ -d "$_cc_base" ] || continue
            for _cc_p in "$_cc_base"/envs/*/bin/python "$_cc_base"/bin/python; do
                [ -x "$_cc_p" ] && printf '%s\n' "$_cc_p"
            done
        done
    } | awk 'NF && !seen[$0]++'
}

# 解析部署权重: configs.yaml 的 model_path，留空则回退 runs/registry.json 最新登记。
model_path_from_config() {
    local cfg="$HOME_DIR/configs.yaml"
    [ -f "$cfg" ] || return 0
    if [ -n "$CHOSEN" ]; then
        "$CHOSEN" - "$cfg" <<'PY' 2>/dev/null
import re, sys
try:
    text = open(sys.argv[1], encoding="utf-8").read()
except OSError:
    sys.exit(0)
m = re.search(r"(?m)^\s*model_path\s*:\s*(.*)$", text)
if m:
    print(m.group(1).split("#", 1)[0].strip().strip("\"'"))
PY
    else
        grep -E '^[[:space:]]*model_path[[:space:]]*:' "$cfg" 2>/dev/null \
            | head -n1 | cut -d: -f2- | sed 's/#.*//' | tr -d ' \t\r"' | tr -d "'"
    fi
}

model_path_from_registry() {
    local reg="$HOME_DIR/runs/registry.json"
    [ -f "$reg" ] || return 0
    [ -n "$CHOSEN" ] || return 0
    "$CHOSEN" - "$reg" <<'PY' 2>/dev/null
import json, re, sys
try:
    j = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(0)
w = j.get("weights") or {}

def num(name):
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0

if w:
    last = sorted(w, key=num)[-1]
    print((w[last] or {}).get("path", ""))
PY
}

port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${port}\$"
    elif command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}\$"
    else
        return 1
    fi
}

# ===========================================================================
# 环境自检
# ===========================================================================
echo
echo "${C_CYAN}pest_detector 环境自检${C_OFF}"
echo "${C_DIM}------------------------------------------------------------${C_OFF}"
if [ "$HOME_DIR" != "$ROOT" ]; then
    echo "  工作根: $HOME_DIR  ${C_DIM}(PESTDET_HOME)${C_OFF}"
else
    echo "  工作根: $HOME_DIR"
fi

# 1) 解释器 + 依赖
CHOSEN=""
CANDIDATES="$(collect_candidates)"
while IFS= read -r cand; do
    [ -n "$cand" ] || continue
    if test_python "$cand"; then CHOSEN="$cand"; break; fi
done <<< "$CANDIDATES"

if [ -z "$CHOSEN" ] && [ "$DO_INSTALL" = 1 ]; then
    if [ -n "${CONDA_PREFIX:-}" ]; then TARGET="$CONDA_PREFIX/bin/python"
    elif [ -n "$PYTHON" ]; then TARGET="$PYTHON"
    else TARGET="python3"; fi
    echo "${C_CYAN}[安装] 向 $TARGET 安装 Web 依赖（临时禁用 user site，确保装进环境本身）...${C_OFF}"
    PYTHONNOUSERSITE=1 "$TARGET" -m pip install -e ".[web]"
    test_python "$TARGET" && CHOSEN="$TARGET"
fi

if [ -n "$CHOSEN" ]; then
    write_cache "$CHOSEN"
    ok "Python 解释器" "$CHOSEN"
    info="$("$CHOSEN" -c 'import sys, importlib.metadata as m; print("py" + sys.version.split()[0]); print(" ".join(p + "=" + m.version(p) for p in ("torch","ultralytics","fastapi","uvicorn","pydantic")))' 2>/dev/null | tr -d '\r' | tr '\n' ' ')"
    [ -n "$info" ] && printf '         %s%s%s\n' "$C_DIM" "$info" "$C_OFF"
else
    fail "Python 解释器" "未找到装有项目依赖的 Python（需 torch/ultralytics/fastapi/uvicorn）"
    printf '         %s已尝试:%s\n' "$C_DIM" "$C_OFF"
    while IFS= read -r c; do
        [ -n "$c" ] && printf '           %s- %s%s\n' "$C_DIM" "$c" "$C_OFF"
    done <<< "$CANDIDATES"
fi

# 2) configs.yaml
CFG_PATH="$HOME_DIR/configs.yaml"
if [ -f "$CFG_PATH" ]; then
    ok "configs.yaml" "$CFG_PATH"
else
    fail "configs.yaml" "缺失（服务无法启动；请从版本库恢复，或把 PESTDET_HOME 指到含它的目录）"
fi

# 3) 模型权重
MODEL_RAW="$(model_path_from_config)"
[ -z "$MODEL_RAW" ] && MODEL_RAW="$(model_path_from_registry)"
case "$MODEL_RAW" in ./*) MODEL_RAW="${MODEL_RAW#./}" ;; esac
MODEL_PATH=""
case "$MODEL_RAW" in
    "")  MODEL_PATH="" ;;
    /*)  MODEL_PATH="$MODEL_RAW" ;;
    *)   MODEL_PATH="$HOME_DIR/$MODEL_RAW" ;;
esac

if [ -z "$MODEL_PATH" ]; then
    warn "模型权重" "configs.yaml 的 model_path 为空且 runs/registry.json 无登记 → 任务会在运行时失败"
elif [ -f "$MODEL_PATH" ]; then
    mb="$(du -m "$MODEL_PATH" 2>/dev/null | awk '{print $1}')"
    ok "模型权重" "$MODEL_PATH  (${mb:-?} MB)"
else
    fail "模型权重" "路径不存在: $MODEL_PATH"
fi

# 4) 前端产物（代码从 PESTDET_HOME/web/dist 挂载，非仓库根）
DIST="$HOME_DIR/web/dist"
if [ -f "$DIST/index.html" ]; then
    built="$(date -r "$DIST/index.html" '+%Y-%m-%d %H:%M' 2>/dev/null || stat -c '%y' "$DIST/index.html" 2>/dev/null | cut -d. -f1)"
    ok "前端产物 web/dist" "$DIST  (构建于 ${built:-未知})"
else
    warn "前端产物 web/dist" "$DIST 不存在 → 启动时会尝试自动构建（需要 Node.js）"
fi

# 5) Node / npm
if command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
    ok "Node / npm" "node $(node --version 2>/dev/null)"
else
    warn "Node / npm" "未找到 → 无法构建前端（已有 web/dist 时不影响启动）"
fi

# 6) ffmpeg（可选：输出视频转 H.264，浏览器播放更流畅）
if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg" "$(command -v ffmpeg)"
else
    warn "ffmpeg" "未在 PATH 中找到 → 输出视频保留 mp4v（可播，但 4K 拖动可能卡）"
fi

# 7) 端口占用
if port_in_use "$PORT"; then
    fail "端口 $PORT" "已被占用 → 换端口: --port 8001，或先结束该进程（ss -ltnp | grep :$PORT）"
else
    ok "端口 $PORT" "空闲"
fi

# 8) 数据目录可写
BAD_DIRS=""
for d in "$HOME_DIR/data/uploads" "$HOME_DIR/runs"; do
    probe="$d/.pestdet_write_test"
    if mkdir -p "$probe" 2>/dev/null; then
        rmdir "$probe" 2>/dev/null || true
    else
        BAD_DIRS="$BAD_DIRS $d"
    fi
done
if [ -z "$BAD_DIRS" ]; then
    ok "数据目录可写" "data/uploads  runs"
else
    fail "数据目录可写" "不可写:$BAD_DIRS"
fi

echo "${C_DIM}------------------------------------------------------------${C_OFF}"
if [ "$FAIL_COUNT" -eq 0 ]; then
    tail_msg=""
    [ "$WARN_COUNT" -gt 0 ] && tail_msg="（$WARN_COUNT 项警告，不影响启动）"
    echo "${C_OK}自检通过 $tail_msg${C_OFF}"
else
    echo "${C_FAIL}自检发现 $FAIL_COUNT 项错误、$WARN_COUNT 项警告${C_OFF}"
fi
echo

if [ "$CHECK_ONLY" = 1 ]; then
    [ "$FAIL_COUNT" -gt 0 ] && exit 1
    exit 0
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "${C_WARN}解决办法:${C_OFF}"
    echo "  1) 指定项目解释器:  --python /path/to/envs/yolo11/bin/python"
    echo "  2) 自动装 Web 依赖: --install"
    echo "  3) 端口被占用:      --port 8001"
    exit 1
fi

# ---------------------------------------------------------------------------
# 前端构建
# ---------------------------------------------------------------------------
# PESTDET_HOME 指向独立数据盘时，代码从 $PESTDET_HOME/web/dist 读前端产物，
# 而 Vite 只会在仓库根 $ROOT/web/dist 生成；这里建软链把两边打通。
ensure_dist_visible() {
    [ "$HOME_DIR" = "$ROOT" ] && return 0
    local dst="$HOME_DIR/web/dist"
    [ -e "$dst" ] && return 0
    mkdir -p "$HOME_DIR/web" 2>/dev/null || return 0
    if ln -sfn "$ROOT/web/dist" "$dst" 2>/dev/null; then
        echo "${C_CYAN}[前端] 已建立软链 $dst -> $ROOT/web/dist${C_OFF}"
    fi
}

if [ "$DO_BUILD" = 1 ] || [ ! -f "$DIST/index.html" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "${C_WARN}[前端] 未找到 npm，跳过构建；根路径将没有界面（仅 /docs 可用）${C_OFF}"
    else
        echo "${C_CYAN}[前端] 构建中 (web/dist) ...${C_OFF}"
        if [ ! -d "$ROOT/web/node_modules" ]; then
            (cd "$ROOT/web" && npm install) || { echo "${C_FAIL}[错误] npm install 失败${C_OFF}"; exit 1; }
        fi
        (cd "$ROOT/web" && npm run build) || { echo "${C_FAIL}[错误] 前端构建失败${C_OFF}"; exit 1; }
    fi
else
    echo "${C_DIM}[前端] web/dist 已存在，跳过构建（需要重建时加 --build）${C_OFF}"
fi
ensure_dist_visible

# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
URL_HOST="$HOST"
[ "$HOST" = "0.0.0.0" ] && URL_HOST="127.0.0.1"
URL="http://${URL_HOST}:${PORT}/"
echo "${C_CYAN}[启动] $URL  (Ctrl+C 停止)${C_OFF}"

if [ "$DO_OPEN" = 1 ]; then
    (
        sleep 3
        if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
        elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1
        fi
    ) &
fi

SERVER_ARGS=(-m pestdet.server --host "$HOST" --port "$PORT")
[ "$DO_RELOAD" = 1 ] && SERVER_ARGS+=(--reload)
exec "$CHOSEN" "${SERVER_ARGS[@]}"