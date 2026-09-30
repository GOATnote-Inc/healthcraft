"""Offline review of saved evidence, without regrading or modifying source files."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from healthcraft.llm.checkpoint import (
    load_latest_summary,
    selected_trajectory_paths,
    trajectory_attempt,
)

_ROOT = Path(__file__).resolve().parents[2]
_STATUSES = (
    "recorded_pass",
    "rubric_fail",
    "incomplete",
    "error",
    "invalid",
    "diagnostic",
    "unsupported",
)
_CRITERION_STATUSES = ("passed", "failed", "ungraded", "abstained", "error", "invalid")
_SUMMARY = re.compile(r"summary(?:-([0-9]+))?\.json$")
# Historical judge artifacts saved keyword-derived booleans after parse failure.
# Recognize only their exact leading marker, not error words inside quoted evidence.
_LEGACY_PARSE_FAILURE = re.compile(r"^(?:\[[^\]\r\n]+\] )?PARSE FAILURE \(fail-closed\):")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def _escape(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def _load(path: Path) -> tuple[str, Any, str | None]:
    raw = ""
    try:
        raw = path.read_text(encoding="utf-8")
        return (
            raw,
            json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_invalid_constant),
            None,
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        return raw, None, str(exc)


def _criterion(row: Any, interrupted: bool) -> dict:
    if not isinstance(row, dict):
        return {"id": "Unknown criterion", "status": "invalid", "evidence": row}
    evidence = row.get("evidence")
    status = "invalid"
    if (
        isinstance(row.get("id"), str)
        and row["id"]
        and type(row.get("satisfied")) is bool
        and isinstance(evidence, str)
    ):
        if (
            row.get("error") is not None
            or evidence.startswith("Judge error:")
            or _LEGACY_PARSE_FAILURE.match(evidence)
        ):
            status = "error"
        elif row.get("abstained") is True or row.get("status") == "abstained":
            status = "abstained"
        elif (
            interrupted
            or row.get("graded") is False
            or row.get("status") == "ungraded"
            or evidence.startswith("LLM judge not yet implemented — criterion evaluation deferred")
        ):
            status = "ungraded"
        else:
            status = "passed" if row["satisfied"] else "failed"
    return {
        "id": row.get("id", "Unknown criterion"),
        "status": status,
        "evidence": evidence,
        "raw": row,
    }


def _completion(turns: Any, metadata: dict, error: Any) -> tuple[str, str]:
    if error is not None:
        return "incomplete", "Execution interrupted by a recorded error"
    stop = metadata.get("stop_reason")
    if not isinstance(stop, str) or stop not in {"stop", "end_turn", "stop_sequence"}:
        if isinstance(stop, str) and stop in {
            "tool_round_limit",
            "length",
            "max_tokens",
            "max_output_tokens",
            "error",
            "content_filter",
            "refusal",
            "pause_turn",
            "tool_calls",
            "tool_use",
        }:
            return "incomplete", f"Execution did not complete normally: {stop}"
        return (
            "unknown",
            "Completion provenance missing or unknown; recorded scores remain unverified",
        )
    if "termination_kind" in metadata and metadata["termination_kind"] != "complete":
        return "unknown", "Final stop conflicts with termination_kind; completion is unverified"
    if metadata.get("provider_refusal") not in (None, "", False):
        return "unknown", "Final stop conflicts with recorded provider refusal"
    if not isinstance(turns, list) or not turns or any(not isinstance(t, dict) for t in turns):
        return "unknown", "Completion cannot be checked against malformed or missing turns"
    final = turns[-1]
    if (
        final.get("role") != "assistant"
        or final.get("tool_calls")
        or not isinstance(final.get("content"), str)
    ):
        return "incomplete", "No terminal assistant response without tool calls"
    pending = set()
    for turn in turns:
        calls = turn.get("tool_calls", [])
        if not isinstance(calls, list):
            return "unknown", "Malformed tool-call list prevents completion verification"
        for call in calls:
            call_id = call.get("id") if isinstance(call, dict) else None
            if (
                turn.get("role") != "assistant"
                or not isinstance(call_id, str)
                or not call_id
                or call_id in pending
            ):
                return (
                    "unknown",
                    "Missing or ambiguous tool-call identity prevents response linkage",
                )
            pending.add(call_id)
        if turn.get("role") == "tool":
            call_id = turn.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                return "unknown", "Tool response cannot be linked to a preceding unanswered call"
            pending.remove(call_id)
    if pending:
        return "incomplete", "Unanswered tool calls remain in the recorded conversation"
    return "complete", ""


def _trajectory(record: dict, data: dict) -> None:
    issues = record["issues"]
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        issues.append("Invalid metadata object")
    for key in ("task_id", "model"):
        if not isinstance(data.get(key), str) or not data[key]:
            issues.append(f"Missing or invalid {key}")
    record.update(
        task_id=data.get("task_id", "Unknown task"),
        model=data.get("model", "Unknown model"),
        seed=data.get("seed"),
        failure_stage=metadata.get("failure_stage", "not recorded"),
    )
    for key in ("passed", "safety_gate_passed"):
        if type(data.get(key)) is not bool:
            issues.append(f"Missing or non-boolean {key}")
    reward = data.get("reward")
    if type(reward) not in (int, float) or not 0 <= reward <= 1 or not math.isfinite(reward):
        issues.append("Missing or invalid reward")
    turns = data.get("turns")
    if not isinstance(turns, list) or not turns or any(not isinstance(t, dict) for t in turns):
        issues.append("Missing, empty or malformed turns; execution completeness unavailable")
    error = data.get("error")
    record["completion"], completion_issue = _completion(turns, metadata, error)
    if completion_issue:
        issues.append(completion_issue)
    elif not turns[-1]["content"].strip():
        record["notes"].append("No final narrative; a completed tool-only task may be valid")
    interrupted = record["completion"] == "incomplete"
    if interrupted:
        issues.append("Execution interrupted; saved criterion verdicts cannot establish completion")
    entries = data.get("criteria_results")
    if not isinstance(entries, list) or not entries:
        issues.append("No usable criterion results; expected criterion coverage unavailable")
        entries = []
    record["criteria"] = [_criterion(row, interrupted) for row in entries]
    if data.get("grading_complete") is False or metadata.get("grading_complete") is False:
        issues.append("Saved metadata explicitly marks grading incomplete")
    identifiers = [row["id"] for row in record["criteria"] if isinstance(row["id"], str)]
    if len(set(identifiers)) != len(identifiers):
        issues.append("Duplicate criterion IDs; criterion coverage is unreliable")
        for row in record["criteria"]:
            if isinstance(row["id"], str) and identifiers.count(row["id"]) > 1:
                row["status"] = "invalid"
    if any(row["status"] not in {"passed", "failed"} for row in record["criteria"]):
        issues.append("Some recorded criteria are invalid, ungraded, abstained or errored")
    expected = metadata.get("expected_criteria_count")
    if type(expected) is int and expected > 0:
        record["expected_criteria"] = expected
        if len(entries) != expected:
            issues.append(f"Expected {expected} criteria, observed {len(entries)}")
    if data.get("passed") is True and (
        data.get("safety_gate_passed") is False
        or any(row["status"] == "failed" for row in record["criteria"])
    ):
        issues.append("Recorded pass conflicts with criterion or safety-gate verdict")
    record["status"] = (
        "error"
        if error is not None
        else "incomplete"
        if issues
        else "recorded_pass"
        if data["passed"]
        else "rubric_fail"
    )
    record["safety_label"] = (
        "Not assessed: execution or grading incomplete"
        if issues
        else f"Recorded gate: {data['safety_gate_passed']} (not clinical safety)"
    )


def collect_evidence(source: Path) -> dict:
    """Read one directory tree; numeric latest attempts control trial selection.

    This is a presentation reader, not a grader. Criteria absent from historical
    artifacts cannot be counted from today's potentially different task files.
    Unknown artifacts remain visible, and raw summaries never override evidence.
    """
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Input must be an existing directory: {source}")
    paths = sorted(source.rglob("*.json"))
    selected = selected_trajectory_paths(paths)
    groups: dict[Path, list[Path]] = defaultdict(list)
    for path in paths:
        groups[trajectory_attempt(path)[0]].append(path)
    selected_bases = {trajectory_attempt(s)[0] for s in selected}
    report = {
        "source": str(source),
        "records": [],
        "summaries": [],
        "issues": [],
        "sidecars": [
            str(p)
            for p in paths
            if p not in selected and trajectory_attempt(p)[0] not in selected_bases
        ],
    }
    counts = Counter({s: 0 for s in _STATUSES})
    counts.update({"criterion_" + s: 0 for s in _CRITERION_STATUSES})
    counts.update(selected_trials=0, raw_attempts=0)
    for path in selected:
        original, attempt = trajectory_attempt(path)
        match = re.search(r"_t([0-9]+)$", original.stem)
        raw, data, error = _load(path)
        record = {
            "path": str(path),
            "attempt_paths": [str(p) for p in groups[original]],
            "attempt": attempt,
            "trial": int(match[1]) if match else None,
            "raw": raw,
            "data": data,
            "issues": [],
            "notes": [],
            "criteria": [],
            "expected_criteria": None,
            "task_id": "—",
            "model": "—",
            "kind": "artifact",
            "status": "unsupported",
        }
        if error or not isinstance(data, dict):
            record["status"] = "invalid"
            record["issues"].append(error or "JSON root must be an object")
            if match or "trajectories" in path.relative_to(source).parts:
                record["kind"] = "trajectory"
        elif ("task_id" in data and "model" in data) or (
            ("task_id" in data or "model" in data)
            and ("turns" in data or "criteria_results" in data)
        ):
            record["kind"] = "trajectory"
            _trajectory(record, data)
        elif "kind" in data or "verification" in data or "outcomes" in data:
            record["status"] = "diagnostic"
            record["issues"].append(
                "Diagnostic artifact; not a benchmark trial or clinical validation"
            )
        else:
            record["issues"].append(
                "Unsupported artifact schema; retained without interpreting verdicts"
            )
        if record["kind"] == "trajectory":
            counts["selected_trials"] += 1
            counts["raw_attempts"] += len(groups[original])
        counts[record["status"]] += 1
        counts.update("criterion_" + row["status"] for row in record["criteria"])
        report["records"].append(record)
    for parent in sorted({p.parent for p in paths if _SUMMARY.fullmatch(p.name)}):
        candidates = [
            p
            for p in paths
            if p.parent == parent
            and _SUMMARY.fullmatch(p.name)
            and (p.name == "summary.json" or int(_SUMMARY.fullmatch(p.name)[1]) >= 2)
        ]
        if not candidates:
            continue
        latest = max(candidates, key=lambda p: int(_SUMMARY.fullmatch(p.name)[1] or 1))
        raw, _, error = _load(latest)
        data = None
        if not error:
            try:
                data = load_latest_summary(parent)
            except (OSError, ValueError) as exc:
                error = str(exc)
        summary = {"path": str(latest), "raw": raw, "data": data, "error": error}
        report["summaries"].append(summary)
        if error:
            report["issues"].append(f"Invalid latest summary: {latest}")
        elif data is not None:
            observed = sum(
                r["kind"] == "trajectory" and Path(r["path"]).is_relative_to(parent)
                for r in report["records"]
            )
            total = data.get("total_runs")
            if type(total) is int and total != observed:
                report["issues"].append(
                    f"{parent.name}: summary reports {total} runs; "
                    f"{observed} selected trajectory files observed"
                )
            tasks, trials = data.get("total_tasks"), data.get("trials")
            if type(tasks) is int and type(trials) is int and tasks > 0 and trials > 0:
                planned = tasks * trials
                if planned != observed:
                    report["issues"].append(
                        f"{parent.name}: {planned} planned trials; {observed} selected files "
                        "observed. Missing or extra trials require review."
                    )
    if not paths:
        report["issues"].append(
            "No JSON evidence found; no completion or safety conclusion available"
        )
    report["counts"] = dict(counts)
    return report


_STYLE = """
:root{color-scheme:light;--ink:#172c35;--muted:#566871;--line:#cdd8dc;--accent:#06605f}
*{box-sizing:border-box}body{margin:0;background:#eef3f3;color:var(--ink);font:16px/1.5 system-ui,sans-serif}
main{max-width:1180px;margin:auto;padding:36px 24px 80px}h1{font-size:32px;line-height:1.2;margin:8px 0}
h2{font-size:21px}h3{font-size:17px}a{color:var(--accent);overflow-wrap:anywhere}small,.muted{color:var(--muted)}
.eyebrow{letter-spacing:.12em;text-transform:uppercase;font-size:12px;font-weight:700;color:var(--accent)}
.notice,.record,.panel{background:white;border:1px solid var(--line);border-radius:10px;padding:20px;margin:16px 0}
.notice{border-left:5px solid #c18218}.metrics{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}
.metric{flex:1;min-width:135px;background:white;border:1px solid var(--line);padding:16px;border-radius:8px}
.metric b{display:block;font-size:27px}.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:end}
label{display:block;font-size:14px}select,input{display:block;margin-top:5px;padding:9px;border:1px solid #83989f;border-radius:5px;max-width:100%;font:inherit}
input{min-width:250px}.badge{display:inline-block;background:#e8efef;border-radius:4px;padding:2px 7px;font-size:13px}
.error,.invalid,.failed{color:#9b3025}.abstained,.ungraded,.incomplete{color:#785414}details{margin:10px 0}
summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f6;border:1px solid #dce4e5;border-radius:5px;padding:13px;font:13px/1.5 ui-monospace,monospace;max-height:480px;overflow:auto}
.record-head{display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap}.record h2{margin:0;overflow-wrap:anywhere}
.criteria{border-top:1px solid var(--line);padding-top:7px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.table-wrap{overflow-x:auto}
[hidden]{display:none!important}@media(max-width:600px){main{padding:22px 14px}.metric{min-width:110px}h1{font-size:26px}}@media print{.controls{display:none}pre{max-height:none}.record{break-inside:avoid}}
"""  # noqa: E501 — embedded stylesheet
_SCRIPT = """
const statusFilter = document.getElementById('status-filter');
const criterionFilter = document.getElementById('criterion-filter');
const query = document.getElementById('query');
function filterEvidence() {
  let visible = 0;
  document.querySelectorAll('.record').forEach(record => {
    const rows = [...record.querySelectorAll('.criterion')];
    rows.forEach(row => { row.hidden = criterionFilter.value !== 'all' && row.dataset.status !== criterionFilter.value; });
    const matchesCriteria = criterionFilter.value === 'all' || rows.some(row => !row.hidden);
    record.hidden = !(matchesCriteria && (statusFilter.value === 'all' || record.dataset.status === statusFilter.value) && record.textContent.toLowerCase().includes(query.value.toLowerCase()));
    if (!record.hidden) visible++;
  });
  document.getElementById('visible-count').textContent = visible + ' evidence records shown';
}
[statusFilter, criterionFilter, query].forEach(control => control.addEventListener('input', filterEvidence));
filterEvidence();
"""  # noqa: E501 — static browser program


def _link(path: str, label: str) -> str:
    return f'<a href="{_escape(Path(path).resolve().as_uri())}">{_escape(label)}</a>'


def _details(label: str, value: Any) -> str:
    return f"<details><summary>{_escape(label)}</summary><pre>{_escape(value)}</pre></details>"


def render_evidence(report: dict) -> str:
    """Render escaped static HTML with local filtering; no external assets or fetches."""
    digest = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
    csp = (
        f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; "
        "connect-src 'none'; base-uri 'none'; form-action 'none'"
    )
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        f"<title>HealthCraft evidence review</title><style>{_STYLE}</style></head><body><main>",
        '<div class="eyebrow">HealthCraft · offline researcher review</div>'
        "<h1>Inspect the evidence behind a run</h1>",
        f'<p class="muted">Source: {_escape(report["source"])}. '
        "Latest saved attempt per trial; original attempts remain linked.</p>",
        '<div class="notice"><strong>Recorded results are research evidence, '
        "not clinical readiness.</strong><p>This report does not regrade results. "
        "Errors, abstentions and ungraded criteria are separate from rubric failures. "
        "A recorded pass or safety gate does not establish clinical safety. "
        "Missing metadata and unknown expected criterion totals remain unknown.</p>",
        "<details><summary>Known historical rubric limitations</summary><p>"
        "IR-001-C03 can credit a resource lookup instead of cross-reactivity evidence. "
        "Historical IR-002 checks can credit tool names without the intended patient "
        "or all four linked visits. V8 judge failures could fail open; clinical judge "
        "calibration is not established. The experimental IR-002 certificate covers "
        "mechanical retrieval and persistence only, leaving clinical and safety "
        "criteria unassessed.</p>",
        _link(str(_ROOT / "docs/TASK_VALIDITY_FINDINGS.md"), "Task validity findings")
        + " · "
        + _link(str(_ROOT / "docs/REFERENCE_CERTIFICATES.md"), "Reference certificate scope")
        + " · "
        + _link(
            str(_ROOT / "docs/EVALUATION_INTEGRITY_2026-09-30.md"), "Evaluator integrity findings"
        )
        + '</details><p class="muted">Raw evidence is embedded below. Source and '
        "documentation links refer to original local files; moving this HTML does "
        "not move those files.</p></div>",
    ]
    counts = report["counts"]
    parts.append('<div class="metrics">')
    for key, label in (
        ("selected_trials", "Selected trials"),
        ("raw_attempts", "Raw attempts"),
        ("recorded_pass", "Recorded passes"),
        ("rubric_fail", "Rubric failures"),
        ("error", "Execution / grader errors"),
        ("incomplete", "Incomplete records"),
        ("invalid", "Malformed artifacts"),
    ):
        parts.append(f'<div class="metric"><b>{counts[key]}</b>{label}</div>')
    parts.append(
        "</div><p>Observed criterion entries: "
        + " · ".join(f"{s}: {counts['criterion_' + s]}" for s in _CRITERION_STATUSES)
        + ". Counts do not estimate missing criteria or clinical error rates.</p>"
    )
    if report["issues"]:
        parts.append(
            '<div class="notice"><strong>Evidence gaps</strong><ul>'
            + "".join(f"<li>{_escape(issue)}</li>" for issue in report["issues"])
            + "</ul></div>"
        )
    models = defaultdict(Counter)
    for record in report["records"]:
        if record["kind"] == "trajectory":
            models[_text(record["model"])][record["status"]] += 1
    if models:
        parts.append(
            '<div class="panel table-wrap"><h2>Model inventory</h2><table><thead><tr>'
            "<th>Model</th><th>Trials</th><th>Recorded pass</th><th>Rubric fail</th>"
            "<th>Incomplete / error / invalid</th></tr></thead><tbody>"
        )
        for model, totals in sorted(models.items()):
            gaps = sum(totals[s] for s in ("incomplete", "error", "invalid"))
            parts.append(
                f"<tr><td>{_escape(model)}</td><td>{sum(totals.values())}</td>"
                f"<td>{totals['recorded_pass']}</td><td>{totals['rubric_fail']}</td>"
                f"<td>{gaps}</td></tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append(
        '<div class="panel controls"><label>Status filter<select id="status-filter">'
        '<option value="all">All statuses</option>'
        + "".join(f'<option value="{s}">{s.replace("_", " ")}</option>' for s in _STATUSES)
        + '</select></label><label>Criterion filter<select id="criterion-filter">'
        '<option value="all">All criterion statuses</option>'
        + "".join(f'<option value="{s}">{s}</option>' for s in _CRITERION_STATUSES)
        + '</select></label><label>Find task, model or evidence<input id="query" '
        'type="search" placeholder="Task ID, criterion ID, tool…"></label>'
        '<span id="visible-count" role="status"></span></div>'
    )
    if not report["records"]:
        parts.append("<p>No evidence records. No completion or safety conclusion is available.</p>")
    for index, record in enumerate(report["records"]):
        status = record["status"]
        parts.append(
            f'<article class="record" data-status="{status}" id="record-{index}">'
            f'<div class="record-head"><h2>{_escape(record["task_id"])}</h2>'
            f'<span class="badge {status}">{status.replace("_", " ")}</span></div>'
        )
        parts.append(
            f"<p>{_escape(record['model'])} · Trial {_escape(record['trial'])} "
            f"· Attempt {record['attempt']}</p>"
        )
        parts.append(
            _link(record["path"], "Raw source") + " · " + _escape(Path(record["path"]).name)
        )
        if record["issues"]:
            parts.append(
                "<ul>" + "".join(f"<li>{_escape(i)}</li>" for i in record["issues"]) + "</ul>"
            )
        if record["notes"]:
            parts.append(
                '<p class="muted">' + "; ".join(_escape(note) for note in record["notes"]) + "</p>"
            )
        if record["kind"] == "trajectory":
            parts.append(
                f"<p>{_escape(record.get('safety_label', 'Not assessed'))}. "
                f"Failure stage: {_escape(record.get('failure_stage', 'not recorded'))}.</p>"
            )
            saved = record["data"] if isinstance(record["data"], dict) else {}
            parts.append(
                f"<p>Completion: {_escape(record.get('completion', 'unknown'))}. "
                f"Recorded reward: {_escape(saved.get('reward', 'missing'))}; "
                f"recorded pass: {_escape(saved.get('passed', 'missing'))}. "
                "These saved values are not revalidated benchmark scores.</p>"
            )
            expected = record["expected_criteria"]
            coverage = (
                "expected total unavailable" if expected is None else f"expected total {expected}"
            )
            parts.append(
                f"<p>{len(record['criteria'])} observed criterion entries; {coverage}.</p>"
            )
        for row in record["criteria"]:
            parts.append(
                f'<details class="criterion criteria" data-status="{row["status"]}">'
                f'<summary>{_escape(row["id"])} <span class="badge {row["status"]}">'
                f"{row['status']}</span></summary><pre>{_escape(row['evidence'])}</pre>"
                f"{_details('Recorded criterion fields', row.get('raw', row))}</details>"
            )
        data = record["data"]
        if isinstance(data, dict) and isinstance(data.get("turns"), list):
            parts.append("<details><summary>Tool calls and full conversation</summary>")
            for turn_index, turn in enumerate(data["turns"]):
                role = turn.get("role", "unknown") if isinstance(turn, dict) else "invalid"
                parts.append(_details(f"Turn {turn_index + 1} · {_text(role)}", turn))
            parts.append("</details>")
        if len(record["attempt_paths"]) > 1:
            parts.append(
                "<details><summary>Immutable attempt history</summary><ul>"
                + "".join(
                    "<li>" + _link(p, Path(p).name) + "</li>" for p in record["attempt_paths"]
                )
                + "</ul></details>"
            )
        parts.append(
            _details("Full raw artifact (including provenance)", record["raw"]) + "</article>"
        )
    if report["summaries"]:
        parts.append(
            '<section class="panel"><h2>Saved run summaries</h2><p>Reported context only. '
            "Counts can include fail-closed execution errors and are not used as evidence "
            "of clinical safety. Latest numbered summary selected.</p>"
        )
        for summary in report["summaries"]:
            parts.append(_link(summary["path"], Path(summary["path"]).name))
            if summary["error"]:
                parts.append(f'<p class="error">{_escape(summary["error"])}</p>')
            if isinstance(summary["data"], dict):
                parts.append(
                    "<p>Reported ungraded criteria: "
                    f"{_escape(summary['data'].get('ungraded_criteria', 'unknown'))} "
                    "· Reported grading complete: "
                    f"{_escape(summary['data'].get('grading_complete', 'unknown'))}</p>"
                )
            parts.append(_details("Summary fields and reported ungraded coverage", summary["raw"]))
        parts.append("</section>")
    if report["sidecars"]:
        parts.append(
            '<details class="panel"><summary>Summary / grading sidecars '
            "(not additional trials)</summary><ul>"
            + "".join("<li>" + _link(p, p) + "</li>" for p in report["sidecars"])
            + "</ul></details>"
        )
    parts.append(f"</main><script>{_SCRIPT}</script></body></html>")
    return "\n".join(parts)


def write_evidence_report(source: Path, output: Path) -> dict:
    """Create one new HTML artifact exclusively; never overwrite a prior report."""
    if output.exists():
        raise FileExistsError(f"Report already exists: {output}")
    report = collect_evidence(source)
    rendered = render_evidence(report)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(rendered)
    return report
