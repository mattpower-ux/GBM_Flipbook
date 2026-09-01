import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pypdf import PdfReader

APP_NAME = "GBM Flipbook"
DEFAULT_STORAGE_PATH = "/data/flipbooks"
FALLBACK_STORAGE_PATH = "/tmp/flipbooks"
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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


def validate_slug(slug: str) -> str:
    normalized_slug = slug.strip().lower()
    if not SLUG_PATTERN.fullmatch(normalized_slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must use lowercase letters, numbers, and single hyphens only.",
        )
    return normalized_slug


def publication_dir(slug: str) -> Path:
    storage_path = active_storage_path or ensure_storage_path()
    return storage_path / validate_slug(slug)


def manifest_path(slug: str) -> Path:
    return publication_dir(slug) / "manifest.json"


def read_manifest(slug: str) -> dict[str, Any]:
    path = manifest_path(slug)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Publication manifest not found.")

    with path.open("r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def write_manifest(slug: str, manifest: dict[str, Any]) -> Path:
    path = manifest_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, indent=2)
        manifest_file.write("\n")
    return path


def get_pdf_page_count(pdf_path: Path) -> int:
    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Upload must be a readable PDF file.") from exc

    if page_count < 1:
        raise HTTPException(status_code=400, detail="PDF must contain at least one page.")

    return page_count


app = FastAPI(
    title=APP_NAME,
    description="Minimal Render-deployable API for the GBM Flipbook service.",
    version="0.3.0",
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
def read_book(slug: str) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    try:
        manifest = read_manifest(normalized_slug)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return {
            "slug": normalized_slug,
            "status": "placeholder",
            "message": "Upload a PDF for this slug to create the first flipbook manifest.",
        }

    return {
        "slug": normalized_slug,
        "status": manifest["status"],
        "title": manifest["title"],
        "page_count": manifest["page_count"],
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "message": "Flipbook viewer will be implemented in a future phase.",
    }


@app.get("/api/publications/{slug}/manifest")
def get_publication_manifest(slug: str) -> dict[str, Any]:
    return read_manifest(slug)


@app.post("/api/publications/{slug}/upload")
def upload_publication_pdf(
    slug: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    filename = file.filename or ""

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload must be a PDF file.")

    destination_dir = publication_dir(normalized_slug)
    destination_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = destination_dir / "original.pdf"

    with pdf_path.open("wb") as output_file:
        shutil.copyfileobj(file.file, output_file)

    page_count = get_pdf_page_count(pdf_path)
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "slug": normalized_slug,
        "title": title or normalized_slug.replace("-", " ").title(),
        "description": description or "",
        "status": "uploaded",
        "original_pdf_path": str(pdf_path),
        "page_count": page_count,
        "created_at": now,
        "updated_at": now,
        "viewer_settings": {},
    }
    manifest_file_path = write_manifest(normalized_slug, manifest)

    return {
        "status": "uploaded",
        "slug": normalized_slug,
        "page_count": page_count,
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
        "pdf_path": str(pdf_path),
    }
