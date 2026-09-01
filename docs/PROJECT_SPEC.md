# GBM Flipbook — Project Specification

## Objective

Create a Green Builder Media-owned online flipbook creator and hosting service that integrates cleanly with HubSpot while using GitHub for source control and Render for application hosting and initial persistent publication storage.

## Product principles

1. **PDF-first:** The MVP accepts completed PDFs rather than attempting to replace InDesign or other page-layout software.
2. **One reusable viewer:** Publications are data/assets loaded into a common viewer, not separate application deployments.
3. **HubSpot-compatible, not HubSpot-dependent:** Publications must work at their own public URLs and also embed cleanly in HubSpot.
4. **Replaceable storage:** Start with a Render persistent disk, but isolate storage operations so object storage can replace it later.
5. **Editorial simplicity:** A nontechnical editor should be able to upload, preview, publish, copy an embed, and view analytics.
6. **Progressive development:** Build a reliable MVP before hotspots, video, advanced lead gating, or sophisticated CRM tracking.

## User flow

### Create publication

`Create Flipbook → Upload PDF → Metadata → Process → Preview → Publish → Embed`

Required metadata:
- Title
- Slug
- Description

Useful optional metadata:
- Cover/thumbnail override
- SEO title/description
- Publication date
- Download enabled/disabled
- Branding/theme
- Table of contents

## Processing pipeline

1. Validate uploaded PDF.
2. Save original PDF through storage service.
3. Determine page count and document metadata.
4. Render each page to an optimized web image.
5. Generate thumbnails.
6. Select/generate cover image.
7. Write publication manifest/metadata.
8. Save database record.
9. Mark processing status complete or failed.
10. Allow preview and publication.

Processing should be resilient to large PDFs. Avoid tying long PDF rendering jobs directly to a browser request if processing time becomes significant; design so a background worker/queue can be added.

## Viewer

The public viewer should accept a publication slug/id and retrieve the corresponding metadata/assets.

MVP controls:
- Previous/next
- Current page/page count
- Thumbnail navigation
- Zoom
- Fullscreen
- Share
- Optional PDF download

Responsive behavior:
- Desktop: two-page spread where appropriate
- Mobile: single page
- Touch/swipe navigation
- Keyboard navigation on desktop

Accessibility should include semantic controls, keyboard operation, labels, sufficient contrast, and sensible focus behavior.

## Public routes

Suggested routes:

- `/` — optional product/home page
- `/admin` — publication management
- `/admin/publications/new` — upload/create
- `/admin/publications/:id` — edit/manage
- `/book/:slug` — public viewer
- `/api/publications` — publication API
- `/api/publications/:id` — metadata/manage
- `/api/publications/:id/upload` — PDF upload
- `/api/publications/:id/publish` — publish action
- `/api/publications/:id/analytics` — analytics

Exact API design can be refined.

## HubSpot

### MVP

Every published flipbook exposes a stable URL suitable for an iframe. Admin should provide a Copy Embed button.

Example concept:

```html
<iframe
  src="https://flip.greenbuildermedia.com/book/example-slug"
  width="100%"
  height="850"
  loading="lazy"
  allowfullscreen>
</iframe>
```

### HubSpot module

After MVP, create a HubSpot module/component that lets editors configure the publication and viewer without manually editing HTML.

### Forms and CRM

Future optional lead gate can display a HubSpot form before opening the publication or after a configured page. Prefer HubSpot as the system of record for contact data.

## Storage

Initial implementation uses a Render persistent disk.

Create a storage interface instead of accessing filesystem paths throughout business logic. Candidate operations:

- save upload
- save generated page
- save thumbnail
- read/stream asset
- delete publication assets
- return asset path/URL

Future storage implementations may include Cloudflare R2 or S3-compatible storage.

## Data model

### Publication

Suggested fields:
- id
- title
- slug (unique)
- description
- status: draft/processing/published/error
- original_pdf_path
- cover_path
- page_count
- allow_download
- viewer_settings JSON
- seo_settings JSON
- created_at
- updated_at
- published_at

### Page

A separate page table is optional for MVP if predictable file naming and manifest data are sufficient. It becomes useful for page titles, hotspots, analytics metadata, and richer content.

### Analytics event

Suggested fields:
- id
- publication_id
- session_id
- event_type
- page_number nullable
- referrer nullable
- metadata JSON
- created_at

Avoid collecting unnecessary personally identifiable information.

## Render deployment

The application should be deployable from this GitHub repository. The initial production architecture may use:

- Render web service
- Render PostgreSQL
- Render persistent disk mounted at a configurable path such as `/data/flipbooks`

All environment-specific values should use environment variables rather than hard-coded credentials or URLs.

Suggested environment variables include:

- `DATABASE_URL`
- `FLIPBOOK_STORAGE_PATH`
- `PUBLIC_BASE_URL`
- HubSpot credentials only when integration work begins

Never commit secrets.

## Recommended implementation order

1. Establish frontend/backend skeleton.
2. Add health endpoint and local development instructions.
3. Implement storage abstraction.
4. Implement PDF upload.
5. Implement PDF rendering and thumbnail generation.
6. Implement publication metadata/database.
7. Build public viewer.
8. Build admin library.
9. Add publish/unpublish workflow.
10. Generate iframe embed.
11. Deploy to Render with persistent disk.
12. Test using a real GBM PDF on desktop/mobile and inside HubSpot.
13. Add basic analytics.
14. Begin custom HubSpot module.

## Definition of MVP success

An editor can upload a finished GBM PDF, wait for processing, preview it, publish it, obtain a permanent web URL and HubSpot embed code, embed the publication on a HubSpot page, and read it successfully on desktop and mobile without manually processing page images or deploying new code for each publication.
