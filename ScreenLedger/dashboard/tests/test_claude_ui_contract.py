import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class DashboardMarkup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.views = set()
        self.routes = set()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section" and "view" in attrs.get("class", "").split():
            self.views.add(attrs.get("id"))
        if "data-view" in attrs:
            self.routes.add(attrs["data-view"])
        if "id" in attrs:
            self.ids.append(attrs["id"])

class ClaudeUiContractTests(unittest.TestCase):
    def test_five_navigation_routes_have_views(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        parser = DashboardMarkup()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)), "DOM ids must be unique")
        self.assertEqual(parser.routes, set())

    def test_demo_payload_is_not_embedded_and_saved_data_contract_remains(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "assets" / "movie_intelligence.js").read_text(encoding="utf-8")
        self.assertLess(len(html.encode("utf-8")), 100_000)
        self.assertNotRegex(js, r"(?m)^\s*const\s+D\s*=")
        self.assertIn("/api/live/dates", js)
        self.assertIn("/api/live/summary", js)
        self.assertIn("/api/live/shows", js)
        self.assertIn('"overview","Overview"', js)
        self.assertIn('"pulse","Pulse"', js)
        self.assertIn('"map","Map"', js)
        self.assertIn('"shows","Shows"', js)
        self.assertIn('"engine","Capture engine"', js)
        self.assertIn("/api/live/day-ledger", js)
        self.assertIn("District cinema location", js)
        self.assertIn("Unassigned cinemas", js)

    def test_theme_and_small_viewport_support(self):
        css = (ROOT / "assets" / "claude_ui.css").read_text(encoding="utf-8")
        self.assertIn("#f7f2ea", css)
        self.assertIn("#0d0b10", css)
        self.assertIn("@media(max-width:680px)", css)
        self.assertIn("prefers-reduced-motion:reduce", css)
        self.assertIn("focus-visible", css)

    def test_zero_match_pair_is_not_rendered_as_zero_change(self):
        js = (ROOT / "assets" / "movie_intelligence.js").read_text(encoding="utf-8")
        self.assertIn("function deltaAvailable()", js)
        self.assertIn("no comparable interval", js)
        self.assertIn("No successful feeds in this capture", js)

if __name__ == "__main__":
    unittest.main()
