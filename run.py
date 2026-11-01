# -*- coding: utf-8 -*-
"""JellyIcons 入口。

用法：
  python run.py              一直运行
  python run.py 5            运行 5 秒（限时测试）
  python run.py --diagnose   诊断模式（不动桌面，只报告链路健康）
  python run.py --diagnose 8 诊断并监听音频 8 秒
"""
import sys

from jellyicons.app import main

if __name__ == "__main__":
    sys.exit(main())
