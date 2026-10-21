"""F7 (live round, 2026-10-21): a cookie notice was left covering turing.ac.uk.
HandOff closes cookie notices itself, choosing the "reject" or "only necessary"
button. It never accepts on the user's behalf."""

from app.browser.page_view import cookie_notice_button
from tests.fakes import FakeCaller, FakePageBrowser, action_reply, page
from tests.test_page_step import start

TURING = page("https://www.turing.ac.uk/", ("link", "Events"), ("button", "I Accept Cookies"),
              ("button", "I Do Not Accept Cookies"), ("link", "cookie notice here"))
GOOGLE_CONSENT = {**page("https://consent.google.com/m?continue=x", ("button", "Reject all"),
                         ("button", "Accept all"), ("button", "More options")), "dialog_open": True}
ONLY_ACCEPT = page("https://shop.example.com/", ("button", "Accept cookies"), ("link", "Shop"))
ADMIN = page("https://admin.example.com/requests", ("button", "Reject request"), ("button", "Approve"))
TURING_CLEAR = page("https://www.turing.ac.uk/", ("link", "Events"), ("link", "About us"), ("link", "Contact us"))


def label(el):
    return el["label"] if el else None


def test_the_reject_button_of_a_cookie_notice_is_found():
    assert label(cookie_notice_button(TURING)) == "I Do Not Accept Cookies"
    assert label(cookie_notice_button(GOOGLE_CONSENT)) == "Reject all"


def test_reject_and_decline_buttons_on_pages_with_a_cookie_link_are_left_alone():
    # Most sites have a "Cookie policy" link; that doesn't make every Reject a cookie answer.
    assert cookie_notice_button({**ADMIN, "elements": ADMIN["elements"] + [
        {"id": 9, "role": "link", "label": "Cookie policy"}]}) is None
    invite = page("https://calendar.example.com/invite", ("button", "Decline"), ("button", "Accept"),
                  ("link", "Cookie settings"))
    assert cookie_notice_button(invite) is None


def test_reject_all_wins_over_a_section_header_that_mentions_necessary_cookies():
    onetrust = page("https://news.example.com/", ("button", "Strictly Necessary Cookies"),
                    ("button", "Accept All Cookies"), ("button", "Reject All"))
    assert label(cookie_notice_button(onetrust)) == "Reject All"


def test_nothing_is_accepted_and_other_reject_buttons_are_left_alone():
    assert cookie_notice_button(ONLY_ACCEPT) is None      # no way to say no: left for the model
    assert cookie_notice_button(ADMIN) is None            # not a cookie notice
    assert cookie_notice_button(None) is None


class Consent(FakePageBrowser):
    """Shows the notice until its reject button is clicked."""

    async def execute_action(self, name, args):
        if name == "click_element" and args.get("element_id") == 3 and self.index == 0:
            self.actions.append((name, args))
            self.index = 1
            return {"success": True}
        return await super().execute_action(name, args)


async def test_the_notice_is_closed_before_the_model_looks_at_the_page():
    seen = []
    browser = Consent([TURING, TURING_CLEAR])
    caller = FakeCaller(actions=[action_reply(call=("task_complete", {"summary": "The site is open."}))])
    original = caller.ask

    async def spy(model, contents, config=None):
        if config is not None and getattr(config, "tools", None):
            seen.append(" ".join(p.text for p in contents[-1].parts if p.text))
        return await original(model, contents, config)

    caller.ask = spy
    await start(caller, browser, task="open turing.ac.uk")
    assert browser.actions[0] == ("click_element", {"element_id": 3})
    assert "closed a cookie notice" in seen[0] and "I Do Not Accept Cookies" in seen[0]
    assert "I Accept Cookies" not in seen[0].replace("I Do Not Accept Cookies", "")   # the page view is the new one
