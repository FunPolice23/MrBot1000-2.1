import os
import tempfile
import unittest
from unittest.mock import patch

from agents.services.application_services import build_earning_services


class TestApplicationServices(unittest.TestCase):
    def test_builds_non_qt_earning_services(self):
        with tempfile.TemporaryDirectory() as base:
            with patch(
                "agents.earning.opportunity_portfolio.canonical_portfolio_path",
                return_value=os.path.join(base, "portfolio.db"),
            ):
                services = build_earning_services(base)
            try:
                self.assertIsNotNone(services.pipeline)
                self.assertIs(services.root.lifecycle, services.pipeline.lifecycle)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
