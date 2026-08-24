"""
Shared core logic for Road Trip Planner.

Both the CLI (`main.py`) and the web app (`web_app.py`) use these functions,
so they live in one place instead of being copy-pasted.
"""

import math
import os
import uuid
from dotenv import load_dotenv
import folium

EARTH_RADIUS_KM = 6371

CAR_TYPES = {
    "economy": 35,
    "sedan": 30,
    "suv": 22,
    "truck": 15,
    "sports": 18
}

# Fallback fuel prices (used when no live source is available)
FALLBACK_PRICES = {
    'regular': 3.50,
    'midgrade': 3.70,
    'premium': 3.90,
    'diesel': 4.20,
    'cng': 2.50,
    'e85': 2.80,
    'electric': 0.12,
    'lpg': 3.00
}

FUEL_URL = "https://www.fueleconomy.gov/ws/rest/fuelprices"


def haversine(coord1, coord2):
    """Straight-line distance between two [lon, lat] points along Earth's surface."""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    lon1, lon2 = math.radians(lon1), math.radians(lon2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def get_ors_api_key():
    """Load ORS_API_KEY from .env files next to the project or its parent."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_env = os.path.join(base_dir, ".env")
    parent_env = os.path.join(base_dir, "..", ".env")

    if os.path.exists(local_env):
        load_dotenv(local_env, override=True)
    if os.path.exists(parent_env):
        load_dotenv(parent_env, override=True)

    key = os.getenv("ORS_API_KEY")
    if not key or not key.strip() or key.strip() == "your_openrouteservice_api_key_here":
        return None
    return key.strip()


def estimate_fuel_cost(distance_km, mpg, price_per_gallon):
    """Estimate gas cost for a distance (km), given MPG and $/gal."""
    miles = distance_km * 0.621371
    gallons = miles / mpg
    return round(gallons * price_per_gallon, 2)


# --- TSP: Brute Force O(n!) ---
def brute_force_tsp(coords):
    """
    Tries every possible ordering of cities and returns the shortest.
    Guaranteed optimal, but only feasible for n <= 8 cities.
    Time complexity: O(n!)
    """
    n = len(coords)
    others = list(range(1, n))
    best_order = None
    best_dist = float("inf")

    for perm in __import__('itertools').permutations(others):
        order = [0] + list(perm)
        dist = sum(haversine(coords[order[i]], coords[order[i + 1]]) for i in range(len(order) - 1))
        if dist < best_dist:
            best_dist = dist
            best_order = order

    if best_order is None:
        return [0], 0.0
    return best_order, best_dist


# --- TSP: Held-Karp Dynamic Programming O(2^n * n^2) ---
def held_karp_tsp(coords):
    """Guaranteed-optimal TSP solver using dynamic programming with a bitmask."""
    n = len(coords)
    if n <= 1:
        return list(range(n)), 0.0
    dist = [[haversine(coords[i], coords[j]) for j in range(n)] for i in range(n)]

    C = {}
    for k in range(1, n):
        C[(1 << k, k)] = (dist[0][k], [0, k])

    for subset_size in range(2, n):
        for subset in __import__('itertools').combinations(range(1, n), subset_size):
            bits = 0
            for bit in subset:
                bits |= 1 << bit

            for k in subset:
                prev_bits = bits & ~(1 << k)
                candidates = []
                for m in subset:
                    if m == k:
                        continue
                    if (prev_bits, m) in C:
                        cost, path = C[(prev_bits, m)]
                        candidates.append((cost + dist[m][k], path + [k]))
                if candidates:
                    C[(bits, k)] = min(candidates, key=lambda x: x[0])

    full_bits = (1 << n) - 2  # all cities except city 0
    best = None
    for k in range(1, n):
        if (full_bits, k) in C:
            cost, path = C[(full_bits, k)]
            if best is None or cost < best[0]:
                best = (cost, path)

    if best is None:
        return [0], 0.0
    return best[1], best[0]


# --- TSP: Nearest Neighbor Heuristic O(n^2) ---
def nearest_neighbor_tsp(coords):
    """Greedy heuristic: always move to the closest unvisited city."""
    n = len(coords)
    visited = [False] * n
    order = [0]
    visited[0] = True

    for _ in range(n - 1):
        current = order[-1]
        nearest, nearest_dist = None, float("inf")
        for j in range(n):
            if not visited[j]:
                d = haversine(coords[current], coords[j])
                if d < nearest_dist:
                    nearest_dist = d
                    nearest = j
        order.append(nearest)
        visited[nearest] = True

    total = sum(haversine(coords[order[i]], coords[order[i + 1]]) for i in range(len(order) - 1))
    return order, total


def generate_map(cities, coords, route_geometry=None, filename=None, maps_dir=None):
    """
    Builds an interactive HTML map showing each city as a pin.
    If route_geometry is provided (the actual road-shaped path from the
    routing API), that gets drawn instead of a straight line between cities.
    coords are expected in [lon, lat] order (how ORS returns them);
    folium expects [lat, lon], so they get flipped here.

    Returns the filename (not the full path).
    """
    if maps_dir is None:
        maps_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps")
    os.makedirs(maps_dir, exist_ok=True)

    if filename is None:
        filename = f"map_{uuid.uuid4().hex}.html"
    filepath = os.path.join(maps_dir, filename)

    latlon_coords = [[lat, lon] for lon, lat in coords]

    center_lat = sum(c[0] for c in latlon_coords) / len(latlon_coords)
    center_lon = sum(c[1] for c in latlon_coords) / len(latlon_coords)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles="OpenStreetMap")

    for i, (city, latlon) in enumerate(zip(cities, latlon_coords)):
        if i == 0:
            color, label = "green", f"Start: {city}"
        elif i == len(cities) - 1:
            color, label = "red", f"End: {city}"
        else:
            color, label = "blue", f"Stop {i}: {city}"

        folium.Marker(
            location=latlon,
            popup=label,
            tooltip=label,
            icon=folium.Icon(color=color)
        ).add_to(m)

    if route_geometry:
        route_latlon = [[lat, lon] for lon, lat in route_geometry]
        folium.PolyLine(route_latlon, color="#3388ff", weight=4, opacity=0.8).add_to(m)
        m.fit_bounds(route_latlon)
    else:
        folium.PolyLine(latlon_coords, color="#3388ff", weight=4, opacity=0.8, dash_array="8").add_to(m)
        m.fit_bounds(latlon_coords)

    m.save(filepath)
    return filename
