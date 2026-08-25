import unittest

from server.agentscope_workflow import RealTimeQueryASAgent
from server.mcp_client import parse_mcp_text


class RealtimeToolTests(unittest.TestCase):
    def test_hotel_relative_date_completion(self):
        params = RealTimeQueryASAgent._complete_trvl_params(
            "hotels", {}, "郑州东站附近有什么酒店，明天住两天"
        )
        self.assertEqual(params["location"], "郑州东站")
        self.assertEqual(params["check_in"], "2026-08-23")
        self.assertEqual(params["check_out"], "2026-08-25")
        self.assertEqual(RealTimeQueryASAgent._required_missing("hotels", params), [])

    def test_flight_parameter_mapping(self):
        params = RealTimeQueryASAgent._normalize_trvl_params(
            "flights",
            {"from": "杭州", "to": "郑州", "date": "2026-08-23", "max_price": 2000},
        )
        self.assertEqual(
            params,
            {
                "origin": "HGH",
                "destination": "CGO",
                "departure_date": "2026-08-23",
                "max_price": 2000,
            },
        )

    def test_hotel_parameter_mapping(self):
        params = RealTimeQueryASAgent._normalize_trvl_params(
            "hotels", {"city": "郑州", "checkin": "2026-08-23", "checkout": "2026-08-25"}
        )
        self.assertEqual(params, {"location": "郑州", "check_in": "2026-08-23", "check_out": "2026-08-25"})

    def test_mcp_error_text_is_not_success(self):
        result = parse_mcp_text("destination is required")
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
