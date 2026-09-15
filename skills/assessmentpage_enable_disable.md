---
name: assessmentpage_enable_disable
description: >
  Enable or disable a button on the Assessment page — e.g. only allow
  proceeding to the next step once required fields/criteria are complete.
file: frontend/src/components/AssessmentPage.jsx
change_type: enable_disable
elements:
  - selector: .submit-btn (handleProceedToReview)
    label: "Proceed to Review Observations button — no existing disabled logic"
    approx_line: 1417
  - selector: .submit-btn (setCurrentStep('ACTION_PLAN'))
    label: "Generate Action Plan button — no existing disabled logic"
    approx_line: 2107
  - selector: .primary-btn / .secondary-btn (handleSave)
    label: "Save / Save Progress / Save Action Plan buttons — no existing disabled logic"
    approx_line: 1205
---

## Steps
1. Read `frontend/src/components/AssessmentPage.jsx`.
2. Match the request's wording against the `elements` list above to pick the target button.
3. None of this page's buttons currently have a `disabled` attribute at all — confirm that by checking the matched line and its surrounding JSX.
4. Check for a nearby completion signal that could gate it: each policy item already computes `isFullyAnswered = answeredCount >= totalCriteria` locally inside the `.map()` loop (~line 1048), but there is no existing aggregate ("are ALL items fully answered") computed for the step as a whole — that would need to be added (e.g. `items.every(item => ...)`) before it could drive a button's `disabled` prop.
5. Report: file path, the button's line, its current (missing) disabled state, and what condition/aggregate would need to exist to gate it — do NOT edit anything.
