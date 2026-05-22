"""Root conftest: ensure in-memory forest is used during tests."""

import os

os.environ["FOREST_TYPE"] = "memory"
