"""Run the API locally:  python serve_api.py   (http://localhost:8000/docs for the interactive docs)"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import uvicorn  # noqa: E402

from researchmatch.api import create_app  # noqa: E402
from researchmatch.config import load_settings  # noqa: E402
from researchmatch.embedding import from_settings  # noqa: E402

settings = load_settings()
origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app = create_app(settings.database_path, from_settings(settings), settings.ranking, allowed_origins=origins)

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("API_HOST", "127.0.0.1"), port=int(os.getenv("API_PORT", "8000")))
