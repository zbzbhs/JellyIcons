# -*- coding: utf-8 -*-
"""一个命令跑完所有单测 + 冒烟。CI 与本地共用。

    python -X utf8 run_tests.py

注意：不要用 `python -m unittest tests.test_jelly`——venv 里 ultralytics
的 `tests` 包会遮蔽我们的包名（环境问题，非代码问题）。
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
TARGETS = [
    "tests/test_jelly.py",
    "tests/test_activity.py",
    "tests/test_app.py",
    "tests/test_music_mode.py",
    "tests/test_audio.py",
    "tests/test_pidl.py",
    "tests/test_single_instance.py",
    "smoke_v13.py",
]


def main():
    failed = []
    for rel in TARGETS:
        print("=" * 60)
        print(">>", rel)
        print("=" * 60)
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(BASE / rel)],
            cwd=str(BASE),
        )
        if proc.returncode != 0:
            failed.append(rel)
    print()
    if failed:
        print("[FAIL] %d 个文件未通过：" % len(failed))
        for rel in failed:
            print("  -", rel)
        return 1
    print("[OK] 全部通过（7 个单测文件 + 1 个端到端冒烟）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
