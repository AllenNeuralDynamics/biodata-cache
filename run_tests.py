#!/usr/bin/env python
"""Test runner that delegates to pytest."""

import subprocess
import sys

if __name__ == "__main__":
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-v"],
        check=False,
    )
    sys.exit(result.returncode)
