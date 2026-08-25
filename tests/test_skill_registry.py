import unittest

from server.skill_registry import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def test_discovers_metadata_without_loading_handlers(self):
        registry = SkillRegistry()
        self.assertIn("trip-planning", [item["name"] for item in registry.metadata()])
        self.assertEqual(registry.loaded(), [])

    def test_loads_handler_on_demand(self):
        registry = SkillRegistry()
        registry.load("realtime-query")
        self.assertEqual(registry.loaded(), ["realtime-query"])
        self.assertEqual(registry.find_for_intent("real_time_query"), "realtime-query")


if __name__ == "__main__":
    unittest.main()
