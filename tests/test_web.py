from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is needed for UI regression tests')
def test_javascript_conversation_rendering():
    suite = Path(__file__).with_suffix('.cjs')
    result = subprocess.run([shutil.which('node'), '--test', str(suite)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
