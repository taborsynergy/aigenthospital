"""
Landing page link integrity tests.

Verifies that every link, anchor, section ID, tab ID, modal ID, and JavaScript
function referenced on frontend/index.html is actually present and correctly
wired — so no button or link silently does nothing or goes to a broken target.

Categories:
  LNK-001  Section anchors (in-page #id navigation)
  LNK-002  Nav link hrefs point to existing section IDs
  LNK-003  Footer link hrefs point to existing section IDs
  LNK-004  Announcement bar link
  LNK-005  Specialty tab IDs (switchTab targets)
  LNK-006  Modal IDs (all four modals present)
  LNK-007  All required JS functions defined
  LNK-008  Mailto links are properly formed
  LNK-009  Bare href="#" links always have onclick handlers
  LNK-010  External image/resource src attributes are valid URLs
  LNK-011  No broken internal JS calls (every onclick references a defined fn)
  LNK-012  Form element IDs referenced in JS exist in HTML
"""
import pathlib
import re
import pytest

INDEX_HTML = (
    pathlib.Path(__file__).parent.parent.parent / "frontend" / "index.html"
)

REQUIRED_SECTION_IDS = [
    "features",
    "how-it-works",
    "specialties",
    "pricing",
]

REQUIRED_TAB_IDS = [
    "tab-dental",
    "tab-pediatrics",
    "tab-familymed",
    "tab-derm",
    "tab-urgentcare",
    "tab-obgyn",
]

REQUIRED_MODAL_IDS = [
    "signup-modal",
    "quote-modal",
    "quote-success-modal",
    "success-modal",
]

REQUIRED_JS_FUNCTIONS = [
    "function openSignup(",
    "function closeSignup(",
    "function openQuoteForm(",
    "function closeQuoteForm(",
    "function closeQuoteSuccess(",
    "function closeSuccess(",
    "function switchTab(",
    "function submitSignup(",
    "function submitQuote(",
    "function showSignupError(",
]

REQUIRED_FORM_ELEMENT_IDS = [
    "f-name",
    "f-email",
    "f-password",
    "f-specialty",
    "f-phone",
    "f-plan",
    "signup-submit-btn",
    "signup-error-msg",
    "signup-plan-tag",
    "quote-form",
    "quote-submit-btn",
    "success-url",
    "success-open-btn",
    "success-paypal-btn",
    "success-trial-end",
    "success-login-email",
    "success-plan-label",
    "quote-reply-email",
]

ALLOWED_MAILTO = "admin@tabor.taborsynergy.com"


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── LNK-001: Section anchors exist ──────────────────────────────────────────

class TestSectionAnchors:

    @pytest.mark.parametrize("section_id", REQUIRED_SECTION_IDS)
    def test_section_id_exists(self, html, section_id):
        """LNK-001: Every in-page anchor target must have a matching id= attribute."""
        assert f'id="{section_id}"' in html, (
            f"LNK-001: Section id=\"{section_id}\" not found. "
            f"Nav/footer links pointing to #{section_id} will silently do nothing."
        )

    def test_main_nav_element_exists(self, html):
        """LNK-001: <nav id='main-nav'> must exist for scroll-effect JS."""
        assert 'id="main-nav"' in html, "<nav id='main-nav'> missing — scroll effect JS will throw."


# ── LNK-002: Nav links point to real sections ────────────────────────────────

class TestNavLinks:

    def test_nav_features_link(self, html):
        """LNK-002: Nav 'Features' href=#features."""
        assert 'href="#features"' in html

    def test_nav_how_it_works_link(self, html):
        """LNK-002: Nav 'How It Works' href=#how-it-works."""
        assert 'href="#how-it-works"' in html

    def test_nav_specialties_link(self, html):
        """LNK-002: Nav 'Specialties' href=#specialties."""
        assert 'href="#specialties"' in html

    def test_nav_pricing_link(self, html):
        """LNK-002: Nav 'Pricing' href=#pricing."""
        assert 'href="#pricing"' in html

    def test_nav_enterprise_link_has_onclick(self, html):
        """LNK-002: Nav 'Enterprise' bare # link must have openQuoteForm onclick."""
        # Find href="#" followed by onclick with openQuoteForm in the nav area
        assert re.search(r'href="#"\s+onclick="openQuoteForm', html), (
            "LNK-002: Enterprise nav link (href='#') must have onclick openQuoteForm."
        )


# ── LNK-003: Footer links point to real sections ────────────────────────────

class TestFooterLinks:

    def test_footer_features_link(self, html):
        """LNK-003: Footer 'Features' href=#features."""
        # footer has multiple #features hrefs — ensure at least one in footer region
        footer_idx = html.index("<footer")
        footer_html = html[footer_idx:]
        assert 'href="#features"' in footer_html, (
            "LNK-003: Footer 'Features' link missing or wrong href."
        )

    def test_footer_how_it_works_link(self, html):
        """LNK-003: Footer 'How It Works' href=#how-it-works."""
        footer_idx = html.index("<footer")
        footer_html = html[footer_idx:]
        assert 'href="#how-it-works"' in footer_html

    def test_footer_specialties_link(self, html):
        """LNK-003: Footer 'Specialties' href=#specialties."""
        footer_idx = html.index("<footer")
        footer_html = html[footer_idx:]
        assert 'href="#specialties"' in footer_html

    def test_footer_pricing_link(self, html):
        """LNK-003: Footer 'Pricing' href=#pricing."""
        footer_idx = html.index("<footer")
        footer_html = html[footer_idx:]
        assert 'href="#pricing"' in footer_html

    def test_footer_white_label_has_onclick(self, html):
        """LNK-003: Footer 'White Label' bare # link must have openQuoteForm onclick."""
        footer_idx = html.index("<footer")
        footer_html = html[footer_idx:]
        assert "openQuoteForm" in footer_html, (
            "LNK-003: Footer 'White Label' link must call openQuoteForm()."
        )


# ── LNK-004: Announcement bar link ───────────────────────────────────────────

class TestAnnouncementBar:

    def test_announcement_bar_exists(self, html):
        """LNK-004: Announcement bar element must be present."""
        assert 'class="announce-bar"' in html

    def test_announcement_bar_link_has_target(self, html):
        """LNK-004: Announcement bar link must navigate to #pricing section."""
        bar_idx = html.index('class="announce-bar"')
        bar_html = html[bar_idx: bar_idx + 400]
        assert "pricing" in bar_html, (
            "LNK-004: Announcement bar link must reference #pricing."
        )


# ── LNK-005: Specialty tab IDs and switchTab calls ──────────────────────────

class TestSpecialtyTabs:

    @pytest.mark.parametrize("tab_id", REQUIRED_TAB_IDS)
    def test_tab_content_div_exists(self, html, tab_id):
        """LNK-005: Every tab content div referenced by switchTab() must exist."""
        assert f'id="{tab_id}"' in html, (
            f"LNK-005: Tab div id=\"{tab_id}\" missing. "
            f"switchTab() will fail silently when this specialty is clicked."
        )

    @pytest.mark.parametrize("tab_id", REQUIRED_TAB_IDS)
    def test_tab_pill_references_tab_id(self, html, tab_id):
        """LNK-005: Each tab pill onclick must reference its matching tab div ID."""
        tab_name = tab_id.replace("tab-", "")
        assert f"switchTab(this,'{tab_name}')" in html, (
            f"LNK-005: No tab pill calling switchTab(this,'{tab_name}') found."
        )

    def test_switch_tab_function_defined(self, html):
        """LNK-005: switchTab() JS function must be defined."""
        assert "function switchTab(" in html


# ── LNK-006: All modal overlays present ─────────────────────────────────────

class TestModalPresence:

    @pytest.mark.parametrize("modal_id", REQUIRED_MODAL_IDS)
    def test_modal_overlay_exists(self, html, modal_id):
        """LNK-006: Every modal overlay div must be present with correct id."""
        assert f'id="{modal_id}"' in html, (
            f"LNK-006: Modal id=\"{modal_id}\" not found. "
            f"Any button targeting this modal will open nothing."
        )

    @pytest.mark.parametrize("modal_id", REQUIRED_MODAL_IDS)
    def test_modal_has_close_button(self, html, modal_id):
        """LNK-006: Every modal must have a close button."""
        modal_start = html.index(f'id="{modal_id}"')
        # Look at the next 600 chars for a modal-close button
        snippet = html[modal_start: modal_start + 600]
        assert 'modal-close' in snippet, (
            f"LNK-006: Modal \"{modal_id}\" is missing a close button — users can't dismiss it."
        )

    def test_signup_modal_has_overlay_click_close(self, html):
        """LNK-006: Signup modal overlay click must close the modal."""
        assert 'onclick="if(event.target===this)closeSignup()"' in html

    def test_quote_modal_has_overlay_click_close(self, html):
        """LNK-006: Quote modal overlay click must close the modal."""
        assert 'onclick="if(event.target===this)closeQuoteForm()"' in html

    def test_success_modal_has_overlay_click_close(self, html):
        """LNK-006: Success modal overlay click must close the modal."""
        assert 'onclick="if(event.target===this)closeSuccess()"' in html


# ── LNK-007: JS functions defined ───────────────────────────────────────────

class TestJSFunctionsDefined:

    @pytest.mark.parametrize("fn_signature", REQUIRED_JS_FUNCTIONS)
    def test_js_function_defined(self, html, fn_signature):
        """LNK-007: Every JS function called by onclick/onsubmit must be defined."""
        assert fn_signature in html, (
            f"LNK-007: JavaScript function '{fn_signature}...' not defined in page. "
            f"Any element calling it will throw ReferenceError."
        )

    def test_plan_labels_constant_defined(self, html):
        """LNK-007: PLAN_LABELS constant must be defined (used by openSignup)."""
        assert "var PLAN_LABELS" in html

    def test_plan_amounts_constant_defined(self, html):
        """LNK-007: PLAN_AMOUNTS constant must be defined (used by success modal)."""
        assert "var PLAN_AMOUNTS" in html

    def test_paypal_me_constant_defined(self, html):
        """LNK-007: PAYPAL_ME constant must be defined (used in success modal)."""
        assert "var PAYPAL_ME" in html

    def test_intersection_observer_scroll_reveal_present(self, html):
        """LNK-007: IntersectionObserver scroll-reveal block must be present."""
        assert "IntersectionObserver" in html

    def test_scroll_event_listener_present(self, html):
        """LNK-007: window scroll event listener for nav effect must be present."""
        assert "window.addEventListener('scroll'" in html


# ── LNK-008: Mailto links are correctly formed ───────────────────────────────

class TestMailtoLinks:

    def test_all_mailto_links_use_correct_address(self, html):
        """LNK-008: Every mailto: link must use the official support email."""
        mailto_links = re.findall(r'href="mailto:([^"]+)"', html)
        assert len(mailto_links) >= 5, (
            f"LNK-008: Expected at least 5 mailto links, found {len(mailto_links)}."
        )
        for address in mailto_links:
            assert address == ALLOWED_MAILTO, (
                f"LNK-008: Found mailto:{address} — expected {ALLOWED_MAILTO}."
            )

    def test_contact_us_mailto_present(self, html):
        """LNK-008: 'Contact Us' footer link must be a mailto."""
        footer_idx = html.index("<footer")
        footer_html = html[footer_idx:]
        assert f'href="mailto:{ALLOWED_MAILTO}"' in footer_html


# ── LNK-009: Bare href="#" links always have onclick handlers ────────────────

class TestBareHashLinks:

    def test_all_bare_hash_hrefs_have_onclick(self, html):
        """LNK-009: Every href='#' link must have an onclick so it's not a dead link."""
        # IDs whose href starts as "#" intentionally — JS fills them after signup/quote
        js_filled_ids = {"success-open-btn", "success-paypal-btn"}
        pattern = re.compile(r'<a\s[^>]*href="#"[^>]*>', re.IGNORECASE)
        matches = pattern.findall(html)
        for tag in matches:
            # Skip dynamically-filled links (JS sets their href after API response)
            id_match = re.search(r'id="([^"]+)"', tag)
            if id_match and id_match.group(1) in js_filled_ids:
                continue
            assert "onclick" in tag, (
                f"LNK-009: Found bare href='#' link without onclick handler: {tag[:120]}"
            )

    def test_success_modal_dynamic_links_start_as_hash(self, html):
        """LNK-009: Success modal PayPal and Aria Chat links start as # (filled by JS)."""
        # These are legitimately # before JS fills them — verify they have IDs so JS can set them
        assert 'id="success-open-btn"' in html
        assert 'id="success-paypal-btn"' in html


# ── LNK-010: External resource URLs ─────────────────────────────────────────

class TestExternalResources:

    def test_google_fonts_preconnect_present(self, html):
        """LNK-010: Google Fonts preconnect hints must be present."""
        assert 'href="https://fonts.googleapis.com"' in html
        assert 'href="https://fonts.gstatic.com"' in html

    def test_google_fonts_stylesheet_present(self, html):
        """LNK-010: Google Fonts Inter stylesheet must be linked."""
        assert "fonts.googleapis.com/css2?family=Inter" in html

    def test_paypal_logo_src_is_https(self, html):
        """LNK-010: PayPal logo img src must be an https URL."""
        match = re.search(r'src="(https://www\.paypalobjects\.com[^"]+)"', html)
        assert match, "LNK-010: PayPal logo img src missing or not an https URL."
        assert match.group(1).startswith("https://"), (
            "LNK-010: PayPal logo must use https (not http)."
        )

    def test_no_http_external_links(self, html):
        """LNK-010: No http:// (insecure) external resource links."""
        insecure = re.findall(r'(?:href|src)="http://[^"]*"', html)
        assert not insecure, (
            f"LNK-010: Found insecure http:// links: {insecure}"
        )


# ── LNK-011: Every onclick function call is defined ─────────────────────────

class TestOnclickFunctionsExist:

    def _extract_onclick_calls(self, html):
        """Return unique function names called in onclick/onsubmit attributes."""
        calls = re.findall(r'on(?:click|submit)="([^"]+)"', html)
        fn_names = set()
        for call in calls:
            # extract bare function name (ignore event.target checks)
            for fn in re.findall(r'(\w+)\s*\(', call):
                fn_names.add(fn)
        # remove browser built-ins and keywords
        builtins = {
            "if", "document", "event", "return", "window",
            "getElementById", "scrollIntoView", "getItem", "setItem",
            "removeItem", "classList", "localStorage", "target",
        }
        return fn_names - builtins

    def test_all_onclick_functions_are_defined(self, html):
        """LNK-011: Every function called in onclick/onsubmit must be defined in <script>."""
        script_start = html.index("<script>")
        script_html = html[script_start:]

        fn_calls = self._extract_onclick_calls(html)
        missing = []
        for fn in fn_calls:
            # Accept both 'function fn(' definitions and built-in browser methods
            if f"function {fn}(" not in script_html:
                missing.append(fn)

        assert not missing, (
            f"LNK-011: These functions are called in onclick but NOT defined: {sorted(missing)}"
        )


# ── LNK-012: Form element IDs referenced in JS exist in HTML ────────────────

class TestFormElementIds:

    @pytest.mark.parametrize("elem_id", REQUIRED_FORM_ELEMENT_IDS)
    def test_form_element_id_exists(self, html, elem_id):
        """LNK-012: Every element ID referenced in submitSignup/submitQuote JS must exist."""
        assert f'id="{elem_id}"' in html, (
            f"LNK-012: Element id=\"{elem_id}\" missing from HTML. "
            f"JavaScript that calls getElementById('{elem_id}') will return null and throw."
        )
