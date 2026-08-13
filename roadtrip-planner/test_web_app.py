import unittest
from unittest.mock import patch

import web_app


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class TestPoiParsing(unittest.TestCase):
    def test_get_pois_along_route_parses_overpass_results(self):
        payload = {
            "elements": [
                {
                    "type": "node",
                    "lat": 40.7128,
                    "lon": -74.0060,
                    "tags": {
                        "name": "Example Cafe",
                        "amenity": "restaurant"
                    }
                }
            ]
        }
        with patch("web_app.overpass_query", return_value=DummyResponse(payload)):
            pois = web_app.get_pois_along_route([[-74.0060, 40.7128]], radius_miles=1)

        self.assertEqual(pois["restaurant"][0]["name"], "Example Cafe")
        self.assertEqual(pois["gas_station"], [])


if __name__ == "__main__":
    unittest.main()
