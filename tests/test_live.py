import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.integration
def test_real_worker_500_jobs():
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, 'tools/verify_live.py'], cwd=root,
                   env=os.environ.copy(), check=True, timeout=330)


@pytest.mark.integration
def test_real_worker_forced_crash():
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, 'tools/verify_crash.py'], cwd=root,
                   env=os.environ.copy(), check=True, timeout=230)
