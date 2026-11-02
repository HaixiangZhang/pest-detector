"""server — Uvicorn 启动入口。

用法:
    python -m pestdet.server                      # 127.0.0.1:8000
    python -m pestdet.server --host 0.0.0.0 --port 8000
    python -m pestdet.server --reload             # 开发热重载

注意: 任务执行器是**进程内**的，多 worker 会各自持有一份任务库与执行器；
MVP 阶段请用单 worker（默认），多用户阶段改用独立推理进程 + 队列。
"""

import argparse

import uvicorn

_APP = "pestdet.api.app:create_app"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="pest_detector Web 服务（FastAPI + Uvicorn）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（服务器部署用 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发热重载")
    parser.add_argument("--log-level", default="info", help="uvicorn 日志级别")
    args = parser.parse_args(argv)

    uvicorn.run(
        _APP,
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()