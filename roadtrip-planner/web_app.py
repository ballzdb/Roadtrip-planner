import math
import os
import requests
import xml.etree.ElementTree as ET
import time
import uuid
import json
from itertools import permutations, combinations
from dotenv import load_dotenv
import folium
from flask import Flask, request, jsonify, send_from_directory

load_dotenv()

# --- Config ---
EARTH_RADIUS_KM = 6371
ORS_API_KEY = os.getenv("ORS_API_KEY")
GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
REVERSE_GEOCODE_URL = "https://api.openrouteservice.org/geocode/reverse"
ROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
FUEL_URL = "https://www.fueleconomy.gov/ws/rest/fuelprices"

# EIA API v2 — U.S. Energy Information Administration
# Provides weekly retail gasoline prices by state, region, and grade
# DEMO_KEY works without registration (rate-limited ~30 req/hr)
EIA_BASE_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
EIA_API_KEY = os.getenv("EIA_API_KEY", "DEMO_KEY")

# Open-Meteo — free weather forecast API (no key needed)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# EIA duoarea codes for US states
# Maps state abbreviation (uppercase) -> EIA duoarea code
STATE_TO_EIA = {
    'AL': 'SAL', 'AK': None, 'AZ': 'SAZ', 'AR': 'SAR', 'CA': 'SCA',
    'CO': 'SCO', 'CT': 'SCT', 'DE': 'SDE', 'FL': 'SFL', 'GA': 'SGA',
    'HI': None, 'ID': 'SID', 'IL': 'SIL', 'IN': 'SIN', 'IA': 'SIA',
    'KS': 'SKS', 'KY': 'SKY', 'LA': 'SLA', 'ME': 'SME', 'MD': 'SMD',
    'MA': 'SMA', 'MI': 'SMI', 'MN': 'SMN', 'MS': 'SMS', 'MO': 'SMO',
    'MT': 'SMT', 'NE': 'SNE', 'NV': 'SNV', 'NH': 'SNH', 'NJ': 'SNJ',
    'NM': 'SNM', 'NY': 'SNY', 'NC': 'SNC', 'ND': 'SND', 'OH': 'SOH',
    'OK': 'SOK', 'OR': 'SOR', 'PA': 'SPA', 'RI': 'SRI', 'SC': 'SSC',
    'SD': 'SSD', 'TN': 'STN', 'TX': 'STX', 'UT': 'SUT', 'VT': 'SVT',
    'VA': 'SVA', 'WA': 'SWA', 'WV': 'SWV', 'WI': 'SWI', 'WY': 'SWY',
    'DC': 'SDC'
}

# EPA CO2 emissions: 8,887 grams CO2 per gallon of gasoline
CO2_GRAMS_PER_GALLON = 8887

# UI route type -> ORS `preference`
ROUTE_PREFERENCES = {
    "fastest": "fastest",
    "shortest": "shortest",
    "eco": "recommended"
}

# UI avoid checkbox -> ORS `options.avoid_features`
AVOID_FEATURES = {
    "tolls": "tollways",
    "highways": "highways",
    "ferries": "ferries"
}

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

def get_ors_api_key():
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

# --- Geocoding ---
def get_coordinates(city_name):
    api_key = get_ors_api_key()
    if not api_key:
        print("ERROR: ORS_API_KEY is missing or not configured in .env file.")
        return None, "OpenRouteService API key is missing. Please add ORS_API_KEY to your .env file."
    headers = {"Authorization": api_key}
    params = {"text": city_name}
    try:
        r = requests.get(GEOCODE_URL, headers=headers, params=params, timeout=10)
        if r.status_code in (401, 403):
            print(f"ERROR: Invalid ORS_API_KEY (HTTP {r.status_code})")
            return None, "Invalid OpenRouteService API key (HTTP 401/403). Please check your ORS_API_KEY in the .env file."
        if r.status_code == 429:
            return None, "OpenRouteService API rate limit exceeded. Please wait a moment and try again."
        r.raise_for_status()
        data = r.json()
        features = data.get("features", [])
        if not features:
            return None, f"Could not find coordinates for city: '{city_name}'. Please check the city name."
        return features[0]["geometry"]["coordinates"], None
    except requests.RequestException as e:
        print(f"Geocoding request error for '{city_name}': {e}")
        return None, f"Network error connecting to geocoding API for '{city_name}'."
    except (KeyError, IndexError) as e:
        print(f"Geocoding data parse error for '{city_name}': {e}")
        return None, f"Could not parse geocoding response for '{city_name}'."

# --- Routing ---
def build_route_options(route_type=None, avoid=None):
    """
    Translate the UI's route preferences into the extra fields ORS expects
    on a directions request. "eco" has no ORS equivalent, so it maps to the
    recommended preference with highways avoided.
    """
    options = {}
    route_type = (route_type or "").strip().lower()

    preference = ROUTE_PREFERENCES.get(route_type)
    if preference:
        options["preference"] = preference

    features = [
        AVOID_FEATURES[name]
        for name, enabled in (avoid or {}).items()
        if enabled and name in AVOID_FEATURES
    ]
    if route_type == "eco" and "highways" not in features:
        features.append("highways")
    if features:
        options["options"] = {"avoid_features": features}

    return options


def get_route(start_coords, end_coords, route_options=None):
    """
    Returns (distance_m, duration_s, geometry).
    geometry is the actual road-shaped path as a list of [lon, lat] points.
    route_options comes from build_route_options() and is merged into the request.
    """
    api_key = get_ors_api_key()
    if not api_key:
        print("ERROR: ORS_API_KEY is missing or not configured in .env file.")
        return None, None, None
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": [start_coords, end_coords], **(route_options or {})}
    try:
        r = requests.post(ROUTE_URL, json=body, headers=headers, timeout=10)
        if r.status_code in (401, 403):
            print(f"ERROR: Invalid ORS_API_KEY in get_route (HTTP {r.status_code})")
            return None, None, None
        if r.status_code == 400 and route_options:
            # The requested preference or avoid_features may be unroutable for
            # this pair of points; fall back to a plain route rather than
            # failing the whole trip.
            print(f"Routing rejected options {route_options}, retrying without them")
            return get_route(start_coords, end_coords)
        r.raise_for_status()
        data = r.json()
        feature = data["features"][0]
        summary = feature["properties"]["summary"]
        geometry = feature["geometry"]["coordinates"]
        return summary["distance"], summary["duration"], geometry
    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"Routing API error: {e}")
        return None, None, None

# --- Reverse-geocode to US state ---
def get_state_from_coords(lon, lat):
    """Reverse-geocode [lon, lat] to a US state abbreviation using ORS."""
    api_key = get_ors_api_key()
    if not api_key:
        return None
    try:
        headers = {"Authorization": api_key}
        params = {"point.lon": lon, "point.lat": lat, "size": 1, "layers": "region"}
        r = requests.get(REVERSE_GEOCODE_URL, headers=headers, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            features = data.get("features", [])
            if features:
                props = features[0].get("properties", {})
                region_a = props.get("region_a")  # e.g. "CA", "TX"
                if region_a and len(region_a) == 2:
                    return region_a.upper()
    except Exception as e:
        print(f"  Reverse geocode error: {e}")
    return None

# --- EIA Gas Prices (primary source) ---
def get_eia_gas_prices(duoarea_codes=None, weeks=1):
    """
    Fetch retail gasoline prices from the EIA API v2.
    duoarea_codes: list of EIA duoarea codes (e.g., ['SCA', 'STX', 'NUS'])
                   If None, fetches national average (NUS).
    weeks: number of most recent weeks to fetch (for trend data)
    Returns list of dicts with keys: period, area_name, product, price
    """
    params = {
        'api_key': EIA_API_KEY,
        'frequency': 'weekly',
        'sort[0][column]': 'period',
        'sort[0][direction]': 'desc',
        'length': str(max(weeks * 10, 20)),  # enough rows for multi-area + weeks
    }
    # Product facets: Regular, Midgrade, Premium, Diesel
    for prod in ['EPMR', 'EPMM', 'EPMP', 'EPMD']:
        params.setdefault('facets[product][]', [])
    # Build product facet params manually since requests doesn't handle repeated keys well
    product_params = '&'.join([
        f'facets[product][]={p}' for p in ['EPMR', 'EPMM', 'EPMP', 'EPMD']
    ])
    # Area facets
    areas = duoarea_codes or ['NUS']
    area_params = '&'.join([f'facets[duoarea][]={a}' for a in areas])

    url = f"{EIA_BASE_URL}?api_key={EIA_API_KEY}&frequency=weekly&{product_params}&{area_params}&sort[0][column]=period&sort[0][direction]=desc&length={max(weeks * len(areas) * 4, 40)}"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = []
        for row in data.get('response', {}).get('data', []):
            value = row.get('value')
            if value is not None:
                results.append({
                    'period': row.get('period'),
                    'area_code': row.get('duoarea'),
                    'area_name': row.get('area-name', '').title(),
                    'product': row.get('product'),
                    'product_name': row.get('product-name', ''),
                    'price': float(value)
                })
        return results
    except Exception as e:
        print(f"  EIA API error: {e}")
        return []


def get_eia_prices_for_states(state_abbrevs):
    """
    Given a list of state abbreviations, fetch the latest gas prices per state.
    Returns dict: {state_abbrev: {regular: price, midgrade: price, premium: price, diesel: price}}
    """
    # Map state abbreviations to EIA duoarea codes
    duoarea_codes = []
    state_map = {}  # duoarea_code -> state_abbrev
    for st in set(state_abbrevs):
        if st and st in STATE_TO_EIA and STATE_TO_EIA[st]:
            code = STATE_TO_EIA[st]
            duoarea_codes.append(code)
            state_map[code] = st

    if not duoarea_codes:
        # Fallback to national average
        duoarea_codes = ['NUS']
        state_map['NUS'] = 'US'

    rows = get_eia_gas_prices(duoarea_codes, weeks=1)

    # EIA product codes -> friendly names
    product_map = {
        'EPMR': 'regular',
        'EPMM': 'midgrade',
        'EPMP': 'premium',
        'EPMD': 'diesel'
    }

    result = {}
    # Get only the most recent period per area+product
    seen = set()
    for row in rows:
        area = row['area_code']
        product = row['product']
        key = (area, product)
        if key in seen:
            continue
        seen.add(key)

        st = state_map.get(area, area)
        if st not in result:
            result[st] = {'state': st, 'area_name': row['area_name']}
        friendly = product_map.get(product, product)
        result[st][friendly] = row['price']

    return result


# --- Legacy fuel prices (fallback) ---
def get_fuel_prices_legacy():
    """Fetch all available fuel prices from fueleconomy.gov (fallback)."""
    try:
        r = requests.get(FUEL_URL, timeout=3)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        fuels = {}
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
        print(f"  Could not fetch legacy fuel prices: {e}")
        return None


# Fallback prices
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


@app.route('/api/fuel_price', methods=['GET'])
def fuel_price():
    """Get all fuel prices (tries EIA national, then legacy, then fallback)."""
    # Try EIA national average first
    eia_data = get_eia_prices_for_states([])
    if eia_data and 'US' in eia_data:
        fuels = {k: v for k, v in eia_data['US'].items() if k in ('regular', 'midgrade', 'premium', 'diesel')}
        if fuels:
            return jsonify({'price_per_gallon': fuels, 'source': 'eia'})
    # Legacy fallback
    fuels = get_fuel_prices_legacy()
    if fuels:
        return jsonify({'price_per_gallon': fuels, 'source': 'fueleconomy.gov'})
    return jsonify({'price_per_gallon': FALLBACK_PRICES, 'source': 'fallback'})


@app.route('/api/gas-prices', methods=['POST'])
def gas_prices_by_route():
    """Get gas prices for each state along the route."""
    data = request.get_json()
    coords = data.get('coords', [])  # list of [lon, lat]
    if not coords:
        return jsonify({'error': 'Coordinates required'}), 400

    # Determine state for each coordinate
    states = []
    for coord in coords:
        st = get_state_from_coords(coord[0], coord[1])
        states.append(st)

    # Get prices for unique states
    unique_states = [s for s in set(states) if s]
    prices_by_state = get_eia_prices_for_states(unique_states)

    # If EIA failed, try legacy
    if not prices_by_state:
        legacy = get_fuel_prices_legacy() or FALLBACK_PRICES
        prices_by_state = {'US': {**legacy, 'state': 'US', 'area_name': 'National Average'}}

    return jsonify({
        'states': states,
        'prices_by_state': prices_by_state,
        'source': 'eia' if unique_states else 'fallback'
    })


@app.route('/api/gas-prices/national', methods=['GET'])
def gas_prices_national():
    """Get national average gas prices + 8-week trend."""
    # Fetch national average for the last 8 weeks
    rows = get_eia_gas_prices(['NUS'], weeks=8)

    # Build trend data (regular only, by week)
    trend = []
    seen_periods = set()
    for row in rows:
        if row['product'] == 'EPMR' and row['period'] not in seen_periods:
            seen_periods.add(row['period'])
            trend.append({'period': row['period'], 'price': row['price']})

    # Sort chronologically
    trend.sort(key=lambda x: x['period'])

    # Get current prices (most recent week, all grades)
    current = {}
    product_map = {'EPMR': 'regular', 'EPMM': 'midgrade', 'EPMP': 'premium', 'EPMD': 'diesel'}
    most_recent_period = None
    for row in rows:
        if most_recent_period is None:
            most_recent_period = row['period']
        if row['period'] == most_recent_period:
            friendly = product_map.get(row['product'])
            if friendly:
                current[friendly] = row['price']

    if not current:
        legacy = get_fuel_prices_legacy() or FALLBACK_PRICES
        current = legacy
        source = 'fallback'
    else:
        source = 'eia'

    return jsonify({
        'current': current,
        'trend': trend,
        'period': most_recent_period,
        'source': source
    })


def get_fuel_price(fuel_type='regular'):
    """Get price for a specific fuel type, with EIA -> legacy -> fallback chain."""
    # Try EIA national
    eia_data = get_eia_prices_for_states([])
    if eia_data and 'US' in eia_data:
        price = eia_data['US'].get(fuel_type)
        if price:
            return price

    # Legacy fallback
    fuels = get_fuel_prices_legacy()
    if fuels and fuel_type in fuels:
        return fuels[fuel_type]

    # Hard fallback
    return FALLBACK_PRICES.get(fuel_type, 3.50)


# --- Weather forecast (Open-Meteo) ---
def get_weather_for_coords(coord_list):
    """
    Fetch 3-day weather forecast for a list of [lon, lat] coordinates.
    Uses the free Open-Meteo API (no key required).
    Returns list of weather dicts.
    """
    results = []
    for coord in coord_list:
        lon, lat = coord[0], coord[1]
        try:
            params = {
                'latitude': lat,
                'longitude': lon,
                'daily': 'temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode',
                'temperature_unit': 'fahrenheit',
                'precipitation_unit': 'inch',
                'timezone': 'auto',
                'forecast_days': 3
            }
            r = requests.get(OPEN_METEO_URL, params=params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                daily = data.get('daily', {})
                days = []
                dates = daily.get('time', [])
                highs = daily.get('temperature_2m_max', [])
                lows = daily.get('temperature_2m_min', [])
                precip = daily.get('precipitation_sum', [])
                codes = daily.get('weathercode', [])
                for i in range(len(dates)):
                    days.append({
                        'date': dates[i],
                        'high_f': highs[i] if i < len(highs) else None,
                        'low_f': lows[i] if i < len(lows) else None,
                        'precip_in': precip[i] if i < len(precip) else 0,
                        'weather_code': codes[i] if i < len(codes) else 0
                    })
                results.append({
                    'lat': lat,
                    'lon': lon,
                    'timezone': data.get('timezone', ''),
                    'days': days
                })
            else:
                results.append({'lat': lat, 'lon': lon, 'days': [], 'error': f'HTTP {r.status_code}'})
        except Exception as e:
            results.append({'lat': lat, 'lon': lon, 'days': [], 'error': str(e)})
    return results

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
    coords, error_msg = get_coordinates(city)
    if coords is None:
        return jsonify({'error': error_msg or f'Could not geocode city: {city}'}), 400
    return jsonify({'coords': coords})

@app.route('/api/route', methods=['POST'])
def route():
    data = request.get_json()
    start = data.get('start')
    end = data.get('end')
    if not start or not end:
        return jsonify({'error': 'Start and end coordinates are required'}), 400
    route_options = build_route_options(data.get('route_type'), data.get('avoid'))
    distance_m, duration_s, geometry = get_route(start, end, route_options)
    if distance_m is None:
        return jsonify({'error': 'Route calculation failed'}), 500
    return jsonify({
        'distance_m': distance_m,
        'duration_s': duration_s,
        'geometry': geometry
    })

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
    route_options = build_route_options(data.get('route_type'), data.get('avoid'))
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

    # Reverse-geocode each stop to get its US state
    stop_states = []
    for coord in ordered_coords:
        st = get_state_from_coords(coord[0], coord[1])
        stop_states.append(st)

    # Fetch EIA gas prices for states along the route
    unique_states = list(set(s for s in stop_states if s))
    state_prices = get_eia_prices_for_states(unique_states) if unique_states else {}

    # Calculate road distances for the optimized route
    total_km = 0
    total_h = 0
    total_gallons = 0
    full_geometry = []
    legs = []  # per leg details
    warnings = []  # warnings for long legs >10h
    for i in range(len(ordered_cities) - 1):
        d_m, dur_s, geometry = get_route(ordered_coords[i], ordered_coords[i + 1], route_options)
        if d_m is None:
            return jsonify({'error': f'Route calculation failed for {ordered_cities[i]} → {ordered_cities[i+1]}'}), 500
        seg_km = d_m / 1000
        seg_h = dur_s / 3600
        total_km += seg_km
        total_h += seg_h
        full_geometry.extend(geometry)

        # Determine per-leg gas price: use origin state price if available
        leg_state = stop_states[i]
        leg_price = None
        leg_state_name = None
        if leg_state and leg_state in state_prices:
            leg_price = state_prices[leg_state].get(fuel_type)
            leg_state_name = state_prices[leg_state].get('area_name', leg_state)
        if leg_price is None:
            leg_price = fuel_price_data.get(fuel_type, fuel_price_data.get('regular', 3.50))

        leg_cost = estimate_fuel_cost(seg_km, mpg, leg_price)
        leg_miles = seg_km * 0.621371
        leg_gallons = leg_miles / mpg
        total_gallons += leg_gallons

        legs.append({
            'from': ordered_cities[i],
            'to': ordered_cities[i+1],
            'distance_km': seg_km,
            'duration_h': seg_h,
            'state': leg_state,
            'state_name': leg_state_name,
            'gas_price': leg_price,
            'fuel_cost': leg_cost
        })
        if seg_h > 10.0:
            warnings.append(f"⚠️ Leg {i+1}: {ordered_cities[i]} → {ordered_cities[i+1]} takes {seg_h:.1f} hours (>10h). Consider breaking this leg with an overnight stop.")

    # Total fuel cost (sum of per-leg costs for state-aware pricing)
    total_cost = sum(leg['fuel_cost'] for leg in legs)
    # Fallback: also compute with flat price for comparison
    price_per_gallon = fuel_price_data.get(fuel_type, fuel_price_data.get('regular', 3.50))
    flat_cost = estimate_fuel_cost(total_km, mpg, price_per_gallon)

    straight_km = sum(haversine(ordered_coords[i], ordered_coords[i+1]) for i in range(len(ordered_coords)-1))
    road_overhead = (total_km / straight_km - 1) * 100 if straight_km > 0 else 0

    # CO2 emissions estimate (EPA: 8,887 grams CO2 per gallon)
    co2_kg = (total_gallons * CO2_GRAMS_PER_GALLON) / 1000

    # Generate map
    map_filename = generate_map(ordered_cities, ordered_coords, route_geometry=full_geometry)

    return jsonify({
        'success': True,
        'ordered_cities': ordered_cities,
        'ordered_coords': ordered_coords,
        'stop_states': stop_states,
        'state_prices': state_prices,
        'total_distance_km': total_km,
        'total_duration_h': total_h,
        'estimated_fuel_cost': total_cost,
        'flat_fuel_cost': flat_cost,
        'total_gallons': total_gallons,
        'co2_kg': co2_kg,
        'straight_line_km': straight_km,
        'road_overhead_percent': road_overhead,
        'method': method,
        'route_type': data.get('route_type'),
        'avoid': data.get('avoid'),
        'car_type': car_type,
        'mpg': mpg,
        'fuel_price_per_gallon': price_per_gallon,
        'fuel_type': fuel_type,
        'fuel_price_all': fuel_price_data,
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

# --- Points of Interest (Overpass API) ---
def get_pois_along_route(coords, radius_miles=5):
    """
    coords: list of [lon, lat] (from ORS)
    Returns dict with keys: 'gas_station', 'restaurant', 'lodging'
    Each value is list of dicts with 'name', 'address', 'lat', 'lon'
    """
    if not coords:
        return {'gas_station': [], 'restaurant': [], 'lodging': []}
    # Overpass API endpoint
    overpass_url = "https://overpass-api.de/api/interpreter"
    # Sample points to avoid too many requests (every nth point)
    step = max(1, len(coords) // 10)  # at most 10 points
    sampled = coords[::step]
    if len(sampled) > 10:
        sampled = sampled[:10]
    pois = {'gas_station': [], 'restaurant': [], 'lodging': []}
    for lon, lat in sampled:
        # Convert radius miles to meters
        radius_meters = int(radius_miles * 1609.34)
        # Build Overpass QL query
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="fuel"](around:{radius_meters},{lat},{lon});
          node["amenity"="restaurant"](around:{radius_meters},{lat},{lon});
          node["amenity"="lodging"](around:{radius_meters},{lat},{lon});
        );
        out center;
        """
        try:
            resp = requests.post(overpass_url, data=query, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for element in data.get('elements', []):
                tags = element.get('tags', {})
                name = tags.get('name') or 'Unnamed'
                # Address approximation
                addr_parts = []
                if tags.get('addr:street'):
                    addr_parts.append(tags['addr:street'])
                if tags.get('addr:housenumber'):
                    addr_parts.insert(0, tags['addr:housenumber'])
                if tags.get('addr:city'):
                    addr_parts.append(tags['addr:city'])
                address = ', '.join(addr_parts) if addr_parts else ''
                poi = {
                    'name': name,
                    'address': address,
                    'lat': element.get('lat'),
                    'lon': element.get('lon')
                }
                amenity = tags.get('amenity')
                if amenity == 'fuel':
                    pois['gas_station'].append(poi)
                elif amenity == 'restaurant':
                    pois['restaurant'].append(poi)
                elif amenity == 'lodging':
                    pois['lodging'].append(poi)
        except Exception as e:
            print(f"POI request error: {e}")
            continue
    # Deduplicate by name+location (simple)
    for key in pois:
        seen = set()
        unique = []
        for p in pois[key]:
            identifier = (p.get('name'), p.get('lat'), p.get('lon'))
            if identifier not in seen:
                seen.add(identifier)
                unique.append(p)
        pois[key] = unique
    return pois


# --- Flask routes for POI ---
@app.route('/api/pois', methods=['POST'])
def pois():
    data = request.get_json()
    coords = data.get('coords')  # list of [lon, lat]
    radius_miles = data.get('radius_miles', 5)
    if not coords:
        return jsonify({'error': 'Coordinates required'}), 400
    pois = get_pois_along_route(coords, radius_miles)
    return jsonify({'poi': pois})


if __name__ == '__main__':
    app.run(debug=True, port=5000)