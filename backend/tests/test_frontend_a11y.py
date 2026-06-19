"""Static accessibility guards (L-1/L-2) — cheap regression checks that run in the
normal pytest suite. The full axe-core + multi-browser audit lives in e2e/
(Playwright) and is documented there; these guards stop the specific issues we
fixed from silently regressing."""
import os
import re
import pathlib

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
INDEX = (FRONTEND / "index.html").read_text(encoding="utf-8")
WIDGET = (FRONTEND / "widget.js").read_text(encoding="utf-8")


def test_html_has_lang_attribute():
    assert re.search(r'<html[^>]*\blang=', INDEX), "<html> must declare a lang for screen readers"


def test_no_faint_text_decoration_none_links():
    # The footer mailto link used rgba(255,255,255,.3) + no underline (failed WCAG
    # contrast AND link-in-text-block). Ensure that exact anti-pattern is gone.
    bad = re.search(r'color:\s*rgba\(255,\s*255,\s*255,\s*\.3\)\s*;\s*text-decoration:\s*none', INDEX)
    assert bad is None, "faint, underline-less link reintroduced (WCAG contrast/link-in-text-block)"


def test_widget_interactive_controls_have_aria_labels():
    # Patient-facing chat widget: launcher, window, input, send, close must be
    # labelled — either as an inline attribute or via setAttribute("aria-label", …).
    for label in ["Open Aria chat", "Aria chat window", "Message", "Send message", "Close chat"]:
        inline = f'aria-label="{label}"' in WIDGET
        scripted = f'"aria-label", "{label}"' in WIDGET
        assert inline or scripted, f"widget control missing accessible label: {label}"


def test_emergency_banner_present_in_widget():
    # Safety affordance (911 banner) must remain in the widget UI.
    assert "aria-911-banner" in WIDGET
