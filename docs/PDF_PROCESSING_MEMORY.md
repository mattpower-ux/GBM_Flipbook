# PDF processing memory regression (2026-11-12)

## Fix

PDF page counting, link refresh and rasterization run in a short-lived Python child. A process-local reentrant guard reserves the PDF slot before upload or processing mutations; a busy request returns 409 without changing existing publication files. Uploads are staged and validated before promotion. Each rendered page releases the MuPDF resource store. Worker timeout/death returns retryable 503; ordinary malformed link metadata remains a best-effort 422 fallback during batch rendering. Null and indirect annotation containers are validated before iteration.

Keep the deployed single-uvicorn-process configuration. Multiple web workers would require a shared queue/lock; this change does not add a paid worker service or change Render settings. Selected-page exports and summary generation are outside this change's isolation scope.

## Reproduction and results

- Baseline: commit 4c01d2c6f3f7e1f4677766a193da488a459019d4.
- Read-only copy of current public Q4 PDF: 68 pages, 67,075,113 bytes.
- PDF SHA256: b7f7661678e38d39226922989777d445ddcecd3f611f43a092bff49f5023ea4f.
- Windows, Python 3.14.6, PyMuPDF 1.28.2, pypdf 6.1.1. Dependencies from requirements.txt; httpx and psutil are test-only dependencies.
- Sequential five-page batches using process_publication_batch; disposable temporary publication storage, never the production disk.
- Peak sampled RSS sums the benchmark application's process and all children every 25 ms. The monitoring process is excluded. Windows RSS is not a Linux cgroup limit or a guarantee about Render's exact peak.
- Baseline: 512.15 MiB peak, 12.64 seconds for 68 pages. An earlier baseline run peaked 518.58 MiB.
- Fixed final code: 264.34 MiB peak across TWO consecutive 68-page runs, 53.17 seconds total. Parent RSS after batches stayed between 76.64 and 77.86 MiB.
- Each run produced all 68 page JPEGs, all 68 thumbnails, and cover. Aggregate path-plus-image-byte SHA256 matched baseline exactly: d74ef1e4dd802e59f93e0c3890c659057c7b3723b2f97e1ffd3de2bd58b2eecf.
- Both baseline and fixed current-Q4 runs extracted 252 links and TOC page 12. The earlier NullObject failure is covered separately by synthetic direct/indirect-null PDFs, not reproduced by this current source copy.

## Checks

31 Python unit/regression tests passed, including real subprocess rendering, direct/indirect null annotations, valid link preservation, busy rejection before mutations, invalid replacement preservation, malformed-link fallback, worker timeout/crash and retry cleanup. All three JavaScript checks passed (viewer script syntax/registration callback, double-click zoom, reading scroll). Python compileall and git diff --check passed.

To repeat locally, install requirements.txt plus httpx and psutil in a virtual environment, then run from the repository root:

    python -m unittest discover -s tests -p 'test_*.py' -v
    python tests/benchmark_pdf_processing.py --repo . --pdf /path/to/copied.pdf --label fixed --repeat 2

Benchmark logs/JSON are written under ignored .benchmark/. Use a baseline checkout with --repo for comparison. The benchmark processes only local copies, and writes all publication assets into a disposable temporary directory.

## Deployment verification

Deploy only after code review. Verify the deployed commit, health endpoint, archive/viewer and representative existing assets without uploading, reprocessing, or changing published Q4 content. Review memory on the next authorized real upload. Extra RAM may still be needed for larger individual pages or overlapping workloads outside this fix; the benchmark demonstrates substantially reduced retained memory for this issue, not a universal ceiling.
