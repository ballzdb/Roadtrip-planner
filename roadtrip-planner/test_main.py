"""
Unit tests for Road Trip Planner.

Run with:
    python -m unittest test_main.py -v

These test the pure logic (math, algorithms) that doesn't depend on
network calls, so they run instantly and don't need an API key.
"""

import unittest
from main import haversine, estimate_fuel_cost, brute_force_tsp, held_karp_tsp


class TestHaversine(unittest.TestCase):
    def test_known_distance_la_to_nyc(self):
        # Real straight-line distance LA to NYC is approximately 3,936 km.
        la = [-118.2437, 34.0522]
        nyc = [-74.0060, 40.7128]
        dist = haversine(la, nyc)
        self.assertAlmostEqual(dist, 3936, delta=50)

    def test_same_point_is_zero(self):
        point = [-100.0, 40.0]
        self.assertAlmostEqual(haversine(point, point), 0, delta=0.001)

    def test_distance_is_symmetric(self):
        a = [-118.2437, 34.0522]
        b = [-122.4194, 37.7749]
        self.assertAlmostEqual(haversine(a, b), haversine(b, a), delta=0.001)


class TestFuelCost(unittest.TestCase):
    def test_known_values(self):
        # 100 km = 62.1371 miles. 62.1371 / 25 mpg = 2.485 gallons. * $4 = $9.94
        cost = estimate_fuel_cost(100, 25, 4)
        self.assertAlmostEqual(cost, 9.94, delta=0.05)

    def test_zero_distance_is_zero_cost(self):
        self.assertEqual(estimate_fuel_cost(0, 25, 4), 0)


class TestTSPCorrectness(unittest.TestCase):
    def test_held_karp_matches_brute_force(self):
        """
        Held-Karp and brute force are both guaranteed-optimal algorithms.
        If they ever disagree on total distance, one of them has a bug.
        """
        coords = [
            [-118.2437, 34.0522],  # LA
            [-115.1398, 36.1699],  # Las Vegas
            [-112.0740, 33.4484],  # Phoenix
            [-117.1611, 32.7157],  # San Diego
            [-119.7871, 36.7378],  # Fresno
        ]
        _, bf_dist = brute_force_tsp(coords)
        _, hk_dist = held_karp_tsp(coords)
        self.assertAlmostEqual(bf_dist, hk_dist, delta=0.01)

    def test_two_cities_trivial_case(self):
        coords = [[-118.2437, 34.0522], [-122.4194, 37.7749]]
        order, dist = brute_force_tsp(coords)
        self.assertEqual(order, [0, 1])
        self.assertAlmostEqual(dist, haversine(coords[0], coords[1]), delta=0.01)


if __name__ == "__main__":
    unittest.main()
