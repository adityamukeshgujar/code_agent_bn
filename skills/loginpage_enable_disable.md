---
name: loginpage_enable_disable
description: >
  Enable or disable the Sign In button on the login page — e.g. only allow
  submitting once all fields are filled in.
file: frontend/src/components/LoginPage.jsx
change_type: enable_disable
elements:
  - selector: .login-btn
    label: "Sign In to Assessment button — no existing disabled logic"
    approx_line: 103
---

## Steps
1. Read `frontend/src/components/LoginPage.jsx`.
2. The button at line 103 has no `disabled` attribute today — validation only happens on submit, inside `handleSubmit` (lines 10-35), which checks `username`/`employeeId`/`password` and sets an error message rather than preventing the click.
3. To gate the button itself (rather than validating on submit), the state already needed is available: `username`, `employeeId`, `password` (declared via `useState` at lines 5-7) — a disabled condition would be something like `disabled={!username.trim() || !employeeId.trim() || !password}`.
4. Report: file path, the button's line, its current (missing) disabled state, and which existing state variables a disabled condition would read. Do NOT edit anything.
