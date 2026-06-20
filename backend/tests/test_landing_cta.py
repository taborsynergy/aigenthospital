"""
Landing page CTA wiring tests.

Verifies that every call-to-action button on index.html calls the correct
JavaScript handler — demo/trial buttons open the signup flow, and only
explicitly white-label / enterprise entry points open the quote form.

REG-009: "Book a Demo" and "Book a Live Demo" must NOT open the white-label
         quote modal — they must open the trial signup modal so visitors can
         choose any plan, not be funnelled straight to white-label quoting.
"""
import pathlib
import pytest

INDEX_HTML = (
    pathlib.Path(__file__).parent.parent.parent / "frontend" / "index.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── REG-009: Demo buttons must open signup, not quote modal ─────────────────

class TestDemoButtonsOpenSignup:

    def test_nav_book_a_demo_calls_open_signup(self, html):
        """REG-009-A: Nav 'Book a Demo' button must call openSignup(), not openQuoteForm()."""
        assert "btn-nav-demo" in html, "Nav demo button class missing"
        # Search for the actual button element (skip the CSS rule which appears first)
        idx = html.index('<button class="btn-nav-demo"')
        snippet = html[idx: idx + 200]
        assert "openSignup" in snippet, (
            "REG-009-A: Nav 'Book a Demo' button calls openQuoteForm() instead of "
            "openSignup(). Demo visitors should enter the trial signup flow, not "
            "the white-label quote form."
        )
        assert "openQuoteForm" not in snippet, (
            "REG-009-A: Nav 'Book a Demo' button must not call openQuoteForm()."
        )

    def test_hero_book_a_live_demo_calls_open_signup(self, html):
        """REG-009-B: Hero 'Book a Live Demo' button must call openSignup(), not openQuoteForm()."""
        assert "Book a Live Demo" in html, "'Book a Live Demo' text missing from hero"
        idx = html.index("Book a Live Demo")
        # Walk back to find the button tag that contains this text
        btn_start = html.rfind("<button", 0, idx)
        snippet = html[btn_start: idx + 20]
        assert "openSignup" in snippet, (
            "REG-009-B: Hero 'Book a Live Demo' button calls openQuoteForm() instead "
            "of openSignup(). Demo visitors should see the trial signup modal."
        )
        assert "openQuoteForm" not in snippet, (
            "REG-009-B: Hero 'Book a Live Demo' button must not open the quote form."
        )

    def test_demo_buttons_default_to_professional_plan(self, html):
        """REG-009-C: Demo buttons must pre-select the professional (Growth) plan."""
        # nav demo button (skip CSS rule, find button element)
        idx = html.index('<button class="btn-nav-demo"')
        nav_snippet = html[idx: idx + 200]
        assert "professional" in nav_snippet, (
            "REG-009-C: Nav demo button should open signup with 'professional' plan."
        )
        # hero demo button
        idx2 = html.index("Book a Live Demo")
        btn_start = html.rfind("<button", 0, idx2)
        hero_snippet = html[btn_start: idx2 + 20]
        assert "professional" in hero_snippet, (
            "REG-009-C: Hero demo button should open signup with 'professional' plan."
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
