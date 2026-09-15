---
name: pdfviewer_button_color
description: >
  Change the color/style of a button in the PDF/document highlight viewer —
  page navigation, zoom, "jump to match", or the close button.
file: frontend/src/components/PdfHighlightViewer.jsx
change_type: change_color
elements:
  - selector: navBtnStyle() helper (shared)
    label: "Prev/Next page buttons and Zoom in/out buttons (4 occurrences) — color comes from a SHARED helper function, not per-button inline styles"
    approx_line: 133
  - selector: inline style object
    label: "'Jump to match (p.N)' button — page-local inline style, not shared"
    approx_line: 529
  - selector: inline style object
    label: "Close viewer button (circular icon button) — page-local inline style, not shared"
    approx_line: 548
---

## Steps
1. Read `frontend/src/components/PdfHighlightViewer.jsx`.
2. Match the request's wording against the `elements` list above.
3. **Prev/Next/Zoom buttons**: these don't set their own inline color — they all call the shared `navBtnStyle(disabled)` function (defined at line 133) via `style={navBtnStyle(...)}`. Changing a color here means editing that one function, which changes it for all 4 buttons at once — flag this as shared/affecting-multiple-elements, do not treat it as a page-local change.
4. **"Jump to match" / "Close viewer"**: each has its own inline `style={{...}}` object at its own call site (~line 529 and ~548 respectively) — genuinely page-local, editing one doesn't affect the other.
5. Report: file, line range of the relevant style object/function, its current color-related propert(ies) (`background`/`color`/`border`), and whether it's shared (navBtnStyle) or page-local. Do NOT edit anything.
