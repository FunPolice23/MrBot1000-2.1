import unittest

from agents.core.persistence_contract import authority_for


class TestPersistenceClassification(unittest.TestCase):
    def test_projection_and_subsystem_boundaries_are_explicit(self):
        self.assertEqual(authority_for("portfolio").classification, "projection")
        self.assertEqual(authority_for("dual_brain").classification, "projection")
        self.assertEqual(authority_for("goals").classification, "subsystem")


if __name__ == "__main__":
    unittest.main()
