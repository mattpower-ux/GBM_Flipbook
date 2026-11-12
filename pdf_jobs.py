"""Short-lived PDF workers: bound native-memory lifetime without a paid worker service."""
import json
from functools import wraps
import logging
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import HTTPException

# The deployed service uses one uvicorn process. Never run multiple PDF children in it.
# Multiple web processes would need a shared queue/lock instead of this process-local guard.
_pdf_job_lock = threading.RLock()
PDF_JOB_TIMEOUT_SECONDS = 180
_WORKER = Path(__file__).resolve()
_LOG = logging.getLogger(__name__)


def pdf_job_guard(function):
    """Reserve the PDF slot before any upload/processing side effects."""
    @wraps(function)
    def guarded(*args, **kwargs):
        if not _pdf_job_lock.acquire(blocking=False):
            raise HTTPException(409, "Another PDF job is running. Please retry shortly.")
        try:
            return function(*args, **kwargs)
        finally:
            _pdf_job_lock.release()
    return guarded


def run_pdf_job(operation, payload):
    if operation not in {"render", "links", "page_count"}:
        raise ValueError("Unsupported PDF job")
    if not _pdf_job_lock.acquire(blocking=False):
        raise HTTPException(409, "Another PDF job is running. Please retry shortly.")
    try:
        with tempfile.TemporaryDirectory(prefix="flipbook-pdf-job-") as directory:
            root = Path(directory)
            request_path, result_path = root / "request.json", root / "result.json"
            request_path.write_text(json.dumps({"operation": operation, "payload": payload}), encoding="utf-8")
            try:
                # No shell and no captured binary output. Native PDF allocations die with this child.
                result = subprocess.run(
                    [sys.executable, str(_WORKER), str(request_path), str(result_path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=PDF_JOB_TIMEOUT_SECONDS, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                # subprocess.run kills and waits for the child before raising.
                raise HTTPException(503, "PDF processing timed out. Retry with a smaller batch.") from exc
            except OSError as exc:
                raise HTTPException(503, "PDF processing worker could not start.") from exc
            if result.returncode != 0:
                _LOG.error("PDF worker failed: operation=%s exit_code=%s", operation, result.returncode)
                raise HTTPException(503, "PDF processing worker stopped. Retry with a smaller batch.")
            try:
                response = json.loads(result_path.read_text(encoding="utf-8"))
                if response["ok"]:
                    return response["result"]
                status, detail = response["status"], response["detail"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise HTTPException(503, "PDF processing worker returned an invalid result.") from exc
            raise HTTPException(status, detail)
    finally:
        _pdf_job_lock.release()


def _worker(request_path, result_path):
    import main

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    operation, payload = request["operation"], request["payload"]
    try:
        if operation == "render":
            main.active_storage_path = Path(payload["storage_path"])
            result = main._render_pdf_page_range(payload["slug"], Path(payload["pdf_path"]),
                                                 payload["start_page"], payload["limit"])
        elif operation == "links":
            result = main._refresh_embedded_links(payload["slug"], payload["manifest"])
        elif operation == "page_count":
            result = main._get_pdf_page_count(Path(payload["pdf_path"]))
        else:
            raise ValueError("Unsupported PDF job")
        response = {"ok": True, "result": result}
    except HTTPException as exc:
        response = {"ok": False, "status": exc.status_code, "detail": exc.detail}
    except MemoryError:
        raise
    except Exception:
        if operation != "links":
            raise
        # Malformed link metadata should not prevent otherwise renderable pages.
        # Keep this distinct from worker death/timeout (503), which must be retried.
        response = {"ok": False, "status": 422, "detail": "PDF links could not be extracted."}
    Path(result_path).write_text(json.dumps(response), encoding="utf-8")


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])
