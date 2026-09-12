import unittest
from unittest.mock import MagicMock, patch

from agents.earning_discoverer import EarningDiscoverer


class TestEarningDiscoverer(unittest.TestCase):
    def test_reddit_json_falls_back_to_atom_rss(self):
        json_response = MagicMock(status_code=403, text="blocked")
        rss_response = MagicMock(
            status_code=200,
            text=(
                '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
                '<entry><id>post-1</id><title>Earn money writing Python</title>'
                '<link href="https://reddit.com/r/WorkOnline/post-1" /></entry>'
                '</feed>'
            ),
        )
        with patch("agents.earning_discoverer.requests.get", side_effect=[json_response, rss_response]):
            opportunities = EarningDiscoverer()._discover_reddit()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].id, "reddit_post-1")

    def test_github_search_parses_live_reward_issue(self):
        response = MagicMock(
            status_code=200,
            json=lambda: {
                "items": [{
                    "id": 42,
                    "title": "Paid bounty: improve parser",
                    "body": "A $25 reward is available.",
                    "html_url": "https://github.com/example/project/issues/1",
                    "repository_url": "https://api.github.com/repos/example/project",
                    "labels": [{"name": "bounty"}],
                }],
            },
        )
        with patch("agents.earning_discoverer.requests.get", return_value=response) as request:
            opportunities = EarningDiscoverer()._discover_github_bounties()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].min_amount, 25.0)
        self.assertIn("example/project", opportunities[0].platform)
        self.assertEqual(request.call_args.kwargs["params"]["per_page"], 30)


if __name__ == "__main__":
    unittest.main()
