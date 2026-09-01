import os
from pathlib import Path

from fastapi import FastAPI

APP_NAME = "GBM Flipbook"
DEFAULT_STORAGE_PATH = "/data/flipbooks"
FALLBACK_STORAGE_PATH = "/tmp/flipbooks"

active_storage_path: Path | None = None
storage_warning: str | None = None


def get_storage_path() -> Path:
    return Path(os.getenv("FLIPBOOK_STORAGE_PATH", DEFAULT_STORAGE_PATH)).expanduser()


def ensure_storage_path() -> Path:
    global active_storage_path, storage_warning

    storage_path = get_storage_path()

    try:
        storage_path.mkdir(parents=True, exist_ok=True)
        active_storage_path = storage_path
        storage_warning = None
    except PermissionError:
        fallback_path = Path(FALLBACK_STORAGE_PATH)
        fallback_path.mkdir(parents=True, exist_ok=True)
        active_storage_path = fallback_path
        storage_warning = (
            f"Could not write to {storage_path}. Using temporary storage at "
            f"{fallback_path}. Attach the Render disk at {storage_path} for persistence."
        )

    return active_storage_path


app = FastAPI(
    title=APP_NAME,
    description="Minimal Render-deployable API for the GBM Flipbook service.",
    version="0.1.1",
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
    storage_path = active_storage_path or ensure_storage_path()
    response = {
        "status": "ok",
        "storage_path": str(storage_path),
    }
    if storage_warning:
        response["storage_warning"] = storage_warning
    return response


@app.get("/book/{slug}")
def read_book(slug: str) -> dict[str, str]:
    return {
        "slug": slug,
        "status": "placeholder",
        "message": "Flipbook viewer will be implemented in a future phase.",
    }
