---
name: loginpage_text_relabel
description: >
  Change/relabel visible text on the login page — the title, subtitle,
  field labels/placeholders, the Sign In button, or a validation error message.
file: frontend/src/components/LoginPage.jsx
change_type: change_text
elements:
  - selector: literal text
    label: "Title: 'AI POLICY REVIEW'"
    approx_line: 44
  - selector: literal text
    label: "Subtitle: 'Accreditation Organization Process Snapshots'"
    approx_line: 45
  - selector: literal text
    label: "Field label 'User Name' / placeholder 'Enter your user name'"
    approx_line: 57
  - selector: literal text
    label: "Field label 'Employee ID' / placeholder 'Enter your employee ID'"
    approx_line: 73
  - selector: literal text
    label: "Field label 'Password'"
    approx_line: 89
  - selector: literal text
    label: "Button text: 'Sign In to Assessment'"
    approx_line: 104
  - selector: literal text (one of 4, chosen by which validation fails)
    label: "Validation error messages: 'Please enter your User Name.' / 'Please enter your Employee ID.' / 'Please enter your Password.' / 'Password must be at least 4 characters long.'"
    approx_line: 15
  - selector: literal text
    label: "Footer: 'Authorized Employee Access Only'"
    approx_line: 110
---

## Steps
1. Read `frontend/src/components/LoginPage.jsx` (it's short — 115 lines, read it in full).
2. Match the request's wording against the `elements` list above — all of these are hardcoded literal strings directly in the JSX (or in `handleSubmit`'s validation branches for the error messages), no data-binding indirection like `AssessmentPage`'s badge.
3. Report: the exact line and current string. Do NOT edit anything.
