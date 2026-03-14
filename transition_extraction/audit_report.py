"""Generate an HTML audit report from pipeline output.

Surfaces discrepancies, candidate additions, and unsupported entries
for human review. Each item includes a YAML snippet for manual_reconciliation.yaml.
"""

import json
from html import escape
from pathlib import Path

from .config import PipelineConfig
from .models import VALID_STATUSES, WorkUnit
from .text_utils import country_slug

STATUS_OPTIONS = ''.join(f'<option value="{s}">{s}</option>' for s in VALID_STATUSES)
STATUS_SELECT = f'<select class="override-status"><option value="">-- status --</option>{STATUS_OPTIONS}</select>'
SPLIT_STATUS_SELECT = f'<select class="split-status"><option value="">-- status --</option>{STATUS_OPTIONS}</select>'


def _load_work_units(config: PipelineConfig, countries_filter: list[str] | None = None) -> list[WorkUnit]:
    work_units_dir = config.paths.output_dir / "local" / "work_units"
    work_units = []
    for path in sorted(work_units_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)
        wu = WorkUnit.model_validate(data)
        if countries_filter and wu.country not in countries_filter:
            continue
        work_units.append(wu)
    return work_units


def _load_decisions(decisions_path: Path) -> dict[str, dict]:
    """Load human decisions, keyed by 'country|csv_row' or 'country|addition|date'."""
    import yaml
    if not decisions_path.exists():
        return {}
    with open(decisions_path) as f:
        raw = yaml.safe_load(f) or []
    decisions = {}
    for entry in raw:
        country = entry.get("country", "")
        if entry.get("type") == "addition":
            key = f"{country}|addition|{entry.get('date', '')}"
        else:
            key = f"{country}|{entry.get('csv_row', '')}"
        decisions[key] = entry
    return decisions


def _get_source_lines(work_unit: WorkUnit, source_type: str, line_start: int, line_end: int) -> str:
    """Get numbered source lines for context display."""
    numbered_text = work_unit.rdcr_text if source_type == "rdcr" else work_unit.pocom_text
    if not numbered_text:
        return ""
    lines = numbered_text.lines
    start = max(0, line_start - 2)  # 1 line of context before
    end = min(len(lines), line_end + 1)  # 1 line of context after
    result = []
    for i in range(start, end):
        line_num = i + 1
        marker = " >> " if line_start <= line_num <= line_end else "    "
        result.append(f"{marker}[{line_num}] {lines[i]}")
    return "\n".join(result)


def _load_suggestions(input_dir: Path) -> dict[str, dict]:
    """Load suggested decisions from suggested_reconciliation.yaml."""
    import yaml
    path = input_dir / "suggested_reconciliation.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        raw = yaml.safe_load(f) or []
    suggestions = {}
    for entry in raw:
        country = entry.get("country", "")
        if entry.get("type") == "addition":
            key = f"{country}|addition|{entry.get('date', '')}"
        else:
            key = f"{country}|{entry.get('csv_row', '')}"
        suggestions[key] = entry
    return suggestions


def generate_audit_html(config: PipelineConfig, countries_filter: list[str] | None = None) -> Path:
    """Generate an HTML audit report. Returns the output path."""
    work_units = _load_work_units(config, countries_filter)
    decisions_path = config.paths.manual_reconciliation
    decisions = _load_decisions(decisions_path)
    suggestions = _load_suggestions(config.paths.manual_reconciliation.parent)

    reconciliations_dir = config.paths.output_dir / "remote_api" / "reconciliations"

    items_by_country: dict[str, list[dict]] = {}
    csv_by_country: dict[str, list] = {}
    totals = {"discrepancy": 0, "candidate_addition": 0, "unsupported": 0, "resolved": 0}

    for wu in work_units:
        slug = country_slug(wu.country)
        recon_path = reconciliations_dir / f"{slug}.json"
        if not recon_path.exists():
            continue

        with open(recon_path) as f:
            recon_data = json.load(f)
        result = recon_data.get("result")
        if not result:
            continue
        merged_events = recon_data.get("merged_events", [])

        country_items = []

        # Discrepancies
        for disc in result.get("discrepancies", []):
            csv_row = disc.get("csv_row")
            decision_key = f"{wu.country}|{csv_row}"
            decision = decisions.get(decision_key)

            extracted_indices = disc.get("extracted_event_indices", [])
            sources = []
            source_date = source_status = ""
            for idx in extracted_indices:
                if 0 <= idx < len(merged_events):
                    ev = merged_events[idx]
                    if not source_date:
                        source_date = ev.get("date", "")
                        source_status = ev.get("new_status", "")
                    if ev.get("source_type") == "rdcr" and not sources:
                        source_date = ev.get("date", "")
                        source_status = ev.get("new_status", "")
                    for e in ev.get("evidence", []):
                        context = _get_source_lines(
                            wu, ev.get("source_type", ""),
                            e.get("line_start", 0), e.get("line_end", 0),
                        )
                        sources.append({
                            "source_type": ev.get("source_type", ""),
                            "quote": e.get("quote", ""),
                            "context": context,
                        })

            # Find the CSV event for display
            csv_event = None
            for ev in wu.csv_events:
                if ev.row_index == csv_row:
                    csv_event = ev
                    break

            suggestion = suggestions.get(decision_key) if not decision else None
            item = {
                "type": "discrepancy",
                "country": wu.country,
                "csv_row": csv_row,
                "csv_date": csv_event.date_str() if csv_event else "?",
                "csv_status": csv_event.status_change if csv_event else "?",
                "field": disc.get("field", "?"),
                "csv_value": disc.get("csv_value", "?"),
                "extracted_value": disc.get("extracted_value", "?"),
                "source_date": source_date,
                "source_status": source_status,
                "assessment": disc.get("assessment", "?"),
                "reasoning": disc.get("reasoning", ""),
                "sources": sources,
                "decision": decision,
                "suggestion": suggestion,
            }
            country_items.append(item)
            if decision:
                totals["resolved"] += 1
            else:
                totals["discrepancy"] += 1

        # Candidate additions
        for missing in result.get("missing_from_csv", []):
            date = missing.get("date", "")
            decision_key = f"{wu.country}|addition|{date}"
            decision = decisions.get(decision_key)

            extracted_indices = missing.get("extracted_event_indices", [])
            sources = []
            for idx in extracted_indices:
                if 0 <= idx < len(merged_events):
                    ev = merged_events[idx]
                    for e in ev.get("evidence", []):
                        context = _get_source_lines(
                            wu, ev.get("source_type", ""),
                            e.get("line_start", 0), e.get("line_end", 0),
                        )
                        sources.append({
                            "source_type": ev.get("source_type", ""),
                            "quote": e.get("quote", ""),
                            "context": context,
                        })

            suggestion = suggestions.get(decision_key) if not decision else None
            item = {
                "type": "candidate_addition",
                "country": wu.country,
                "date": date,
                "new_status": missing.get("new_status", ""),
                "event_description": missing.get("event_description", ""),
                "notes": missing.get("notes", ""),
                "sources": sources,
                "decision": decision,
                "suggestion": suggestion,
            }
            country_items.append(item)
            if decision:
                totals["resolved"] += 1
            else:
                totals["candidate_addition"] += 1

        # Unsupported
        for unsupported in result.get("unsupported_in_sources", []):
            csv_row = unsupported.get("csv_row")
            decision_key = f"{wu.country}|{csv_row}"
            decision = decisions.get(decision_key)

            csv_event = None
            for ev in wu.csv_events:
                if ev.row_index == csv_row:
                    csv_event = ev
                    break

            suggestion = suggestions.get(decision_key) if not decision else None
            item = {
                "type": "unsupported",
                "country": wu.country,
                "csv_row": csv_row,
                "csv_date": csv_event.date_str() if csv_event else "?",
                "csv_status": csv_event.status_change if csv_event else "?",
                "notes": unsupported.get("notes", ""),
                "sources": [],
                "decision": decision,
                "suggestion": suggestion,
            }
            country_items.append(item)
            if decision:
                totals["resolved"] += 1
            else:
                totals["unsupported"] += 1

        if country_items:
            items_by_country[wu.country] = country_items
            csv_by_country[wu.country] = wu.csv_events

    # Render HTML
    html = _render_html(items_by_country, csv_by_country, totals)

    output_path = config.paths.output_dir / "local" / "final" / "audit_report.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    return output_path


def _render_csv_table(csv_events: list) -> str:
    """Render CSV events as an HTML table."""
    rows = []
    for ev in csv_events:
        rows.append(
            f"<tr><td>{ev.row_index}</td>"
            f"<td>{escape(ev.date_str())}</td>"
            f"<td>{escape(ev.status_change)}</td>"
            f"<td>{escape(ev.notes)}</td></tr>"
        )
    return f"""<details class="csv-table" open>
  <summary>CSV events ({len(csv_events)} rows)</summary>
  <table>
    <thead><tr><th>Row</th><th>Date</th><th>Status</th><th>Notes</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</details>"""


def _render_html(items_by_country: dict[str, list[dict]], csv_by_country: dict[str, list], totals: dict) -> str:
    total_pending = totals["discrepancy"] + totals["candidate_addition"] + totals["unsupported"]

    country_nav = []
    country_sections = []

    for country, items in sorted(items_by_country.items()):
        pending = sum(1 for it in items if not it.get("decision"))
        resolved = sum(1 for it in items if it.get("decision"))
        badge = f' <span class="badge resolved">{resolved} resolved</span>' if resolved else ""
        pending_badge = f'<span class="badge pending">{pending}</span>' if pending else '<span class="badge resolved">all resolved</span>'

        anchor = country.lower().replace(" ", "-").replace("(", "").replace(")", "")
        country_nav.append(f'<li><a href="#{escape(anchor)}">{escape(country)}</a> {pending_badge}</li>')

        csv_table = _render_csv_table(csv_by_country.get(country, []))

        items_html = []
        for item in items:
            items_html.append(_render_item(item))

        all_resolved = all(it.get("decision") for it in items)
        country_open = "" if all_resolved else " open"
        country_sections.append(f"""
<details id="{escape(anchor)}" class="country-section"{country_open}>
  <summary><h2>{escape(country)} {pending_badge}{badge}</h2></summary>
  {csv_table}
  {"".join(items_html)}
</details>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Audit Report: US Diplomatic Transitions</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; line-height: 1.5; color: #1a1a1a; max-width: 960px; margin: 0 auto; padding: 2rem 1rem; }}
  h1 {{ margin-bottom: 0.5rem; }}
  .summary {{ background: #f5f5f5; padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 2rem; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-top: 0.75rem; }}
  .summary-item {{ text-align: center; }}
  .summary-item .number {{ font-size: 2rem; font-weight: 700; }}
  .summary-item .label {{ font-size: 0.85rem; color: #666; }}
  .summary-item.discrepancy .number {{ color: #d97706; }}
  .summary-item.addition .number {{ color: #2563eb; }}
  .summary-item.unsupported .number {{ color: #dc2626; }}
  .summary-item.resolved .number {{ color: #16a34a; }}
  nav ul {{ list-style: none; columns: 3; margin-bottom: 2rem; }}
  nav li {{ margin-bottom: 0.25rem; }}
  nav a {{ color: #2563eb; text-decoration: none; }}
  nav a:hover {{ text-decoration: underline; }}
  .badge {{ font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 10px; font-weight: 600; }}
  .badge.pending {{ background: #fef3c7; color: #92400e; }}
  .badge.resolved {{ background: #dcfce7; color: #166534; }}
  .country-section {{ margin-bottom: 3rem; }}
  .country-section > summary {{ cursor: pointer; padding: 0.5rem 0; margin-bottom: 1rem; border-bottom: 2px solid #e5e7eb; }}
  .country-section > summary::marker {{ color: #9ca3af; }}
  .country-section > summary h2 {{ display: inline; }}
  .country-section > summary .badge {{ vertical-align: middle; margin-left: 0.5rem; }}
  details.item {{ border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 1rem; overflow: hidden; }}
  details.item > summary {{ padding: 0.75rem 1.25rem; cursor: pointer; font-size: 0.95rem; }}
  details.item > summary .item-type {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
  details.item[open] > summary {{ border-bottom: 1px solid #e5e7eb; }}
  .item-body {{ padding: 1rem 1.25rem; }}
  .csv-table {{ margin-bottom: 1.25rem; }}
  .csv-table summary {{ font-size: 0.9rem; font-weight: 600; color: #4b5563; cursor: pointer; margin-bottom: 0.5rem; }}
  .csv-table table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  .csv-table th {{ text-align: left; padding: 0.35rem 0.5rem; background: #f9fafb; border-bottom: 2px solid #e5e7eb; font-weight: 600; color: #374151; }}
  .csv-table td {{ padding: 0.3rem 0.5rem; border-bottom: 1px solid #f3f4f6; }}
  .csv-table tr:hover {{ background: #f9fafb; }}
  .item.resolved {{ opacity: 0.6; }}
  .item-type.discrepancy {{ color: #d97706; }}
  .item-type.candidate_addition {{ color: #2563eb; }}
  .item-type.unsupported {{ color: #dc2626; }}
  .field-row {{ display: flex; gap: 2rem; margin-bottom: 0.5rem; flex-wrap: wrap; }}
  .field {{ }}
  .field .label {{ font-size: 0.8rem; color: #666; }}
  .field .value {{ font-weight: 600; }}
  .field .value.csv {{ color: #7c3aed; }}
  .field .value.source {{ color: #059669; }}
  .reasoning {{ margin-top: 0.75rem; padding: 0.75rem; background: #fffbeb; border-left: 3px solid #d97706; font-size: 0.9rem; }}
  .source-block {{ margin-top: 0.75rem; }}
  .source-label {{ font-size: 0.8rem; font-weight: 600; color: #666; margin-bottom: 0.25rem; }}
  .quote {{ padding: 0.5rem 0.75rem; background: #f0fdf4; border-left: 3px solid #16a34a; font-size: 0.9rem; margin-bottom: 0.5rem; }}
  .context {{ font-family: "SF Mono", "Consolas", monospace; font-size: 0.8rem; background: #f9fafb; padding: 0.5rem 0.75rem; overflow-x: auto; white-space: pre; border-radius: 4px; margin-bottom: 0.5rem; }}
  .suggestion-banner {{ margin-top: 0.75rem; padding: 0.75rem; background: #eff6ff; border: 1px solid #93c5fd; border-radius: 6px; }}
  .suggestion-header {{ font-size: 0.9rem; margin-bottom: 0.5rem; }}
  .suggestion-header strong {{ color: #1d4ed8; }}
  .suggestion-yaml {{ font-family: "SF Mono", "Consolas", monospace; font-size: 0.78rem; background: #1e293b; color: #e2e8f0; padding: 0.5rem 0.75rem; border-radius: 4px; overflow-x: auto; white-space: pre; margin-bottom: 0.5rem; }}
  .accept-suggestion-btn {{ font-size: 0.85rem; padding: 0.35rem 1rem; border: 1px solid #3b82f6; border-radius: 4px; background: #3b82f6; color: white; cursor: pointer; font-weight: 600; }}
  .accept-suggestion-btn:hover {{ background: #2563eb; }}
  .accept-suggestion-btn.accepted {{ background: #16a34a; border-color: #16a34a; }}
  .decision-form {{ margin-top: 1rem; padding: 0.75rem; background: #f9fafb; border-radius: 6px; border: 1px solid #e5e7eb; }}
  .radio-group {{ display: flex; flex-wrap: wrap; gap: 0.25rem 1.25rem; margin-bottom: 0.5rem; }}
  .radio-group label {{ font-size: 0.85rem; cursor: pointer; display: flex; align-items: center; gap: 0.3rem; }}
  .notes-input, .override-date, .override-status, .split-date, .split-status {{ font-size: 0.85rem; padding: 0.3rem 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; background: white; }}
  .notes-input {{ width: 100%; margin-top: 0.5rem; }}
  .custom-fields, .split-fields, .addition-overrides {{ margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }}
  .split-entries {{ display: flex; flex-direction: column; gap: 0.35rem; width: 100%; }}
  .split-entry {{ display: flex; gap: 0.5rem; }}
  .split-entry input {{ flex: 1; }}
  .add-split-entry {{ font-size: 0.8rem; padding: 0.2rem 0.6rem; border: 1px solid #d1d5db; border-radius: 4px; background: white; cursor: pointer; }}
  .yaml-output {{ margin-top: 0.5rem; }}
  .yaml-output pre {{ font-family: "SF Mono", "Consolas", monospace; font-size: 0.8rem; background: #1e293b; color: #e2e8f0; padding: 0.75rem; border-radius: 4px; overflow-x: auto; white-space: pre; }}
  .copy-btn {{ margin-top: 0.35rem; font-size: 0.8rem; padding: 0.25rem 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; background: white; cursor: pointer; }}
  .copy-btn:hover {{ background: #f3f4f6; }}
  .copy-btn.copied {{ background: #dcfce7; border-color: #16a34a; color: #166534; }}
  .clear-btn {{ margin-top: 0.35rem; margin-left: 0.5rem; font-size: 0.8rem; padding: 0.25rem 0.75rem; border: 1px solid #d1d5db; border-radius: 4px; background: white; cursor: pointer; color: #9ca3af; }}
  .clear-btn:hover {{ background: #fef2f2; border-color: #f87171; color: #dc2626; }}
  .copy-all-section {{ margin-top: 2rem; text-align: center; }}
  .copy-all-btn {{ font-size: 1rem; padding: 0.6rem 1.5rem; border: 2px solid #2563eb; border-radius: 6px; background: white; color: #2563eb; font-weight: 600; cursor: pointer; }}
  .copy-all-btn:hover {{ background: #eff6ff; }}
  .copy-all-btn.copied {{ background: #dcfce7; border-color: #16a34a; color: #166534; }}
  #copy-all-status {{ margin-left: 0.75rem; font-size: 0.9rem; color: #666; }}
  .decision-banner {{ background: #dcfce7; border: 1px solid #16a34a; border-radius: 4px; padding: 0.5rem 0.75rem; margin-bottom: 0.75rem; font-size: 0.9rem; }}
  .decision-banner strong {{ color: #166534; }}
  .notes {{ margin-top: 0.5rem; font-size: 0.9rem; color: #4b5563; }}
</style>
</head>
<body>
<h1>Audit Report</h1>
<p style="color:#666; margin-bottom:1.5rem;">US Diplomatic Transitions Extraction Pipeline</p>

<div class="summary">
  <strong>Items requiring review: {total_pending}</strong> across {len(items_by_country)} countries
  <div class="summary-grid">
    <div class="summary-item discrepancy"><div class="number">{totals["discrepancy"]}</div><div class="label">Discrepancies</div></div>
    <div class="summary-item addition"><div class="number">{totals["candidate_addition"]}</div><div class="label">Candidate Additions</div></div>
    <div class="summary-item unsupported"><div class="number">{totals["unsupported"]}</div><div class="label">Unsupported</div></div>
    <div class="summary-item resolved"><div class="number">{totals["resolved"]}</div><div class="label">Resolved</div></div>
  </div>
</div>

<nav>
  <h3>Countries</h3>
  <ul>
    {"".join(country_nav)}
  </ul>
</nav>

{"".join(country_sections)}

<div class="copy-all-section">
  <button type="button" id="copy-all-btn" class="copy-all-btn">Copy all YAML</button>
  <span id="copy-all-status"></span>
</div>

<footer style="margin-top:2rem; padding-top:1rem; border-top:1px solid #e5e7eb; color:#999; font-size:0.85rem;">
  Paste into <code>input/manual_reconciliation.yaml</code>, then run <code>python main.py assemble</code> to apply decisions. Re-run <code>python main.py audit</code> to update this report.
</footer>
<script>
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('.decision-form').forEach(form => {{
    const type = form.dataset.type;
    const radios = form.querySelectorAll('input[type="radio"]');
    const notesInput = form.querySelector('.notes-input');
    const yamlOutput = form.querySelector('.yaml-output pre');
    const copyBtn = form.querySelector('.copy-btn');
    const clearBtn = form.querySelector('.clear-btn');
    const customFields = form.querySelector('.custom-fields');
    const splitFields = form.querySelector('.split-fields');

    function getSelected() {{
      const checked = form.querySelector('input[type="radio"]:checked');
      return checked ? checked.value : null;
    }}

    function escYaml(s) {{
      if (!s) return '""';
      if (/[:#{{}}\\[\\],&*?|>!%@`"']/.test(s) || s.includes('\\n')) return '"' + s.replace(/"/g, '\\\\"') + '"';
      return '"' + s + '"';
    }}

    function updateYaml() {{
      const decision = getSelected();
      if (!decision) {{
        yamlOutput.textContent = '';
        copyBtn.style.display = 'none';
        clearBtn.style.display = 'none';
        return;
      }}
      const notes = notesInput.value.trim();
      let lines = [];
      lines.push('- country: ' + escYaml(form.dataset.country));

      if (type === 'discrepancy' || type === 'unsupported') {{
        lines.push('  csv_row: ' + form.dataset.csvRow);
      }}
      if (type === 'candidate_addition') {{
        lines.push('  type: addition');
        lines.push('  date: ' + escYaml(form.dataset.date));
      }}

      lines.push('  decision: ' + decision);

      if (type === 'candidate_addition' && decision === 'add') {{
        const addOverrides = form.querySelector('.addition-overrides');
        if (addOverrides) {{
          const od = addOverrides.querySelector('.override-date').value.trim();
          const os = addOverrides.querySelector('.override-status').value.trim();
          if (od) lines.push('  override_date: ' + escYaml(od));
          if (os) lines.push('  override_status: ' + escYaml(os));
        }}
      }}

      if (decision === 'accept_source' || decision === 'custom') {{
        const od = form.querySelector('.custom-fields .override-date').value.trim();
        const os = form.querySelector('.custom-fields .override-status').value.trim();
        if (od) lines.push('  override_date: ' + escYaml(od));
        if (os) lines.push('  override_status: ' + escYaml(os));
      }}

      if (decision === 'split') {{
        lines.push('  entries:');
        form.querySelectorAll('.split-entry').forEach(entry => {{
          const d = entry.querySelector('.split-date').value.trim();
          const s = entry.querySelector('.split-status').value.trim();
          lines.push('    - date: ' + escYaml(d));
          lines.push('      status: ' + escYaml(s));
        }});
      }}

      if (notes) lines.push('  notes: ' + escYaml(notes));

      yamlOutput.textContent = lines.join('\\n');
      copyBtn.style.display = 'inline-block';
      clearBtn.style.display = 'inline-block';
    }}

    const additionOverrides = form.querySelector('.addition-overrides');

    radios.forEach(r => r.addEventListener('change', () => {{
      const val = getSelected();
      if (customFields) {{
        customFields.style.display = (val === 'accept_source' || val === 'custom') ? 'flex' : 'none';
        if (val === 'accept_source') {{
          const sd = form.dataset.sourceDate || '';
          const ss = form.dataset.sourceStatus || '';
          customFields.querySelector('.override-date').value = sd;
          const sel = customFields.querySelector('.override-status');
          sel.value = ss;
        }} else if (val !== 'custom') {{
          customFields.querySelectorAll('input, select').forEach(i => i.value = '');
        }}
      }}
      if (splitFields) splitFields.style.display = val === 'split' ? 'block' : 'none';
      if (additionOverrides) additionOverrides.style.display = val === 'add' ? 'flex' : 'none';
      updateYaml();
    }}));

    if (notesInput) notesInput.addEventListener('input', updateYaml);
    if (customFields) {{
      customFields.querySelectorAll('input, select').forEach(i => i.addEventListener(i.tagName === 'SELECT' ? 'change' : 'input', updateYaml));
    }}
    if (additionOverrides) {{
      additionOverrides.querySelectorAll('input, select').forEach(i => i.addEventListener(i.tagName === 'SELECT' ? 'change' : 'input', updateYaml));
    }}
    if (splitFields) {{
      splitFields.querySelectorAll('input, select').forEach(i => i.addEventListener(i.tagName === 'SELECT' ? 'change' : 'input', updateYaml));
      const addBtn = splitFields.querySelector('.add-split-entry');
      if (addBtn) addBtn.addEventListener('click', () => {{
        const entries = splitFields.querySelector('.split-entries');
        const entry = document.createElement('div');
        entry.className = 'split-entry';
        entry.innerHTML = '<input type="text" class="split-date" placeholder="date"><select class="split-status"><option value="">-- status --</option>{STATUS_OPTIONS}</select>';
        entries.appendChild(entry);
        entry.querySelectorAll('input, select').forEach(i => i.addEventListener(i.tagName === 'SELECT' ? 'change' : 'input', updateYaml));
        updateYaml();
      }});
    }}

    if (copyBtn) copyBtn.addEventListener('click', () => {{
      navigator.clipboard.writeText(yamlOutput.textContent).then(() => {{
        copyBtn.textContent = 'Copied!';
        copyBtn.classList.add('copied');
        setTimeout(() => {{ copyBtn.textContent = 'Copy YAML'; copyBtn.classList.remove('copied'); }}, 1500);
      }});
    }});

    if (clearBtn) clearBtn.addEventListener('click', () => {{
      radios.forEach(r => r.checked = false);
      if (notesInput) notesInput.value = '';
      if (customFields) {{
        customFields.style.display = 'none';
        customFields.querySelectorAll('input, select').forEach(i => i.value = '');
      }}
      if (splitFields) {{
        splitFields.style.display = 'none';
        splitFields.querySelectorAll('input, select').forEach(i => i.value = '');
      }}
      if (additionOverrides) {{
        additionOverrides.style.display = 'none';
        additionOverrides.querySelectorAll('input, select').forEach(i => i.value = '');
      }}
      yamlOutput.textContent = '';
      copyBtn.style.display = 'none';
      clearBtn.style.display = 'none';
    }});
  }});

  document.querySelectorAll('.accept-suggestion-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const banner = btn.closest('.suggestion-banner');
      const itemBody = banner.closest('.item-body');
      const form = itemBody.querySelector('.decision-form');
      if (!form) return;

      const decision = banner.dataset.decision;
      const overrideDate = banner.dataset.overrideDate || '';
      const overrideStatus = banner.dataset.overrideStatus || '';
      const notes = banner.dataset.notes || '';

      // Select the right radio
      const radio = form.querySelector('input[type="radio"][value="' + decision + '"]');
      if (radio) {{
        radio.checked = true;
        radio.dispatchEvent(new Event('change', {{ bubbles: true }}));
      }}

      // Fill override fields
      const customFields = form.querySelector('.custom-fields');
      const additionOverrides = form.querySelector('.addition-overrides');
      if (customFields && (decision === 'accept_source' || decision === 'custom')) {{
        customFields.style.display = 'flex';
        if (overrideDate) customFields.querySelector('.override-date').value = overrideDate;
        if (overrideStatus) {{
          const sel = customFields.querySelector('.override-status');
          if (sel) sel.value = overrideStatus;
        }}
      }}
      if (additionOverrides && decision === 'add') {{
        additionOverrides.style.display = 'flex';
        if (overrideDate) additionOverrides.querySelector('.override-date').value = overrideDate;
        if (overrideStatus) {{
          const sel = additionOverrides.querySelector('.override-status');
          if (sel) sel.value = overrideStatus;
        }}
      }}

      // Fill notes
      const notesInput = form.querySelector('.notes-input');
      if (notesInput && notes) notesInput.value = notes;

      // Trigger YAML regeneration
      const changeEvent = new Event('input', {{ bubbles: true }});
      if (notesInput) notesInput.dispatchEvent(changeEvent);

      btn.textContent = 'Accepted!';
      btn.classList.add('accepted');
    }});
  }});

  document.getElementById('copy-all-btn').addEventListener('click', () => {{
    const snippets = [];
    document.querySelectorAll('.yaml-output pre').forEach(pre => {{
      const text = pre.textContent.trim();
      if (text) snippets.push(text);
    }});
    if (snippets.length === 0) {{
      document.getElementById('copy-all-status').textContent = 'No decisions to copy';
      return;
    }}
    const combined = snippets.join('\\n\\n') + '\\n';
    navigator.clipboard.writeText(combined).then(() => {{
      const btn = document.getElementById('copy-all-btn');
      const status = document.getElementById('copy-all-status');
      btn.textContent = 'Copied!';
      btn.classList.add('copied');
      status.textContent = snippets.length + ' entries';
      setTimeout(() => {{ btn.textContent = 'Copy all YAML'; btn.classList.remove('copied'); }}, 1500);
    }});
  }});
}});
</script>
</body>
</html>"""


def _render_item(item: dict) -> str:
    item_type = item["type"]
    decision = item.get("decision")
    resolved_class = " resolved" if decision else ""

    # Build summary line for the <details> element
    type_label = item_type.replace("_", " ")
    if item_type == "discrepancy":
        summary_text = f'CSV row {item["csv_row"]}: {escape(item["csv_date"])} {escape(item["csv_status"])}'
    elif item_type == "candidate_addition":
        summary_text = f'{escape(item["date"])} {escape(item["new_status"])}'
    elif item_type == "unsupported":
        summary_text = f'CSV row {item["csv_row"]}: {escape(item["csv_date"])} {escape(item["csv_status"])}'
    else:
        summary_text = ""

    resolved_tag = ""
    if decision:
        resolved_tag = f' <span class="badge resolved">{escape(decision.get("decision", ""))}</span>'

    item_open = "" if decision else " open"
    parts = [f'<details class="item{resolved_class}"{item_open}>']
    parts.append(f'<summary><span class="item-type {item_type}">{type_label}</span> {summary_text}{resolved_tag}</summary>')
    parts.append('<div class="item-body">')

    if decision:
        d = escape(decision.get("decision", ""))
        n = escape(decision.get("notes", ""))
        parts.append(f'<div class="decision-banner"><strong>Resolved:</strong> {d}. {n}</div>')

    if item_type == "discrepancy":
        parts.append('<div class="field-row">')
        parts.append(f'<div class="field"><div class="label">Field</div><div class="value">{escape(item["field"])}</div></div>')
        parts.append(f'<div class="field"><div class="label">CSV value</div><div class="value csv">{escape(str(item["csv_value"]))}</div></div>')
        parts.append(f'<div class="field"><div class="label">Source value</div><div class="value source">{escape(str(item["extracted_value"]))}</div></div>')
        parts.append(f'<div class="field"><div class="label">Assessment</div><div class="value">{escape(item["assessment"])}</div></div>')
        parts.append('</div>')
        if item.get("reasoning"):
            parts.append(f'<div class="reasoning">{escape(item["reasoning"])}</div>')

    elif item_type == "candidate_addition":
        if item.get("event_description"):
            parts.append(f'<div class="notes">{escape(item["event_description"])}</div>')
        if item.get("notes"):
            parts.append(f'<div class="reasoning">{escape(item["notes"])}</div>')

    elif item_type == "unsupported":
        if item.get("notes"):
            parts.append(f'<div class="reasoning">{escape(item["notes"])}</div>')

    # Source citations
    for src in item.get("sources", []):
        parts.append('<div class="source-block">')
        parts.append(f'<div class="source-label">{escape(src["source_type"].upper())}</div>')
        if src.get("quote"):
            parts.append(f'<div class="quote">{escape(src["quote"])}</div>')
        if src.get("context"):
            parts.append(f'<div class="context">{escape(src["context"])}</div>')
        parts.append('</div>')

    # Interactive decision form
    if not decision:
        suggestion = item.get("suggestion")
        if suggestion:
            parts.append(_render_suggestion_banner(suggestion))
        parts.append(_render_decision_form(item))

    parts.append('</div>')  # close .item-body
    parts.append('</details>')
    return "\n".join(parts)


def _render_suggestion_banner(suggestion: dict) -> str:
    """Render a suggestion banner with an accept button."""
    choice = escape(suggestion.get("decision", ""))
    notes = escape(suggestion.get("notes", ""))
    override_date = escape(suggestion.get("override_date", ""), quote=True)
    override_status = escape(suggestion.get("override_status", ""), quote=True)

    # Build the YAML preview
    lines = []
    lines.append(f'- country: "{suggestion.get("country", "")}"')
    if suggestion.get("type") == "addition":
        lines.append(f'  type: addition')
        lines.append(f'  date: "{suggestion.get("date", "")}"')
    else:
        lines.append(f'  csv_row: {suggestion.get("csv_row", "")}')
    lines.append(f'  decision: {suggestion.get("decision", "")}')
    if suggestion.get("override_date"):
        lines.append(f'  override_date: "{suggestion["override_date"]}"')
    if suggestion.get("override_status"):
        lines.append(f'  override_status: "{suggestion["override_status"]}"')
    if suggestion.get("entries"):
        lines.append("  entries:")
        for entry in suggestion["entries"]:
            lines.append(f'    - date: "{entry.get("date", "")}"')
            lines.append(f'      status: "{entry.get("status", "")}"')
    if suggestion.get("notes"):
        lines.append(f'  notes: "{suggestion["notes"]}"')
    yaml_text = "\n".join(lines)

    return f"""<div class="suggestion-banner"
  data-decision="{choice}"
  data-override-date="{override_date}"
  data-override-status="{override_status}"
  data-notes="{escape(suggestion.get('notes', ''), quote=True)}">
  <div class="suggestion-header"><strong>Suggested:</strong> {choice}. {notes}</div>
  <pre class="suggestion-yaml">{escape(yaml_text)}</pre>
  <button type="button" class="accept-suggestion-btn">Accept suggestion</button>
</div>"""


_form_counter = 0


def _next_form_id() -> str:
    global _form_counter
    _form_counter += 1
    return f"form-{_form_counter}"


def _render_decision_form(item: dict) -> str:
    item_type = item["type"]
    form_id = _next_form_id()

    # Encode item metadata as data attributes for JS
    country = escape(item.get("country", ""), quote=True)

    if item_type == "discrepancy":
        csv_row = item.get("csv_row", "")
        csv_value = escape(str(item.get("csv_value", "")), quote=True)
        extracted_value = escape(str(item.get("extracted_value", "")), quote=True)
        field = escape(item.get("field", ""), quote=True)
        csv_date = escape(item.get("csv_date", ""), quote=True)
        csv_status = escape(item.get("csv_status", ""), quote=True)
        source_date = escape(item.get("source_date", ""), quote=True)
        source_status = escape(item.get("source_status", ""), quote=True)

        return f"""<div class="decision-form" id="{form_id}"
  data-type="discrepancy" data-country="{country}" data-csv-row="{csv_row}"
  data-field="{field}" data-csv-value="{csv_value}" data-extracted-value="{extracted_value}"
  data-csv-date="{csv_date}" data-csv-status="{csv_status}"
  data-source-date="{source_date}" data-source-status="{source_status}">
  <div class="radio-group">
    <label><input type="radio" name="{form_id}" value="accept_csv"> Accept CSV value</label>
    <label><input type="radio" name="{form_id}" value="accept_source"> Accept source value</label>
    <label><input type="radio" name="{form_id}" value="custom"> Custom override</label>
    <label><input type="radio" name="{form_id}" value="split"> Split into multiple</label>
    <label><input type="radio" name="{form_id}" value="remove"> Remove</label>
  </div>
  <div class="custom-fields" style="display:none">
    <input type="text" class="override-date" placeholder="override_date (e.g. 1995-02-21)">
    {STATUS_SELECT}
  </div>
  <div class="split-fields" style="display:none">
    <div class="split-entries">
      <div class="split-entry">
        <input type="text" class="split-date" placeholder="date">
        {SPLIT_STATUS_SELECT}
      </div>
      <div class="split-entry">
        <input type="text" class="split-date" placeholder="date">
        {SPLIT_STATUS_SELECT}
      </div>
    </div>
    <button type="button" class="add-split-entry">+ entry</button>
  </div>
  <input type="text" class="notes-input" placeholder="notes">
  <div class="yaml-output"><pre></pre></div>
  <button type="button" class="copy-btn" style="display:none">Copy YAML</button>
  <button type="button" class="clear-btn" style="display:none">Clear</button>
</div>"""

    elif item_type == "candidate_addition":
        date = escape(item.get("date", ""), quote=True)
        new_status = escape(item.get("new_status", ""), quote=True)

        return f"""<div class="decision-form" id="{form_id}"
  data-type="candidate_addition" data-country="{country}"
  data-date="{date}" data-new-status="{new_status}">
  <div class="radio-group">
    <label><input type="radio" name="{form_id}" value="add"> Add to dataset</label>
    <label><input type="radio" name="{form_id}" value="reject"> Reject</label>
  </div>
  <div class="addition-overrides" style="display:none">
    <input type="text" class="override-date" placeholder="override date (leave blank to keep)">
    {STATUS_SELECT}
  </div>
  <input type="text" class="notes-input" placeholder="notes">
  <div class="yaml-output"><pre></pre></div>
  <button type="button" class="copy-btn" style="display:none">Copy YAML</button>
  <button type="button" class="clear-btn" style="display:none">Clear</button>
</div>"""

    elif item_type == "unsupported":
        csv_row = item.get("csv_row", "")

        return f"""<div class="decision-form" id="{form_id}"
  data-type="unsupported" data-country="{country}" data-csv-row="{csv_row}">
  <div class="radio-group">
    <label><input type="radio" name="{form_id}" value="keep"> Keep despite no source</label>
    <label><input type="radio" name="{form_id}" value="remove"> Remove</label>
  </div>
  <input type="text" class="notes-input" placeholder="notes">
  <div class="yaml-output"><pre></pre></div>
  <button type="button" class="copy-btn" style="display:none">Copy YAML</button>
  <button type="button" class="clear-btn" style="display:none">Clear</button>
</div>"""

    return ""


def run_audit_report(config: PipelineConfig, countries_filter: list[str] | None = None) -> None:
    """Generate the audit report and print the output path."""
    output_path = generate_audit_html(config, countries_filter)
    print(f"Audit report: {output_path}")
