import asyncio
import time
import unittest
from unittest.mock import patch

import server.main as main


class OrchestrationTests(unittest.TestCase):
    def test_same_priority_tasks_run_in_parallel(self):
        def policy(_):
            time.sleep(0.15)
            return {"answer": "policy"}

        def realtime(_):
            time.sleep(0.10)
            return {"answer": "realtime"}

        def trip(_, __):
            time.sleep(0.12)
            return {"event": {}, "itinerary": {}}

        intent = {"intents": [
            {"type": "policy_query"},
            {"type": "real_time_query"},
            {"type": "trip_planning"},
        ]}
        with patch("server.agentscope_workflow.run_rag_workflow", policy), \
             patch("server.agentscope_workflow.run_realtime_workflow", realtime), \
             patch("server.agentscope_workflow.run_trip_workflow", trip):
            started = time.perf_counter()
            result = asyncio.run(main.route_intent_async(intent, "测试", None, "scheduler-test"))
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.25)
        self.assertEqual(result["_orchestration"]["mode"], "priority_plus_parallel")
        self.assertEqual(
            result["_orchestration"]["phases"][0]["parallel_tasks"],
            ["policy", "realtime", "trip"],
        )


if __name__ == "__main__":
    unittest.main()
