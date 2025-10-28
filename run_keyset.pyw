"""
KeySet - launch without terminal window (uses pythonw.exe).
"""
from __future__ import annotations

import os
import sys

# Установить UTF-8 кодировку
os.environ['PYTHONIOENCODING'] = 'utf-8'


def _bootstrap() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    os.chdir(project_root)

    from keyset.app.main import main

    main()


if __name__ == "__main__":
    _bootstrap()
