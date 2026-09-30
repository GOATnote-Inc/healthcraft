"""Self-contained, escaped review surface for synthetic reconciliation evidence."""

from __future__ import annotations

import re
from html import escape


def render_report(bundle: dict) -> str:
    """Render every scheduled trial, including missing or invalid evidence."""
    roster = bundle["roster"]
    by_id: dict[str, list[dict]] = {}
    for trial in bundle["trials"]:
        by_id.setdefault(trial["id"], []).append(trial)

    def badge(value) -> str:
        if value is True:
            return '<span class="yes">Verified</span>'
        if value is False:
            return '<span class="no">Not satisfied</span>'
        return '<span class="unknown">Unassessed</span>'

    rows, details = [], []
    source_banner = ""
    if bundle.get("sources_unchanged") is False:
        message = (
            "Source identity capture failed"
            if bundle.get("source_identity_error")
            else "Source identity changed"
        )
        source_banner = (
            f'<aside role="alert"><strong>{message}</strong><p>'
            "This bundle cannot establish stable execution sources. Individual source/note "
            "checks below do not establish a reproducible run.</p></aside>"
        )
    for planned in roster:
        trial_id = planned["id"]
        matches = by_id.get(trial_id, [])
        trial = matches[0] if len(matches) == 1 else {}
        verification = trial.get("verification") or {}
        checks = verification.get("checks", {})
        status = trial.get(
            "status", "Missing evidence" if not matches else "Duplicate trial evidence"
        )
        upstream = trial.get("upstream", {})
        upstream_text = upstream.get("status", "Unassessed")
        if upstream.get("upstream_reward") is not None:
            upstream_text += f" · reward {upstream['upstream_reward']}"
        cells = "".join(
            f"<td>{badge(checks.get(key))}</td>"
            for key in (
                "provenance",
                "source_fidelity",
                "persisted_action",
                "readback",
                "execution_complete",
            )
        )
        rows.append(
            f'<tr><th scope="row">{escape(trial_id)}'
            f"<small>{escape(planned['description'])}</small></th>"
            f"{cells}<td>{escape(status)}</td><td>{escape(upstream_text)}</td></tr>"
        )
        messages = verification.get("errors", {})
        links = ""
        if verification and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", trial_id):
            links = (
                f'<p><a href="{trial_id}/evidence.json">Raw execution evidence</a> · '
                f'<a href="{trial_id}/verification.json">Independent source checks</a></p>'
            )
        details.append(
            f"<details><summary>{escape(trial_id)} — verifier details</summary>"
            f"<pre>{escape(str(messages))}</pre>{links}</details>"
        )
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synthetic reconciliation · evidence review</title>
<style>
:root{{color-scheme:light;--ink:#132e3d;--muted:#526672;--line:#d5e1e4}}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f5;color:var(--ink);
font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:48px 28px}}header{{max-width:880px;margin-bottom:32px}}
.eyebrow{{font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:#326d67;font-weight:750}}
h1{{font-size:clamp(30px,4vw,48px);line-height:1.13;letter-spacing:-.035em;margin:12px 0 20px}}
p{{color:var(--muted)}}.facts{{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}}
.facts span{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 16px}}
.table-wrap{{overflow:auto;background:white;border:1px solid var(--line);border-radius:12px}}
table{{width:100%;border-collapse:collapse;text-align:left;font-size:13px}}
caption{{text-align:left;padding:20px;font-size:18px;font-weight:700}}
th,td{{padding:16px 12px;border-top:1px solid var(--line);vertical-align:top}}
thead th{{background:#edf3f2;white-space:nowrap}}tbody th{{min-width:220px;max-width:300px}}
small{{display:block;font-weight:400;color:var(--muted);margin-top:5px}}
.yes{{color:#11624e}}.no{{color:#974922}}.unknown{{color:#647580}}.yes,.no,.unknown{{font-weight:650}}
aside{{border-left:3px solid #397b72;padding:0 20px;margin:30px 0;max-width:940px}}
details{{background:white;border:1px solid var(--line);border-radius:8px;
padding:14px 18px;margin:8px 0}}
summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}
footer{{color:var(--muted);font-size:13px;margin-top:30px}}
</style><main><header><div class="eyebrow">HealthCraft / original synthetic workflow</div>
<h1>Can every documented fact be traced to its source—and its note to a real write?</h1>
<p>Inspect source fidelity, note persistence and completion separately. These software controls
exercise eight synthetic records across two same-name patients and three encounters.</p></header>
<div class="facts"><span>{len(roster)} scheduled</span>
<span>{len(bundle["trials"])} evidence entries</span>
<span>0 model calls</span><span>0 clinical criteria</span><span>No benchmark score</span></div>
{source_banner}<div class="table-wrap"><table><caption>Declared development controls</caption>
<thead><tr>
<th scope="col">Execution</th><th scope="col">Evidence binding</th>
<th scope="col">Source fidelity</th>
<th scope="col">Correct note persisted</th><th scope="col">Readback</th>
<th scope="col">Completion</th>
<th scope="col">Run status</th><th scope="col">Secondary CSV verifier</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<aside><p>The Microsoft verifier reports cluster retrieval with its original thresholds.
It cannot establish that a note is accurate or persisted. A positive CSV reward with failed note
checks is an expected distinction between these contracts.</p>
<p>This is an engineering development artifact, not a formal red team, model comparison, clinical
validation or evidence of healthcare superiority. No real-patient data are used.</p></aside>
{"".join(details)}<footer>Raw calls, audits, store snapshots and checks are retained per trial.
The manifest records file hashes; hashes are not execution attestations.
Visual browser QA is not recorded.</footer>
</main></html>"""
