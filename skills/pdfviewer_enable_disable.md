---
name: pdfviewer_enable_disable
description: >
  Enable or disable a navigation/zoom button in the PDF/document highlight
  viewer — e.g. the page controls already do this, the zoom controls don't yet.
file: frontend/src/components/PdfHighlightViewer.jsx
change_type: enable_disable
elements:
  - selector: disabled={currentPage <= 1}
    label: "Previous page button — ALREADY has real disabled logic"
    approx_line: 503
  - selector: disabled={currentPage >= numPages}
    label: "Next page button — ALREADY has real disabled logic"
    approx_line: 509
  - selector: (no disabled attribute — style-only bounds check)
    label: "Zoom out button — style dims at the scale<=0.6 limit via navBtnStyle(), but stays clickable"
    approx_line: 518
  - selector: (no disabled attribute — style-only bounds check)
    label: "Zoom in button — style dims at the scale>=2.5 limit via navBtnStyle(), but stays clickable"
    approx_line: 522
---

## Steps
1. Read `frontend/src/components/PdfHighlightViewer.jsx`.
2. Match the request's wording against the `elements` list above.
3. If the request is about the page nav buttons: this already exists (`disabled={currentPage <= 1}` / `disabled={currentPage >= numPages}`) — report the current condition as-is; there's nothing to add, only to adjust if the request wants different bounds.
4. If the request is about the zoom buttons: note that `navBtnStyle(scale <= 0.6)` / `navBtnStyle(scale >= 2.5)` already computes the SAME boundary condition used for dimming, but it's only passed to the `style` prop, not to a `disabled` prop — the button is visually dimmed yet still clickable. Making it actually disabled means adding `disabled={scale <= 0.6}` / `disabled={scale >= 2.5}` to those two buttons, reusing the exact expression already being passed to `navBtnStyle()`.
5. Report: file path, the button's line, its current disabled state (present or absent), and the exact boundary expression to use. Do NOT edit anything.
