"""Editorial summaries, independent of replaceable PDF assets."""
import html
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / 'data' / 'magazine_summaries.json'
CATALOG = json.loads(CATALOG_PATH.read_text(encoding='utf-8')) if CATALOG_PATH.exists() else {}


def issue_blurb(manifest):
    if 'summary_blurb' in manifest:
        return str(manifest['summary_blurb'] or '')
    return CATALOG.get(str(manifest.get('slug') or ''), '')


def summary_button(publication):
    summary = issue_blurb(publication)
    if not summary:
        return ''
    return '<button class="summary-link" type="button" data-summary="{}" data-title="{}" aria-haspopup="dialog">SUMMARY</button>'.format(
        html.escape(summary, quote=True), html.escape(publication.get('title', 'Issue summary'), quote=True))


def summary_styles():
    return '''
.featured-heading{grid-column:2;grid-row:1}.featured-visual{grid-column:1;grid-row:2;min-width:0}.featured-copy{grid-column:2;grid-row:2}
.issue-blurb{margin:32px 0 0;font-size:17px;line-height:1.6;color:var(--muted)}
.summary-link{display:block;margin:12px auto 0;padding:6px 10px;border:0;background:transparent;color:#087f59;font:700 13px Arial,sans-serif;text-decoration:underline;text-underline-offset:3px;cursor:pointer}
.summary-link:focus-visible,.summary-close:focus-visible{outline:2px solid #087f59;outline-offset:3px}
.summary-dialog{position:fixed;inset:0;margin:auto;width:min(520px,calc(100% - 32px));max-height:80vh;padding:44px 28px 28px;border:1px solid #dde5ea;border-radius:8px;background:#fff;color:#303052;box-shadow:0 16px 60px #0003}
.summary-dialog::backdrop{background:#0006}.summary-dialog p{margin:0;font:17px/1.65 Arial,sans-serif;white-space:pre-wrap}
.summary-close{position:absolute;right:10px;top:8px;width:32px;height:32px;background:#fff;border:0;color:#303052;font:22px Arial,sans-serif;cursor:pointer}
@media(max-width:800px){.featured-heading,.featured-visual,.featured-copy{grid-column:1;grid-row:auto}.featured{gap:22px}.featured-visual{max-width:420px}.issue-blurb{margin-top:24px}}
'''


def summary_dialog_markup():
    return '''<dialog class="summary-dialog" id="issueSummary" aria-label="Issue summary"><button class="summary-close" type="button" aria-label="Close summary">X</button><p id="issueSummaryText"></p></dialog>
<script>(()=>{const dialog=document.getElementById('issueSummary');let opener;
document.querySelectorAll('.summary-link').forEach(button=>button.addEventListener('click',()=>{opener=button;dialog.setAttribute('aria-label',button.dataset.title+' summary');document.getElementById('issueSummaryText').textContent=button.dataset.summary;dialog.showModal()}));
dialog.querySelector('.summary-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close()}});
dialog.addEventListener('close',()=>opener?.focus());})();</script>'''
