"""Root conftest: ensure in-memory backend is used during tests."""

import os

os.environ["BIODATA_CACHE_BACKEND"] = "memory"
