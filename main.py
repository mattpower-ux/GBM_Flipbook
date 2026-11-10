import html
import hmac
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from starlette.background import BackgroundTask
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf
from issue_summaries import issue_blurb, summary_button, summary_dialog_markup, summary_styles
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NumberObject

APP_NAME = "GBM Flipbook"
DEFAULT_STORAGE_PATH = "/data/flipbooks"
FALLBACK_STORAGE_PATH = "/tmp/flipbooks"
PAGE_RENDER_SCALE = float(os.getenv("PAGE_RENDER_SCALE", "1.5"))
THUMB_RENDER_SCALE = 0.35
COVER_RENDER_SCALE = float(os.getenv("COVER_RENDER_SCALE", "1.8"))
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ASSET_FILENAME_PATTERN = re.compile(r"^page-[0-9]{3,5}\.jpg$")
VALID_FLIPBOOK_TYPES = {"magazine": "Magazine", "ebook": "Ebook"}
ADMIN_PASSWORD_ENV = "FLIPBOOK_ADMIN_PASSWORD"
DEFAULT_ADMIN_PASSWORD = "1313"
ADMIN_SESSION_COOKIE = "flipbook_admin_session"
BASELINE_VIEW_COUNTS = {
    "green-builder-q3-2026": 154,
    "green-builder-may-jun-2026": 270,
    "green-builder-mar-apr-2026": 1055,
    "green-builder-jan-feb-2026": 1075,
    "green-builder-nov-dec-2025": 234,
    "green-builder-sep-oct-2025": 380,
    "green-builder-jul-aug-2025": 398,
    "green-builder-may-jun-2025": 358,
    "green-builder-mar-apr-2025": 605,
    "green-builder-jan-feb-2025": 1288,
    "green-builder-nov-dec-2024": 441,
    "green-builder-jul-aug-2024": 561,
    "green-builder-sep-oct-2024": 389,
    "green-builder-may-jun-2024": 372,
    "green-builder-mar-apr-2024": 2176,
    "green-builder-jan-feb-2024": 1036,
    "green-builder-nov-dec-2023": 446,
    "green-builder-sep-oct-2023": 416,
    "green-builder-jul-aug-2023": 742,
    "green-builder-may-jun-2023": 366,
    "green-builder-jan-feb-2023": 1340,
    "green-builder-mar-apr-2023": 2284,
    "green-builder-nov-dec-2022": 436,
    "green-builder-sep-oct-2022": 720,
    "green-builder-jul-aug-2022": 967,
    "2025-homeowner-s-handbook": 365,
    "homeowners-handbook-of-green-building-remodeling-v1": 365,
    "the-2022-homeowner-s-handbook-of-green-building-remodeling": 365,
    "gbm-remodeling-field-report": 45,
    "remodeling-field-report": 45,
    "outdoor-living-guide": 59,
    "2021-outdoor-living-guide": 59,
    "healthy-home-august-2022": 59,
}
PUBLICATION_DISPLAY_OVERRIDES = {
    "green-builder-may-jun-2026": {
        "title": "Green Builder May/June 2026",
        "display_date": "May/June 2026",
    },
    "green-builder-mar-apr-2026": {
        "title": "Green Builder March/April 2026",
        "display_date": "March/April 2026",
    },
}
EBOOK_CHRONOLOGY_ORDER = {
    "a-growing-resiliency-economy-addressing-upfront-cost-challenges": 2600,
    "the-case-for-residential-fire-sprinklers": 2590,
    "the-perfect-envelope": 2580,
    "resilient-homes": 2570,
    "intelligent-energy-solutions": 2560,
    "multifamily-projects": 2550,
    "why-right-sizing-water-calculations-matter": 2540,
    "home-retrofits-that-pay-their-way": 2530,
    "builder-consumer-dynamics-in-the-age-of-electrification": 2520,
    "pushing-the-envelope": 2510,
    "sustainable-kitchens-and-baths": 2500,
    "2025-homeowner-s-handbook": 2490,
    "2024-homeowners-handbook": 2400,
    "cultured-stone": 2390,
    "net-zero-everything": 2380,
    "2023-homeowner-s-handbook": 2370,
    "remodeling-field-report": 2360,
    "the-return-of-the-garden": 2350,
    "the-great-american-electrification": 2340,
    "the-2022-homeowner-s-handbook-of-green-building-remodeling": 2330,
    "2024-energy-insights": 2320,
    "healthy-homes": 2310,
    "healthy-home-august-2022": 2305,
    "decarbonization-from-theory-to-reality": 2300,
    "2023-outdoor-living-guide": 2290,
    "the-healthy-home-handbook": 2280,
    "2022-outdoor-living-guide": 2275,
    "water-heaters-in-control": 2270,
    "make-every-house-a-smart-home": 2260,
    "today-s-smart-solar-home": 2250,
    "enough-is-enough": 2240,
    "the-sonders-project": 2230,
    "the-evolution-of-housing": 2220,
    "the-pursuit-of-perfect-air": 2210,
    "how-to-profit-from-smart-tech-for-garage-door-openers": 2200,
    "2021-outdoor-living-guide": 2190,
    "grow-your-business-with-the-gold-standard-of-green-paints": 2180,
    "get-severe-weather-protection-from-closed-cell-spray-foam-insulation": 2170,
    "coronavirus-and-health-wellness": 2160,
    "2024-outdoor-living": 2150,
    "beat-the-heat": 2140,
    "energy-insights-2023": 2130,
    "the-tiny-house-tactical-guide-2nd-edition": 2120,
    "the-celestia-project": 2100,
    "metal-roofing-inspiration-book": 2090,
    "design-with-fire-in-mind": 2080,
    "safe-havens-in-turbulent-times": 2070,
    "2021-home-buyers-guide": 2060,
}
MAGAZINE_SUBSCRIPTION_URL = "https://app.hubspot.com/payments/RyZtj5CYSiem?referrer=PAYMENT_LINK"
EDITOR_EMAIL = "matt.power@greenbuildermedia.com"
HUBSPOT_PORTAL_ID = "309276"
HUBSPOT_EVENT_PREFIX = f"pe{HUBSPOT_PORTAL_ID}"
HUBSPOT_DEFAULT_FORM_ID = "ca14e4bc-4743-4ed4-a010-36be9140ec09"
REGISTRATION_CAMPAIGNS = {
    "": "Unassigned",
    "resiliency": "Resiliency",
    "energy-efficiency": "Energy Efficiency",
    "indoor-air-quality": "Indoor Air Quality",
    "building-envelope": "Building Envelope",
    "electrification": "Electrification",
    "water": "Water",
    "multifamily": "Multifamily",
    "homeowners-handbook": "Homeowners Handbook",
    "outdoor-living": "Outdoor Living",
    "retrofits": "Retrofits",
    "vha-henry": "VHA Henry",
    "kitchens-baths": "Sustainable Kitchens and Baths",
    "sustainable-products": "Sustainable Products",
    "other": "Other",
}

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
        return "magazine"
    return normalized_value


def flipbook_type_label(value: str | None) -> str:
    return VALID_FLIPBOOK_TYPES[normalize_flipbook_type(value)]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def baseline_view_count(slug: str) -> int:
    try:
        normalized_slug = validate_slug(slug)
    except HTTPException:
        return 0
    return BASELINE_VIEW_COUNTS.get(normalized_slug, 0)


def publication_view_count(manifest: dict[str, Any]) -> int:
    slug = str(manifest.get("slug") or "")
    current_views = safe_int(manifest.get("view_count"), 0)
    if slug:
        current_views = max(current_views, baseline_view_count(slug))
    return current_views


def increment_publication_view_count(slug: str, manifest: dict[str, Any]) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    manifest["view_count"] = max(publication_view_count(manifest), baseline_view_count(normalized_slug)) + 1
    manifest["last_viewed_at"] = now_iso()
    write_manifest(normalized_slug, manifest)
    return manifest


def format_count(value: Any) -> str:
    return f"{safe_int(value):,}"


def get_admin_password() -> str:
    return os.getenv(ADMIN_PASSWORD_ENV, DEFAULT_ADMIN_PASSWORD).strip() or DEFAULT_ADMIN_PASSWORD


def admin_session_value() -> str:
    signature = hmac.new(
        get_admin_password().encode("utf-8"),
        b"gbm-flipbook-admin",
        hashlib.sha256,
    ).hexdigest()
    return f"v1:{signature}"


def require_admin_request(request: Request) -> None:
    expected_session = admin_session_value()
    provided_session = str(request.cookies.get(ADMIN_SESSION_COOKIE) or "")
    if not secrets.compare_digest(provided_session, expected_session):
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

    try:
        with path.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Publication manifest is invalid JSON: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Publication manifest could not be read: {exc}") from exc


def write_manifest(slug: str, manifest: dict[str, Any]) -> Path:
    path = manifest_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, indent=2)
        manifest_file.write("\n")
    return path


def event_log_path() -> Path:
    storage_path = active_storage_path or ensure_storage_path()
    return storage_path / "event-log.json"


def read_event_log() -> list[dict[str, str]]:
    path = event_log_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as event_log_file:
            events = json.load(event_log_file)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def write_event_log(events: list[dict[str, str]]) -> Path:
    path = event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as event_log_file:
        json.dump(events, event_log_file, indent=2)
        event_log_file.write("\n")
    return path


def record_archive_event(
    *,
    action: str,
    slug: str,
    title: str,
    flipbook_type: str | None,
    notes: str | None = None,
) -> None:
    event = {
        "timestamp": now_iso(),
        "action": action,
        "slug": validate_slug(slug),
        "title": title,
        "flipbook_type": normalize_flipbook_type(flipbook_type),
        "notes": str(notes or "").strip(),
    }
    events = read_event_log()
    events.insert(0, event)
    write_event_log(events)


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


def cover_asset_url(slug: str) -> str:
    return f"/api/publications/{slug}/assets/covers/cover.jpg"


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


def normalize_pymupdf_rect(rect: Any, page_width: float, page_height: float) -> dict[str, float] | None:
    x0, y0, x1, y1 = [float(value) for value in rect]
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    if width <= 0 or height <= 0:
        return None
    return {
        "x": max(0.0, min(1.0, x0 / page_width)),
        "y": max(0.0, min(1.0, y0 / page_height)),
        "width": max(0.0, min(1.0, width / page_width)),
        "height": max(0.0, min(1.0, height / page_height)),
    }


def find_toc_page_number(pdf_path: Path, max_pages: int = 15) -> int | None:
    try:
        document = pymupdf.open(str(pdf_path))
    except Exception:
        return None
    try:
        for page_index in range(min(document.page_count, max_pages)):
            text = document[page_index].get_text("text").lower()
            if "table of contents" in text:
                return page_index + 1
    finally:
        document.close()
    return None


MANUAL_TOC_PAGE_LINKS: dict[str, dict[str, Any]] = {
    "green-builder-q3-2026": {
        "toc_page_number": 10,
        "links": [
            {"target_page_number": 12, "source_rect": {"x": 0.085, "y": 0.395, "width": 0.16, "height": 0.095}},
            {"target_page_number": 36, "source_rect": {"x": 0.085, "y": 0.47, "width": 0.16, "height": 0.095}},
            {"target_page_number": 44, "source_rect": {"x": 0.085, "y": 0.565, "width": 0.16, "height": 0.095}},
            {"target_page_number": 50, "source_rect": {"x": 0.425, "y": 0.39, "width": 0.18, "height": 0.105}},
            {"target_page_number": 54, "source_rect": {"x": 0.425, "y": 0.495, "width": 0.18, "height": 0.105}},
            {"target_page_number": 4, "source_rect": {"x": 0.085, "y": 0.795, "width": 0.1, "height": 0.045}},
            {"target_page_number": 8, "source_rect": {"x": 0.085, "y": 0.82, "width": 0.1, "height": 0.045}},
            {"target_page_number": 66, "source_rect": {"x": 0.085, "y": 0.845, "width": 0.1, "height": 0.045}},
        ],
    }
}


def manual_toc_page_number(slug: str) -> int | None:
    manual_toc = MANUAL_TOC_PAGE_LINKS.get(slug)
    if manual_toc:
        return int(manual_toc["toc_page_number"])
    return None


def get_manual_toc_page_links(slug: str, total_pages: int, embedded_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manual_toc = MANUAL_TOC_PAGE_LINKS.get(slug)
    if not manual_toc:
        return []

    toc_page_number = int(manual_toc["toc_page_number"])
    existing_targets = {
        int(link["target_page_number"])
        for link in embedded_links
        if int(link.get("source_page_number") or 0) == toc_page_number
        and "target_page_number" in link
    }
    generated_links: list[dict[str, Any]] = []
    for link in manual_toc["links"]:
        target_page = int(link["target_page_number"])
        if target_page == toc_page_number or target_page in existing_targets or not 1 <= target_page <= total_pages:
            continue
        generated_links.append(
            {
                "source_page_number": toc_page_number,
                "source_rect": link["source_rect"],
                "target_page_number": target_page,
                "generated": "manual-toc-page-number",
            }
        )
    return generated_links


def extract_toc_page_links(
    pdf_path: Path,
    total_pages: int,
    embedded_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    toc_page_number = find_toc_page_number(pdf_path)
    if toc_page_number is None:
        return []

    existing_targets = {
        int(link["target_page_number"])
        for link in embedded_links
        if int(link.get("source_page_number") or 0) == toc_page_number
        and "target_page_number" in link
    }
    try:
        document = pymupdf.open(str(pdf_path))
    except Exception:
        return []

    generated_links: list[dict[str, Any]] = []
    seen_targets: set[int] = set()
    try:
        page = document[toc_page_number - 1]
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        text_page = page.get_text("dict")
        for block in text_page.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "").strip()
                    if not re.fullmatch(r"\d{1,3}", text):
                        continue
                    target_page = int(text)
                    if not 1 <= target_page <= total_pages:
                        continue
                    if target_page == toc_page_number or target_page in existing_targets or target_page in seen_targets:
                        continue
                    source_rect = normalize_pymupdf_rect(span.get("bbox"), page_width, page_height)
                    if source_rect is None:
                        continue
                    generated_links.append(
                        {
                            "source_page_number": toc_page_number,
                            "source_rect": source_rect,
                            "target_page_number": target_page,
                            "generated": "toc-page-number",
                        }
                    )
                    seen_targets.add(target_page)
    finally:
        document.close()

    return generated_links


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
    covers_dir = destination_dir / "covers"
    pages_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)

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

            if page_number == 1:
                cover_pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(COVER_RENDER_SCALE, COVER_RENDER_SCALE),
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                cover_pixmap.save(str(covers_dir / "cover.jpg"))
                del cover_pixmap
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
    if manual_toc_page_number(slug):
        pdf_links.extend(get_manual_toc_page_links(slug, page_count, pdf_links))
    else:
        pdf_links.extend(extract_toc_page_links(pdf_path, page_count, pdf_links))
    manifest["page_count"] = page_count
    manifest["links"] = pdf_links
    manifest["toc_page_number"] = manual_toc_page_number(slug) or find_toc_page_number(pdf_path) or detect_toc_page_number(pdf_links)
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
    registration_required: bool = False,
    registration_portal_id: str | None = None,
    registration_form_id: str | None = None,
    registration_label_value: str | None = None,
    registration_campaign: str | None = None,
) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    existing_view_count = 0
    existing_summary = None
    validate_registration_settings(bool(registration_required), str(registration_portal_id or HUBSPOT_PORTAL_ID).strip(), str(registration_form_id or "").strip())
    existing_manifest_path = manifest_path(normalized_slug)
    if existing_manifest_path.exists():
        try:
            with existing_manifest_path.open("r", encoding="utf-8") as existing_manifest_file:
                previous_manifest = json.load(existing_manifest_file)
                existing_view_count = publication_view_count(previous_manifest)
                existing_summary = issue_blurb(previous_manifest)
        except (OSError, json.JSONDecodeError):
            existing_view_count = 0
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
    try:
        with pdf_path.open("wb") as output_file:
            shutil.copyfileobj(file.file, output_file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Uploaded PDF could not be stored: {exc}") from exc

    try:
        page_count = get_pdf_page_count(pdf_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Uploaded PDF page count failed: {exc}") from exc
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
        "view_count": max(existing_view_count, baseline_view_count(normalized_slug)),
        "last_viewed_at": None,
        "source_url": source_url or "",
        "registration_required": bool(registration_required) and bool(str(registration_form_id or "").strip()),
        "registration_portal_id": str(registration_portal_id or HUBSPOT_PORTAL_ID).strip() or HUBSPOT_PORTAL_ID,
        "registration_form_id": str(registration_form_id or "").strip(),
        "registration_label": str(registration_label_value or "").strip(),
        "registration_campaign": normalize_registration_campaign(registration_campaign),
        "created_at": timestamp,
        "updated_at": timestamp,
        "processed_at": None,
        "toc_page_number": None,
        "flipbook_type": normalize_flipbook_type(flipbook_type),
        "links": [],
        "pages": [],
        "viewer_settings": {},
    }
    if existing_summary is not None:
        manifest["summary_blurb"] = existing_summary
    try:
        manifest_file_path = write_manifest(normalized_slug, manifest)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Publication manifest could not be written: {exc}") from exc
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


def external_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith(("https://", "http://")):
        return url
    return ""


def form_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_registration_campaign(value: Any) -> str:
    campaign = str(value or "").strip()
    return campaign[:200]


def registration_campaign_options(selected: str = "") -> str:
    selected_campaign = normalize_registration_campaign(selected)
    return "".join(
        f"""<option value="{html.escape(key)}"{' selected' if key == selected_campaign else ''}>{html.escape(label)}</option>"""
        for key, label in REGISTRATION_CAMPAIGNS.items()
    )


def registration_enabled(manifest: dict[str, Any]) -> bool:
    return bool(manifest.get("registration_required") and str(manifest.get("registration_form_id") or "").strip())


def validate_registration_settings(required: bool, portal: str, form: str) -> None:
    if required and (not re.fullmatch(r"[0-9]+", portal) or not re.fullmatch(
        r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", form
    )):
        raise HTTPException(status_code=400, detail="Registration requires a numeric HubSpot portal ID and a valid form ID.")


def registration_label(manifest: dict[str, Any]) -> str:
    return str(manifest.get("registration_label") or "Register to read this flipbook")


def hubspot_tracking_markup() -> str:
    return f"""<script>var _hsq=window._hsq=window._hsq||[];function trackFlipbookEvent(action,properties){{_hsq.push(["trackCustomBehavioralEvent",{{name:"{HUBSPOT_EVENT_PREFIX}_flipbook_"+action,properties:properties}}]);}}document.addEventListener("click",function(event){{var target=event.target.closest("[data-hs-action]");if(!target)return;trackFlipbookEvent(target.dataset.hsAction,{{flipbook_slug:target.dataset.hsSlug||"",flipbook_title:target.dataset.hsTitle||"",flipbook_type:target.dataset.hsType||"",target_url:target.href||"",page_path:window.location.pathname}});}});</script><script type="text/javascript" id="hs-script-loader" async defer src="https://js.hs-scripts.com/{HUBSPOT_PORTAL_ID}.js"></script>"""


def hs_tracking_attrs(publication: dict[str, str], action: str) -> str:
    return (
        f"""data-hs-action="{html.escape(action)}" """
        f"""data-hs-slug="{html.escape(publication["slug"])}" """
        f"""data-hs-title="{html.escape(publication["title"])}" """
        f"""data-hs-type="{html.escape(normalize_flipbook_type(publication.get("flipbook_type")))}" """
    )


def hs_manifest_tracking_attrs(manifest: dict[str, Any], action: str) -> str:
    slug = str(manifest.get("slug") or "")
    title = str(manifest.get("title") or slug.replace("-", " ").title())
    flipbook_type = normalize_flipbook_type(str(manifest.get("flipbook_type") or "magazine"))
    return (
        f"""data-hs-action="{html.escape(action)}" """
        f"""data-hs-slug="{html.escape(slug)}" """
        f"""data-hs-title="{html.escape(title)}" """
        f"""data-hs-type="{html.escape(flipbook_type)}" """
    )


def publication_summary(manifest: dict[str, Any]) -> dict[str, str]:
    slug = str(manifest.get("slug") or "")
    display_override = PUBLICATION_DISPLAY_OVERRIDES.get(slug, {})
    pages = manifest.get("pages") or []
    cover_url = str(manifest.get("cover_url") or "")
    if pages and isinstance(pages[0], dict):
        cover_url = cover_url or str(pages[0].get("image_url") or pages[0].get("thumb_url") or "")
    flipbook_type = normalize_flipbook_type(str(manifest.get("flipbook_type") or "magazine"))
    date = publication_date(manifest)
    sort_rank = EBOOK_CHRONOLOGY_ORDER.get(slug, 0) if flipbook_type == "ebook" else 0
    return {
        "slug": slug,
        "title": str(display_override.get("title") or manifest.get("title") or slug.replace("-", " ").title()),
        "description": str(manifest.get("description") or ""),
        "summary_blurb": issue_blurb(manifest),
        "date": date,
        "display_date": str(display_override.get("display_date") or date),
        "sort_rank": f"{sort_rank:04d}",
        "cover_url": cover_url,
        "status": str(manifest.get("status") or "unknown"),
        "flipbook_type": flipbook_type,
        "flipbook_type_label": VALID_FLIPBOOK_TYPES[flipbook_type],
        "upload_date": str(manifest.get("upload_date") or "")[:10],
        "version_notes": str(manifest.get("version_notes") or ""),
        "interactive_url": external_url(manifest.get("interactive_url")),
        "view_count": str(publication_view_count(manifest)),
        "registration_required": "true" if registration_enabled(manifest) else "false",
        "registration_portal_id": str(manifest.get("registration_portal_id") or HUBSPOT_PORTAL_ID),
        "registration_form_id": str(manifest.get("registration_form_id") or ""),
        "registration_label": registration_label(manifest),
        "registration_campaign": normalize_registration_campaign(manifest.get("registration_campaign")),
    }


def featured_description_markup(publication: dict[str, str], selected_type: str) -> str:
    if selected_type == "magazine":
        subscription_url = html.escape(MAGAZINE_SUBSCRIPTION_URL)
        editor_email = html.escape(EDITOR_EMAIL)
        return f"""<div class="current-copy"><p class="subscribe-line"><a href="{subscription_url}" {hs_tracking_attrs(publication, "subscribe")}>Download the current issue for FREE--Or click here to subscribe for a print subscription of <em>Green Builder</em> magazine for only $39.95 a year!</a></p><p>For 21 years, <em>Green Builder</em> has inspired and informed the U.S. construction industry with ideas, building science and innovative approaches to shelter.</p><p>Take a few minutes, or an hour, and peruse our latest issue, and our library below. If you do not find something you can use, <a href="mailto:{editor_email}">drop me an email</a>, and I will add it to the to do list. Thanks for checking in.--Matt Power, Editor-in-Chief</p><img src="https://www.greenbuildermedia.com/hubfs/matt-power-headshot-640.jpg" alt="Matt Power, Editor-in-Chief" width="250" height="233" style="display:block;max-width:100%;height:auto;margin:0 0 20px" loading="lazy"></div>"""

    return f"""<p class="lede">{html.escape(publication["description"])}</p>"""


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

    return sorted(publications, key=lambda item: (item["date"], item.get("sort_rank", "0000")), reverse=True)


def render_archive_view(
    publications: list[dict[str, str]],
    *,
    flipbook_type: str = "magazine",
    page_title: str = "Green Builder Magazine Archive",
    latest_label: str = "Latest Issue",
    backlist_label: str = "Back Issues",
    embedded: bool = False,
) -> HTMLResponse:
    selected_type = normalize_flipbook_type(flipbook_type)
    archive_body_styles = (
        "--bg:#ffffff;--bg-soft:#ffffff;--panel:#ffffff;--panel-strong:#eef7f4;"
        "--ink:#303052;--muted:#4f5e68;--line:#dde5ea;--brand:#25b783;"
        "--brand-bright:#03c78a;background:#ffffff;color:var(--ink)"
    )
    body_classes = ["archive-light"]
    if embedded:
        body_classes.append("embed")
    body_class = f' class="{" ".join(body_classes)}" style="{archive_body_styles}"'
    book_base_path = "/embed/book" if embedded else "/book"
    archive_publications = [
        dict(publication)
        for publication in publications
        if publication["status"] == "processed"
        and publication["cover_url"]
        and normalize_flipbook_type(publication.get("flipbook_type")) == selected_type
    ]
    for publication in archive_publications:
        if publication.get("registration_required") == "true":
            publication["interactive_url"] = ""
    featured = archive_publications[0] if archive_publications else None
    remaining_publications = archive_publications[1:] if featured else []

    if featured:
        featured_pdf_href = (f"{book_base_path}/{featured['slug']}" if featured.get("registration_required") == "true"
                             else f"/api/publications/{featured['slug']}/original.pdf")
        featured_download_flag = "" if featured.get("registration_required") == "true" else "download"
        featured_attrs = hs_tracking_attrs(featured, "open")
        featured_download_attrs = hs_tracking_attrs(featured, "download")
        featured_cover = (
            f'<img src="{html.escape(featured["cover_url"])}" alt="{html.escape(featured["title"])} cover">'
            if featured["cover_url"]
            else "<span>No cover</span>"
        )
        featured_interactive = (
            f"""<a class="button" href="{html.escape(featured["interactive_url"])}" target="_blank" rel="noopener noreferrer" {hs_tracking_attrs(featured, "interactive")}>Interactive Version</a>"""
            if featured.get("interactive_url")
            else ""
        )
        featured_description = featured_description_markup(featured, selected_type)
        featured_blurb = html.escape(featured.get("summary_blurb") or "")
        blurb_markup = f'<p class="issue-blurb">{featured_blurb}</p>' if selected_type == "magazine" and featured_blurb else ""
        featured_markup = f"""<section class="featured"><div class="featured-heading"><p class="eyebrow">{html.escape(latest_label)}</p><h2><a href="{book_base_path}/{html.escape(featured['slug'])}" {featured_attrs}>{html.escape(featured['title'])}</a></h2></div><div class="featured-visual"><a class="featured-cover" href="{book_base_path}/{html.escape(featured['slug'])}" aria-label="Open {html.escape(featured['title'])}" {featured_attrs}>{featured_cover}</a>{blurb_markup}</div><div class="featured-copy">{featured_description}<div class="featured-actions"><a class="button primary" href="{book_base_path}/{html.escape(featured['slug'])}" {featured_attrs}>Read Flipbook</a>{featured_interactive}<a class="button" href="{html.escape(featured_pdf_href)}" {featured_download_flag} {featured_download_attrs}>Download PDF</a></div></div></section>"""
        if selected_type != "magazine":
            featured_markup = f"""<section class="featured"><a class="featured-cover" href="{book_base_path}/{html.escape(featured['slug'])}" aria-label="Open {html.escape(featured['title'])}" {featured_attrs}>{featured_cover}</a><div class="featured-copy"><p class="eyebrow">{html.escape(latest_label)}</p><h2><a href="{book_base_path}/{html.escape(featured['slug'])}" {featured_attrs}>{html.escape(featured['title'])}</a></h2>{featured_description}<div class="featured-actions"><a class="button primary" href="{book_base_path}/{html.escape(featured['slug'])}" {featured_attrs}>Read Flipbook</a>{featured_interactive}<a class="button" href="{html.escape(featured_pdf_href)}" {featured_download_flag} {featured_download_attrs}>Download PDF</a></div></div></section>"""
    else:
        featured_markup = '<p class="empty">No flipbooks have been published yet.</p>'

    if remaining_publications:
        cards = "".join(
            f"""<article class="publication"><a class="cover" href="{book_base_path}/{html.escape(pub['slug'])}" aria-label="Open {html.escape(pub['title'])}" {hs_tracking_attrs(pub, "open")}>{f'<img src="{html.escape(pub["cover_url"])}" alt="{html.escape(pub["title"])} cover" loading="lazy">' if pub['cover_url'] else '<span>No cover</span>'}</a><time datetime="{html.escape(pub['date'])}">{html.escape(pub['display_date'])}</time><h3><a href="{book_base_path}/{html.escape(pub['slug'])}" {hs_tracking_attrs(pub, "open")}>{html.escape(pub['title'])}</a></h3>{f'<a class="text-link" href="{html.escape(pub["interactive_url"])}" target="_blank" rel="noopener noreferrer" {hs_tracking_attrs(pub, "interactive")}>Interactive version</a>' if pub.get('interactive_url') else ''}{summary_button(pub) if selected_type == 'magazine' else ''}</article>"""
            for pub in remaining_publications
        )
    else:
        cards = ""

    return HTMLResponse(
        content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(page_title)}</title><style>:root{{color-scheme:light;--bg:#fff;--bg-soft:#fff;--panel:#fff;--panel-strong:#f2f6f4;--ink:#303052;--muted:#4f5e68;--line:#dde5ea;--brand:#087f59;--brand-bright:#087f59}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}}main{{width:min(1260px,100%);margin:0 auto;padding:34px 22px 56px}}header{{display:flex;align-items:flex-end;justify-content:flex-end;gap:16px;margin-bottom:28px}}body.embed main{{width:100%;padding:0 24px 42px}}body.embed header{{margin-bottom:22px}}.count{{color:var(--muted);font-size:14px}}.featured{{display:grid;grid-template-columns:minmax(240px,470px) minmax(0,1fr);gap:0 40px;align-items:start;margin-bottom:42px;padding-bottom:34px;border-bottom:1px solid var(--line)}}.featured-cover,.cover{{background:#fff;overflow:hidden;display:grid;place-items:center;color:var(--muted);text-decoration:none}}.featured-cover{{aspect-ratio:648/783;border-radius:8px;box-shadow:0 28px 54px rgba(0,0,0,.42)}}.featured-cover img,.cover img{{width:100%;height:100%;object-fit:cover;display:block}}.eyebrow{{margin:0 0 12px;color:var(--brand-bright);font-weight:800;text-transform:uppercase;letter-spacing:0;font-size:14px}}h2{{margin:0 0 16px;font-size:52px;overflow-wrap:anywhere;line-height:1.02;letter-spacing:0}}h2 a,h3 a{{color:var(--ink);text-decoration:none}}h2 a:hover,h3 a:hover,.text-link:hover,.current-copy a:hover{{color:var(--brand-bright)}}.lede,.current-copy{{max-width:760px;margin:0 0 24px;color:var(--muted);font-size:18px;line-height:1.55}}.current-copy p{{margin:0 0 18px}}.current-copy .issue-label{{margin-bottom:8px;color:var(--ink);font-size:22px;font-weight:900}}.subscribe-line a{{color:var(--brand-bright);font-size:29px;line-height:1.25;font-weight:900;text-decoration:none}}.current-copy a{{color:var(--brand-bright);font-weight:800;text-decoration:none}}.featured-actions{{display:flex;flex-wrap:wrap;gap:10px}}.button{{min-height:42px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:0 14px;font-weight:800;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}}.button:hover{{border-color:var(--brand-bright);background:var(--panel-strong)}}.button.primary{{background:var(--brand);border-color:var(--brand);color:#06120d}}.archive-heading{{margin:0 0 16px;color:var(--muted);font-size:13px;text-transform:uppercase;font-weight:800;letter-spacing:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:24px 20px}}.publication{{min-width:0}}.cover{{aspect-ratio:648/783;border:1px solid var(--line);border-radius:6px;margin-bottom:10px}}.publication:hover .cover{{border-color:var(--brand-bright)}}time{{display:block;color:var(--brand-bright);font-size:12px;font-weight:800;text-transform:uppercase;margin-bottom:6px}}h3{{margin:0;font-size:16px;line-height:1.25;letter-spacing:0}}.text-link{{display:inline-flex;margin-top:8px;color:var(--muted);font-size:13px;font-weight:800;text-decoration:none}}.empty{{font-size:16px;color:var(--muted)}}@media(max-width:800px){{main{{padding:24px 14px 42px}}body.embed main{{padding:0 16px 42px}}header{{align-items:flex-start;flex-direction:column}}.featured{{grid-template-columns:1fr;gap:22px}}.featured-cover{{max-width:420px}}.grid{{grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:18px 14px}}h2{{font-size:34px}}.subscribe-line a{{font-size:22px}}h3{{font-size:14px}}}}{summary_styles() if selected_type == "magazine" else ".featured{gap:40px;align-items:center}"}</style></head><body{body_class}><main><header><div class="count">{len(archive_publications)} flipbook{'s' if len(archive_publications) != 1 else ''}</div></header>{featured_markup}<h2 class="archive-heading">{html.escape(backlist_label)}</h2><section class="grid">{cards}</section></main>{summary_dialog_markup() if selected_type == "magazine" else ""}{hubspot_tracking_markup()}</body></html>"""
    )


def render_missing_book(slug: str) -> HTMLResponse:
    safe_slug = html.escape(slug)
    return HTMLResponse(
        content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>GBM Flipbook</title><style>body{{margin:0;font-family:Arial,sans-serif;background:#111820;color:#eef5f0}}main{{min-height:100vh;display:grid;place-items:center;padding:24px}}section{{max-width:620px}}h1{{margin:0 0 12px;font-size:34px;line-height:1.1}}p{{margin:0;color:#b8c7bf;font-size:16px;line-height:1.5}}code{{color:#94e0bf}}</style></head><body><main><section><h1>GBM Flipbook</h1><p>No publication manifest exists for <code>{safe_slug}</code>.</p></section></main></body></html>""",
        status_code=404,
    )


def embedded_archive_path(manifest: dict[str, Any]) -> str:
    if normalize_flipbook_type(str(manifest.get("flipbook_type") or "magazine")) == "ebook":
        return "/embed/ebooks"
    return "/embed/archive"


def archive_path(manifest: dict[str, Any], embedded: bool = False) -> str:
    if embedded:
        return embedded_archive_path(manifest)
    if normalize_flipbook_type(str(manifest.get("flipbook_type") or "magazine")) == "ebook":
        return "/ebooks"
    return "/archive"


def render_book_viewer(manifest: dict[str, Any], embedded: bool = False) -> HTMLResponse:
    title = html.escape(str(manifest.get("title") or "GBM Flipbook"))
    description = html.escape(str(manifest.get("description") or ""))
    slug = html.escape(str(manifest.get("slug") or ""))
    status = html.escape(str(manifest.get("status") or "unknown"))
    back_href = html.escape(archive_path(manifest, embedded=embedded))
    interactive_url = external_url(manifest.get("interactive_url"))
    interactive_attrs = hs_manifest_tracking_attrs(manifest, "interactive")
    download_attrs = hs_manifest_tracking_attrs(manifest, "download")
    interactive_button = (
        f"""<a class="button" href="{html.escape(interactive_url)}" target="_blank" rel="noopener noreferrer" title="Open the media-rich interactive version" {interactive_attrs}>Interactive Version</a>"""
        if interactive_url
        else ""
    )
    manifest_json = json.dumps(manifest).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    requires_registration = registration_enabled(manifest)
    registration_gate_markup = ""
    hubspot_forms_script = ""
    if requires_registration:
        gate_title = html.escape(registration_label(manifest))
        gate_campaign = "Green Builder Media"
        registration_gate_markup = f"""<section class="registration-gate" id="registrationGate"><div class="registration-card"><p class="eyebrow">{html.escape(gate_campaign)}</p><h2>{gate_title}</h2><p>Submit the short form below to open this flipbook.</p><div id="registrationFormMount"></div></div></section>"""
        hubspot_forms_script = '<script src="https://js.hsforms.net/forms/v2.js" defer></script>'
    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;--bg:#0e141b;--bg-soft:#151d27;--panel:#202a35;--panel-strong:#27333f;--ink:#edf5f0;--muted:#a8b8b1;--line:#3a4855;--brand:#29b17d;--brand-dark:#11271e;--link:#d8b24c;--paper:#f7faf8}*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}button,a.button{min-height:38px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:0 12px;font:inherit;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px}button:hover,a.button:hover,button:focus-visible,a.button:focus-visible{border-color:var(--brand);outline:2px solid transparent;background:var(--panel-strong)}button[aria-pressed=true]{border-color:var(--brand);background:var(--brand-dark);color:#cbf4e2}button:disabled{cursor:not-allowed;opacity:.42}.app{min-height:100vh;display:grid;grid-template-rows:auto 1fr}header{background:#111820;border-bottom:1px solid var(--line);padding:12px 18px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:14px;align-items:center;position:sticky;top:0;z-index:10}.archive-button{white-space:nowrap;background:#0f151d;border-color:#536270;text-transform:uppercase;font-size:13px}.title-block{min-width:0}h1{margin:0;font-size:18px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{margin-top:4px;color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.toolbar,.reader-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.reader-actions{justify-content:flex-end}.reader-bar{position:sticky;top:0;z-index:8;margin:0 auto 16px;width:min(100%,1180px);display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:10px;align-items:center;background:rgba(17,24,32,.92);border:1px solid var(--line);border-radius:8px;padding:10px;box-shadow:0 14px 28px rgba(0,0,0,.25);backdrop-filter:blur(10px)}.counter{color:var(--muted);font-size:14px;min-width:86px;text-align:center}.keyboard-hint{color:var(--muted);font-size:13px;font-weight:700;white-space:nowrap}.download-button{background:var(--brand);border-color:var(--brand);color:#06120d}.download-button:hover,.download-button:focus-visible{background:#35c992;color:#04100b}.exit-button{position:fixed;right:18px;bottom:18px;z-index:20;background:#0f151d;border-color:#536270;box-shadow:0 18px 34px rgba(0,0,0,.35)}.exit-button:hover,.exit-button:focus-visible{background:#1c2630}.layout{min-height:0;display:grid;grid-template-columns:138px minmax(0,1fr);background:var(--bg)}aside{border-right:1px solid var(--line);background:#111820;overflow:auto;padding:10px}.thumbs{display:grid;gap:10px}.thumb{width:100%;border:2px solid transparent;border-radius:6px;padding:4px;background:transparent;height:auto;display:grid;gap:4px;color:var(--muted);font-size:12px;font-weight:700}.thumb:hover{background:#1c2630}.thumb[aria-current=true]{border-color:var(--brand);background:#123226;color:#cbf4e2}.thumb img{width:100%;aspect-ratio:648/783;object-fit:cover;display:block;border-radius:3px;background:#222c36}.stage-wrap{min-width:0;min-height:0;overflow:auto;padding:18px 22px 28px;background:var(--bg-soft)}.stage{min-height:100%;display:flex;align-items:flex-start;justify-content:center}.page-frame{position:relative;width:min(100%,calc(760px * var(--zoom,1)));max-width:none;background:var(--paper);filter:drop-shadow(0 26px 42px rgba(0,0,0,.45))}.page-frame img{width:100%;display:block;background:var(--paper)}.spread-frame{display:flex;align-items:flex-start;justify-content:center;gap:10px;width:min(100%,calc(1520px * var(--zoom,1)));filter:drop-shadow(0 26px 42px rgba(0,0,0,.45))}.spread-frame .page-frame{width:calc(50% - 5px);filter:none}.pdf-hotspot{position:absolute;z-index:2;border:2px solid transparent;background:rgba(216,178,76,.01);border-radius:3px;cursor:pointer;padding:0}.pdf-hotspot.generated-link{border-color:rgba(216,178,76,.9);background:rgba(216,178,76,.16)}.pdf-hotspot:hover,.pdf-hotspot:focus-visible{border-color:var(--link);background:rgba(216,178,76,.25);outline:0}.empty{max-width:680px;margin:18vh auto 0;color:var(--muted);line-height:1.5}.registration-gate{display:none;min-height:calc(100vh - 74px);padding:38px 18px;background:var(--bg-soft);place-items:start center}.registration-card{width:min(720px,100%);border:1px solid var(--line);border-radius:8px;background:#fff;color:#303052;padding:24px;box-shadow:0 24px 50px rgba(0,0,0,.32)}.registration-card .eyebrow{margin:0 0 8px;color:var(--brand);font-size:13px;text-transform:uppercase;font-weight:900}.registration-card h2{margin:0 0 10px;font-size:30px;line-height:1.1}.registration-card p{margin:0 0 18px;color:#4f5e68;line-height:1.45}body.registration-locked .registration-gate{display:grid}body.registration-locked .layout,body.registration-locked .exit-button{display:none}@media(max-width:760px){header{grid-template-columns:1fr;padding:12px}.archive-button{justify-self:start}.reader-bar{grid-template-columns:1fr;margin-bottom:12px}.toolbar,.reader-actions{justify-content:flex-start;overflow-x:auto;flex-wrap:nowrap;padding-bottom:2px}.layout{grid-template-columns:1fr;grid-template-rows:1fr auto}aside{grid-row:2;border-right:0;border-top:1px solid var(--line);padding:8px}.thumbs{grid-auto-flow:column;grid-auto-columns:76px;overflow-x:auto;gap:8px}.stage-wrap{padding:12px 12px 68px}.page-frame{width:min(100%,calc(560px * var(--zoom,1)))}.spread-frame{gap:6px;width:min(100%,calc(960px * var(--zoom,1)))}.keyboard-hint{font-size:12px}.exit-button{right:12px;bottom:12px}}
body.registration-unlocked .registration-gate{display:none}.registration-card{color-scheme:light}.registration-thanks .button,.registration-thanks button{margin-top:12px}.registration-thanks h2{color:#303052}
</style>
<style id="responsive-white-viewer">
:root{color-scheme:light;--bg:#fff;--bg-soft:#fff;--panel:#fff;--panel-strong:#f2f6f4;--ink:#303052;--muted:#4f5e68;--line:#d8e0e5;--brand:#087f59;--brand-dark:#e8f5ef;--paper:#fff}
html,body{width:100%;height:100%;overflow:hidden;background:#fff}
.app{width:100%;height:100vh;height:100dvh;min-height:0;grid-template-rows:auto minmax(0,1fr);background:#fff}
header,aside,.layout,.stage-wrap,.reader-bar,.registration-gate,.thumb img{background:#fff}
header{position:relative;min-width:0}
.layout{overflow:hidden;min-width:0;grid-template-columns:120px minmax(0,1fr)}
aside{min-height:0;min-width:0;overscroll-behavior:contain}
.stage-wrap{display:flex;flex-direction:column;overflow:hidden;padding:16px 20px 54px}
.reader-bar{position:relative;top:auto;width:100%;flex:0 0 auto;display:flex;flex-wrap:wrap;box-shadow:none;backdrop-filter:none;gap:10px}
.toolbar,.reader-actions{min-width:0;flex-wrap:wrap;overflow:visible;padding:0;gap:6px}
.reader-actions{margin-left:auto}
#pageDownloadForm{display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:13px}
#pageSelection{width:150px;max-width:100%;min-height:38px;border:1px solid var(--line);border-radius:4px;padding:6px;color:var(--ink);background:#fff;font:inherit}
.stage{min-height:0;min-width:0;flex:1;overflow:auto;justify-content:flex-start;overscroll-behavior:contain;padding:4px 0 12px}
.page-frame{flex-shrink:0;width:calc(min(100%,900px) * var(--zoom,1));margin-inline:auto;filter:none;box-shadow:0 3px 12px rgba(30,40,50,.12);border:1px solid var(--line)}
.spread-frame{flex-shrink:0;width:calc(100% * var(--zoom,1));margin-inline:auto;gap:8px;filter:none}
.spread-frame .page-frame{width:calc(50% - 4px);margin:0}
.archive-button,.exit-button{background:#fff;border-color:var(--line);box-shadow:none;color:var(--ink)}
.exit-button:hover,.archive-button:hover,.thumb:hover{background:#f2f6f4}
.thumb[aria-current=true],button[aria-pressed=true]{background:#e8f5ef;color:#075b40;border-color:#087f59}
.download-button{background:#fff;color:#075b40;border-color:#087f59}
.registration-gate{min-height:0;overflow:auto}
.registration-card{box-shadow:none}
button:focus-visible,a.button:focus-visible{outline:2px solid #087f59;outline-offset:2px}
@media(min-width:601px){.layout{grid-template-rows:minmax(0,1fr)}.layout aside{grid-row:auto;border-top:0;border-right:1px solid var(--line)}.thumbs{grid-auto-flow:row;grid-auto-columns:auto;overflow:visible}.reader-bar{margin-bottom:12px}}
@media(max-width:1000px){.layout{grid-template-columns:90px minmax(0,1fr)}.stage-wrap{padding:12px 12px 54px}.reader-actions{margin-left:0}}
@media(max-width:600px){header{grid-template-columns:1fr;padding:8px 12px;gap:8px}h1{font-size:16px;white-space:normal;overflow-wrap:anywhere}.meta{display:none}.layout{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr) 100px}.layout aside{grid-row:2;padding:6px;border-top:1px solid var(--line);overflow:auto}.thumbs{grid-auto-flow:column;grid-auto-columns:56px;gap:6px;overflow:visible}.thumb img{height:65px;width:100%;object-fit:contain}.thumb{gap:2px;padding:2px}.stage-wrap{padding:8px 8px 48px}.reader-bar{padding:6px;gap:6px;margin-bottom:6px}.reader-bar button,.reader-bar a.button{min-height:40px;padding:0 9px;font-size:13px}.counter{font-size:12px;min-width:76px}.keyboard-hint{display:none}.reader-actions{margin-left:0}.exit-button{bottom:108px;right:8px;min-height:34px;font-size:13px}.registration-gate{padding:18px 12px}.registration-card{padding:18px}.registration-card h2{font-size:24px}}
@media(pointer:coarse){button,a.button{min-height:44px}.reader-bar button,.reader-bar a.button{min-height:44px}}
</style>
</head>
<body>
<div class="app"><header><a class="button archive-button" href="__BACK_HREF__" title="Return to publication archive">Return to Archive</a><div class="title-block"><h1>__TITLE__</h1><div class="meta"><span>__DESCRIPTION__</span><span id="status"> __STATUS__</span></div></div></header>__REGISTRATION_GATE__<div class="layout"><aside aria-label="Thumbnails"><div class="thumbs" id="thumbs"></div></aside><main class="stage-wrap" id="stageWrap"><div class="reader-bar"><div class="toolbar" aria-label="Page controls"><button type="button" id="prevBtn" title="Previous page">Prev</button><span class="counter" id="pageCounter">Page 0 / 0</span><button type="button" id="nextBtn" title="Next page">Next</button><span class="keyboard-hint">PgDn=Next Page</span></div><div class="toolbar" aria-label="View controls"><button type="button" id="zoomOutBtn" title="Zoom out">-</button><button type="button" id="zoomInBtn" title="Zoom in">+</button><button type="button" id="spreadBtn" title="Show side-by-side page spreads after the cover" aria-pressed="false">SHOW SPREADS</button><button type="button" id="tocBtn" title="Table of contents">TOC</button><a class="button" id="expandLink" href="/book/__SLUG__" target="_blank" rel="noopener noreferrer" title="Open expanded viewer in a full browser tab">Expand</a><button type="button" id="shareBtn" title="Copy link">Share</button></div><div class="reader-actions">__INTERACTIVE_BUTTON__<a class="button download-button" href="/api/publications/__SLUG__/original.pdf" download title="Download full PDF" __DOWNLOAD_ATTRS__>Download PDF</a><form id="pageDownloadForm" action="/api/publications/__SLUG__/selected-pages.pdf" method="get"><label for="pageSelection">Download Pages:</label> <input id="pageSelection" name="pages" required maxlength="1000" placeholder="2,5,7 or 14-17" aria-label="Pages to download"><button type="submit" title="Download selected pages" aria-label="Download selected pages">&#8595;</button></form></div></div><div class="stage" id="stage"></div></main></div><a class="button exit-button" href="__BACK_HREF__" title="Exit to publication archive">Exit</a></div>
<script type="application/json" id="manifest-data">__MANIFEST__</script>
__HUBSPOT_FORMS_SCRIPT__
<script>
const manifest=JSON.parse(document.getElementById('manifest-data').textContent);const pages=Array.isArray(manifest.pages)?manifest.pages:[];const links=Array.isArray(manifest.links)?manifest.links:[];const registrationRequired=__REGISTRATION_REQUIRED__;const registrationPortalId=__REGISTRATION_PORTAL_ID__;const registrationFormId=__REGISTRATION_FORM_ID__;const registrationAccessKey='gbm-registration-'+String(manifest.slug||'')+'-'+registrationFormId;function hasRegistrationAccess(){try{return sessionStorage.getItem(registrationAccessKey)==='1'}catch(error){return false}}const linksByPage=links.reduce((acc,link)=>{const page=String(link.source_page_number);(acc[page]||(acc[page]=[])).push(link);return acc},{});const stage=document.getElementById('stage');const thumbs=document.getElementById('thumbs');const counter=document.getElementById('pageCounter');const prevBtn=document.getElementById('prevBtn');const nextBtn=document.getElementById('nextBtn');const zoomInBtn=document.getElementById('zoomInBtn');const zoomOutBtn=document.getElementById('zoomOutBtn');const spreadBtn=document.getElementById('spreadBtn');const expandLink=document.getElementById('expandLink');const shareBtn=document.getElementById('shareBtn');const tocBtn=document.getElementById('tocBtn');const stageWrap=document.getElementById('stageWrap');let pageIndex=0;let zoom=1;let spreadsEnabled=false;let readerRendered=false;function pageUrl(path){return new URL(path,window.location.origin).toString()}function normalizePageIndex(index){const bounded=Math.max(0,Math.min(index,pages.length-1));if(!spreadsEnabled||bounded===0)return bounded;return bounded%2===0?bounded-1:bounded}function visiblePageIndexes(){if(!spreadsEnabled||pageIndex===0)return[pageIndex];return[pageIndex,pageIndex+1].filter((index)=>index<pages.length)}function syncHash(){const pageNumber=pageIndex+1;if(window.location.hash!=='#page-'+pageNumber)history.replaceState(null,'','#page-'+pageNumber);if(expandLink)expandLink.href='/book/'+encodeURIComponent(manifest.slug)+'#page-'+pageNumber}function addPdfLinks(frame,pageNumber){(linksByPage[String(pageNumber)]||[]).forEach((link)=>{const rect=link.source_rect;if(!rect)return;const button=document.createElement('button');button.type='button';button.className='pdf-hotspot'+(link.generated==='manual-toc-page-number'?' generated-link':'');button.title=link.uri?'Open link':'Go to page '+link.target_page_number;button.setAttribute('aria-label',button.title);button.style.left=(rect.x*100)+'%';button.style.top=(rect.y*100)+'%';button.style.width=(rect.width*100)+'%';button.style.height=(rect.height*100)+'%';button.addEventListener('click',()=>{if(link.uri)window.open(link.uri,'_blank','noopener,noreferrer');else if(link.target_page_number)showPage(Number(link.target_page_number)-1)});frame.append(button)})}function buildPageFrame(page){const frame=document.createElement('div');frame.className='page-frame';frame.style.setProperty('--zoom',String(zoom));const img=document.createElement('img');img.src=pageUrl(page.image_url);img.alt=manifest.title+', page '+page.page_number;frame.append(img);addPdfLinks(frame,Number(page.page_number));return frame}function showPage(index){if(!pages.length){stage.innerHTML='<p class="empty">This publication has no rendered pages yet.</p>';counter.textContent='Page 0 / 0';prevBtn.disabled=true;nextBtn.disabled=true;spreadBtn.disabled=true;return}pageIndex=normalizePageIndex(index);const indexes=visiblePageIndexes();stage.innerHTML='';stage.classList.toggle('spread-view',spreadsEnabled&&indexes.length>1);if(indexes.length>1){const spread=document.createElement('div');spread.className='spread-frame';spread.style.setProperty('--zoom',String(zoom));indexes.forEach((pageNumberIndex)=>spread.append(buildPageFrame(pages[pageNumberIndex])));stage.append(spread)}else{stage.append(buildPageFrame(pages[pageIndex]))}const pageNumbers=indexes.map((pageNumberIndex)=>pages[pageNumberIndex].page_number);counter.textContent=pageNumbers.length>1?'Pages '+pageNumbers.join('-')+' / '+pages.length:'Page '+pageNumbers[0]+' / '+pages.length;prevBtn.disabled=pageIndex===0;nextBtn.disabled=spreadsEnabled?pageIndex>=pages.length-2:pageIndex===pages.length-1;const activeIndexes=new Set(indexes.map(String));document.querySelectorAll('.thumb').forEach((thumb)=>thumb.setAttribute('aria-current',activeIndexes.has(thumb.dataset.index)?'true':'false'));stage.scrollTo({top:0,left:0,behavior:'instant'});fitPages();syncHash()}function movePage(direction){if(!spreadsEnabled)showPage(pageIndex+direction);else if(direction>0)showPage(pageIndex===0?1:pageIndex+2);else showPage(pageIndex<=1?0:pageIndex-2)}function fitPages(){const frames=[...stage.querySelectorAll('.page-frame')];if(!frames.length)return;const ratios=frames.map(frame=>{const img=frame.querySelector('img');return img.naturalWidth&&img.naturalHeight?img.naturalWidth/img.naturalHeight:648/783});const gap=frames.length>1?8:0;const availableWidth=Math.max(1,stage.clientWidth-4-gap);const availableHeight=Math.max(1,stage.clientHeight-20);const height=Math.min(availableHeight,availableWidth/ratios.reduce((a,b)=>a+b,0))*zoom;frames.forEach((frame,i)=>{frame.style.width=(height*ratios[i])+'px';frame.style.height='auto'});const spread=stage.querySelector('.spread-frame');if(spread)spread.style.width=(height*ratios.reduce((a,b)=>a+b,0)+gap)+'px'}function setZoom(nextZoom){zoom=Math.max(.4,Math.min(nextZoom,3));fitPages()}new ResizeObserver(fitPages).observe(stage);stage.addEventListener('load',fitPages,true);const pageSelection=document.getElementById('pageSelection');pageSelection.addEventListener('input',()=>pageSelection.setCustomValidity(''));document.getElementById('pageDownloadForm').addEventListener('submit',event=>{const parts=pageSelection.value.split(',');const valid=parts.every(part=>{const m=part.trim().match(/^([0-9]+)(?:\\s*-\\s*([0-9]+))?$/);return m&&Number(m[1])>=1&&Number(m[2]||m[1])>=Number(m[1])&&Number(m[2]||m[1])<=pages.length});if(!valid){event.preventDefault();pageSelection.setCustomValidity('Choose pages 1 to '+pages.length+', for example 2,5,14-17.');pageSelection.reportValidity()}});function renderThumbs(){thumbs.innerHTML='';pages.forEach((page,index)=>{const button=document.createElement('button');button.type='button';button.className='thumb';button.setAttribute('aria-label','Page '+page.page_number);button.dataset.index=String(index);const img=document.createElement('img');img.src=pageUrl(page.thumb_url);img.alt='';img.loading='lazy';const label=document.createElement('span');label.textContent=String(page.page_number);button.append(img,label);button.addEventListener('click',()=>showPage(index));thumbs.append(button)})}function renderReader(){if(readerRendered)return;readerRendered=true;document.body.classList.remove('registration-locked');document.body.classList.add('registration-unlocked');renderThumbs();showPage(pageIndex)}function unlockRegistration(){try{sessionStorage.setItem(registrationAccessKey,'1')}catch(error){}const mount=document.getElementById('registrationFormMount');mount.replaceChildren();const heading=document.createElement('h2');heading.textContent='Thank you!';const message=document.createElement('p');message.textContent='Your registration for '+manifest.title+' is complete.';const download=document.createElement('a');download.className='button download-button';download.href='/api/publications/'+encodeURIComponent(manifest.slug)+'/original.pdf';download.textContent='Download PDF';download.setAttribute('download','');const read=document.createElement('button');read.type='button';read.textContent='Read Flipbook';read.addEventListener('click',renderReader);mount.className='registration-thanks';mount.append(heading,message,download,document.createTextNode(' '),read);document.querySelector('.registration-card>h2').hidden=true;document.querySelector('.registration-card>p:not(.eyebrow)').hidden=true;}function mountRegistrationForm(){document.body.classList.add('registration-locked');let attempts=0;const mount=()=>{if(!window.hbspt||!window.hbspt.forms){if(++attempts<100){window.setTimeout(mount,150);return}document.getElementById('registrationFormMount').textContent='The registration form could not load. Please allow HubSpot forms in your browser and reload this page.';return}try{window.hbspt.forms.create({region:'na1',portalId:registrationPortalId,formId:registrationFormId,target:'#registrationFormMount',inlineMessage:'Thank you for registering.',onFormSubmitted:unlockRegistration})}catch(error){document.getElementById('registrationFormMount').textContent='Unable to load this registration form. Please contact Green Builder Media.'}};mount()}prevBtn.addEventListener('click',()=>movePage(-1));nextBtn.addEventListener('click',()=>movePage(1));zoomInBtn.addEventListener('click',()=>setZoom(zoom+.15));zoomOutBtn.addEventListener('click',()=>setZoom(zoom-.15));spreadBtn.addEventListener('click',()=>{spreadsEnabled=!spreadsEnabled;spreadBtn.setAttribute('aria-pressed',String(spreadsEnabled));spreadBtn.textContent=spreadsEnabled?'SHOW SINGLE':'SHOW SPREADS';showPage(pageIndex)});tocBtn.addEventListener('click',()=>{if(manifest.toc_page_number)showPage(Number(manifest.toc_page_number)-1)});shareBtn.addEventListener('click',async()=>{syncHash();await navigator.clipboard?.writeText(window.location.href);shareBtn.textContent='Copied';window.setTimeout(()=>shareBtn.textContent='Share',1200)});document.addEventListener('keydown',(event)=>{if(document.body.classList.contains('registration-locked')||event.target.closest('input,textarea,select,[contenteditable]'))return;if(event.key==='ArrowLeft'||event.key==='PageUp'){event.preventDefault();movePage(-1)}if(event.key==='ArrowRight'||event.key==='PageDown'){event.preventDefault();movePage(1)}});window.addEventListener('hashchange',()=>{const match=window.location.hash.match(/^#page-(\\d+)$/);if(match)showPage(Number(match[1])-1)});const initialMatch=window.location.hash.match(/^#page-(\\d+)$/);if(initialMatch)pageIndex=Number(initialMatch[1])-1;if(registrationRequired&&registrationFormId&&!hasRegistrationAccess())mountRegistrationForm();else renderReader();
</script>
__HUBSPOT_TRACKING__
</body>
</html>"""
    return HTMLResponse(
        content=template
        .replace("__TITLE__", title)
        .replace("__DESCRIPTION__", description)
        .replace("__STATUS__", status)
        .replace("__SLUG__", slug)
        .replace("__BACK_HREF__", back_href)
        .replace("__DOWNLOAD_ATTRS__", download_attrs)
        .replace("__INTERACTIVE_BUTTON__", interactive_button)
        .replace("__REGISTRATION_GATE__", registration_gate_markup)
        .replace("__HUBSPOT_FORMS_SCRIPT__", hubspot_forms_script)
        .replace("__REGISTRATION_REQUIRED__", json.dumps(requires_registration))
        .replace("<body>", '<body class="registration-locked">' if requires_registration else '<body>')
        .replace("__REGISTRATION_PORTAL_ID__", json.dumps(str(manifest.get("registration_portal_id") or HUBSPOT_PORTAL_ID)))
        .replace("__REGISTRATION_FORM_ID__", json.dumps(str(manifest.get("registration_form_id") or "")))
        .replace("__HUBSPOT_TRACKING__", hubspot_tracking_markup())
        .replace("__MANIFEST__", manifest_json)
    )


def render_admin_login(section: str = "magazine", error: str = "") -> HTMLResponse:
    selected_section = normalize_flipbook_type(section)
    error_markup = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flipbook Admin Login</title>
<style>
:root{{color-scheme:light;--bg:#ffffff;--panel:#ffffff;--ink:#303052;--muted:#4f5e68;--line:#dde5ea;--brand:#25b783;--danger:#b42318}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;display:grid;place-items:center;padding:22px}}main{{width:min(420px,100%);border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:22px}}h1{{margin:0 0 10px;font-size:30px;line-height:1.1;letter-spacing:0}}p{{margin:0 0 18px;color:var(--muted);line-height:1.45}}label{{display:grid;gap:6px;color:var(--muted);font-size:13px;font-weight:800}}input{{width:100%;min-height:42px;border:1px solid var(--line);border-radius:6px;padding:9px;color:var(--ink);font:inherit}}button{{width:100%;min-height:42px;margin-top:14px;border:1px solid var(--brand);border-radius:6px;background:var(--brand);color:#06120d;font:inherit;font-weight:900;cursor:pointer}}.error{{color:var(--danger);font-weight:800}}
</style>
</head>
<body>
<main>
<h1>Flipbook Admin</h1>
<p>Enter the admin password to manage flipbooks.</p>
{error_markup}
<form method="post" action="/admin/login">
<input type="hidden" name="section" value="{html.escape(selected_section)}">
<label>Password<input name="password" type="password" autocomplete="current-password" autofocus required></label>
<button type="submit">Enter Admin</button>
</form>
</main>
</body>
</html>"""
    )


def render_admin_view(
    publications: list[dict[str, str]],
    section: str = "magazine",
) -> HTMLResponse:
    selected_section = normalize_flipbook_type(section)
    section_label = VALID_FLIPBOOK_TYPES[selected_section]
    saved_forms = [p for p in publications if p.get("registration_form_id")]
    form_options = '<option value="">Choose an existing form or enter a new ID below</option>'
    for p in sorted(saved_forms, key=lambda p: p["title"]):
        form_options += '<option value="{}" data-portal="{}" data-campaign="{}" data-label="{}">{}</option>'.format(
            html.escape(p["registration_form_id"], quote=True),
            html.escape(p.get("registration_portal_id") or HUBSPOT_PORTAL_ID, quote=True),
            html.escape(p.get("registration_campaign") or "", quote=True),
            html.escape(p.get("registration_label") or p["title"], quote=True),
            html.escape(p["title"]))
    filtered_publications = [
        publication
        for publication in publications
        if normalize_flipbook_type(publication.get("flipbook_type")) == selected_section
    ]
    rows = []
    for publication in filtered_publications:
        slug = html.escape(publication["slug"])
        title = html.escape(publication["title"])
        date = html.escape(publication["date"])
        status = html.escape(publication["status"])
        cover_url = html.escape(publication["cover_url"])
        view_count = html.escape(format_count(publication.get("view_count")))
        registration_required_value = html.escape(publication.get("registration_required", "false"))
        registration_portal_id = html.escape(publication.get("registration_portal_id", HUBSPOT_PORTAL_ID))
        registration_form_id = html.escape(publication.get("registration_form_id", ""))
        registration_label_value = html.escape(publication.get("registration_label", ""))
        registration_campaign = html.escape(publication.get("registration_campaign", ""))
        registration_badge = "Registration" if publication.get("registration_required") == "true" else "Open"
        cover = (
            f'<img src="{cover_url}" alt="{title} cover">'
            if cover_url
            else '<span class="cover-placeholder">No cover</span>'
        )
        rows.append(
            f"""<article class="publication-row" data-summary="{html.escape(publication.get("summary_blurb") or "", quote=True)}" data-registration-required="{registration_required_value}" data-registration-portal-id="{registration_portal_id}" data-registration-form-id="{registration_form_id}" data-registration-label="{registration_label_value}" data-registration-campaign="{registration_campaign}"><label class="select-target"><input type="radio" name="selectedSlug" value="{slug}"><span class="cover">{cover}</span><span class="publication-copy"><strong>{title}</strong><span>{date} · {status} · {html.escape(registration_badge)}</span></span></label><span class="views-count">{view_count}</span></article>"""
        )
    row_markup = "".join(rows) if rows else f'<p class="empty">No {html.escape(section_label.lower())} flipbooks have been uploaded yet.</p>'
    action_labels = {
        "uploaded": "New flipbook uploaded",
        "updated": "Existing flipbook updated",
        "deleted": "Existing flipbook deleted",
    }
    event_rows = []
    for event in read_event_log():
        if normalize_flipbook_type(str(event.get("flipbook_type") or "magazine")) != selected_section:
            continue
        event_action = html.escape(action_labels.get(str(event.get("action") or ""), str(event.get("action") or "Change")))
        event_time = html.escape(str(event.get("timestamp") or ""))
        event_title = html.escape(str(event.get("title") or event.get("slug") or "Untitled flipbook"))
        event_type = html.escape(flipbook_type_label(str(event.get("flipbook_type") or "magazine")))
        event_notes = html.escape(str(event.get("notes") or ""))
        notes_markup = f'<span class="event-notes">{event_notes}</span>' if event_notes else ""
        event_rows.append(
            f"""<article class="event-row"><div><strong>{event_action}</strong><span>{event_time} · {event_type}</span></div><div><b>{event_title}</b>{notes_markup}</div></article>"""
        )
        if len(event_rows) >= 50:
            break
    event_markup = "".join(event_rows) if event_rows else f'<p class="empty">No {html.escape(section_label.lower())} archive changes have been recorded yet.</p>'
    section_json = json.dumps(selected_section)
    magazine_href = "/admin?section=magazine"
    ebook_href = "/admin?section=ebook"
    magazine_active = " active" if selected_section == "magazine" else ""
    ebook_active = " active" if selected_section == "ebook" else ""
    campaign_options = registration_campaign_options()
    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flipbook Admin</title>
<style>
:root{color-scheme:dark;--bg:#0e141b;--panel:#141d27;--panel-strong:#1d2935;--ink:#edf5f0;--muted:#a8b8b1;--line:#344351;--brand:#29b17d;--danger:#c84d4d}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif}main{width:min(1280px,100%);margin:0 auto;padding:22px}h1{margin:0 0 14px;font-size:32px;line-height:1.1;letter-spacing:0}.section-switch{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 18px}.section-switch a{min-height:38px;border:1px solid var(--line);border-radius:6px;background:var(--panel-strong);color:var(--ink);font-weight:800;text-decoration:none;display:inline-flex;align-items:center;padding:0 12px}.section-switch a:hover,.section-switch a:focus-visible{border-color:var(--brand);outline:0}.section-switch a.active{background:var(--brand);border-color:var(--brand);color:#06120d}.logout-form{margin-left:auto}.logout-form button{background:transparent}.actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:18px}.panel{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px;min-width:0}h2{margin:0 0 12px;font-size:16px;letter-spacing:0}label{display:grid;gap:6px;color:var(--muted);font-size:12px;font-weight:700}.check-row{display:flex;align-items:center;gap:8px;color:var(--ink)}.check-row input{width:18px;height:18px}fieldset{border:1px solid var(--line);border-radius:8px;padding:10px;display:grid;gap:10px}legend{padding:0 6px;color:var(--muted);font-size:12px;font-weight:900}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:6px;background:#0f151d;color:var(--ink);padding:9px}textarea{min-height:72px;resize:vertical}button{min-height:38px;border:1px solid var(--line);border-radius:6px;background:var(--panel-strong);color:var(--ink);font-weight:800;cursor:pointer;padding:0 12px}button:hover,button:focus-visible{border-color:var(--brand);outline:0}button:disabled{cursor:not-allowed;opacity:.45}button.primary{background:var(--brand);border-color:var(--brand);color:#06120d}button.danger{background:#2c1719;border-color:#683137;color:#ffdcdc}.form-grid{display:grid;gap:10px}.status{position:sticky;top:0;z-index:2;margin-bottom:14px;border:1px solid var(--line);background:#101820;border-radius:8px;padding:10px;color:var(--muted);font-size:14px}.admin-content{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,340px);align-items:start;gap:18px}.list-tools{display:flex;justify-content:flex-end;margin:0 0 10px}.publication-list-header{display:grid;grid-template-columns:minmax(0,1fr) 90px;gap:12px;padding:0 14px 8px;color:var(--muted);font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:0}.publication-list-header span:last-child{text-align:right}.publication-list{display:grid;gap:10px}.publication-row{display:grid;grid-template-columns:minmax(0,1fr) 90px;gap:12px;align-items:center;border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:10px}.select-target{grid-template-columns:auto 56px minmax(0,1fr);align-items:center;gap:10px;color:var(--ink);font-size:14px;min-width:0}.select-target input{width:18px;height:18px}.cover{width:56px;aspect-ratio:648/783;border:1px solid var(--line);border-radius:4px;background:#202a35;display:grid;place-items:center;overflow:hidden;color:var(--muted);font-size:10px;text-align:center}.cover img{width:100%;height:100%;object-fit:cover;display:block}.publication-copy{display:grid;gap:4px;min-width:0}.publication-copy strong{font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.publication-copy span{color:var(--muted);font-size:12px}.views-count{justify-self:end;color:var(--ink);font-size:15px;font-weight:900;font-variant-numeric:tabular-nums}.empty{color:var(--muted)}@media(max-width:860px){.admin-content{grid-template-columns:1fr}.logout-form{margin-left:0}.publication-list-header{display:none}.publication-row{grid-template-columns:1fr}.views-count{justify-self:start;margin-left:90px;color:var(--muted)}.views-count::before{content:"Views ";font-weight:700}}
section.event-tracking{position:sticky;top:68px;max-height:calc(100vh - 90px);overflow:auto}.event-list{display:grid;gap:8px}.event-row{display:grid;gap:10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:10px}.event-row div{display:grid;gap:3px;min-width:0}.event-row strong,.event-row b{font-size:14px;color:var(--ink)}.event-row span{color:var(--muted);font-size:12px;line-height:1.35}.event-notes{font-style:italic}@media(max-width:860px){section.event-tracking{position:static;max-height:none}}
body.admin-light{color-scheme:light;--bg:#ffffff;--panel:#ffffff;--panel-strong:#eef7f4;--ink:#303052;--muted:#4f5e68;--line:#dde5ea;--brand:#25b783;--danger:#b42318}body.admin-light input,body.admin-light select,body.admin-light textarea{background:#ffffff;color:var(--ink)}body.admin-light .status{background:#f8fbfa;color:var(--muted)}body.admin-light button.danger{background:#fff4f3;border-color:#dc8b84;color:#9f1f17}body.admin-light .cover{background:#f4f7f8}body.admin-light input::file-selector-button{background:#eef2f4;color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:6px 10px;font-weight:800}
</style>
</head>
<body class="admin-light">
<main>
<h1>Flipbook Admin</h1>
<nav class="section-switch" aria-label="Admin section switch"><a class="__MAGAZINE_ACTIVE__" href="__MAGAZINE_HREF__">Manage Magazines</a><a class="__EBOOK_ACTIVE__" href="__EBOOK_HREF__">Manage Ebooks</a><form class="logout-form" method="post" action="/admin/logout"><button type="submit">Log Out</button></form></nav>
<div class="status" id="status">Ready.</div>
<section class="actions" aria-label="Flipbook actions">
<form class="panel form-grid" id="uploadForm">
<h2>Upload New __SECTION_LABEL__</h2>
<label>PDF<input name="file" type="file" accept="application/pdf" required></label>
<label>Issue Title <input name="issue_title" type="text" placeholder="Optional"></label>
<label class="magazine-summary-field">Issue summary <textarea name="summary_blurb" maxlength="2400" placeholder="A short, conversational summary of this issue"></textarea></label>
<label>Upload Date <input name="upload_date" type="date"></label>
<input name="flipbook_type" type="hidden" value="__SECTION__">
<label>Version Notes <textarea name="version_notes" placeholder="What changed in this upload?"></textarea></label>
<fieldset>
<legend>Registration</legend>
<label>Saved HubSpot form <select class="saved-form">__SAVED_FORM_OPTIONS__</select></label>
<label class="check-row"><input name="registration_required_toggle" type="checkbox"> Require HubSpot registration</label>
<label>HubSpot Portal ID <input name="registration_portal_id" type="text" value="__HUBSPOT_PORTAL_ID__"></label>
<label>HubSpot Form ID <input name="registration_form_id" type="text" placeholder="ca14e4bc-4743-4ed4-a010-36be9140ec09"></label>
<label>Form Label <input name="registration_label_value" type="text" placeholder="Landing Page: 2026 Resiliency ebook"></label>
<label>Campaign name in HubSpot <input name="registration_campaign" type="text" list="hubspot-campaigns" placeholder="Exact campaign name"></label>
</fieldset>
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
<form class="panel form-grid" id="registrationForm">
<h2>Registration Capture</h2>
<label>Saved HubSpot form <select class="saved-form">__SAVED_FORM_OPTIONS__</select></label>
<p class="empty">Select one flipbook below, then save its HubSpot registration settings.</p>
<label class="check-row"><input name="registration_required_toggle" type="checkbox"> Require HubSpot registration</label>
<label>HubSpot Portal ID <input name="registration_portal_id" type="text" value="__HUBSPOT_PORTAL_ID__"></label>
<label>HubSpot Form ID <input name="registration_form_id" type="text" placeholder="HubSpot form GUID"></label>
<label>Form Label <input name="registration_label_value" type="text" placeholder="Landing Page name"></label>
<label>Campaign name in HubSpot <input name="registration_campaign" type="text" list="hubspot-campaigns" placeholder="Exact campaign name"></label>
<a href="https://app.hubspot.com/marketing/309276/campaigns" target="_blank" rel="noopener noreferrer">Manage Campaigns in HubSpot</a>
<a href="https://app.hubspot.com/forms/309276" target="_blank" rel="noopener noreferrer">Manage Forms in HubSpot</a>
<p class="empty">Create or select the form in HubSpot, associate it with its campaign under Options, then enter the form ID here. Campaign names here are reference labels; they do not change HubSpot associations.</p>
<datalist id="hubspot-campaigns">__CAMPAIGN_OPTIONS__</datalist>
<button class="primary" type="submit">Save Registration Settings</button>
</form>
</section>
<form class="panel form-grid" id="summaryForm" style="margin:20px 0"><h2>Issue Summary</h2><p>Select a magazine below to edit the blurb shown in the archive. Replacing its PDF keeps this summary.</p><label>Summary blurb<textarea id="summaryBlurb" name="summary_blurb" maxlength="2400" rows="5"></textarea></label><button class="primary" type="submit">Save Summary</button></form>
<section class="admin-content">
<div>
<div class="list-tools"><button type="button" id="deselectBtn" disabled>Deselect</button></div>
<div class="publication-list-header" aria-hidden="true"><span>Title</span><span>Views</span></div>
<section class="publication-list" aria-label="Existing flipbooks">
__ROWS__
</section>
</div>
<aside class="panel event-tracking" aria-label="Event tracking">
<h2>__SECTION_LABEL__ Event Tracking</h2>
<div class="event-list">
__EVENT_ROWS__
</div>
</aside>
</section>
</main>
<script>
const currentSection=__SECTION_JSON__;if(currentSection!=='magazine'){document.getElementById('summaryForm').style.display='none';document.querySelectorAll('.magazine-summary-field').forEach(el=>el.style.display='none')};document.getElementById('summaryForm').addEventListener('submit',async event=>{event.preventDefault();const slug=selectedSlug();if(!slug){setStatus('Select a magazine to edit its summary.');return}try{await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/metadata',{method:'POST',body:new FormData(event.currentTarget)}));window.location.reload()}catch(error){setStatus(error.message)}});const statusEl=document.getElementById('status');const deselectBtn=document.getElementById('deselectBtn');const registrationForm=document.getElementById('registrationForm');const today=new Date().toISOString().slice(0,10);document.querySelectorAll('input[type=date]').forEach((input)=>{if(!input.value)input.value=today});function setStatus(message){statusEl.textContent=message}function selectedInput(){return document.querySelector('input[name=selectedSlug]:checked')}function selectedRow(){return selectedInput()?.closest('.publication-row')||null}function selectedSlug(){return selectedInput()?.value||''}function selectedTitle(){return selectedRow()?.querySelector('.publication-copy strong')?.textContent||selectedSlug()}function applyRegistrationFlag(formData,form){formData.set('registration_required',form.querySelector('[name=registration_required_toggle]')?.checked?'true':'false');return formData}function populateRegistrationForm(){const row=selectedRow();if(!registrationForm)return;registrationForm.querySelector('.saved-form').value='';if(!row){registrationForm.reset();registrationForm.querySelector('[name=registration_portal_id]').value='__HUBSPOT_PORTAL_ID__';registrationForm.querySelector('[name=registration_required_toggle]').checked=false;return}registrationForm.querySelector('[name=registration_required_toggle]').checked=row.dataset.registrationRequired==='true';registrationForm.querySelector('[name=registration_portal_id]').value=row.dataset.registrationPortalId||'__HUBSPOT_PORTAL_ID__';registrationForm.querySelector('[name=registration_form_id]').value=row.dataset.registrationFormId||'';registrationForm.querySelector('[name=registration_label_value]').value=row.dataset.registrationLabel||'';registrationForm.querySelector('[name=registration_campaign]').value=row.dataset.registrationCampaign||''}function updateDeselectState(){deselectBtn.disabled=!selectedSlug();populateRegistrationForm();document.getElementById('summaryBlurb').value=selectedRow()?.dataset.summary||''}async function readJson(response){const data=await response.json().catch(()=>({detail:'Request failed.'}));if(!response.ok)throw new Error(data.detail||'Request failed.');return data}async function processPublication(slug,pageCount){let start=1;while(start<=pageCount){setStatus('Processing '+slug+' page '+start+' of '+pageCount+'...');const response=await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/process-batch?start_page='+start+'&limit=5',{method:'POST',body:new FormData()});const data=await readJson(response);if(Number(data.rendered_total)>=Number(data.page_count)){setStatus('Processed '+slug+'.');return data}start=Number(data.next_start_page||data.rendered_total+1)}}document.querySelectorAll('input[name=selectedSlug]').forEach((input)=>input.addEventListener('change',updateDeselectState));deselectBtn.addEventListener('click',()=>{document.querySelectorAll('input[name=selectedSlug]').forEach((input)=>{input.checked=false});updateDeselectState();setStatus('Selection cleared.')});updateDeselectState();document.getElementById('uploadForm').addEventListener('submit',async(event)=>{event.preventDefault();try{setStatus('Uploading new '+currentSection+' flipbook...');const formData=applyRegistrationFlag(new FormData(event.currentTarget),event.currentTarget);const data=await readJson(await fetch('/admin/api/publications/upload',{method:'POST',body:formData}));await processPublication(data.slug,Number(data.page_count));window.location.reload()}catch(error){setStatus(error.message)}});document.getElementById('replaceForm').addEventListener('submit',async(event)=>{event.preventDefault();const slug=selectedSlug();if(!slug){setStatus('Select one flipbook to replace.');return}try{setStatus('Replacing '+slug+'...');const data=await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/replace',{method:'POST',body:new FormData(event.currentTarget)}));await processPublication(data.slug,Number(data.page_count));window.location.reload()}catch(error){setStatus(error.message)}});registrationForm.addEventListener('submit',async(event)=>{event.preventDefault();const slug=selectedSlug();if(!slug){setStatus('Select one flipbook to update registration.');return}try{setStatus('Saving registration settings for '+slug+'...');const formData=applyRegistrationFlag(new FormData(event.currentTarget),event.currentTarget);await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/metadata',{method:'POST',body:formData}));window.location.reload()}catch(error){setStatus(error.message)}});document.getElementById('deleteForm').addEventListener('submit',async(event)=>{event.preventDefault();const slug=selectedSlug();if(!slug){setStatus('Select one flipbook to delete.');return}const title=selectedTitle();const confirmed=confirm('Are you sure?\\n\\nThis will delete \"'+title+'\" from the archive and remove its stored PDF, page images, thumbnails, and manifest.\\n\\nClick OK to permanently delete it.');if(!confirmed)return;try{setStatus('Deleting '+slug+'...');await readJson(await fetch('/admin/api/publications/'+encodeURIComponent(slug)+'/delete',{method:'POST',body:new FormData()}));window.location.reload()}catch(error){setStatus(error.message)}});document.querySelectorAll('.saved-form').forEach((select)=>select.addEventListener('change',()=>{const option=select.selectedOptions[0];if(!option.value)return;const form=select.closest('form');form.querySelector('[name=registration_form_id]').value=option.value;form.querySelector('[name=registration_portal_id]').value=option.dataset.portal;form.querySelector('[name=registration_campaign]').value=option.dataset.campaign;form.querySelector('[name=registration_label_value]').value=option.dataset.label;form.querySelector('[name=registration_required_toggle]').checked=true}));
</script>
</body>
</html>"""
    return HTMLResponse(
        content=template
        .replace("__ROWS__", row_markup)
        .replace("__EVENT_ROWS__", event_markup)
        .replace("__SECTION_JSON__", section_json)
        .replace("__SECTION__", selected_section)
        .replace("__SECTION_LABEL__", section_label)
        .replace("__HUBSPOT_PORTAL_ID__", HUBSPOT_PORTAL_ID)
        .replace("__SAVED_FORM_OPTIONS__", form_options)
        .replace("__CAMPAIGN_OPTIONS__", "".join('<option value="{}"></option>'.format(html.escape(name, quote=True)) for name in sorted({p.get("registration_campaign") for p in publications if p.get("registration_campaign")})))
        .replace("__MAGAZINE_HREF__", magazine_href)
        .replace("__EBOOK_HREF__", ebook_href)
        .replace("__MAGAZINE_ACTIVE__", magazine_active)
        .replace("__EBOOK_ACTIVE__", ebook_active)
    )


def process_publication_batch(slug: str, start_page: int, limit: int) -> dict[str, Any]:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    pdf_path = Path(manifest["original_pdf_path"])
    if not manifest.get("links") and not manifest.get("link_extraction_checked_at"):
        try:
            manifest = refresh_embedded_links(normalized_slug, manifest)
        except Exception as exc:
            manifest["links"] = []
            manifest["toc_page_number"] = None
            manifest["error"] = f"Embedded link extraction skipped: {exc}"
        manifest["link_extraction_checked_at"] = now_iso()
    rendered_batch = render_pdf_page_range(normalized_slug, pdf_path, start_page=start_page, limit=limit)
    manifest["page_count"] = rendered_batch["page_count"]
    manifest["pages"] = merge_page_assets(manifest.get("pages") or [], rendered_batch["rendered_pages"])
    manifest["pages_path"] = rendered_batch["pages_path"]
    manifest["thumbs_path"] = rendered_batch["thumbs_path"]
    if any(int(page.get("page_number") or 0) == 1 for page in rendered_batch["rendered_pages"]):
        manifest["cover_url"] = cover_asset_url(normalized_slug)
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


@app.get("/embed/archive", response_class=HTMLResponse)
def read_archive_embed() -> HTMLResponse:
    return render_archive_view(list_publications(), flipbook_type="magazine", embedded=True)


@app.get("/ebooks", response_class=HTMLResponse)
def read_ebooks() -> HTMLResponse:
    return render_archive_view(
        list_publications(),
        flipbook_type="ebook",
        page_title="Green Builder Ebooks",
        latest_label="Latest Ebook",
        backlist_label="Ebooks",
    )


@app.get("/embed/ebooks", response_class=HTMLResponse)
def read_ebooks_embed() -> HTMLResponse:
    return render_archive_view(
        list_publications(),
        flipbook_type="ebook",
        page_title="Green Builder Ebooks",
        latest_label="Latest Ebook",
        backlist_label="Ebooks",
        embedded=True,
    )


@app.get("/admin", response_class=HTMLResponse)
def read_admin(
    request: Request,
    section: str = Query(default="magazine"),
) -> HTMLResponse:
    try:
        require_admin_request(request)
    except HTTPException:
        return render_admin_login(section=section)
    return render_admin_view(list_publications(), section=section)


@app.post("/admin/login", response_model=None)
def login_admin(
    password: str = Form(...),
    section: str = Form(default="magazine"),
):
    selected_section = normalize_flipbook_type(section)
    if not secrets.compare_digest(password, get_admin_password()):
        return render_admin_login(section=selected_section, error="Incorrect password.")
    response = RedirectResponse(url=f"/admin?section={selected_section}", status_code=303)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        admin_session_value(),
        httponly=True,
        secure=True,
        samesite="none",
        max_age=60 * 60 * 12,
    )
    return response


@app.post("/admin/logout")
def logout_admin() -> RedirectResponse:
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie(ADMIN_SESSION_COOKIE, secure=True, samesite="none")
    return response


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
    manifest = increment_publication_view_count(normalized_slug, manifest)
    return render_book_viewer(manifest)


@app.get("/embed/book/{slug}", response_class=HTMLResponse)
def read_book_embed(slug: str) -> HTMLResponse:
    normalized_slug = validate_slug(slug)
    try:
        manifest = read_manifest(normalized_slug)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return render_missing_book(normalized_slug)
    manifest = increment_publication_view_count(normalized_slug, manifest)
    return render_book_viewer(manifest, embedded=True)


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


def parse_page_selection(value: str, count: int) -> list[int]:
    if not value.strip() or len(value) > 1000:
        raise HTTPException(400, "Enter page numbers or ranges, such as 2,5,14-17.")
    selected = set()
    for part in value.split(','):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", part)
        if not match:
            raise HTTPException(400, "Use commas and page ranges, such as 2,5,14-17.")
        first = int(match[1])
        last = int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise HTTPException(400, f"Choose pages from 1 to {count}, with ranges in ascending order.")
        selected.update(range(first - 1, last))
    return sorted(selected)


@app.get("/api/publications/{slug}/selected-pages.pdf")
def download_selected_pages(slug: str, pages: str = Query(..., max_length=1000)) -> FileResponse:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    source = Path(str(manifest.get("original_pdf_path") or ""))
    if not source.is_file():
        raise HTTPException(404, "Original PDF not available for page selection.")
    output_path = None
    try:
        with pymupdf.open(source) as original:
            selection = parse_page_selection(pages, len(original))
            with pymupdf.open() as output:
                for index in selection:
                    output.insert_pdf(original, from_page=index, to_page=index)
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temporary:
                    output_path = Path(temporary.name)
                output.save(output_path, deflate=True)
        return FileResponse(output_path, media_type="application/pdf",
            filename=f"{normalized_slug}-selected-pages.pdf",
            background=BackgroundTask(output_path.unlink, missing_ok=True))
    except Exception:
        if output_path:
            output_path.unlink(missing_ok=True)
        raise


@app.get("/api/publications/{slug}/original.pdf")
def get_publication_pdf(slug: str) -> Any:
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    original_pdf_path = str(manifest.get("original_pdf_path") or "")
    if original_pdf_path:
        pdf_path = Path(original_pdf_path)
        if pdf_path.exists():
            return FileResponse(pdf_path, media_type="application/pdf", filename=f"{normalized_slug}.pdf")
    source_url = external_url(manifest.get("source_url"))
    if source_url:
        return RedirectResponse(url=source_url, status_code=302)
    raise HTTPException(status_code=404, detail="Original PDF not found.")


@app.get("/api/publications/{slug}/assets/{asset_type}/{filename}")
def get_publication_asset(slug: str, asset_type: str, filename: str) -> FileResponse:
    normalized_slug = validate_slug(slug)
    if asset_type not in {"pages", "thumbs", "covers"}:
        raise HTTPException(status_code=404, detail="Asset type not found.")
    if asset_type == "covers":
        if filename != "cover.jpg":
            raise HTTPException(status_code=400, detail="Invalid cover filename.")
    elif not ASSET_FILENAME_PATTERN.fullmatch(filename):
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
    request: Request,
    file: UploadFile = File(...),
    issue_title: str | None = Form(default=None),
    summary_blurb: str | None = Form(default=None),
    upload_date: str | None = Form(default=None),
    version_notes: str | None = Form(default=None),
    flipbook_type: str | None = Form(default="magazine"),
    registration_required: str | None = Form(default=None),
    registration_portal_id: str | None = Form(default=None),
    registration_form_id: str | None = Form(default=None),
    registration_label_value: str | None = Form(default=None),
    registration_campaign: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_request(request)
    filename_stem = Path(file.filename or "").stem
    title = (issue_title or filename_stem).strip()
    slug = unique_slug(slugify(title))
    result = save_publication_upload(
        slug=slug,
        file=file,
        title=title,
        description=f"{flipbook_type_label(flipbook_type)} uploaded from Flipbook Admin",
        publication_date=upload_date,
        source_url="Flipbook Admin",
        flipbook_type=flipbook_type,
        upload_date=upload_date,
        version_notes=version_notes,
        registration_required=form_truthy(registration_required),
        registration_portal_id=registration_portal_id,
        registration_form_id=registration_form_id,
        registration_label_value=registration_label_value,
        registration_campaign=registration_campaign,
    )
    if summary_blurb and summary_blurb.strip():
        manifest = read_manifest(result["slug"])
        manifest["summary_blurb"] = summary_blurb.strip()[:2400]
        write_manifest(result["slug"], manifest)
    record_archive_event(
        action="uploaded",
        slug=result["slug"],
        title=title,
        flipbook_type=flipbook_type,
        notes=version_notes,
    )
    return result


@app.post("/admin/api/publications/{slug}/replace")
def admin_replace_publication_pdf(
    slug: str,
    request: Request,
    file: UploadFile = File(...),
    upload_date: str | None = Form(default=None),
    version_notes: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    existing_manifest = read_manifest(normalized_slug)
    title = str(existing_manifest.get("title") or normalized_slug.replace("-", " ").title())
    result = save_publication_upload(
        slug=normalized_slug,
        file=file,
        title=title,
        description=str(existing_manifest.get("description") or ""),
        publication_date=str(existing_manifest.get("publication_date") or ""),
        source_url=str(existing_manifest.get("source_url") or "Flipbook Admin replacement"),
        flipbook_type=str(existing_manifest.get("flipbook_type") or "magazine"),
        upload_date=upload_date,
        version_notes=version_notes,
        registration_required=registration_enabled(existing_manifest),
        registration_portal_id=str(existing_manifest.get("registration_portal_id") or HUBSPOT_PORTAL_ID),
        registration_form_id=str(existing_manifest.get("registration_form_id") or ""),
        registration_label_value=str(existing_manifest.get("registration_label") or ""),
        registration_campaign=str(existing_manifest.get("registration_campaign") or ""),
    )
    record_archive_event(
        action="updated",
        slug=normalized_slug,
        title=title,
        flipbook_type=str(existing_manifest.get("flipbook_type") or "magazine"),
        notes=version_notes,
    )
    return result


@app.post("/admin/api/publications/{slug}/external")
def admin_create_external_publication(
    slug: str,
    request: Request,
    title: str = Form(...),
    description: str | None = Form(default=None),
    publication_date: str | None = Form(default=None),
    source_url: str = Form(...),
    flipbook_type: str | None = Form(default="ebook"),
    page_count: int = Form(...),
) -> dict[str, Any]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    if page_count < 1:
        raise HTTPException(status_code=400, detail="page_count must be at least 1.")
    if not external_url(source_url):
        raise HTTPException(status_code=400, detail="source_url must be an http or https URL.")

    destination_dir = publication_dir(normalized_slug)
    destination_dir.mkdir(parents=True, exist_ok=True)
    reset_directory(destination_dir / "pages")
    reset_directory(destination_dir / "thumbs")
    previous_pdf_path = destination_dir / "original.pdf"
    if previous_pdf_path.exists():
        previous_pdf_path.unlink()

    timestamp = now_iso()
    manifest = {
        "slug": normalized_slug,
        "title": title,
        "description": description or "",
        "status": "uploaded",
        "original_pdf_path": "",
        "page_count": page_count,
        "publication_date": publication_date or timestamp[:10],
        "upload_date": timestamp[:10],
        "version_notes": "External PDF with pre-rendered page assets.",
        "view_count": baseline_view_count(normalized_slug),
        "last_viewed_at": None,
        "source_url": source_url,
        "created_at": timestamp,
        "updated_at": timestamp,
        "processed_at": None,
        "toc_page_number": None,
        "flipbook_type": normalize_flipbook_type(flipbook_type),
        "links": [],
        "pages": [],
        "viewer_settings": {},
        "external_pdf": True,
    }
    manifest_file_path = write_manifest(normalized_slug, manifest)
    record_archive_event(
        action="uploaded",
        slug=normalized_slug,
        title=title,
        flipbook_type=str(manifest["flipbook_type"]),
        notes="External PDF manifest created for low-memory ingestion.",
    )
    return {
        "status": "uploaded",
        "slug": normalized_slug,
        "page_count": page_count,
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
    }


@app.post("/admin/api/publications/{slug}/remote-pages")
def admin_create_remote_page_publication(
    slug: str,
    request: Request,
    title: str = Form(...),
    description: str | None = Form(default=None),
    publication_date: str | None = Form(default=None),
    source_url: str = Form(...),
    flipbook_type: str | None = Form(default="ebook"),
    page_urls: str = Form(...),
    cover_url: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    if not external_url(source_url):
        raise HTTPException(status_code=400, detail="source_url must be an http or https URL.")
    try:
        parsed_page_urls = json.loads(page_urls)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="page_urls must be a JSON array.") from exc
    if not isinstance(parsed_page_urls, list) or not parsed_page_urls:
        raise HTTPException(status_code=400, detail="page_urls must be a non-empty JSON array.")

    pages = []
    for index, value in enumerate(parsed_page_urls, start=1):
        page_url = str(value or "").strip()
        if not (external_url(page_url) or page_url.startswith("/api/")):
            raise HTTPException(status_code=400, detail="Each page URL must be absolute or an internal /api/ URL.")
        pages.append({"page_number": index, "image_url": page_url, "thumb_url": page_url})

    cleaned_cover_url = str(cover_url or "").strip()
    if cleaned_cover_url and not (external_url(cleaned_cover_url) or cleaned_cover_url.startswith("/api/")):
        raise HTTPException(status_code=400, detail="cover_url must be absolute or an internal /api/ URL.")

    destination_dir = publication_dir(normalized_slug)
    destination_dir.mkdir(parents=True, exist_ok=True)
    previous_pdf_path = destination_dir / "original.pdf"
    if previous_pdf_path.exists():
        previous_pdf_path.unlink()

    timestamp = now_iso()
    manifest = {
        "slug": normalized_slug,
        "title": title,
        "description": description or "",
        "status": "processed",
        "original_pdf_path": "",
        "page_count": len(pages),
        "publication_date": publication_date or timestamp[:10],
        "upload_date": timestamp[:10],
        "version_notes": "Remote page assets; no local PDF stored.",
        "view_count": baseline_view_count(normalized_slug),
        "last_viewed_at": None,
        "source_url": source_url,
        "created_at": timestamp,
        "updated_at": timestamp,
        "processed_at": timestamp,
        "toc_page_number": None,
        "flipbook_type": normalize_flipbook_type(flipbook_type),
        "links": [],
        "pages": pages,
        "viewer_settings": {},
        "external_pdf": True,
    }
    if cleaned_cover_url:
        manifest["cover_url"] = cleaned_cover_url
    manifest_file_path = write_manifest(normalized_slug, manifest)
    record_archive_event(
        action="uploaded",
        slug=normalized_slug,
        title=title,
        flipbook_type=str(manifest["flipbook_type"]),
        notes="Remote page manifest created for low-disk ingestion.",
    )
    return {
        "status": "processed",
        "slug": normalized_slug,
        "page_count": len(pages),
        "manifest_url": f"/api/publications/{normalized_slug}/manifest",
        "manifest_path": str(manifest_file_path),
    }


@app.post("/admin/api/publications/{slug}/page-assets")
def admin_upload_publication_page_assets(
    slug: str,
    request: Request,
    page_number: int = Form(...),
    page: UploadFile = File(...),
    thumb: UploadFile = File(...),
) -> dict[str, Any]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    page_count = int(manifest.get("page_count") or 0)
    if page_number < 1 or page_number > page_count:
        raise HTTPException(status_code=400, detail="page_number is outside the publication page range.")

    filename = f"page-{page_number:03d}.jpg"
    destination_dir = publication_dir(normalized_slug)
    pages_dir = destination_dir / "pages"
    thumbs_dir = destination_dir / "thumbs"
    pages_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    for upload, target_dir, label in ((page, pages_dir, "page"), (thumb, thumbs_dir, "thumb")):
        if not (upload.content_type or "").lower().startswith("image/jpeg"):
            raise HTTPException(status_code=400, detail=f"{label} must be a JPEG image.")
        try:
            with (target_dir / filename).open("wb") as output_file:
                shutil.copyfileobj(upload.file, output_file)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"{label} image could not be stored: {exc}") from exc

    manifest["pages"] = merge_page_assets(manifest.get("pages") or [], [page_asset(page_number, normalized_slug)])
    manifest["status"] = "processed" if len(manifest["pages"]) >= page_count else "processing"
    if manifest["status"] == "processed":
        manifest["processed_at"] = now_iso()
    manifest["updated_at"] = now_iso()
    manifest["pages_path"] = str(pages_dir)
    manifest["thumbs_path"] = str(thumbs_dir)
    write_manifest(normalized_slug, manifest)
    return {
        "status": manifest["status"],
        "slug": normalized_slug,
        "page_number": page_number,
        "rendered_total": len(manifest["pages"]),
        "page_count": page_count,
    }


@app.post("/admin/api/publications/{slug}/cover")
def admin_upload_publication_cover(
    slug: str,
    request: Request,
    cover: UploadFile = File(...),
) -> dict[str, str]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    if not (cover.content_type or "").lower().startswith("image/jpeg"):
        raise HTTPException(status_code=400, detail="Cover must be a JPEG image.")

    covers_dir = publication_dir(normalized_slug) / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    cover_path = covers_dir / "cover.jpg"
    try:
        with cover_path.open("wb") as output_file:
            shutil.copyfileobj(cover.file, output_file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cover image could not be stored: {exc}") from exc

    manifest["cover_url"] = cover_asset_url(normalized_slug)
    manifest["updated_at"] = now_iso()
    write_manifest(normalized_slug, manifest)
    return {"status": "updated", "slug": normalized_slug, "cover_url": manifest["cover_url"]}


@app.post("/admin/api/publications/{slug}/type")
def admin_update_publication_type(
    slug: str,
    request: Request,
    flipbook_type: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)
    manifest["flipbook_type"] = normalize_flipbook_type(flipbook_type)
    manifest["updated_at"] = now_iso()
    write_manifest(normalized_slug, manifest)
    record_archive_event(
        action="updated",
        slug=normalized_slug,
        title=str(manifest.get("title") or normalized_slug.replace("-", " ").title()),
        flipbook_type=str(manifest.get("flipbook_type") or "magazine"),
        notes="Flipbook type changed.",
    )
    return {
        "status": "updated",
        "slug": normalized_slug,
        "flipbook_type": manifest["flipbook_type"],
        "flipbook_type_label": flipbook_type_label(manifest["flipbook_type"]),
    }


@app.post("/admin/api/publications/{slug}/metadata")
def admin_update_publication_metadata(
    slug: str,
    request: Request,
    summary_blurb: str | None = Form(default=None),
    interactive_url: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    publication_date: str | None = Form(default=None),
    registration_required: str | None = Form(default=None),
    registration_portal_id: str | None = Form(default=None),
    registration_form_id: str | None = Form(default=None),
    registration_label_value: str | None = Form(default=None),
    registration_campaign: str | None = Form(default=None),
) -> dict[str, Any]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    manifest = read_manifest(normalized_slug)

    if summary_blurb is not None:
        if len(summary_blurb) > 2400:
            raise HTTPException(status_code=400, detail="Summary must be 2400 characters or fewer.")
        manifest["summary_blurb"] = summary_blurb.strip()

    if interactive_url is not None:
        cleaned_interactive_url = external_url(interactive_url)
        if interactive_url.strip() and not cleaned_interactive_url:
            raise HTTPException(status_code=400, detail="Interactive URL must start with http:// or https://.")
        manifest["interactive_url"] = cleaned_interactive_url

    if source_url is not None:
        cleaned_source_url = external_url(source_url)
        if source_url.strip() and not cleaned_source_url:
            raise HTTPException(status_code=400, detail="Source URL must start with http:// or https://.")
        manifest["source_url"] = cleaned_source_url

    if publication_date is not None:
        cleaned_publication_date = publication_date.strip()
        if cleaned_publication_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned_publication_date):
            raise HTTPException(status_code=400, detail="Publication date must use YYYY-MM-DD format.")
        manifest["publication_date"] = cleaned_publication_date

    if registration_portal_id is not None:
        manifest["registration_portal_id"] = registration_portal_id.strip() or HUBSPOT_PORTAL_ID

    if registration_form_id is not None:
        manifest["registration_form_id"] = registration_form_id.strip()

    if registration_label_value is not None:
        manifest["registration_label"] = registration_label_value.strip()

    if registration_campaign is not None:
        manifest["registration_campaign"] = normalize_registration_campaign(registration_campaign)

    if registration_required is not None:
        manifest["registration_required"] = form_truthy(registration_required)

    validate_registration_settings(bool(manifest.get("registration_required")),
        str(manifest.get("registration_portal_id") or HUBSPOT_PORTAL_ID),
        str(manifest.get("registration_form_id") or ""))

    manifest["updated_at"] = now_iso()
    write_manifest(normalized_slug, manifest)
    record_archive_event(
        action="updated",
        slug=normalized_slug,
        title=str(manifest.get("title") or normalized_slug.replace("-", " ").title()),
        flipbook_type=str(manifest.get("flipbook_type") or "magazine"),
        notes="Metadata changed.",
    )
    return {
        "status": "updated",
        "slug": normalized_slug,
        "interactive_url": manifest.get("interactive_url") or "",
        "source_url": manifest.get("source_url") or "",
        "publication_date": manifest.get("publication_date") or "",
        "registration_required": registration_enabled(manifest),
        "registration_portal_id": manifest.get("registration_portal_id") or HUBSPOT_PORTAL_ID,
        "registration_form_id": manifest.get("registration_form_id") or "",
        "registration_label": manifest.get("registration_label") or "",
        "registration_campaign": manifest.get("registration_campaign") or "",
    }


@app.post("/admin/api/publications/{slug}/delete")
def admin_delete_publication(
    slug: str,
    request: Request,
) -> dict[str, str]:
    require_admin_request(request)
    normalized_slug = validate_slug(slug)
    target_dir = publication_dir(normalized_slug)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="Publication not found.")
    manifest = read_manifest(normalized_slug)
    record_archive_event(
        action="deleted",
        slug=normalized_slug,
        title=str(manifest.get("title") or normalized_slug.replace("-", " ").title()),
        flipbook_type=str(manifest.get("flipbook_type") or "magazine"),
    )
    shutil.rmtree(target_dir)
    return {"status": "deleted", "slug": normalized_slug}


@app.post("/admin/api/publications/{slug}/process-batch")
def admin_process_publication_pdf_batch(
    slug: str,
    request: Request,
    start_page: int = Query(default=1, ge=1),
    limit: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    require_admin_request(request)
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
    if manual_toc_page_number(normalized_slug):
        pdf_links.extend(get_manual_toc_page_links(normalized_slug, rendered_assets["page_count"], pdf_links))
    else:
        pdf_links.extend(extract_toc_page_links(pdf_path, rendered_assets["page_count"], pdf_links))
    manifest.update(rendered_assets)
    manifest["links"] = pdf_links
    manifest["toc_page_number"] = manual_toc_page_number(normalized_slug) or find_toc_page_number(pdf_path) or detect_toc_page_number(pdf_links)
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
