---
name: assessmentpage_button_color
description: >
  Change the background/text color of a button on the Assessment page —
  the header Log Out button, or any step's Save/Back/Proceed/Submit button.
file: frontend/src/components/AssessmentPage.jsx
change_type: change_color
elements:
  - selector: .logout-btn
    label: "Log Out button (page header)"
    approx_line: 889
  - selector: .secondary-btn
    label: "Back / Save Progress buttons (appears on every step, 4 occurrences)"
    approx_line: 1205
  - selector: .primary-btn
    label: "Save buttons (Review Observations & Action Plan steps, 2 occurrences, plus a modal-close use at ~2367)"
    approx_line: 2103
  - selector: .submit-btn
    label: "Proceed/forward buttons (appears on every step, 3 occurrences; the Review->Action Plan one also carries an extra `obs-footer-cta` class)"
    approx_line: 1209
---

## Steps
1. Read `frontend/src/components/AssessmentPage.jsx`.
2. Match the request's element wording (e.g. "submit button", "logout button", "back button") against the `elements` list above to pick the target CSS class.
3. Search the file for that class — several of these classes are reused across all 4 wizard steps (`ASSESSMENT` / `UPLOAD_DOCUMENTS` / `REVIEW_OBSERVATIONS` / `ACTION_PLAN`); use the request's wording (which step, which action) to pick the right occurrence, or report all matching occurrences if it can't be narrowed down from the request alone.
4. The actual color is controlled by that class's rule in `frontend/src/index.css` — a shared/global stylesheet, not page-local — not by anything in this file directly. Locate the exact rule there (e.g. `.submit-btn { ... }`) and its color-related property (`background`, `background-color`, or `color`).
5. Report: the CSS file, the rule's line range, its current color-related property/value, which JSX line(s) in `AssessmentPage.jsx` use that class, and whether the class is shared with other buttons (changing it affects all of them). Do NOT edit anything.
