#!/usr/bin/env bash
#
# 卸载 systemd 服务（pest_detector Web）
#
# 用法（需 root）:
#   sudo ./scripts/uninstall-service.sh
#   sudo ./scripts/uninstall-service.sh --name pestdet
#
# 说明: 停止并禁用服务，删除 /etc/systemd/system/<name>.service。
#       **不会**删除 runs/ data/ logs/ 等数据目录，也不会动仓库文件。
#       本文件必须保持 LF 换行（见 .gitattributes: *.sh text eol=lf）。

set -uo pipefail

NAME="pestdet"

while [ $# -gt 0 ]; do
    case "$1" in
        --name)    NAME="${2:-}"; shift 2 ;;
        -h|--help) echo "用法: sudo $0 [--name pestdet]"; exit 0 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$NAME" ]; then
    echo "参数错误: --name 不能为空" >&2
    exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行:  sudo $0 $*" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "未找到 systemctl，本脚本仅支持 systemd 系统" >&2
    exit 1
fi

UNIT="/etc/systemd/system/${NAME}.service"

systemctl disable --now "$NAME" 2>/dev/null || true

if [ -f "$UNIT" ]; then
    rm -f "$UNIT"
    echo "[卸载] 已删除 $UNIT"
else
    echo "[卸载] 未找到 $UNIT（可能未安装，或服务名不是 $NAME）"
fi

systemctl daemon-reload 2>/dev/null || true
systemctl reset-failed "$NAME" 2>/dev/null || true

echo "[卸载] 完成（数据目录 runs/ data/ logs/ 未改动）"