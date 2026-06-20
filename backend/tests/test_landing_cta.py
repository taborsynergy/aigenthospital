"""
Landing page CTA wiring tests.

Verifies that every call-to-action button on index.html calls the correct
JavaScript handler — demo/trial buttons open the dedicated demo-request form,
pricing/trial buttons open the signup flow, and only explicitly white-label /
enterprise entry points open the quote form.

REG-009: "Book a Demo" and "Book a Live Demo" must NOT open the trial signup
         modal or the white-label quote modal — they must open the dedicated
         demo-request modal (openDemoForm) so visitors fill in their details
         and receive a personalised demo booking.
"""
import pathlib
import pytest

INDEX_HTML = (
    pathlib.Path(__file__).parent.parent.parent / "frontend" / "index.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── REG-009: Demo buttons must open the demo-request modal ──────────────────

class TestDemoButtonsOpenDemoForm:

    def test_nav_book_a_demo_calls_open_demo_form(self, html):
        """REG-009-A: Nav 'Book a Demo' button must call openDemoForm(), not openSignup/openQuoteForm."""
        assert "btn-nav-demo" in html, "Nav demo button class missing"
        # Skip the CSS rule — find the actual button element; read only to its closing tag
        idx = html.index('<button class="btn-nav-demo"')
        end = html.index('</button>', idx) + 9
        snippet = html[idx:end]
        assert "openDemoForm" in snippet, (
            "REG-009-A: Nav 'Book a Demo' must call openDemoForm() to open the "
            "dedicated demo-request lead capture form."
        )
        assert "openQuoteForm" not in snippet, (
            "REG-009-A: Nav 'Book a Demo' must not open the white-label quote form."
        )
        assert "openSignup" not in snippet, (
            "REG-009-A: Nav 'Book a Demo' must not open the trial signup form."
        )

    def test_hero_book_a_live_demo_calls_open_demo_form(self, html):
        """REG-009-B: Hero 'Book a Live Demo' must call openDemoForm()."""
        assert "Book a Live Demo" in html, "'Book a Live Demo' text missing from hero"
        idx = html.index("Book a Live Demo")
        btn_start = html.rfind("<button", 0, idx)
        snippet = html[btn_start: idx + 20]
        assert "openDemoForm" in snippet, (
            "REG-009-B: Hero 'Book a Live Demo' must call openDemoForm()."
        )
        assert "openQuoteForm" not in snippet, (
            "REG-009-B: Hero demo button must not open the white-label quote form."
        )
        assert "openSignup" not in snippet, (
            "REG-009-B: Hero demo button must not open the trial signup form."
        )

    def test_demo_modal_exists(self, html):
        """REG-009-C: demo-modal overlay must be present in the page."""
        assert 'id="demo-modal"' in html, "demo-modal overlay div is missing"

    def test_demo_success_modal_exists(self, html):
        """REG-009-D: demo-success-modal must be present for post-submit feedback."""
        assert 'id="demo-success-modal"' in html, "demo-success-modal div is missing"

    def test_open_demo_form_js_defined(self, html):
        """REG-009-E: openDemoForm() JS function must be defined."""
        assert "function openDemoForm(" in html, "openDemoForm() function missing from page JS"

    def test_submit_demo_request_js_defined(self, html):
        """REG-009-F: submitDemoRequest() JS function must be defined."""
        assert "function submitDemoRequest(" in html, "submitDemoRequest() function missing"

    def test_demo_form_posts_to_correct_endpoint(self, html):
        """REG-009-G: submitDemoRequest must POST to /api/demo-request."""
        assert '"/api/demo-request"' in html, (
            "submitDemoRequest must POST to /api/demo-request"
        )


# ── White-label and enterprise entry points must still open quote form ───────

class TestWhiteLabelEntryPointsOpenQuoteForm:

    def test_enterprise_nav_link_opens_quote_form(self, html):
        """Enterprise nav link must still open the white-label quote form."""
        assert "Enterprise" in html
        idx = html.index(">Enterprise<")
        # Walk back to find the anchor tag
        a_start = html.rfind("<a", 0, idx)
        snippet = html[a_start: idx + 15]
        assert "openQuoteForm" in snippet, (
            "Enterprise nav link must open the quote form."
        )

    def test_white_label_pricing_card_get_quote_opens_quote_form(self, html):
        """White Label pricing card 'Get a Quote' button must open the quote form."""
        assert "Get a Quote" in html
        idx = html.index("Get a Quote")
        btn_start = html.rfind("<button", 0, idx)
        snippet = html[btn_start: idx + 15]
        assert "openQuoteForm" in snippet, (
            "White Label 'Get a Quote' button must open the quote form, not signup."
        )

    def test_talk_to_sales_opens_quote_form(self, html):
        """Bottom CTA 'Talk to Sales' button must open the quote form."""
        assert "Talk to Sales" in html
        idx = html.index("Talk to Sales")
        btn_start = html.rfind("<button", 0, idx)
        snippet = html[btn_start: idx + 15]
        assert "openQuoteForm" in snippet, (
            "'Talk to Sales' button must open the quote form."
        )

    def test_footer_white_label_link_opens_quote_form(self, html):
        """Footer 'White Label' link must open the quote form."""
        assert "White Label" in html
        idx = html.index(">White Label<")
        a_start = html.rfind("<a", 0, idx)
        snippet = html[a_start: idx + 15]
        assert "openQuoteForm" in snippet, (
            "Footer 'White Label' link must open the quote form."
        )


# ── Pricing plan buttons must open signup ───────────────────────────────────

class TestPricingButtonsOpenSignup:

    def test_starter_plan_cta_opens_signup(self, html):
        """Starter pricing button must call openSignup('starter')."""
        assert "openSignup('starter')" in html, (
            "Starter plan button must call openSignup('starter')."
        )

    def test_professional_plan_cta_opens_signup(self, html):
        """Growth (professional) pricing button must call openSignup('professional')."""
        assert "openSignup('professional')" in html, (
            "Growth plan button must call openSignup('professional')."
        )

    def test_enterprise_plan_cta_opens_signup(self, html):
        """Pro (enterprise) pricing button must call openSignup('enterprise')."""
        assert "openSignup('enterprise')" in html, (
            "Pro plan button must call openSignup('enterprise')."
        )

    def test_start_free_trial_nav_button_opens_signup(self, html):
        """Nav 'Start Free Trial' button must call openSignup()."""
        assert "btn-nav-trial" in html
        # Skip CSS rule, find button element directly
        idx = html.index('<button class="btn-nav-trial"')
        snippet = html[idx: idx + 200]
        assert "openSignup" in snippet, (
            "Nav 'Start Free Trial' button must call openSignup()."
        )

    def test_hero_start_free_trial_opens_signup(self, html):
        """Hero 'Start Free 14-Day Trial' button must call openSignup()."""
        assert "Start Free" in html
        idx = html.index("Start Free")
        btn_start = html.rfind("<button", 0, idx)
        snippet = html[btn_start: idx + 30]
        assert "openSignup" in snippet, (
            "Hero primary CTA must call openSignup()."
        )


# ── Signup modal must exist with correct IDs ─────────────────────────────────

class TestSignupModalPresent:

    def test_signup_modal_exists(self, html):
        """signup-modal overlay div must be present."""
        assert 'id="signup-modal"' in html

    def test_quote_modal_exists(self, html):
        """quote-modal overlay div must be present."""
        assert 'id="quote-modal"' in html

    def test_signup_form_has_plan_field(self, html):
        """Signup form must contain hidden plan input so openSignup(plan) works."""
        assert 'id="f-plan"' in html
        assert 'type="hidden"' in html

    def test_open_signup_js_function_defined(self, html):
        """openSignup() JavaScript function must be defined in the page."""
        assert "function openSignup(" in html

    def test_open_quote_form_js_function_defined(self, html):
        """openQuoteForm() JavaScript function must be defined in the page."""
        assert "function openQuoteForm(" in html
