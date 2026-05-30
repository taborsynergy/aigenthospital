# Bug Report - Aigenthospital Application

## Critical Bugs

1.  **Administrative Panel Unauthorized Access (Authentication Failure):** Admin routes consistently fail with a 401 Unauthorized error, even with the "admin123" password. This prevents access to all administrative functionalities.
2.  **Hardcoded Default Admin Password:** The presence of `admin_password: str = "admin123"` in `backend/config.py` is a severe security vulnerability, allowing anyone to guess the password and gain full admin access if the environment variable loading issue were ever resolved without changing this default.

## High Priority Bugs

1.  **Environment Variable Masking/Loading Failure for `ADMIN_PASSWORD`:** The environment (specifically `pydantic-settings` interaction with the execution shell) is masking the supplied `ADMIN_PASSWORD` (e.g., to `***`), causing authentication to fail even when the correct value is provided. This prevents secure configuration during deployment.
2.  **Lack of Automated Testing:** Absence of unit, integration, and E2E tests means any changes can introduce regressions without detection, critically impacting reliability and maintainability.

## Medium Priority Bugs

1.  **Monolithic Mock Response Logic:** The `mock_responses.py` uses a single `mock_chat` function with cascading `if/elif` statements. This brittle keyword-matching approach is prone to errors, hard to scale, and makes mock behavior less predictable.
2.  **Inline HTML/CSS in Backend Code:** The `clinic_page` route generating HTML directly within `backend/main.py` is an anti-pattern that hinders maintainability, separate UI development, and is difficult to properly test.

## Low Priority Bugs

1.  **Predictable Admin Panel Path:** The default `/ts-mgmt` path, while configurable, offers no security by obscurity.
2.  **Inconsistent Frontend Asset Loading:** A "QR Code" image was detected by `browser_get_images` on the login page but not visually rendered, indicating a potential mismatch or deferred loading strategy.
