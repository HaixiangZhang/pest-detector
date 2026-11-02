"""cli — 统一命令行入口（薄转发层）。

实际实现已迁入 ``src/pestdet/cli/main.py``；本文件只负责把仓库根的
``python cli.py ...`` 调用转发进包内，保持旧命令继续可用：

    python cli.py sahi    --source videos/test0.mp4
    python cli.py direct  --source videos/test0.mp4
    python cli.py roi     --source videos/test0.mp4
    python cli.py weights --list
"""

import sys
from pathlib import Path

# 未 pip install 时把 src/ 加入 sys.path，让仓库根的 python cli.py 也能 import pestdet
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pestdet.cli.main import main  # noqa: E402  （须在 sys.path 调整之后导入）


if __name__ == "__main__":
    raise SystemExit(main())