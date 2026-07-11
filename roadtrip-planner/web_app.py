import math
import os
import requests
import xml.etree.ElementTree as ET
import time
import uuid
from itertools import permutations, combinations
from dotenv import load_dotenv
import folium
from flask import Flask, request, jsonify, send_from_directory

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

app = Flask(__name__, static_folder='static')

# Directory for generated maps
MAPS_DIR = os.path.join(os.path.dirname(__file__), 'maps')
os.makedirs(MAPS_DIR, exist_ok=True)

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
        return None

# --- Routing ---
def get_route(start_coords, end_coords):
    """
    Returns (distance_m, duration_s, geometry).
    geometry is the actual road-shaped path as a list of [lon, lat] points.
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
        return None, None, None

# --- Fuel price ---
def get_fuel_price():
    try:
        r = requests.get(FUEL_URL, timeout=3)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        fuels = {}
        for fuel_type in ['regular', 'mid', 'premium', 'diesel']:
            elem = root.find(fuel_type)
            if elem is not None and elem.text:
                fuels[fuel_type] = float(elem.text)
        # If none found, fallback
        if not fuels:
            return {'regular': 3.50, 'mid': 3.50, 'premium': 3.50, 'diesel': 3.50}
        return fuels
    except Exception:
        pass
    return {'regular': 3.50, 'mid': 3.50, 'premium': 3.50, 'diesel': 3.50}

# --- Fuel cost ---
def estimate_fuel_cost(distance_km, mpg, price_per_gallon):
    miles = distance_km * 0.621371
    gallons = miles / mpg
    return round(gallons * price_per_gallon, 2)

# --- TSP: Brute Force O(n!) ---
def brute_force_tsp(coords):
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
    n = len(coords)
    dist = [[haversine(coords[i], coords[j]) for j in range(n)] for i in range(n)]
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
def generate_map(cities, coords, route_geometry=None, filename=None):
    if filename is None:
        filename = f"map_{uuid.uuid4().hex}.html"
    filepath = os.path.join(MAPS_DIR, filename)
    print(f"Generating map: {filepath}")  # Debug
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
    print(f"Map saved: {filepath}")  # Debug
    return filename

# --- Flask routes ---
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

@app.route('/api/geocode', methods=['POST'])
def geocode():
    data = request.get_json()
    city = data.get('city')
    if not city:
        return jsonify({'error': 'City is required'}), 400
    coords = get_coordinates(city)
    if coords is None:
        return jsonify({'error': f'Could not geocode city: {city}'}), 404
    return jsonify({'coords': coords})

@app.route('/api/route', methods=['POST'])
def route():
    data = request.get_json()
    start = data.get('start')
    end = data.get('end')
    if not start or not end:
        return jsonify({'error': 'Start and end coordinates are required'}), 400
    distance_m, duration_s, geometry = get_route(start, end)
    if distance_m is None:
        return jsonify({'error': 'Route calculation failed'}), 500
    return jsonify({
        'distance_m': distance_m,
        'duration_s': duration_s,
        'geometry': geometry
    })

@app.route('/api/fuel_price', methods=['GET'])
def fuel_price():
    price = get_fuel_price()
    return jsonify({'price_per_gallon': price})

@app.route('/api/car-types/<car_type>', methods=['GET'])
def car_type_info(car_type):
    mpg = CAR_TYPES.get(car_type.lower())
    if mpg is None:
        return jsonify({'error': 'Invalid car type'}), 400
    return jsonify({'mpg': mpg})

@app.route('/api/optimize', methods=['POST'])
def optimize():
    data = request.get_json()
    cities = data.get('cities')
    coords = data.get('coords')
    car_type = data.get('car_type')
    mpg = data.get('mpg')
    fuel_price_data = data.get('fuel_price')  # dict of fuel type to price
    fuel_type = data.get('fuel_type', 'regular')  # default to regular
    if not cities or not coords or not car_type or mpg is None or not fuel_price_data:
        return jsonify({'error': 'Missing required parameters'}), 400
    if len(cities) != len(coords):
        return jsonify({'error': 'Cities and coordinates length mismatch'}), 400

    n = len(cities)
    # Choose algorithm based on number of cities
    if n <= 8:
        order, dist = brute_force_tsp(coords)
        method = 'brute_force'
    elif n <= 15:
        order, dist = held_karp_tsp(coords)
        method = 'held_karp'
    else:
        order, dist = nearest_neighbor_tsp(coords)
        method = 'nearest_neighbor'

    ordered_cities = [cities[i] for i in order]
    ordered_coords = [coords[i] for i in order]

    # Calculate road distances for the optimized route
    total_km = 0
    total_h = 0
    full_geometry = []
    legs = []  # per leg details
    warnings = []  # warnings for long legs >10h
    for i in range(len(ordered_cities) - 1):
        d_m, dur_s, geometry = get_route(ordered_coords[i], ordered_coords[i + 1])
        if d_m is None:
            return jsonify({'error': f'Route calculation failed for {ordered_cities[i]} → {ordered_cities[i+1]}'}), 500
        seg_km = d_m / 1000
        seg_h = dur_s / 3600
        total_km += seg_km
        total_h += seg_h
        full_geometry.extend(geometry)
        legs.append({
            'from': ordered_cities[i],
            'to': ordered_cities[i+1],
            'distance_km': seg_km,
            'duration_h': seg_h,
            'geometry': geometry  # optional, could be large; we might omit to keep payload small
        })
        if seg_h > 10.0:
            warnings.append(f"⚠️ Leg {i+1}: {ordered_cities[i]} → {ordered_cities[i+1]} takes {seg_h:.1f} hours (>10h). Consider breaking this leg with an overnight stop.")

    # Determine fuel price per gallon for selected fuel type
    price_per_gallon = fuel_price_data.get(fuel_type, fuel_price_data.get('regular', 3.50))
    cost = estimate_fuel_cost(total_km, mpg, price_per_gallon)
    straight_km = sum(haversine(ordered_coords[i], ordered_coords[i+1]) for i in range(len(ordered_coords)-1))
    road_overhead = (total_km / straight_km - 1) * 100 if straight_km > 0 else 0

    # Generate map
    map_filename = generate_map(ordered_cities, ordered_coords, route_geometry=full_geometry)

    return jsonify({
        'success': True,
        'ordered_cities': ordered_cities,
        'ordered_coords': ordered_coords,
        'total_distance_km': total_km,
        'total_duration_h': total_h,
        'estimated_fuel_cost': cost,
        'straight_line_km': straight_km,
        'road_overhead_percent': road_overhead,
        'method': method,
        'car_type': car_type,
        'mpg': mpg,
        'fuel_price_per_gallon': price_per_gallon,
        'fuel_type': fuel_type,
        'fuel_price_all': fuel_price_data,  # send all fuel types for display
        'legs': legs,
        'warnings': warnings,
        'map_filename': map_filename
    })

@app.route('/map/<filename>')
def serve_map(filename):
    filepath = os.path.join(MAPS_DIR, filename)
    with open('map_requests.log', 'a') as f:
        f.write(f'Serving map: {filepath} from {request.remote_addr}\\n')
    if not os.path.exists(filepath):
        with open('map_requests.log', 'a') as f:
            f.write(f'File not found: {filepath}\\n')
        return 'Map not found', 404
    return send_from_directory(MAPS_DIR, filename)

if __name__ == '__main__':
    app.run(debug=True, port=5000)