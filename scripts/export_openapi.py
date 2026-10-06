"""Write the FastAPI OpenAPI schema for the web client's generated types.

Usage: python scripts/export_openapi.py web/src/api/openapi.json
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("APP_SECRET_KEY", "openapi-export-only")
os.environ.setdefault("DEBUG", "true")

from app.main import app  # noqa: E402

out = sys.argv[1]
schema = app.openapi()
schema["paths"] = {k: v for k, v in schema["paths"].items() if k.startswith("/api/v1/")}
with open(out, "w") as f:
    json.dump(schema, f, indent=2, sort_keys=True)
    f.write("\n")
