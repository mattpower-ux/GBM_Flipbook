import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfReader

APP_NAME = "GBM Flipbook"
DEFAULT_STORAGE_PATH = "/data/flipbooks"
FALLBACK_STORAGE_PATH = "/tmp/flipbooks"
PAGE_RENDER_SCALE = 2.0
THUMB_RENDER_SCALE = 0.35
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ASSET_FILENAME_PATTERN = re.compile(r"^page-[0-9]{3,5}\.jpg$")

active_storage_path: Path | None = None
storage_warning: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def render_pdf_assets(slug: str, pdf_path: Path) -> dict[str, Any]:
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Original PDF not found.")

    destination_dir = publication_dir(slug)
    pages_dir = destination_dir / "pages"
    thumbs_dir = destination_dir / "thumbs"
    reset_directory(pages_dir)
    reset_directory(thumbs_dir)

    try:
        document = pymupdf.open(str(pdf_path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Original PDF could not be opened for processing.") from exc

    page_assets = []
    with document:
        for page_index in range(document.page_count):
            page_number = page_index + 1
            filename = f"page-{page_number:03d}.jpg"
            page = document.load_page(page_index)

            page_pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(PAGE_RENDER_SCALE, PAGE_RENDER_SCALE),
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            thumb_pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(THUMB_RENDER_SCALE, THUMB_RENDER_SCALE),
                colorspace=pymupdf.csRGB,
                alpha=False,
            )

            page_pixmap.save(str(pages_dir / filename))
            thumb_pixmap.save(str(thumbs_dir / filename))

            page_assets.append(
                {
                    "page_number": page_number,
                    "image_url": f"/api/publications/{slug}/assets/pages/{filename}",
                    "thumb_url": f"/api/publications/{slug}/assets/thumbs/{filename}",
                }
            )

    return {
        "page_count": len(page_assets),
        "pages": page_assets,
        "pages_path": str(pages_dir),
        "thumbs_path": str(thumbs_dir),
    }


app = FastAPI(
    title=APP_NAME,
    description="Minimal Render-deployable API for the GBM Flipbook service.",
    version="0.4.0",
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


@app.get("/api/publications/{slug}/assets/{asset_type}/{filename}")
def get_publication_asset(slug: str, asset_type: str, filename: str) -> FileResponse:
    normalized_slug = validate_slug(slug)
    if asset_type not in {"pages", "thumbs"}:
        raise HTTPException(status_code=404, detail="Asset type not found.")
    if not ASSET_FILENAME_PATTERN.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid asset filename.")

    asset_path = publication_dir(normalized_slug) / asset_type / filename
    if not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset not found.")

    return FileResponse(asset_path, media_type="image/jpeg")


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
    timestamp = now_iso()
    manifest = {
        "slug": normalized_slug,
        "title": title or normalized_slug.replace("-", " ").title(),
        "description": description or "",
        "status": "uploaded",
        "original_pdf_path": str(pdf_path),
        "page_count": page_count,
        "created_at": timestamp,
        "updated_at": timestamp,
        "processed_at": None,
        "pages": [],
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


@app.post("/api/publications/{slug}/process")
def process_publication_pdf(slug: str) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    pdf_path = Path(manifest["original_pdf_path"])

    manifest["status"] = "processing"
    manifest["updated_at"] = now_iso()
    write_manifest(normalized_slug, manifest)

    try:
        rendered_assets = render_pdf_assets(normalized_slug, pdf_path)
    except HTTPException as exc:
        manifest["status"] = "error"
        manifest["error"] = exc.detail
        manifest["updated_at"] = now_iso()
        write_manifest(normalized_slug, manifest)
        raise

    manifest.update(rendered_assets)
    manifest["status"] = "processed"
    manifest["processed_at"] = now_iso()
    manifest["updated_at"] = manifest["processed_at"]
    manifest.pop("error", None)
    manifest_file_path = write_manifest(normalized_slug, manifest)

    return {
        "status": "processed",
        "slug": normalized_slug,
        "page_count": manifest["page_count"],
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
        "first_page_url": manifest["pages"][0]["image_url"] if manifest["pages"] else None,
    }
