import unittest

from agents.freelance_finder import FreelanceFinder


class FakeWeb:
    def __init__(self):
        self.calls = []

    def search(self, query, max_results=10):
        self.calls.append((query, max_results))
        return {
            "ok": True,
            "results": [{
                "title": "Build an AI agent",
                "url": "https://example.test/agent",
                "snippet": "Paid AI automation contract, $500",
            }],
        }


class TestFreelanceFinder(unittest.TestCase):
    def test_default_targets_include_agent_and_crypto_work(self):
        platforms = FreelanceFinder.DEFAULT_PLATFORMS
        self.assertIn("ai_agent", platforms)
        self.assertIn("crypto_work", platforms)
        self.assertIn("bounty", platforms)

    def test_targeted_marketplace_results_are_normalized(self):
        web = FakeWeb()
        finder = FreelanceFinder(web=web)
        result = finder.search("python", max_results=1, platforms=["ai_agent"])

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["platform"], "ai-agent marketplace")
        self.assertEqual(result["results"][0]["budget"], "$500")
        self.assertIn("virtuals.io", web.calls[0][0])


if __name__ == "__main__":
    unittest.main()