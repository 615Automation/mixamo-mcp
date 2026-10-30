"""Offline tests for searching Mixamo. No login, browser profile or network needed.

Run from the project folder:  python -m unittest discover -s tests -t .
"""
import json
import logging
import re
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, quote, urldefrag

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

import mcp_server
from screens import animations

logging.getLogger("asyncio").setLevel(logging.ERROR)  # slow-step warnings on a busy machine

FIXTURES = Path(__file__).parent / "fixtures"
API_URL ="https://www.mixamo.com/api/v1/products?page=1&limit=48&order=&type=Motion%2CMotionPack&query={}"

RELOAD_IDS = ["116660901", "115730901", "116620901", "115780901", "101710901", "113030901", "127690905"]

# Copied from the real page.
CLIP_CARD = (
    '<div class="product product-animation{extra}"><div class="product-image">'
    '<img src="https://d99n9xvb9513w.cloudfront.net/thumbnails/motions/{id}/animated.gif"></div>'
    '<div class="product-overlay"><div class="product-overlay-details">'
    '<img src="images/type-animation.png" class="product-type product-type-animation" alt="3D Animation">'
    '</div></div><div class="product-description"><div class="product-info">'
    '<p class="text-capitalize">{name}</p><ul class="list-unstyled product-metadata"><li>'
    "<!-- react-text: 848 -->Description: <!-- /react-text --><!-- react-text: 849 -->{description}"
    "<!-- /react-text --></li></ul></div></div></div>"
)
PACK_CARD = (
    '<div class="product product-animation-pack"><div class="product-image">'
    '<img src="https://d99n9xvb9513w.cloudfront.net/thumbnails/motion_packs/fps_slim/animated.gif"></div>'
    '<div class="product-overlay"><div class="product-overlay-details"><span>'
    '<small class="img-circle product-count">7</small>'
    '<img src="images/type-animation.png" class="product-type product-type-animation-pack" alt="3D Animation">'
    '</span></div></div><div class="product-description"><div class="product-info">'
    '<p class="text-capitalize">Slim Shooter Pack</p><ul class="list-unstyled product-metadata"><li>'
    "<!-- react-text: 949 -->7<!-- /react-text --><!-- react-text: 950 --> animations<!-- /react-text -->"
    "</li></ul></div></div></div>"
)


def real_response(name):
    """A complete search response saved from the real site."""
    return 200, json.loads((FIXTURES / f"{name}.json").read_text())


def clip_card(anim_id, extra=""):
    return CLIP_CARD.format(extra=extra, id=anim_id, name="Clip", description="A clip")


def numeric_id(result):
    return re.search(r"/motions/(\d+)/", result["thumbnail"]).group(1)


class FakeResponse:
    def __init__(self, query, status, body):
        self.url = API_URL.format(quote(query))
        self.status = status
        self.ok = 200 <= status < 300
        self.body = body


class FakeMixamo:
    """The search page, behaving the way the real one was measured to behave.

    A new URL starts a search but leaves the old cards on screen until the results render.
    Going to the URL the page is already on does nothing at all. A search with no results
    never shows a card. Only a reload makes the page ask Mixamo again for the same URL, and
    a reload forgets the selected clip.
    """

    def __init__(self, responses):
        self.responses = responses  # query -> (status, body); a query not listed gets no answer
        self.url = "https://www.mixamo.com/#/"
        self.cards = []
        self.selected_id = None
        self.searching = None
        self.cards_are_stuck = False

    def _query_in_url(self):
        return parse_qs(urldefrag(self.url).fragment.split("?", 1)[1]).get("query", [""])[0]

    def goto(self, url):
        if url != self.url:
            self.url = url
            self.searching = self._query_in_url()

    def reload(self):
        self.cards = []
        self.selected_id = None
        self.searching = self._query_in_url()

    def answer(self, predicate):
        if self.searching in self.responses:
            status, body = self.responses[self.searching]
            response = FakeResponse(self.searching, status, body)
            if predicate(response):
                return response
        self.searching = None  # the page asked once and won't ask again by itself
        raise PlaywrightTimeoutError("no matching response")

    def render(self):
        if self.searching in self.responses:
            _, body = self.responses[self.searching]
            self.cards = [r for r in body["results"] if r["type"] == "Motion"]
            self.searching = None

    def wait_until_cards_are(self, ids):
        if self.cards_are_stuck:
            raise PlaywrightTimeoutError("cards never updated")
        self.render()
        if sorted(numeric_id(r) for r in self.cards) != sorted(ids):
            raise PlaywrightTimeoutError("cards don't match")

    def html(self):
        cards = []
        for result in self.cards:
            anim_id = numeric_id(result)
            extra = " product-selected" if anim_id == self.selected_id else ""
            cards.append(
                CLIP_CARD.format(extra=extra, id=anim_id, name=result["name"], description=result["description"])
            )
        return f"<html><body>{''.join(cards)}</body></html>"


class AsyncResponse:
    def __init__(self, fake):
        self.url, self.status, self.ok, self.body = fake.url, fake.status, fake.ok, fake.body

    async def json(self):
        return self.body


class SyncResponse:
    def __init__(self, fake):
        self.url, self.status, self.ok, self.body = fake.url, fake.status, fake.ok, fake.body

    def json(self):
        return self.body


class AsyncExpectResponse:
    def __init__(self, site, predicate):
        self.site, self.predicate = site, predicate

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.response = AsyncResponse(self.site.answer(self.predicate))

    @property
    def value(self):
        async def get():
            return self.response

        return get()


class SyncExpectResponse:
    def __init__(self, site, predicate):
        self.site, self.predicate = site, predicate

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.value = SyncResponse(self.site.answer(self.predicate))


class AsyncPage:
    def __init__(self, site):
        self.site = site

    @property
    def url(self):
        return self.site.url

    async def goto(self, url, wait_until=None):
        self.site.goto(url)

    async def reload(self, wait_until=None):
        self.site.reload()

    async def wait_for_function(self, expression, arg=None, timeout=None, polling=None):
        self.site.wait_until_cards_are(arg)

    async def content(self):
        return self.site.html()

    def expect_response(self, predicate, timeout=None):
        return AsyncExpectResponse(self.site, predicate)


class SyncPage:
    def __init__(self, site):
        self.site = site

    @property
    def url(self):
        return self.site.url

    def goto(self, url, wait_until=None):
        self.site.goto(url)

    def reload(self, wait_until=None):
        self.site.reload()

    def wait_for_function(self, expression, arg=None, timeout=None, polling=None):
        self.site.wait_until_cards_are(arg)

    def content(self):
        return self.site.html()

    def expect_response(self, predicate, timeout=None):
        return SyncExpectResponse(self.site, predicate)


def clip_ids(lines):
    return [m.group(1) for m in (re.match(r"\[.\] (\d+)", line) for line in lines) if m]


class SearchPromises:
    """What a search must get right, whichever front end runs it."""

    async def search(self, site, query):
        raise NotImplementedError

    async def test_a_single_page_search_reports_the_real_total(self):
        site = FakeMixamo({"reload": real_response("reload")})
        lines = await self.search(site, "reload")
        self.assertEqual(lines[0], "Page 1 of 1 (12 total)")

    async def test_a_multi_page_search_reports_its_pages_and_total(self):
        _, body = real_response("vault")
        body["pagination"] = {"limit": 48, "page": 1, "num_pages": 5, "num_results": 207}
        site = FakeMixamo({"sprint": (200, body)})
        lines = await self.search(site, "sprint")
        self.assertEqual(lines[0], "Page 1 of 5 (207 total)")

    async def test_no_results_right_after_a_search_with_clips_says_so(self):
        site = FakeMixamo({"vault": real_response("vault"), "parachute": real_response("parachute")})
        await self.search(site, "vault")
        self.assertEqual(await self.search(site, "parachute"), ["No animations found for 'parachute'."])

    async def test_no_results_right_after_a_search_without_clips_says_so(self):
        site = FakeMixamo({"parachute": real_response("parachute"), "skydiving": real_response("parachute")})
        await self.search(site, "parachute")
        self.assertEqual(await self.search(site, "skydiving"), ["No animations found for 'skydiving'."])

    async def test_cards_left_from_the_last_search_are_not_reported_as_results(self):
        site = FakeMixamo({"vault": real_response("vault"), "reload": real_response("reload")})
        await self.search(site, "vault")
        self.assertEqual(clip_ids(await self.search(site, "reload")), RELOAD_IDS)

    async def test_the_new_cards_are_on_the_page_when_the_search_returns(self):
        site = FakeMixamo({"vault": real_response("vault"), "reload": real_response("reload")})
        await self.search(site, "vault")
        await self.search(site, "reload")
        self.assertEqual([numeric_id(r) for r in site.cards], RELOAD_IDS)

    async def test_clips_show_mixamos_description(self):
        site = FakeMixamo({"vault": real_response("vault")})
        lines = await self.search(site, "vault")
        self.assertIn("[ ] 135690901  Vault Over Box - Vault Over Box And Hide", lines)

    async def test_packs_are_listed_with_their_clip_counts(self):
        site = FakeMixamo({"reload": real_response("reload")})
        lines = await self.search(site, "reload")
        self.assertIn("[pack] Slim Shooter Pack (7 clips)", lines)
        self.assertIn("[pack] Pro Longbow Pack (39 clips)", lines)

    async def test_repeating_a_search_gives_the_same_results(self):
        site = FakeMixamo({"vault": real_response("vault")})
        first = await self.search(site, "vault")
        self.assertEqual(await self.search(site, "vault"), first)

    async def test_repeating_a_search_marks_a_clip_selected_since_the_first_time(self):
        site = FakeMixamo({"vault": real_response("vault")})
        await self.search(site, "vault")
        site.selected_id = "135690901"
        lines = await self.search(site, "vault")
        self.assertIn("[*] 135690901  Vault Over Box - Vault Over Box And Hide", lines)

    async def test_results_still_come_back_when_the_cards_are_slow_to_appear(self):
        site = FakeMixamo({"vault": real_response("vault")})
        site.cards_are_stuck = True
        lines = await self.search(site, "vault")
        self.assertEqual(clip_ids(lines), ["135690901"])
        self.assertTrue(any("select_animation" in line for line in lines))

    async def test_no_answer_from_mixamo_is_an_error_not_an_empty_result(self):
        with self.assertRaisesRegex(RuntimeError, "ghost"):
            await self.search(FakeMixamo({}), "ghost")

    async def test_an_http_error_from_mixamo_is_an_error_not_an_empty_result(self):
        site = FakeMixamo({"vault": (401, {"message": "Unauthorized"})})
        with self.assertRaisesRegex(RuntimeError, "401"):
            await self.search(site, "vault")

    async def test_retrying_after_no_answer_asks_mixamo_again(self):
        site = FakeMixamo({})
        with self.assertRaises(RuntimeError):
            await self.search(site, "vault")
        site.responses["vault"] = real_response("vault")
        self.assertEqual(clip_ids(await self.search(site, "vault")), ["135690901"])


class McpToolSearch(SearchPromises, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(mcp_server, "_last_search", None, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def search(self, site, query):
        async def get_page():
            return AsyncPage(site)

        with mock.patch.object(mcp_server, "_get_page", get_page):
            return (await mcp_server.list_animations(query)).splitlines()


class CommandLineSearch(SearchPromises, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(animations, "_last_search", None, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def search(self, site, query):
        return animations.format_search_results(animations.search(SyncPage(site), query), query)


class SearchUrlTests(unittest.TestCase):
    def test_no_query(self):
        self.assertEqual(animations.search_url(), "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack")

    def test_a_space_is_encoded(self):
        self.assertEqual(
            animations.search_url("falling idle"),
            "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack&query=falling%20idle",
        )

    def test_an_ampersand_stays_part_of_the_query(self):
        self.assertEqual(
            animations.search_url("rock&roll"),
            "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack&query=rock%26roll",
        )


class SearchResponseMatchTests(unittest.TestCase):
    def test_a_search_matches_its_own_response(self):
        self.assertTrue(animations.is_search_response(API_URL.format("falling%20idle"), "falling idle"))

    def test_a_blank_search_matches_a_blank_query(self):
        self.assertTrue(animations.is_search_response(API_URL.format(""), ""))

    def test_capitals_in_the_query_do_not_matter(self):
        self.assertTrue(animations.is_search_response(API_URL.format("falling%20idle"), "Falling Idle"))

    def test_the_response_to_another_search_does_not_match(self):
        self.assertFalse(animations.is_search_response(API_URL.format("reload"), "falling idle"))

    def test_looking_up_one_product_does_not_match(self):
        url = "https://www.mixamo.com/api/v1/products/c9c8bc4d-b96c-11e4-a802-0aaa78deedf9?similar=0"
        self.assertFalse(animations.is_search_response(url, ""))

    def test_a_character_listing_does_not_match(self):
        url = "https://www.mixamo.com/api/v1/products?page=1&limit=48&order=&type=Character&query="
        self.assertFalse(animations.is_search_response(url, ""))


class CardsMatchScriptTests(unittest.IsolatedAsyncioTestCase):
    """Runs the real script in a real browser, with all network traffic blocked."""

    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def cards_match(self, shown_cards, ids):
        await self.page.set_content("".join(shown_cards))
        return await self.page.evaluate(animations.CARDS_MATCH_JS, ids)

    async def test_exactly_the_expected_cards_match(self):
        self.assertTrue(await self.cards_match([clip_card("111"), clip_card("222")], ["111", "222"]))

    async def test_the_order_of_the_cards_does_not_matter(self):
        self.assertTrue(await self.cards_match([clip_card("222"), clip_card("111")], ["111", "222"]))

    async def test_a_selected_card_still_counts(self):
        self.assertTrue(await self.cards_match([clip_card("111", " product-selected")], ["111"]))

    async def test_cards_from_another_search_do_not_match(self):
        self.assertFalse(await self.cards_match([clip_card("333")], ["111"]))

    async def test_a_part_of_the_expected_cards_does_not_match(self):
        self.assertFalse(await self.cards_match([clip_card("111")], ["111", "222"]))

    async def test_extra_cards_do_not_match(self):
        self.assertFalse(await self.cards_match([clip_card("111"), clip_card("222")], ["111"]))

    async def test_old_cards_do_not_match_an_empty_search(self):
        self.assertFalse(await self.cards_match([clip_card("111")], []))

    async def test_an_empty_page_matches_an_empty_search(self):
        self.assertTrue(await self.cards_match([], []))

    async def test_pack_cards_are_ignored(self):
        self.assertTrue(await self.cards_match([PACK_CARD, clip_card("111")], ["111"]))


if __name__ == "__main__":
    unittest.main()
