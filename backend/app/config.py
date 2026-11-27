"""Deployment settings; never infer permissions from a request or an old index."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")


def data_dir() -> Path:
    return Path(os.getenv("RAG_DATA_DIR") or BACKEND / "data" / "enterprise").resolve()


def access_path() -> Path:
    return Path(os.getenv("RAG_ACCESS_FILE") or data_dir() / "access.json").resolve()
