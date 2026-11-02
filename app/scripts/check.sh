#!/usr/bin/env bash
#
# 环境自检脚本（不启动服务）
#
# 用法:
#   ./scripts/check.sh
#   ./scripts/check.sh --port 8001
#   ./scripts/check.sh --python /path/to/python
#
# 说明: 转发到 start.sh --check，检查解释器/依赖、configs.yaml、模型权重、
#       前端产物、Node/npm、ffmpeg、端口占用、数据目录可写性。
#       退出码 0 = 通过（可能有警告），1 = 有错误。
#       本文件必须保持 LF 换行（见 .gitattributes: *.sh text eol=lf）。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start.sh" --check "$@"