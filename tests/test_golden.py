"""Golden outputs of the release-candidate modes (tools/golden.py, tests/golden/): a change that
moves any encoder's frames, a fixed-point decoder's samples or a float decoder's PESQ fails
here. If the move is meant, run python tools/golden.py --update and commit tests/golden/.
SPDX-License-Identifier: MIT"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import golden  # noqa: E402


@pytest.mark.skipif(bool(golden.need_builds()), reason="needs make, make fixed and make c37")
def test_golden_outputs_unchanged():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "golden.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[r.stdout.find("GOLDEN"):] + r.stderr
