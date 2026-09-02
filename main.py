import html
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NumberObject

APP_NAME = "GBM Flipbook"
DEFAULT_STORAGE_PATH = "/data/flipbooks"
FALLBACK_STORAGE_PATH = "/tmp/flipbooks"
PAGE_RENDER_SCALE = 2.0
THUMB_RENDER_SCALE = 0.35
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ASSET_FILENAME_PATTERN = re.compile(r"^page-[0-9]{3,5}\.jpg$")
VALID_FLIPBOOK_TYPES = {"magazine": "Magazine", "ebook": "Ebook", "other": "Other"}
ADMIN_TOKEN_ENV = "FLIPBOOK_ADMIN_TOKEN"

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


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise HTTPException(status_code=400, detail="A usable title or PDF filename is required.")
    return validate_slug(slug)


def unique_slug(base_slug: str) -> str:
    normalized_base = validate_slug(base_slug)
    candidate = normalized_base
    suffix = 2
    while manifest_path(candidate).exists():
        candidate = f"{normalized_base}-{suffix}"
        suffix += 1
    return candidate


def normalize_flipbook_type(value: str | None) -> str:
    normalized_value = str(value or "magazine").strip().lower()
    if normalized_value not in VALID_FLIPBOOK_TYPES:
        raise HTTPException(status_code=400, detail="Flipbook type must be Magazine, Ebook, or Other.")
    return normalized_value


def flipbook_type_label(value: str | None) -> str:
    return VALID_FLIPBOOK_TYPES[normalize_flipbook_type(value)]


def get_admin_token() -> str:
    token = os.getenv(ADMIN_TOKEN_ENV, "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail=f"Set {ADMIN_TOKEN_ENV} in Render before using Flipbook Admin.",
        )
    return token


def require_admin_token(admin_token: str | None) -> None:
    expected_token = get_admin_token()
    provided_token = str(admin_token or "")
    if not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="Admin access required.")


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


def page_asset(page_number: int, slug: str) -> dict[str, Any]:
    filename = f"page-{page_number:03d}.jpg"
    return {
        "page_number": page_number,
        "image_url": f"/api/publications/{slug}/assets/pages/{filename}",
        "thumb_url": f"/api/publications/{slug}/assets/thumbs/{filename}",
    }


def get_pdf_object(value: Any) -> Any:
    if isinstance(value, IndirectObject):
        return value.get_object()
    return value


def get_pdf_link_destination(annotation: DictionaryObject) -> Any:
    if "/Dest" in annotation:
        return annotation["/Dest"]

    action = get_pdf_object(annotation.get("/A"))
    if isinstance(action, DictionaryObject):
        if action.get("/S") == "/GoTo" and "/D" in action:
            return action["/D"]
        if action.get("/S") == "/URI" and "/URI" in action:
            return {"uri": str(action["/URI"])}

    return None


def page_object_number(page: Any) -> int | None:
    indirect_reference = getattr(page, "indirect_reference", None)
    if indirect_reference is None:
        indirect_reference = getattr(page, "indirectRef", None)
    return getattr(indirect_reference, "idnum", None)


def resolve_link_page_number(destination: Any, page_object_numbers: dict[int, int], total_pages: int) -> int | None:
    if isinstance(destination, dict) and "uri" in destination:
        return None

    if isinstance(destination, ArrayObject) and destination:
        destination = destination[0]

    destination = get_pdf_object(destination)

    if isinstance(destination, NumberObject) or isinstance(destination, int):
        target_page = int(destination) + 1
        if 1 <= target_page <= total_pages:
            return target_page
        return None

    object_number = page_object_number(destination)
    if object_number is not None:
        return page_object_numbers.get(object_number)

    return None


def normalize_pdf_rect(rect: Any, page_width: float, page_height: float) -> dict[str, float] | None:
    if not rect or len(rect) != 4:
        return None

    x0, y0, x1, y1 = [float(value) for value in rect]
    left = min(x0, x1)
    right = max(x0, x1)
    bottom = min(y0, y1)
    top = max(y0, y1)

    return {
        "x": max(0.0, min(1.0, left / page_width)),
        "y": max(0.0, min(1.0, (page_height - top) / page_height)),
        "width": max(0.0, min(1.0, (right - left) / page_width)),
        "height": max(0.0, min(1.0, (top - bottom) / page_height)),
    }


def extract_pdf_links(pdf_path: Path, total_pages: int) -> list[dict[str, Any]]:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return []

    page_object_numbers = {
        object_number: page_index + 1
        for page_index, page in enumerate(reader.pages)
        if (object_number := page_object_number(page)) is not None
    }
    links: list[dict[str, Any]] = []

    for page_index, page in enumerate(reader.pages):
        annotations = page.get("/Annots") or []
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)

        for annotation_reference in annotations:
            annotation = get_pdf_object(annotation_reference)
            if not isinstance(annotation, DictionaryObject) or annotation.get("/Subtype") != "/Link":
                continue

            source_rect = normalize_pdf_rect(annotation.get("/Rect"), page_width, page_height)
            if source_rect is None or source_rect["width"] <= 0 or source_rect["height"] <= 0:
                continue

            destination = get_pdf_link_destination(annotation)
            uri = destination.get("uri") if isinstance(destination, dict) else None
            target_page_number = resolve_link_page_number(destination, page_object_numbers, total_pages)

            if not uri and target_page_number is None:
                continue

            link: dict[str, Any] = {
                "source_page_number": page_index + 1,
                "source_rect": source_rect,
            }
            if target_page_number is not None:
                link["target_page_number"] = target_page_number
            if uri:
                link["uri"] = uri
            links.append(link)

    return links


def detect_toc_page_number(links: list[dict[str, Any]]) -> int | None:
    internal_link_counts: dict[int, int] = {}
    for link in links:
        if "target_page_number" in link:
            page_number = int(link["source_page_number"])
            internal_link_counts[page_number] = internal_link_counts.get(page_number, 0) + 1

    if not internal_link_counts:
        return None

    toc_page_number, link_count = max(internal_link_counts.items(), key=lambda item: item[1])
    if toc_page_number <= 20 and link_count >= 5:
        return toc_page_number
    return None


def render_pdf_page_range(slug: str, pdf_path: Path, start_page: int, limit: int) -> dict[str, Any]:
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Original PDF not found.")

    destination_dir = publication_dir(slug)
    pages_dir = destination_dir / "pages"
    thumbs_dir = destination_dir / "thumbs"
    pages_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    try:
        document = pymupdf.open(str(pdf_path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Original PDF could not be opened for processing.") from exc

    if start_page < 1:
        raise HTTPException(status_code=400, detail="start_page must be 1 or greater.")
    if limit < 1 or limit > 25:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 25.")

    page_assets = []
    with document:
        total_pages = document.page_count
        if start_page > total_pages:
            return {
                "page_count": total_pages,
                "rendered_pages": [],
                "next_start_page": None,
                "pages_path": str(pages_dir),
                "thumbs_path": str(thumbs_dir),
            }

        end_page = min(total_pages, start_page + limit - 1)
        for page_number in range(start_page, end_page + 1):
            page_index = page_number - 1
            page_number = page_index + 1
            filename = f"page-{page_number:03d}.jpg"
            page = document.load_page(page_index)

            page_pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(PAGE_RENDER_SCALE, PAGE_RENDER_SCALE),
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            page_pixmap.save(str(pages_dir / filename))
            del page_pixmap

            thumb_pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(THUMB_RENDER_SCALE, THUMB_RENDER_SCALE),
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            thumb_pixmap.save(str(thumbs_dir / filename))
            del thumb_pixmap
            del page

            page_assets.append(page_asset(page_number, slug))

    return {
        "page_count": total_pages,
        "rendered_pages": page_assets,
        "next_start_page": end_page + 1 if end_page < total_pages else None,
        "pages_path": str(pages_dir),
        "thumbs_path": str(thumbs_dir),
    }


def render_pdf_assets(slug: str, pdf_path: Path) -> dict[str, Any]:
    destination_dir = publication_dir(slug)
    pages_dir = destination_dir / "pages"
    thumbs_dir = destination_dir / "thumbs"
    reset_directory(pages_dir)
    reset_directory(thumbs_dir)

    page_count = get_pdf_page_count(pdf_path)
    pages = []
    start_page = 1
    while start_page <= page_count:
        batch = render_pdf_page_range(slug, pdf_path, start_page=start_page, limit=10)
        pages.extend(batch["rendered_pages"])
        if batch["next_start_page"] is None:
            break
        start_page = int(batch["next_start_page"])

    return {
        "page_count": page_count,
        "pages": pages,
        "pages_path": str(pages_dir),
        "thumbs_path": str(thumbs_dir),
    }


def refresh_embedded_links(slug: str, manifest: dict[str, Any]) -> dict[str, Any]:
    pdf_path = Path(manifest["original_pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Original PDF not found.")

    page_count = int(manifest.get("page_count") or get_pdf_page_count(pdf_path))
    pdf_links = extract_pdf_links(pdf_path, page_count)
    manifest["page_count"] = page_count
    manifest["links"] = pdf_links
    manifest["toc_page_number"] = detect_toc_page_number(pdf_links)
    manifest["updated_at"] = now_iso()

    if manifest.get("pages") and manifest.get("status") in {"processing", "uploaded", "error"}:
        manifest["status"] = "processed"
        manifest["processed_at"] = manifest.get("processed_at") or manifest["updated_at"]
        manifest.pop("error", None)

    return manifest


def merge_page_assets(existing_pages: list[Any], rendered_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pages_by_number = {
        int(page["page_number"]): page
        for page in existing_pages
        if isinstance(page, dict) and "page_number" in page
    }
    for page in rendered_pages:
        pages_by_number[int(page["page_number"])] = page
    return [pages_by_number[page_number] for page_number in sorted(pages_by_number)]


def save_publication_upload(
    *,
    slug: str,
    file: UploadFile,
    title: str | None = None,
    description: str | None = None,
    publication_date: str | None = None,
    source_url: str | None = None,
    flipbook_type: str | None = None,
    upload_date: str | None = None,
    version_notes: str | None = None,
) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload must be a PDF file.")

    destination_dir = publication_dir(normalized_slug)
    destination_dir.mkdir(parents=True, exist_ok=True)
    for asset_dir_name in ("pages", "thumbs"):
        asset_dir = destination_dir / asset_dir_name
        if asset_dir.exists():
            shutil.rmtree(asset_dir)

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
        "publication_date": publication_date or upload_date or "",
        "upload_date": upload_date or timestamp[:10],
        "version_notes": version_notes or "",
        "source_url": source_url or "",
        "created_at": timestamp,
        "updated_at": timestamp,
        "processed_at": None,
        "toc_page_number": None,
        "flipbook_type": normalize_flipbook_type(flipbook_type),
        "links": [],
        "pages": [],
        "viewer_settings": {},
    }
    manifest_file_path = write_manifest(normalized_slug, manifest)
    return {
        "status": "uploaded",
        "slug": normalized_slug,
        "page_count": page_count,
        "link_count": 0,
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
        "pdf_path": str(pdf_path),
    }


def publication_date(manifest: dict[str, Any]) -> str:
    for key in ("publication_date", "published_at", "issue_date", "created_at"):
        value = str(manifest.get(key) or "").strip()
        if value:
            return value[:10]
    return "Date pending"


def publication_summary(manifest: dict[str, Any]) -> dict[str, str]:
    slug = str(manifest.get("slug") or "")
    pages = manifest.get("pages") or []
    cover_url = ""
    if pages and isinstance(pages[0], dict):
        cover_url = str(pages[0].get("thumb_url") or pages[0].get("image_url") or "")
    flipbook_type = normalize_flipbook_type(str(manifest.get("flipbook_type") or "magazine"))
    return {
        "slug": slug,
        "title": str(manifest.get("title") or slug.replace("-", " ").title()),
        "description": str(manifest.get("description") or ""),
        "date": publication_date(manifest),
        "cover_url": cover_url,
        "status": str(manifest.get("status") or "unknown"),
        "flipbook_type": flipbook_type,
        "flipbook_type_label": VALID_FLIPBOOK_TYPES[flipbook_type],
        "upload_date": str(manifest.get("upload_date") or "")[:10],
        "version_notes": str(manifest.get("version_notes") or ""),
    }


def list_publications() -> list[dict[str, str]]:
    storage_path = active_storage_path or ensure_storage_path()
    publications = []
    if not storage_path.exists():
        return publications

    for child in storage_path.iterdir():
        if not child.is_dir():
            continue
        manifest_file_path = child / "manifest.json"
        if not manifest_file_path.exists():
            continue
        try:
            with manifest_file_path.open("r", encoding="utf-8") as manifest_file:
                publications.append(publication_summary(json.load(manifest_file)))
        except (OSError, json.JSONDecodeError):
            continue

    return sorted(publications, key=lambda item: item["date"], reverse=True)


def render_archive_view(
    publications: list[dict[str, str]],
    *,
    flipbook_type: str = "magazine",
    page_title: str = "Green Builder Magazine Archive",
    latest_label: str = "Latest Issue",
    backlist_label: str = "Back Issues",
) -> HTMLResponse:
    selected_type = normalize_flipbook_type(flipbook_type)
    archive_publications = [
        publication
        for publication in publications
        if publication["status"] == "processed"
        and publication["cover_url"]
        and normalize_flipbook_type(publication.get("flipbook_type")) == selected_type
    ]
    featured = archive_publications[0] if archive_publications else None
    remaining_publications = archive_publications[1:] if featured else []

    if featured:
        featured_cover = (
            f'<img src="{html.escape(featured["cover_url"])}" alt="{html.escape(featured["title"])} cover">'
            if featured["cover_url"]
            else "<span>No cover</span>"
        )
        featured_markup = f"""<section class="featured"><a class="featured-cover" href="/book/{html.escape(featured['slug'])}" aria-label="Open {html.escape(featured['title'])}">{featured_cover}</a><div class="featured-copy"><p class="eyebrow">{html.escape(latest_label)}</p><h2><a href="/book/{html.escape(featured['slug'])}">{html.escape(featured['title'])}</a></h2><p class="lede">{html.escape(featured['description'])}</p><div class="featured-actions"><a class="button primary" href="/book/{html.escape(featured['slug'])}">Read Flipbook</a><a class="button" href="/api/publications/{html.escape(featured['slug'])}/original.pdf" download>Download PDF</a></div></div></section>"""
    else:
        featured_markup = '<p class="empty">No flipbooks have been published yet.</p>'

    if remaining_publications:
        cards = "".join(
            f"""<article class="publication"><a class="cover" href="/book/{html.escape(pub['slug'])}" aria-label="Open {html.escape(pub['title'])}">{f'<img src="{html.escape(pub["cover_url"])}" alt="{html.escape(pub["title"])} cover" loading="lazy">' if pub['cover_url'] else '<span>No cover</span>'}</a><time>{html.escape(pub['date'])}</time><h3><a href="/book/{html.escape(pub['slug'])}">{html.escape(pub['title'])}</a></h3></article>"""
            for pub in remaining_publications
        )
    else:
        cards = ""

    return HTMLResponse(
        content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(page_title)}</title><style>:root{{color-scheme:dark;--bg:#0e141b;--bg-soft:#121a23;--panel:#18222d;--panel-strong:#202d39;--ink:#edf5f0;--muted:#a8b8b1;--line:#33414e;--brand:#29b17d;--brand-bright:#35c992}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;font-family:Arial,Helvetica,sans-serif;background:radial-gradient(circle at top left,rgba(41,177,125,.12),transparent 34rem),var(--bg);color:var(--ink)}}main{{width:min(1260px,100%);margin:0 auto;padding:34px 22px 56px}}header{{display:flex;align-items:flex-end;justify-content:flex-end;gap:16px;margin-bottom:28px}}.count{{color:var(--muted);font-size:14px}}.featured{{display:grid;grid-template-columns:minmax(240px,470px) minmax(0,1fr);gap:40px;align-items:center;margin-bottom:42px;padding-bottom:34px;border-bottom:1px solid var(--line)}}.featured-cover,.cover{{background:#202a35;overflow:hidden;display:grid;place-items:center;color:var(--muted);text-decoration:none}}.featured-cover{{aspect-ratio:648/783;border-radius:8px;box-shadow:0 28px 54px rgba(0,0,0,.42)}}.featured-cover img,.cover img{{width:100%;height:100%;object-fit:cover;display:block}}.eyebrow{{margin:0 0 12px;color:var(--brand-bright);font-weight:800;text-transform:uppercase;letter-spacing:0;font-size:14px}}h2{{margin:0 0 16px;font-size:clamp(34px,4.8vw,66px);line-height:1.02;letter-spacing:0}}h2 a,h3 a{{color:var(--ink);text-decoration:none}}h2 a:hover,h3 a:hover{{color:var(--brand-bright)}}.lede{{max-width:680px;margin:0 0 24px;color:var(--muted);font-size:18px;line-height:1.55}}.featured-actions{{display:flex;flex-wrap:wrap;gap:10px}}.button{{min-height:42px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:0 14px;font-weight:800;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}}.button:hover{{border-color:var(--brand-bright);background:var(--panel-strong)}}.button.primary{{background:var(--brand);border-color:var(--brand);color:#06120d}}.archive-heading{{margin:0 0 16px;color:var(--muted);font-size:13px;text-transform:uppercase;font-weight:800;letter-spacing:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:24px 20px}}.publication{{min-width:0}}.cover{{aspect-ratio:648/783;border:1px solid var(--line);border-radius:6px;margin-bottom:10px}}.publication:hover .cover{{border-color:var(--brand-bright)}}time{{display:block;color:var(--brand-bright);font-size:12px;font-weight:800;text-transform:uppercase;margin-bottom:6px}}h3{{margin:0;font-size:16px;line-height:1.25;letter-spacing:0}}.empty{{font-size:16px;color:var(--muted)}}@media(max-width:800px){{main{{padding:24px 14px 42px}}header{{align-items:flex-start;flex-direction:column}}.featured{{grid-template-columns:1fr;gap:22px}}.featured-cover{{max-width:420px}}.grid{{grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:18px 14px}}h3{{font-size:14px}}}}</style></head><body><main><header><div class="count">{len(archive_publications)} flipbook{'s' if len(archive_publications) != 1 else ''}</div></header>{featured_markup}<h2 class="archive-heading">{html.escape(backlist_label)}</h2><section class="grid">{cards}</section></main></body></html>"""
    )


def render_missing_book(slug: str) -> HTMLResponse:
    safe_slug = html.escape(slug)
    return HTMLResponse(
        content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>GBM Flipbook</title><style>body{{margin:0;font-family:Arial,sans-serif;background:#111820;color:#eef5f0}}main{{min-height:100vh;display:grid;place-items:center;padding:24px}}section{{max-width:620px}}h1{{margin:0 0 12px;font-size:34px;line-height:1.1}}p{{margin:0;color:#b8c7bf;font-size:16px;line-height:1.5}}code{{color:#94e0bf}}</style></head><body><main><section><h1>GBM Flipbook</h1><p>No publication manifest exists for <code>{safe_slug}</code>.</p></section></main></body></html>""",
        status_code=404,
    )


def render_book_viewer(manifest: dict[str, Any]) -> HTMLResponse:
    title = html.escape(str(manifest.get("title") or "GBM Flipbook"))
    description = html.escape(str(manifest.get("description") or ""))
    slug = html.escape(str(manifest.get("slug") or ""))
    status = html.escape(str(manifest.get("status") or "unknown"))
    manifest_json = html.escape(json.dumps(manifest), quote=False)
    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;--bg:#0e141b;--bg-soft:#151d27;--panel:#202a35;--panel-strong:#27333f;--ink:#edf5f0;--muted:#a8b8b1;--line:#3a4855;--brand:#29b17d;--brand-dark:#11271e;--link:#d8b24c;--paper:#f7faf8}*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}button,a.button{min-height:38px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:0 12px;font:inherit;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px}button:hover,a.button:hover,button:focus-visible,a.button:focus-visible{border-color:var(--brand);outline:2px solid transparent;background:var(--panel-strong)}button[aria-pressed=true]{border-color:var(--brand);background:var(--brand-dark);color:#cbf4e2}button:disabled{cursor:not-allowed;opacity:.42}.app{min-height:100vh;display:grid;grid-template-rows:auto 1fr}header{background:#111820;border-bottom:1px solid var(--line);padding:12px 18px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:14px;align-items:center;position:sticky;top:0;z-index:10}.archive-button{white-space:nowrap;background:#0f151d;border-color:#536270;text-transform:uppercase;font-size:13px}.title-block{min-width:0}h1{margin:0;font-size:18px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{margin-top:4px;color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.toolbar,.reader-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.reader-actions{justify-content:flex-end}.reader-bar{position:sticky;top:0;z-index:8;margin:0 auto 16px;width:min(100%,1180px);display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:10px;align-items:center;background:rgba(17,24,32,.92);border:1px solid var(--line);border-radius:8px;padding:10px;box-shadow:0 14px 28px rgba(0,0,0,.25);backdrop-filter:blur(10px)}.counter{color:var(--muted);font-size:14px;min-width:86px;text-align:center}.download-button{background:var(--brand);border-color:var(--brand);color:#06120d}.download-button:hover,.download-button:focus-visible{background:#35c992;color:#04100b}.exit-button{position:fixed;right:18px;bottom:18px;z-index:20;background:#0f151d;border-color:#536270;box-shadow:0 18px 34px rgba(0,0,0,.35)}.exit-button:hover,.exit-button:focus-visible{background:#1c2630}.layout{min-height:0;display:grid;grid-template-columns:138px minmax(0,1fr);background:var(--bg)}aside{border-right:1px solid var(--line);background:#111820;overflow:auto;padding:10px}.thumbs{display:grid;gap:10px}.thumb{width:100%;border:2px solid transparent;border-radius:6px;padding:4px;background:transparent;height:auto;display:grid;gap:4px;color:var(--muted);font-size:12px;font-weight:700}.thumb:hover{background:#1c2630}.thumb[aria-current=true]{border-color:var(--brand);background:#123226;color:#cbf4e2}.thumb img{width:100%;aspect-ratio:648/783;object-fit:cover;display:block;border-radius:3px;background:#222c36}.stage-wrap{min-width:0;min-height:0;overflow:auto;padding:18px 22px 28px;background:var(--bg-soft)}.stage{min-height:100%;display:flex;align-items:flex-start;justify-content:center}.page-frame{position:relative;width:min(100%,calc(760px * var(--zoom,1)));max-width:none;background:var(--paper);filter:drop-shadow(0 26px 42px rgba(0,0,0,.45))}.page-frame img{width:100%;display:block;background:var(--paper)}.spread-frame{display:flex;align-items:flex-start;justify-content:center;gap:10px;width:min(100%,calc(1520px * var(--zoom,1)));filter:drop-shadow(0 26px 42px rgba(0,0,0,.45))}.spread-frame .page-frame{width:calc(50% - 5px);filter:none}.pdf-hotspot{position:absolute;border:2px solid transparent;background:rgba(216,178,76,.01);border-radius:3px;cursor:pointer;padding:0}.pdf-hotspot:hover,.pdf-hotspot:focus-visible{border-color:var(--link);background:rgba(216,178,76,.22);outline:0}.empty{max-width:680px;margin:18vh auto 0;color:var(--muted);line-height:1.5}@media(max-width:760px){header{grid-template-columns:1fr;padding:12px}.archive-button{justify-self:start}.reader-bar{grid-template-columns:1fr;margin-bottom:12px}.toolbar,.reader-actions{justify-content:flex-start;overflow-x:auto;flex-wrap:nowrap;padding-bottom:2px}.layout{grid-template-columns:1fr;grid-template-rows:1fr auto}aside{grid-row:2;border-right:0;border-top:1px solid var(--line);padding:8px}.thumbs{grid-auto-flow:column;grid-auto-columns:76px;overflow-x:auto;gap:8px}.stage-wrap{padding:12px 12px 68px}.page-frame{width:min(100%,calc(560px * var(--zoom,1)))}.spread-frame{gap:6px;width:min(100%,calc(960px * var(--zoom,1)))}.exit-button{right:12px;bottom:12px}}
</style>
</head>
<body>
<div class="app"><header><a class="button archive-button" href="/archive" title="Return to publication archive">Return to Archive</a><div class="title-block"><h1>__TITLE__</h1><div class="meta"><span>__DESCRIPTION__</span><span id="status"> __STATUS__</span></div></div></header><div class="layout"><aside aria-label="Thumbnails"><div class="thumbs" id="thumbs"></div></aside><main class="stage-wrap" id="stageWrap"><div class="reader-bar"><div class="toolbar" aria-label="Page controls"><button type="button" id="prevBtn" title="Previous page">Prev</button><span class="counter" id="pageCounter">Page 0 / 0</span><button type="button" id="nextBtn" title="Next page">Next</button></div><div class="toolbar" aria-label="View controls"><button type="button" id="zoomOutBtn" title="Zoom out">-</button><button type="button" id="zoomInBtn" title="Zoom in">+</button><button type="button" id="spreadBtn" title="Show side-by-side page spreads after the cover" aria-pressed="false">SHOW SPREADS</button><button type="button" id="tocBtn" title="Table of contents">TOC</button><button type="button" id="fullscreenBtn" title="Fullscreen">Full</button><button type="button" id="shareBtn" title="Copy link">Share</button></div><div class="reader-actions"><a class="button download-button" href="/api/publications/__SLUG__/original.pdf" download title="Download full PDF">Download PDF</a></div></div><div class="stage" id="stage"></div></main></div><a class="button exit-button" href="/archive" title="Exit to publication archive">Exit</a></div>
<script type="application/json" id="manifest-data">__MANIFEST__</script>
<script>
const manifest=JSON.parse(document.getElementById('manifest-data').textContent);const pages=Array.isArray(manifest.pages)?manifest.pages:[];const links=Array.isArray(manifest.links)?manifest.links:[];const linksByPage=links.reduce((acc,link)=>{const page=String(link.source_page_number);(acc[page]||(acc[page]=[])).push(link);return acc},{});const stage=document.getElementById('stage');const thumbs=document.getElementById('thumbs');const counter=document.getElementById('pageCounter');const prevBtn=document.getElementById('prevBtn');const nextBtn=document.getElementById('nextBtn');const zoomInBtn=document.getElementById('zoomInBtn');const zoomOutBtn=document.getElementById('zoomOutBtn');const spreadBtn=document.getElementById('spreadBtn');const fullscreenBtn=document.getElementById('fullscreenBtn');const shareBtn=document.getElementById('shareBtn');const tocBtn=document.getElementById('tocBtn');const stageWrap=document.getElementById('stageWrap');let pageIndex=0;let zoom=1;let spreadsEnabled=false;function pageUrl(path){return new URL(path,window.location.origin).toString()}function normalizePageIndex(index){const bounded=Math.max(0,Math.min(index,pages.length-1));if(!spreadsEnabled||bounded===0)return bounded;return bounded%2===0?bounded-1:bounded}function visiblePageIndexes(){if(!spreadsEnabled||pageIndex===0)return[pageIndex];return[pageIndex,pageIndex+1].filter((index)=>index<pages.length)}function syncHash(){const pageNumber=pageIndex+1;if(window.location.hash!=='#page-'+pageNumber)history.replaceState(null,'','#page-'+pageNumber)}function addPdfLinks(frame,pageNumber){(linksByPage[String(pageNumber)]||[]).forEach((link)=>{const rect=link.source_rect;if(!rect)return;const button=document.createElement('button');button.type='button';button.className='pdf-hotspot';button.title=link.uri?'Open link':'Go to page '+link.target_page_number;button.setAttribute('aria-label',button.title);button.style.left=(rect.x*100)+'%';button.style.top=(rect.y*100)+'%';button.style.width=(rect.width*100)+'%';button.style.height=(rect.height*100)+'%';button.addEventListener('click',()=>{if(link.uri)window.open(link.uri,'_blank','noopener,noreferrer');else if(link.target_page_number)showPage(Number(link.target_page_number)-1)});frame.append(button)})}function buildPageFrame(page){const frame=document.createElement('div');frame.className='page-frame';frame.style.setProperty('--zoom',String(zoom));const img=document.createElement('img');img.src=pageUrl(page.image_url);img.alt=manifest.title+', page '+page.page_number;frame.append(img);addPdfLinks(frame,Number(page.page_number));return frame}function showPage(index){if(!pages.length){stage.innerHTML='<p class="empty">This publication has no rendered pages yet.</p>';counter.textContent='Page 0 / 0';prevBtn.disabled=true;nextBtn.disabled=true;spreadBtn.disabled=true;return}pageIndex=normalizePageIndex(index);const indexes=visiblePageIndexes();stage.innerHTML='';stage.classList.toggle('spread-view',spreadsEnabled&&indexes.length>1);if(indexes.length>1){const spread=document.createElement('div');spread.className='spread-frame';spread.style.setProperty('--zoom',String(zoom));indexes.forEach((pageNumberIndex)=>spread.append(buildPageFrame(pages[pageNumberIndex])));stage.append(spread)}else{stage.append(buildPageFrame(pages[pageIndex]))}const pageNumbers=indexes.map((pageNumberIndex)=>pages[pageNumberIndex].page_number);counter.textContent=pageNumbers.length>1?'Pages '+pageNumbers.join('-')+' / '+pages.length:'Page '+pageNumbers[0]+' / '+pages.length;prevBtn.disabled=pageIndex===0;nextBtn.disabled=spreadsEnabled?pageIndex>=pages.length-2:pageIndex===pages.length-1;const activeIndexes=new Set(indexes.map(String));document.querySelectorAll('.thumb').forEach((thumb)=>thumb.setAttribute('aria-current',activeIndexes.has(thumb.dataset.index)?'true':'false'));stageWrap.scrollTo({top:0,behavior:'smooth'});syncHash()}function movePage(direction){if(!spreadsEnabled)showPage(pageIndex+direction);else if(direction>0)showPage(pageIndex===0?1:pageIndex+2);else showPage(pageIndex<=1?0:pageIndex-2)}function setZoom(nextZoom){zoom=Math.max(.7,Math.min(nextZoom,2.4));document.querySelectorAll('.page-frame,.spread-frame').forEach((frame)=>frame.style.setProperty('--zoom',String(zoom)))}function renderThumbs(){thumbs.innerHTML='';pages.forEach((page,index)=>{const button=document.createElement('button');button.type='button';button.className='thumb';button.setAttribute('aria-label','Page '+page.page_number);button.dataset.index=String(index);const img=document.createElement('img');img.src=pageUrl(page.thumb_url);img.alt='';img.loading='lazy';const label=document.createElement('span');label.textContent=String(page.page_number);button.append(img,label);button.addEventListener('click',()=>showPage(index));thumbs.append(button)})}prevBtn.addEventListener('click',()=>movePage(-1));nextBtn.addEventListener('click',()=>movePage(1));zoomInBtn.addEventListener('click',()=>setZoom(zoom+.15));zoomOutBtn.addEventListener('click',()=>setZoom(zoom-.15));spreadBtn.addEventListener('click',()=>{spreadsEnabled=!spreadsEnabled;spreadBtn.setAttribute('aria-pressed',String(spreadsEnabled));spreadBtn.textContent=spreadsEnabled?'SHOW SINGLE':'SHOW SPREADS';showPage(pageIndex)});tocBtn.addEventListener('click',()=>{if(manifest.toc_page_number)showPage(Number(manifest.toc_page_number)-1)});fullscreenBtn.addEventListener('click',()=>{if(!document.fullscreenElement)document.documentElement.requestFullscreen?.();else document.exitFullscreen?.()});shareBtn.addEventListener('click',async()=>{syncHash();await navigator.clipboard?.writeText(window.location.href);shareBtn.textContent='Copied';window.setTimeout(()=>shareBtn.textContent='Share',1200)});document.addEventListener('keydown',(event)=>{if(event.key==='ArrowLeft'||event.key==='PageUp'){event.preventDefault();movePage(-1)}if(event.key==='ArrowRight'||event.key==='PageDown'){event.preventDefault();movePage(1)}});window.addEventListener('hashchange',()=>{const match=window.location.hash.match(/^#page-(\\d+)$/);if(match)showPage(Number(match[1])-1)});const initialMatch=window.location.hash.match(/^#page-(\\d+)$/);if(initialMatch)pageIndex=Number(initialMatch[1])-1;renderThumbs();showPage(pageIndex);
</script>
</body>
</html>"""
    return HTMLResponse(
        content=template
        .replace("__TITLE__", title)
        .replace("__DESCRIPTION__", description)
        .replace("__STATUS__", status)
        .replace("__SLUG__", slug)
        .replace("__MANIFEST__", manifest_json)
    )


def render_admin_view(publications: list[dict[str, str]], admin_token: str) -> HTMLResponse:
    rows = []
    for publication in publications:
        slug = html.escape(publication["slug"])
        title = html.escape(publication["title"])
        date = html.escape(publication["date"])
        status = html.escape(publication["status"])
        cover_url = html.escape(publication["cover_url"])
        cover = (
            f'<img src="{cover_url}" alt="{title} cover">'
            if cover_url
            else '<span class="cover-placeholder">No cover</span>'
        )
        options = "".join(
            f'<option value="{html.escape(value)}"{" selected" if publication["flipbook_type"] == value else ""}>{html.escape(label)}</option>'
            for value, label in VALID_FLIPBOOK_TYPES.items()
        )
        rows.append(
            f"""<article class="publication-row"><label class="select-target"><input type="radio" name="selectedSlug" value="{slug}"><span class="cover">{cover}</span><span class="publication-copy"><strong>{title}</strong><span>{date} · {status}</span></span></label><label class="type-control"><span>Type</span><select data-slug="{slug}" class="type-select">{options}</select></label></article>"""
        )
    row_markup = "".join(rows) if rows else '<p class="empty">No flipbooks have been uploaded yet.</p>'
    admin_token_json = json.dumps(admin_token)
    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flipbook Admin</title>
<style>
:root{color-scheme:dark;--bg:#0e141b;--panel:#141d27;--panel-strong:#1d2935;--ink:#edf5f0;--muted:#a8b8b1;--line:#344351;--brand:#29b17d;--danger:#c84d4d}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif}main{width:min(1040px,100%);margin:0 auto;padding:22px}h1{margin:0 0 18px;font-size:32px;line-height:1.1;letter-spacing:0}.actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:18px}.panel{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px;min-width:0}h2{margin:0 0 12px;font-size:16px;letter-spacing:0}label{display:grid;gap:6px;color:var(--muted);font-size:12px;font-weight:700}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:6px;background:#0f151d;color:var(--ink);padding:9px}textarea{min-height:72px;resize:vertical}button{min-height:38px;border:1px solid var(--line);border-radius:6px;background:var(--panel-strong);color:var(--ink);font-weight:800;cursor:pointer;padding:0 12px}button:hover,button:focus-visible{border-color:var(--brand);outline:0}button.primary{background:var(--brand);border-color:var(--brand);color:#06120d}button.danger{background:#2c1719;border-color:#683137;color:#ffdcdc}.form-grid{display:grid;gap:10px}.status{position:sticky;top:0;z-index:2;margin-bottom:14px;border:1px solid var(--line);background:#101820;border-radius:8px;padding:10px;color:var(--muted);font-size:14px}.publication-list{display:grid;gap:10px}.publication-row{display:grid;grid-template-columns:minmax(0,1fr) 150px;gap:12px;align-items:center;border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:10px}.select-target{grid-template-columns:auto 56px minmax(0,1fr);align-items:center;gap:10px;color:var(--ink);font-size:14px}.select-target input{width:18px;height:18px}.cover{width:56px;aspect-ratio:648/783;border:1px solid var(--line);border-radius:4px;background:#202a35;display:grid;place-items:center;overflow:hidden;color:var(--muted);font-size:10px;text-align:center}.cover img{width:100%;height:100%;object-fit:cover;display:block}.publication-copy{display:grid;gap:4px;min-width:0}.publication-copy strong{font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.publication-copy span{color:var(--muted);font-size:12px}.type-control{grid-template-columns:1fr;gap:5px}.empty{color:var(--muted)}@media(max-width:860px){.actions{grid-template-columns:1fr}.publication-row{grid-template-columns:1fr}.type-control{max-width:220px}}
</style>
</head>
<body>
<main>
<h1>Flipbook Admin</h1>
<div class="status" id="status">Ready.</div>
<section class="actions" aria-label="Flipbook actions">
<form class="panel form-grid" id="uploadForm">
<h2>Upload New Flipbook</h2>
<label>PDF<input name="file" type="file" accept="application/pdf" required></label>
<label>Issue Title <input name="issue_title" type="text" placeholder="Optional"></label>
<label>Upload Date <input name="upload_date" type="date"></label>
<label>Type <select name="flipbook_type"><option value="magazine">Magazine</option><option value="ebook">Ebook</option><option value="other">Other</option></select></label>
<label>Version Notes <textarea name="version_notes" placeholder="What changed in this upload?"></textarea></label>
<button class="primary" type="submit">Upload New</button>
</form>
<form class="panel form-grid" id="replaceForm">
<h2>Replace Existing Flipbook</h2>
<label>Replacement PDF<input name="file" type="file" accept="application/pdf" required></label>
<label>Upload Date <input name="upload_date" type="date"></label>
<label>Version Notes <textarea name="version_notes" placeholder="Why is this replacing the current PDF?"></textarea></label>
<button class="primary" type="submit">Replace Selected</button>
</form>
<form class="panel form-grid" id="deleteForm">
<h2>Delete a Flipbook</h2>
<p class="empty">Select one flipbook below, then delete it from storage.</p>
<button class="danger" type="submit">Delete Selected</button>
</form>
</section>
<section class="publication-list" aria-label="Existing flipbooks">
__ROWS__
</section>
</main>
<script>
const adminToken=__ADMIN_TOKEN__;const statusEl=document.getElementById('status');const today=new Date().toISOString().slice(0,10);document.querySelectorAll('input[type=date]').forEach((input)=>{if(!input.value)input.value=today});function setStatus(message){statusEl.textContent=message}function selectedSlug(){return document.querySelector('input[name=selectedSlug]:checked')?.value||''}function withToken(formData){formData.append('admin_token',adminToken);return formData}async function readJson(response){const data=await response.json().catch(()=>({detail:'Request failed.'}));if(!response.ok)throw new Error(data.detail||'Request failed.');return data}async function processPublication(slug,pageCount){let start=1;while(start<=pageCount){setStatus('Processing '+slug+' page '+start+' of '+pageCount+'...');const formData=withToken(new FormData());const response=await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/process-batch?start_page='+start+'&limit=5',{method:'POST',body:formData});const data=await readJson(response);if(Number(data.rendered_total)>=Number(data.page_count)){setStatus('Processed '+slug+'.');return data}start=Number(data.next_start_page||data.rendered_total+1)}}document.getElementById('uploadForm').addEventListener('submit',async(event)=>{event.preventDefault();try{setStatus('Uploading new flipbook...');const data=await readJson(await fetch('/admin/api/publications/upload',{method:'POST',body:withToken(new FormData(event.currentTarget))}));await processPublication(data.slug,Number(data.page_count));window.location.reload()}catch(error){setStatus(error.message)}});document.getElementById('replaceForm').addEventListener('submit',async(event)=>{event.preventDefault();const slug=selectedSlug();if(!slug){setStatus('Select one flipbook to replace.');return}try{setStatus('Replacing '+slug+'...');const data=await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/replace',{method:'POST',body:withToken(new FormData(event.currentTarget))}));await processPublication(data.slug,Number(data.page_count));window.location.reload()}catch(error){setStatus(error.message)}});document.getElementById('deleteForm').addEventListener('submit',async(event)=>{event.preventDefault();const slug=selectedSlug();if(!slug){setStatus('Select one flipbook to delete.');return}if(!confirm('Delete '+slug+'?'))return;try{setStatus('Deleting '+slug+'...');await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/delete',{method:'POST',body:withToken(new FormData())}));window.location.reload()}catch(error){setStatus(error.message)}});document.querySelectorAll('.type-select').forEach((select)=>select.addEventListener('change',async(event)=>{const slug=event.currentTarget.dataset.slug;try{const formData=withToken(new FormData());formData.append('flipbook_type',event.currentTarget.value);setStatus('Updating type for '+slug+'...');await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/type',{method:'POST',body:formData}));setStatus('Updated type for '+slug+'.')}catch(error){setStatus(error.message)}}));
</script>
</body>
</html>"""
    return HTMLResponse(
        content=template
        .replace("__ROWS__", row_markup)
        .replace("__ADMIN_TOKEN__", admin_token_json)
    )


def process_publication_batch(slug: str, start_page: int, limit: int) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    pdf_path = Path(manifest["original_pdf_path"])
    if not manifest.get("links"):
        manifest = refresh_embedded_links(normalized_slug, manifest)
    rendered_batch = render_pdf_page_range(normalized_slug, pdf_path, start_page=start_page, limit=limit)
    manifest["page_count"] = rendered_batch["page_count"]
    manifest["pages"] = merge_page_assets(manifest.get("pages") or [], rendered_batch["rendered_pages"])
    manifest["pages_path"] = rendered_batch["pages_path"]
    manifest["thumbs_path"] = rendered_batch["thumbs_path"]
    manifest["status"] = "processed" if len(manifest["pages"]) >= manifest["page_count"] else "processing"
    if manifest["status"] == "processed":
        manifest["processed_at"] = now_iso()
    manifest["updated_at"] = now_iso()
    manifest.pop("error", None)
    manifest_file_path = write_manifest(normalized_slug, manifest)
    return {
        "status": manifest["status"],
        "slug": normalized_slug,
        "page_count": manifest["page_count"],
        "rendered_this_batch": len(rendered_batch["rendered_pages"]),
        "rendered_total": len(manifest["pages"]),
        "next_start_page": rendered_batch["next_start_page"],
        "link_count": len(manifest.get("links") or []),
        "toc_page_number": manifest.get("toc_page_number"),
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
    }


app = FastAPI(title=APP_NAME, description="Minimal Render-deployable API for the GBM Flipbook service.", version="0.8.0")


@app.on_event("startup")
def startup() -> None:
    ensure_storage_path()


@app.get("/")
def read_root() -> dict[str, str]:
    return {"app": APP_NAME, "message": "GBM Flipbook service is running."}


@app.get("/health")
def health_check() -> dict[str, str]:
    storage_path = active_storage_path or ensure_storage_path()
    response = {"status": "ok", "storage_path": str(storage_path)}
    if storage_warning:
        response["storage_warning"] = storage_warning
    return response


@app.get("/archive", response_class=HTMLResponse)
def read_archive() -> HTMLResponse:
    return render_archive_view(list_publications(), flipbook_type="magazine")


@app.get("/ebooks", response_class=HTMLResponse)
def read_ebooks() -> HTMLResponse:
    return render_archive_view(
        list_publications(),
        flipbook_type="ebook",
        page_title="Green Builder Ebooks",
        latest_label="Latest Ebook",
        backlist_label="Ebooks",
    )


@app.get("/other-titles", response_class=HTMLResponse)
def read_other_titles() -> HTMLResponse:
    return render_archive_view(
        list_publications(),
        flipbook_type="other",
        page_title="Green Builder Other Titles",
        latest_label="Latest Title",
        backlist_label="Other Titles",
    )


@app.get("/admin", response_class=HTMLResponse)
def read_admin(admin_token: str | None = Query(default=None)) -> HTMLResponse:
    require_admin_token(admin_token)
    return render_admin_view(list_publications(), admin_token or "")


@app.get("/api/publications")
def get_publications() -> dict[str, Any]:
    publications = list_publications()
    return {"publications": publications, "count": len(publications)}


@app.get("/book/{slug}", response_class=HTMLResponse)
def read_book(slug: str) -> HTMLResponse:
    normalized_slug = validate_slug(slug)
    try:
        manifest = read_manifest(normalized_slug)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return render_missing_book(normalized_slug)
    return render_book_viewer(manifest)


@app.get("/api/publications/{slug}/manifest")
def get_publication_manifest(slug: str) -> dict[str, Any]:
    return read_manifest(slug)


@app.post("/api/publications/{slug}/refresh-links")
def refresh_publication_links(slug: str) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    manifest = refresh_embedded_links(normalized_slug, read_manifest(normalized_slug))
    manifest_file_path = write_manifest(normalized_slug, manifest)
    return {
        "status": manifest["status"],
        "slug": normalized_slug,
        "page_count": manifest["page_count"],
        "page_assets": len(manifest.get("pages") or []),
        "link_count": len(manifest.get("links") or []),
        "toc_page_number": manifest.get("toc_page_number"),
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
    }


@app.get("/api/publications/{slug}/original.pdf")
def get_publication_pdf(slug: str) -> FileResponse:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    pdf_path = Path(manifest["original_pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Original PDF not found.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{normalized_slug}.pdf")


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
    publication_date: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    flipbook_type: str | None = Form(default="magazine"),
) -> dict[str, Any]:
    return save_publication_upload(
        slug=slug,
        file=file,
        title=title,
        description=description,
        publication_date=publication_date,
        source_url=source_url,
        flipbook_type=flipbook_type,
    )


@app.post("/admin/api/publications/upload")
def admin_upload_publication_pdf(
    admin_token: str | None = Form(default=None),
    file: UploadFile = File(...),
    issue_title: str | None = Form(default=None),
    upload_date: str | None = Form(default=None),
    version_notes: str | None = Form(default=None),
    flipbook_type: str | None = Form(default="magazine"),
) -> dict[str, Any]:
    require_admin_token(admin_token)
    filename_stem = Path(file.filename or "").stem
    title = (issue_title or filename_stem).strip()
    slug = unique_slug(slugify(title))
    return save_publication_upload(
        slug=slug,
        file=file,
        title=title,
        description=f"{flipbook_type_label(flipbook_type)} uploaded from Flipbook Admin",
        publication_date=upload_date,
        source_url="Flipbook Admin",
        flipbook_type=flipbook_type,
        upload_date=upload_date,
        version_notes=version_notes,
    )


@app.post("/admin/api/publications/{slug}/replace")
def admin_replace_publication_pdf(
    slug: str,
    admin_token: str | None = Form(default=None),
    file: UploadFile = File(...),
    upload_date: str | None = Form(default=None),
    version_notes: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_token(admin_token)
    normalized_slug = validate_slug(slug)
    existing_manifest = read_manifest(normalized_slug)
    return save_publication_upload(
        slug=normalized_slug,
        file=file,
        title=str(existing_manifest.get("title") or normalized_slug.replace("-", " ").title()),
        description=str(existing_manifest.get("description") or ""),
        publication_date=str(existing_manifest.get("publication_date") or ""),
        source_url=str(existing_manifest.get("source_url") or "Flipbook Admin replacement"),
        flipbook_type=str(existing_manifest.get("flipbook_type") or "magazine"),
        upload_date=upload_date,
        version_notes=version_notes,
    )


@app.post("/admin/api/publications/{slug}/type")
def admin_update_publication_type(
    slug: str,
    admin_token: str | None = Form(default=None),
    flipbook_type: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_token(admin_token)
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    manifest["flipbook_type"] = normalize_flipbook_type(flipbook_type)
    manifest["updated_at"] = now_iso()
    write_manifest(normalized_slug, manifest)
    return {
        "status": "updated",
        "slug": normalized_slug,
        "flipbook_type": manifest["flipbook_type"],
        "flipbook_type_label": flipbook_type_label(manifest["flipbook_type"]),
    }


@app.post("/admin/api/publications/{slug}/delete")
def admin_delete_publication(
    slug: str,
    admin_token: str | None = Form(default=None),
) -> dict[str, str]:
    require_admin_token(admin_token)
    normalized_slug = validate_slug(slug)
    target_dir = publication_dir(normalized_slug)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="Publication not found.")
    shutil.rmtree(target_dir)
    return {"status": "deleted", "slug": normalized_slug}


@app.post("/admin/api/publications/{slug}/process-batch")
def admin_process_publication_pdf_batch(
    slug: str,
    admin_token: str | None = Form(default=None),
    start_page: int = Query(default=1, ge=1),
    limit: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    require_admin_token(admin_token)
    return process_publication_batch(slug, start_page, limit)


@app.post("/api/publications/{slug}/process-batch")
def process_publication_pdf_batch(
    slug: str,
    start_page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=25),
) -> dict[str, Any]:
    return process_publication_batch(slug, start_page, limit)


@app.post("/api/publications/{slug}/process")
def process_publication_pdf(slug: str) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    pdf_path = Path(manifest["original_pdf_path"])
    manifest = refresh_embedded_links(normalized_slug, manifest)
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
    pdf_links = extract_pdf_links(pdf_path, rendered_assets["page_count"])
    manifest.update(rendered_assets)
    manifest["links"] = pdf_links
    manifest["toc_page_number"] = detect_toc_page_number(pdf_links)
    manifest["status"] = "processed"
    manifest["processed_at"] = now_iso()
    manifest["updated_at"] = manifest["processed_at"]
    manifest.pop("error", None)
    manifest_file_path = write_manifest(normalized_slug, manifest)
    return {
        "status": "processed",
        "slug": normalized_slug,
        "page_count": manifest["page_count"],
        "link_count": len(pdf_links),
        "toc_page_number": manifest["toc_page_number"],
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
        "first_page_url": manifest["pages"][0]["image_url"] if manifest["pages"] else None,
    }
