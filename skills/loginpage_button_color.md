---
name: loginpage_button_color
description: Change the background/text color of the Sign In button on the login page.
file: frontend/src/components/LoginPage.jsx
change_type: change_color
elements:
  - selector: .login-btn
    label: "Sign In to Assessment button"
    approx_line: 103
---

## Steps
1. Read `frontend/src/components/LoginPage.jsx`.
2. The button is `<button type="submit" className="login-btn">` at line 103.
3. The color is controlled by the `.login-btn` rule in `frontend/src/index.css` — a shared/global stylesheet — not by anything in this file directly. Locate the exact rule there and its color-related property (`background`, `background-color`, or `color`).
4. Report: the CSS file, the rule's line range, its current color-related property/value, and whether `.login-btn` is used anywhere else (making it shared) or only here. Do NOT edit anything.
