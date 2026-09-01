import os
from pathlib import Path

from fastapi import FastAPI

APP_NAME = "GBM Flipbook"
DEFAULT_STORAGE_PATH = "/data/flipbooks"


def get_storage_path() -> Path:
    return Path(os.getenv("FLIPBOOK_STORAGE_PATH", DEFAULT_STORAGE_PATH)).expanduser()


def ensure_storage_path() -> Path:
    storage_path = get_storage_path()
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


app = FastAPI(
    title=APP_NAME,
    description="Minimal Render-deployable API for the GBM Flipbook service.",
    version="0.1.0",
)


@app.on_event("startup")
def startup() -> None:
    ensure_storage_path()


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "app": APP_NAME,
        "message": "GBM Flipbook service is running.",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/book/{slug}")
def read_book(slug: str) -> dict[str, str]:
    return {
        "slug": slug,
        "status": "placeholder",
        "message": "Flipbook viewer will be implemented in a future phase.",
    }
