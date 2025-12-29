"""
NetworkSpace 入口文件
---------------------

便于通过 `python main.py` 直接运行 CLI。
"""

import sys

from networkspace.cli import main


if __name__ == "__main__":
    # 将命令行参数传递给 CLI 层，保证 --interactive 等参数生效
    raise SystemExit(main(sys.argv[1:]))


