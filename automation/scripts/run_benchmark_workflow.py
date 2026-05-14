#!/usr/bin/env python3
"""Unified SiliconBoutique benchmark workflow entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOMATION_LIB = REPO_ROOT / "automation" / "lib"
if str(AUTOMATION_LIB) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_LIB))

from silicon_boutique_automation.unified_workflow import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
