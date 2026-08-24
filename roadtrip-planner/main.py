"""
cs50-roadtrip-planner — CLI entry point.

Type in two or more cities, pick a car type, and the program estimates
distance, duration, and gas cost. With 3+ cities it optimizes the visit
order (Travelling Salesman Problem) using brute force / Held-Karp /
nearest neighbor from the shared roadtrip_core module.
"""

import os
import time
import requests
import xml.etree.ElementTree as ET
from itertools import permutations, combinations

try:
    import webview
except ImportError:
    webview = None

from roadtrip_core import (
    haversine,
    get_ors_api_key,
    estimate_fuel_cost,
    brute_force_tsp,
    held_karp_tsp,
    nearest_neighbor_tsp,
    generate_map,
    CAR_TYPES,
)

# --- Config ---
GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
ROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
FUEL_URL = "https://www.fueleconomy.gov/ws/rest/fuelprices"


# --- Geocoding ---
def get_coordinates(city_name):
    api_key = get_ors_api_key()
    if not api_key:
        print("  ❌ Error: ORS_API_KEY is missing. Please set your API key in the .env file.")
        return None
    headers = {"Authorization": api_key}
    params = {"text": city_name}
    try:
        r = requests.get(GEOCODE_URL, headers=headers, params=params, timeout=10)
        if r.status_code in (401, 403):
            print(f"  ❌ Error: Invalid OpenRouteService API key (HTTP {r.status_code}). Please check your .env file.")
            return None
        r.raise_for_status()
        data = r.json()
        features = data.get("features", [])
        if not features:
            print(f"  ❌ Geocoding returned no results for '{city_name}'.")
            return None
        return features[0]["geometry"]["coordinates"]
    except requests.RequestException as e:
        print(f"  ❌ Geocoding network error for '{city_name}': {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"  ❌ Geocoding parse error for '{city_name}': {e}")
        return None


# --- Routing ---
def get_route(start_coords, end_coords):
    """
    Returns (distance_m, duration_s, geometry).
    geometry is the actual road-shaped path as a list of [lon, lat] points —
    not just the two endpoints — pulled from the geojson response.
    """
    api_key = get_ors_api_key()
    if not api_key:
        print("  ❌ Error: ORS_API_KEY is missing. Please set your API key in the .env file.")
        return None, None, None
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": [start_coords, end_coords]}
    try:
        r = requests.post(ROUTE_URL, json=body, headers=headers, timeout=10)
        if r.status_code in (401, 403):
            print(f"  ❌ Error: Invalid OpenRouteService API key (HTTP {r.status_code}) during routing.")
            return None, None, None
        r.raise_for_status()
        data = r.json()
        feature = data["features"][0]
        summary = feature["properties"]["summary"]
        geometry = feature["geometry"]["coordinates"]
        return summary["distance"], summary["duration"], geometry
    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  ❌ Routing failed: {e}")
        return None, None, None


# --- Fuel price ---
def get_fuel_prices():
    """Fetch all available fuel prices from the API."""
    try:
        r = requests.get(FUEL_URL, timeout=3)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        fuels = {}

        # Extract all available fuel types
        fuel_types = ['regular', 'midgrade', 'premium', 'diesel', 'cng', 'e85', 'electric', 'lpg']
        for fuel in fuel_types:
            elem = root.find(fuel)
            if elem is not None and elem.text:
                try:
                    fuels[fuel] = float(elem.text)
                except ValueError:
                    pass

        return fuels if fuels else None
    except Exception as e:
        print(f"  Could not fetch live fuel prices: {e}")
        return None


def get_fuel_price(fuel_type='regular'):
    """Get price for a specific fuel type, with fallback."""
    from roadtrip_core import FALLBACK_PRICES

    fuels = get_fuel_prices()
    if fuels and fuel_type in fuels:
        return fuels[fuel_type]

    if fuel_type in FALLBACK_PRICES:
        print(f"  Using fallback price for {fuel_type}: ${FALLBACK_PRICES[fuel_type]:.2f}/gal")
        return FALLBACK_PRICES[fuel_type]
    else:
        print(f"  Unknown fuel type '{fuel_type}', using regular fallback: $3.50/gal")
        return 3.50


# --- Map generation ---
def show_map_window(filename):
    """Opens the generated map in its own native app window instead of a browser tab."""
    abs_path = os.path.abspath(filename)
    if webview is not None:
        webview.create_window("Road Trip Planner — Route Map", abs_path, width=1000, height=700)
        webview.start()
    else:
        import webbrowser
        webbrowser.open(f"file://{abs_path}")


# --- Main ---
def main():
    print("🚗 Road Trip Planner")

    print("\nEnter locations (type 'done' when finished, minimum 2):")
    cities = []
    while True:
        city = input(f"  Location {len(cities) + 1}: ").strip()
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
