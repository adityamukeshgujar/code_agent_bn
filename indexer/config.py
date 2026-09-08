"""Central place that loads .env and exposes config. Import this (or any
module that imports it) before reading credentials so .env is guaranteed to
be loaded exactly once."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

QDRANT_URL = os.environ.get("QDRANT_URL")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")

# Reserved for later phases (intent parsing, patch generation) — not used
# by the indexer/embedder; Groq has no embeddings endpoint.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Reserved for Phase 5 (git/PR integration) — deferred, not used yet.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")  # "owner/name"
