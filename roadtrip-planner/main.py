import math
import os
import requests
import xml.etree.ElementTree as ET
import time
from itertools import permutations, combinations
from dotenv import load_dotenv
import folium
import webview

load_dotenv()

# --- Config ---
EARTH_RADIUS_KM = 6371
ORS_API_KEY = os.getenv("ORS_API_KEY")
GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
ROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
FUEL_URL = "https://www.fueleconomy.gov/ws/rest/fuelprices"

CAR_TYPES = {
    "economy": 35,
    "sedan": 30,
    "suv": 22,
    "truck": 15,
    "sports": 18
}


# --- Haversine ---
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


# --- Geocoding ---
def get_coordinates(city_name):
    headers = {"Authorization": ORS_API_KEY}
    params = {"text": city_name}
    try:
        r = requests.get(GEOCODE_URL, headers=headers, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        return data["features"][0]["geometry"]["coordinates"]
    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  Geocoding failed for '{city_name}': {e}")
        return None


# --- Routing ---
# --- Routing ---
def get_route(start_coords, end_coords):
    """
    Returns (distance_m, duration_s, geometry).
    geometry is the actual road-shaped path as a list of [lon, lat] points —
    not just the two endpoints — pulled from the geojson response.
    """
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {"coordinates": [start_coords, end_coords]}
    try:
        r = requests.post(ROUTE_URL, json=body, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        feature = data["features"][0]
        summary = feature["properties"]["summary"]
        geometry = feature["geometry"]["coordinates"]
        return summary["distance"], summary["duration"], geometry
    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  Route request failed: {e}")
        return None, None, None


# --- Fuel price ---
def get_fuel_price():
    try:
        r = requests.get(FUEL_URL, timeout=3)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        regular = root.find("regular")
        if regular is not None and regular.text:
            return float(regular.text)
    except Exception:
        pass
    print("  Could not fetch live fuel price, using fallback $3.50.")
    return 3.50


# --- Fuel cost ---
def estimate_fuel_cost(distance_km, mpg, price_per_gallon):
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

    for perm in permutations(others):
        order = [0] + list(perm)
        dist = sum(haversine(coords[order[i]], coords[order[i + 1]]) for i in range(len(order) - 1))
        if dist < best_dist:
            best_dist = dist
            best_order = order

    return best_order, best_dist


# --- TSP: Held-Karp Dynamic Programming O(2^n * n^2) ---
def held_karp_tsp(coords):
    """
    Guaranteed-optimal TSP solver using dynamic programming with a bitmask
    to track which cities have been visited. Same correct answer as brute
    force, but avoids recomputing overlapping sub-routes, which is why it's
    dramatically faster: O(2^n * n^2) instead of O(n!).

    For example, at n=12: brute force is ~479 million operations,
    Held-Karp is roughly 590,000. Still exponential, so it also breaks
    down eventually (usable up to roughly 15-18 cities), but it pushes
    the "guaranteed optimal" ceiling much higher than brute force alone.
    """
    n = len(coords)
    dist = [[haversine(coords[i], coords[j]) for j in range(n)] for i in range(n)]

    # C[(visited_bitmask, last_city)] = (min_cost_so_far, path_so_far)
    # Every route starts at city 0.
    C = {}
    for k in range(1, n):
        C[(1 << k, k)] = (dist[0][k], [0, k])

    for subset_size in range(2, n):
        for subset in combinations(range(1, n), subset_size):
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

    # Close the loop back to city 0 is NOT needed here since a road trip
    # doesn't need to return to the start — we just want the shortest path
    # that visits every city once.
    full_bits = (1 << n) - 2  # all cities except city 0
    best = None
    for k in range(1, n):
        if (full_bits, k) in C:
            cost, path = C[(full_bits, k)]
            if best is None or cost < best[0]:
                best = (cost, path)

    return best[1], best[0]


# --- TSP: Nearest Neighbor Heuristic O(n^2) ---
def nearest_neighbor_tsp(coords):
    """
    Greedy heuristic: always move to the closest unvisited city.
    Not guaranteed optimal, but fast for any number of cities.
    Time complexity: O(n^2)
    """
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


# --- Map generation ---
def generate_map(cities, coords, route_geometry=None, filename="trip_map.html"):
    """
    Builds an interactive HTML map showing each city as a pin.
    If route_geometry is provided (the actual road-shaped path from the
    routing API), that gets drawn instead of a straight line between cities.
    coords are expected in [lon, lat] order (how ORS returns them);
    folium expects [lat, lon], so they get flipped here.
    """
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

    m.save(filename)
    return filename


def show_map_window(filename):
    """Opens the generated map in its own native app window instead of a browser tab."""
    abs_path = os.path.abspath(filename)
    webview.create_window("Road Trip Planner — Route Map", abs_path, width=1000, height=700)
    webview.start()


# --- Main ---
def main():
    print("🚗 Road Trip Planner")

    print("\nEnter cities (type 'done' when finished, minimum 2):")
    cities = []
    while True:
        city = input(f"  City {len(cities) + 1}: ").strip()
        if city.lower() == "done":
            if len(cities) < 2:
                print("  Need at least 2 cities.")
            else:
                break
        elif city:
            cities.append(city)

    print("\nCar types: economy / sedan / suv / truck / sports")
    car_type = input("Choose car type: ").strip().lower()
    mpg = CAR_TYPES.get(car_type, 30)

    print("\nGeocoding cities...")
    coords = []
    for city in cities:
        c = get_coordinates(city)
        if not c:
            print(f"  Could not find '{city}'. Exiting.")
            return
        coords.append(c)
        print(f"  ✓ {city}")

    fuel_price = get_fuel_price()

    # --- Two cities: simple direct route ---
    if len(cities) == 2:
        straight_km = haversine(coords[0], coords[1])
        distance_m, duration_s, geometry = get_route(coords[0], coords[1])
        if distance_m is None:
            print("Route calculation failed.")
            return
        distance_km = distance_m / 1000
        duration_h = duration_s / 3600
        cost = estimate_fuel_cost(distance_km, mpg, fuel_price)

        print("\n--- TRIP INFO ---")
        print(f"Route:                  {cities[0]} → {cities[1]}")
        print(f"Car type:               {car_type} ({mpg} MPG)")
        print(f"Fuel price:             ${fuel_price:.2f}/gal")
        print(f"Straight-line distance: {straight_km:.2f} km")
        print(f"Actual road distance:   {distance_km:.2f} km")
        print(f"Road overhead:          {((distance_km / straight_km - 1) * 100):.1f}%")
        print(f"Duration:               {duration_h:.2f} hours")
        print(f"Estimated fuel cost:    ${cost}")

        map_file = generate_map(cities, coords, route_geometry=geometry)
        print(f"\nOpening route map...")
        show_map_window(map_file)

    # --- Multi-stop: TSP optimization ---
    else:
        n = len(cities)
        print(f"\nOptimizing route for {n} cities...")

        t0 = time.perf_counter()
        nn_order, nn_dist = nearest_neighbor_tsp(coords)
        nn_time = (time.perf_counter() - t0) * 1000
        print(f"  Nearest neighbor:  {nn_dist:.1f} km  ({nn_time:.2f} ms)")

        if n <= 8:
            t0 = time.perf_counter()
            bf_order, bf_dist = brute_force_tsp(coords)
            bf_time = (time.perf_counter() - t0) * 1000
            print(f"  Brute force:       {bf_dist:.1f} km  ({bf_time:.2f} ms)")

            t0 = time.perf_counter()
            hk_order, hk_dist = held_karp_tsp(coords)
            hk_time = (time.perf_counter() - t0) * 1000
            print(f"  Held-Karp:         {hk_dist:.1f} km  ({hk_time:.2f} ms)")

            agree = abs(bf_dist - hk_dist) < 0.01
            print(f"  Brute force and Held-Karp agree: {agree}")

            best_order = bf_order
            method = "Brute force / Held-Karp (both guaranteed optimal, agree above)"

        elif n <= 15:
            print(f"  {n} cities is too many for brute force (O(n!)) to finish in reasonable time.")
            t0 = time.perf_counter()
            hk_order, hk_dist = held_karp_tsp(coords)
            hk_time = (time.perf_counter() - t0) * 1000
            print(f"  Held-Karp:         {hk_dist:.1f} km  ({hk_time:.2f} ms) — still guaranteed optimal")

            best_order = hk_order
            method = "Held-Karp dynamic programming (guaranteed optimal)"

        else:
            print(f"  {n} cities is too many for Held-Karp (O(2^n * n^2)) to finish in reasonable time.")
            best_order = nn_order
            method = "Nearest neighbor heuristic (not guaranteed optimal)"

        ordered_cities = [cities[i] for i in best_order]
        ordered_coords = [coords[i] for i in best_order]

        print(f"\nCalculating road distances for optimized route...")
        total_km = 0
        total_h = 0
        full_geometry = []

        for i in range(len(ordered_cities) - 1):
            d_m, dur_s, geometry = get_route(ordered_coords[i], ordered_coords[i + 1])
            if d_m is None:
                print(f"  Route failed: {ordered_cities[i]} → {ordered_cities[i + 1]}")
                return
            seg_km = d_m / 1000
            seg_h = dur_s / 3600
            total_km += seg_km
            total_h += seg_h
            full_geometry.extend(geometry)
            print(f"  {ordered_cities[i]} → {ordered_cities[i + 1]}: {seg_km:.1f} km, {seg_h:.2f} hrs")

        cost = estimate_fuel_cost(total_km, mpg, fuel_price)

        print(f"\n--- TRIP INFO ---")
        print(f"Optimization:           {method}")
        print(f"Optimized route:        {' → '.join(ordered_cities)}")
        print(f"Car type:               {car_type} ({mpg} MPG)")
        print(f"Fuel price:             ${fuel_price:.2f}/gal")
        print(f"Total road distance:    {total_km:.2f} km")
        print(f"Total duration:         {total_h:.2f} hours")
        print(f"Estimated fuel cost:    ${cost}")

        map_file = generate_map(ordered_cities, ordered_coords, route_geometry=full_geometry)
        print(f"\nOpening route map...")
        show_map_window(map_file)


if __name__ == "__main__":
    main()
