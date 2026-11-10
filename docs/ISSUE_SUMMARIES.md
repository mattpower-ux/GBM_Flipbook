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

The admin fields store editorial copy; this release does not call an AI service
or automatically generate copy during an unattended upload.
