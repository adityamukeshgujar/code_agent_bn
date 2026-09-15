---
name: assessmentpage_text_relabel
description: >
  Change/relabel visible text on the Assessment page — a button's label,
  or the criticality badge shown on each policy card.
file: frontend/src/components/AssessmentPage.jsx
change_type: change_text
elements:
  - selector: literal text
    label: "Log Out (header button)"
    approx_line: 891
  - selector: literal text
    label: "Save Progress (Assessment step footer)"
    approx_line: 1207
  - selector: literal text
    label: "Proceed to Upload Documents (Assessment step footer)"
    approx_line: 1210
  - selector: literal text
    label: "Back to Assessment (Upload Documents step footer)"
    approx_line: 1415
  - selector: literal text
    label: "Proceed to Review Observations (Upload Documents step footer)"
    approx_line: 1418
  - selector: literal text
    label: "Back to Upload (Review Observations step footer)"
    approx_line: 2100
  - selector: literal text
    label: "Save (Review Observations step footer)"
    approx_line: 2105
  - selector: literal text
    label: "Generate Action Plan (Review Observations step footer)"
    approx_line: 2108
  - selector: literal text
    label: "Back to Review Observations (Action Plan step footer)"
    approx_line: 2251
  - selector: literal text
    label: "Save Action Plan (Action Plan step footer)"
    approx_line: 2254
  - selector: data-bound value, NOT literal text
    label: "Criticality badge (shows item.criticalLevel — 'Critical' or 'Non Critical')"
    approx_line: 1058
---

## Steps
1. Read `frontend/src/components/AssessmentPage.jsx`.
2. Match the request's wording against the `elements` list above.
3. For any **literal text** element: the string is hardcoded directly in the JSX at the given line — report that line and the exact current string.
4. For the **criticality badge**: this is NOT a literal string in this file. `{item.criticalLevel}` is bound to data from `frontend/src/data/questionsData.js` (8 records, values `'Critical'` / `'Non Critical'`), and that same value also drives the badge's CSS class via `item.criticalLevel === 'Critical' ? 'critical' : 'non-critical'` on the line just above it. Relabeling this safely means EITHER (a) wrapping the displayed value in a mapping that swaps only the label, leaving the underlying data value and the `=== 'Critical'` comparison untouched, or (b) renaming the data value itself in `questionsData.js` (affects all 8 records and anything else that compares against that exact string). Report both options and which lines/files each touches — do not pick one and do NOT edit anything.
5. Report: file path, line, current text/expression, and what needs to change.
