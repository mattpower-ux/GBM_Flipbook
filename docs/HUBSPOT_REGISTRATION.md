# HubSpot Registration

The public archives can be embedded with:

```html
<iframe src="https://gbm-flipbook.onrender.com/embed/archive" title="Green Builder Magazines" width="100%" height="1000" style="border:0" allow="fullscreen" allowfullscreen></iframe>
<iframe src="https://gbm-flipbook.onrender.com/embed/ebooks" title="Green Builder Ebooks" width="100%" height="1000" style="border:0" allow="fullscreen" allowfullscreen></iframe>
```

Admin: https://gbm-flipbook.onrender.com/admin

Select a publication, check Require HubSpot registration, select a saved form or
enter its HubSpot portal and form IDs, then Save Registration Settings. Uploads
offer the same settings. Replacing a PDF retains its settings.

Manage Forms and Manage Campaigns open HubSpot in a new tab. Create the form and
associate it with the actual campaign there. The campaign name in this portal is
a reference label, not a HubSpot campaign assignment or live campaign sync.
Reusing an existing form retains its existing HubSpot association and workflows.

The viewer embeds the legacy HubSpot form. Successful submission displays an
inline thank-you screen with that publication's Download PDF and Read Flipbook
actions. No new email workflow is added. Existing HubSpot automation remains
unchanged. Access is remembered for the current browser-tab session where
session storage is available. Browser privacy controls may limit embedded forms.

This is a marketing lead-capture gate, not protected document storage: direct
PDF and asset URLs remain public. Do not use it to protect confidential files.

Verification: Python registration tests cover settings persistence, validation,
viewer rendering and embedded download routing. The Node callback test requires
the isolated preview on localhost:8768; it verifies the thank-you actions without
submitting synthetic contacts to HubSpot. A real submission should be confirmed
in HubSpot using an authorized test contact before a marketing launch.
