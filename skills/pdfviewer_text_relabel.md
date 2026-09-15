---
name: pdfviewer_text_relabel
description: >
  Change/relabel visible text or tooltips in the PDF/document highlight
  viewer — button titles (tooltips) or the "jump to match" label.
file: frontend/src/components/PdfHighlightViewer.jsx
change_type: change_text
elements:
  - selector: title attribute (tooltip, no visible label — icon-only buttons)
    label: "'Previous page' / 'Next page' tooltips"
    approx_line: 503
  - selector: title attribute (tooltip, no visible label — icon-only buttons)
    label: "'Zoom out' / 'Zoom in' tooltips"
    approx_line: 518
  - selector: literal text with one dynamic segment
    label: "'Jump to match (p.{matchPage})' — the prefix 'Jump to match (p.' and suffix ')' are literal, {matchPage} is a variable"
    approx_line: 542
  - selector: title attribute (tooltip)
    label: "'Close viewer' tooltip"
    approx_line: 549
---

## Steps
1. Read `frontend/src/components/PdfHighlightViewer.jsx`.
2. Match the request's wording against the `elements` list above.
3. Most of these buttons are icon-only (no visible label) — their only text is a `title="..."` tooltip attribute. Confirm which kind the request means (tooltip vs. visible label) before assuming.
4. For "Jump to match": only the literal text around `{matchPage}` can be changed safely; `{matchPage}` itself is a page-number variable, not text to relabel.
5. Report: file path, line, current string (and which part is literal vs. dynamic, if applicable). Do NOT edit anything.
