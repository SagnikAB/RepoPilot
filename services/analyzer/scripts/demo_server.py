"""Local demo server for frontend development (not for production).

Starts the normal API on 127.0.0.1 and pre-loads the documented example
analysis (built by the real pipeline from tests/fixtures/repos/shop_api), so
the frontend can call every read endpoint without GitHub access:

    .venv/bin/python -m scripts.demo_server            # port 8000
    .venv/bin/python -m scripts.demo_server --port 8010

    GET /api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a          (summary)
    GET /api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a/graph
    GET /api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a/paths?source=...&target=...

POST /api/analyze works as usual (it clones from GitHub, so it needs network).
The example is in memory only and is re-created on every start.
"""

from __future__ import annotations

import argparse

import uvicorn

from app.config import get_settings
from app.main import create_app
from scripts.doc_fixtures import EXAMPLE_ANALYSIS_ID, example_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    settings = get_settings()
    app = create_app(settings)
    app.state.analysis_store.save(example_analysis(settings))
    print(f"Example analysis: http://127.0.0.1:{args.port}/api/analyses/{EXAMPLE_ANALYSIS_ID}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
