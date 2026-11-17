"""Run the API:  python serve_api.py   (http://localhost:8000/docs for the interactive docs)

Deployed (Render): EMBEDDING_BACKEND=fastembed, and if DATABASE_PATH does not exist yet it is unpacked from
deploy/research_match.db.gz (made by export_serving_db.py).
"""
import gzip
import os
import shutil

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import uvicorn  # noqa: E402

from researchmatch.api import create_app  # noqa: E402
from researchmatch.config import PROJECT_ROOT, load_settings  # noqa: E402
from researchmatch.embedding import from_settings  # noqa: E402

settings = load_settings()
packed = PROJECT_ROOT / "deploy" / "research_match.db.gz"
if not settings.database_path.exists() and packed.exists():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(packed, "rb") as src, settings.database_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"unpacked {packed.name} -> {settings.database_path}", flush=True)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app = create_app(settings.database_path, from_settings(settings), settings.ranking, allowed_origins=origins)

if __name__ == "__main__":
    # Render (and most hosts) set PORT and need 0.0.0.0; locally stay on 127.0.0.1
    port = os.getenv("PORT") or os.getenv("API_PORT", "8000")
    host = os.getenv("API_HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    uvicorn.run(app, host=host, port=int(port), proxy_headers=False)
