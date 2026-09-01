# GBM Flipbook

GBM Flipbook is a Green Builder Media project for creating, hosting, embedding, and analyzing online flipbook publications.

## Project goal

Build a GitHub + Render flipbook platform that accepts PDF publications, converts them into a responsive web flipbook, stores publication assets on a Render persistent disk, and makes each publication easy to embed and use within HubSpot.

## Core architecture

- **GitHub:** source of truth for application code and deployment configuration.
- **Render:** hosts the frontend, backend/API, PDF processing, and public flipbook viewer.
- **Render persistent disk:** stores uploaded PDFs, generated page images, thumbnails, manifests, and other publication assets for the initial implementation.
- **PostgreSQL:** stores publication metadata, configuration, analytics, and integration data.
- **HubSpot:** public-facing CMS/marketing layer. Flipbooks can initially be embedded through an iframe/custom module, with deeper API integration added later.

## MVP workflow

1. User signs into an internal Flipbook Studio/admin portal.
2. User uploads a PDF.
3. User enters title, description, slug, and publication settings.
4. Backend stores the original PDF on persistent storage.
5. PDF processor renders pages into optimized WebP/JPEG page images and thumbnails.
6. System creates publication metadata/manifest.
7. User previews the flipbook.
8. User publishes it.
9. System creates a permanent public URL such as `/book/green-building-outlook-2026`.
10. System provides HubSpot-compatible embed code.

## MVP viewer features

- Responsive desktop/mobile reader
- Two-page desktop spread
- Single-page mobile mode
- Page-turn navigation/animation
- Thumbnail navigation
- Zoom
- Full screen
- Direct page linking
- Optional PDF download
- Share link
- Custom branding/logo/colors
- Optional table of contents

## Admin interface

The initial admin should provide a publication library with:

- Create Flipbook
- Upload PDF
- Draft / Published status
- Edit
- Preview
- Publish / Unpublish
- View public version
- Copy embed code
- Analytics
- Delete

## Storage layout

Example initial Render disk layout:

```
/data/flipbooks/
  green-building-outlook-2026/
    original.pdf
    manifest.json
    pages/
      page-001.webp
      page-002.webp
    thumbs/
      page-001.webp
      page-002.webp
```

Do not scatter hard-coded `/data` paths throughout the application. Create a storage abstraction such as `storage.save_file()`, `storage.get_file()`, and `storage.delete_file()` so assets can later migrate to S3, Cloudflare R2, or another object store without rewriting the application.

## Suggested application structure

```
GBM_Flipbook/
  backend/
    main.py
    pdf_processor.py
    storage.py
    analytics.py
    hubspot.py
  frontend/
    src/
      Admin.jsx
      FlipbookViewer.jsx
      Upload.jsx
      Analytics.jsx
  hubspot/
    flipbook-module/
  docs/
    PROJECT_SPEC.md
  requirements.txt
  package.json
  render.yaml
```

The exact structure may be refined during implementation.

## Database model

Initial `publications` fields should include:

- id
- title
- slug
- description
- pdf_path
- cover_path
- page_count
- status
- created_at
- published_at
- hubspot_url
- allow_download
- viewer_settings

Initial analytics should support publication views, unique readers/sessions, pages viewed, page-level engagement, reading time, referrer, and outbound/link clicks where practical.

## HubSpot integration roadmap

### Phase 1 — embed

Generate a standard iframe embed for each publication. HubSpot editors can place it in a custom HTML/module area.

### Phase 2 — custom HubSpot module

Create a reusable HubSpot Flipbook module with fields for publication URL/selection, height, background, download visibility, fullscreen controls, and related viewer options.

### Phase 3 — deeper HubSpot integration

Add authenticated HubSpot API integration so the admin can eventually publish or update HubSpot landing/pages and populate the flipbook component automatically.

### Lead capture

Support HubSpot forms as optional reading gates, for example immediately, after page 3, or after page 10. Contact/CRM data should remain in HubSpot rather than creating a competing CRM inside GBM Flipbook.

## Analytics direction

The platform should eventually report:

- Total views
- Unique readers
- Average pages viewed
- Average reading time
- Most-read pages
- Drop-off by page
- Link/ad clicks
- Publication/referrer performance

Longer term, where HubSpot permissions and tracking permit, connect publication engagement to HubSpot contacts and marketing activity.

## Development phases

### Phase 1 — working MVP

- PDF upload
- Persistent storage
- PDF-to-page conversion
- Flipbook viewer
- Permanent publication URL
- HubSpot iframe embed

### Phase 2 — publishing platform

- Admin publication library
- Branding controls
- Thumbnails/navigation
- SEO metadata
- Download controls
- Basic analytics

### Phase 3 — HubSpot integration

- HubSpot custom module
- HubSpot forms/lead gates
- Contact/event tracking where appropriate
- HubSpot publishing/API integration

### Phase 4 — advanced publishing

Potential additions:

- Clickable hotspots
- Video embeds
- Rich links
- Advertisements
- Sponsor analytics
- Search
- Advanced lead gates
- Publication summaries
- Enhanced engagement analytics

## Codex implementation guidance

Start with Phase 1. Do not attempt to build a full Issuu/Flipsnack replacement in the first iteration. Prioritize a reliable PDF-upload-to-published-flipbook pipeline.

Keep the viewer reusable and independent from individual publications: one viewer application should load any publication by slug/manifest rather than creating a separate deployment for each flipbook.

Keep storage behind an abstraction so the initial Render persistent disk can later be replaced by object storage.

Keep HubSpot loosely coupled to the core viewer. A flipbook must work at its direct Render/custom-domain URL even if HubSpot is unavailable.

## Deployment target

Initial target:

- GitHub repository: `mattpower-ux/GBM_Flipbook`
- Render web service for application/API
- Render persistent disk mounted for publication assets
- PostgreSQL for metadata/analytics
- HubSpot for embeds and marketing pages

A future custom domain such as `flip.greenbuildermedia.com` can point to the Render-hosted viewer.
