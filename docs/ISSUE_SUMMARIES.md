# Magazine issue summaries

The archive shows a summary beneath the featured magazine cover and a SUMMARY
button for each older issue. The button opens an accessible text-only dialog.

Initial editorial summaries live in `data/magazine_summaries.json`. They were
drafted from the corresponding PDFs' contents pages and covers. Q4 2026 uses
Matt's supplied paragraph verbatim, including both existing Q4 archive entries.
Manifest `summary_blurb` overrides the catalog, including an intentionally empty
value. Admin edits are stored on the persistent publication disk; replacing a
PDF preserves its summary. No PDF assets need to be regenerated.

For future new magazine issues, draft a 60-word summary from the actual issue in
a casual, conversational editorial voice. Save it using Issue summary during
upload or Issue Summary after selecting the magazine. Do not draft a new summary
just because an existing issue's PDF is replaced. The supplied Q4 paragraph is
an explicit exception to the 60-word target.


## Automatic drafting
New magazine uploads with a blank Issue summary receive an automatic 60-word
summary after page processing completes. The admin browser calls the authenticated
drafting endpoint. Keep the tab open until upload and drafting finish. A failed
AI request leaves the uploaded PDF intact; select the issue and use Draft Missing
Summary to retry. Existing summaries and PDF replacements are never redrafted.
Manual summary entry takes priority. Ebooks do not use automatic drafting.

Set OPENAI_API_KEY in the Render service environment (never in the repository).
FLIPBOOK_SUMMARY_MODEL optionally overrides the default gpt-4.1-mini model.
Only bounded PDF text excerpts are sent to OpenAI, with response storage disabled.
Generation is serialized and checks for exactly 60 whitespace-separated words,
with at most three attempts. Image-only PDFs need a manually entered summary.
