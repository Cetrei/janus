"""Hatchling build hook: compiles the cffi binding to hnsw-c (build_hnsw.py)
before the wheel is assembled.

Only runs the cffi compilation step. It does NOT run `make` in
vendor/hnsw/: build_hnsw.py already fails loudly and explicitly if hnsw.a
is missing, with instructions to build it first. That failure is
deliberately not caught or auto-fixed here (see build_hnsw.py's own
docstring on why a missing .a must not trigger a silent, possibly
non-release rebuild).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_ROOT = Path(__file__).parent


class CffiBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        result = subprocess.run(
            [sys.executable, str(_ROOT / "build_hnsw.py")],
            cwd=_ROOT,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "build_hnsw.py failed — see output above. Most likely "
                "vendor/hnsw/hnsw.a is missing; build it first with "
                "`make` in vendor/hnsw/."
            )
        build_data["pure_python"] = False
        build_data["infer_tag"] = True
