import os
import requests
import xml.etree.ElementTree as ET
import time
import functools
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory

from roadtrip_core import (
    haversine,
    get_ors_api_key,
    estimate_fuel_cost,
    brute_force_tsp,
    held_karp_tsp,
    nearest_neighbor_tsp,
    generate_map,
    CAR_TYPES,
    FALLBACK_PRICES,
)

load_dotenv()

# --- Config ---
ORS_API_KEY = os.getenv("ORS_API_KEY")
GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
REVERSE_GEOCODE_URL = "https://api.openrouteservice.org/geocode/reverse"
ROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
FUEL_URL = "https://www.fueleconomy.gov/ws/rest/fuelprices"
EIA_BASE_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
EIA_API_KEY = os.getenv("EIA_API_KEY", "DEMO_KEY")


def has_valid_eia_key():
    return bool(EIA_API_KEY and EIA_API_KEY.strip() and EIA_API_KEY != "DEMO_KEY")

# Open-Meteo — free weather forecast API (no key needed)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Overpass (OpenStreetMap) — points of interest along the route
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]
OVERPASS_USER_AGENT = "roadtrip-planner/1.0"
LODGING_TOURISM_TAGS = {'hotel', 'motel', 'hostel', 'guest_house'}
# Sample more points along the route so POIs cover the whole trip,
# not just the midpoint. Each sample triggers one Overpass query.
POI_SAMPLE_POINTS = 4
POI_MAX_PER_CATEGORY = 12
# Overpass throttles hard (429/504) and each extra element costs latency,
# so cap what a single query returns.
POI_QUERY_LIMIT = 50

# Map files are generated per-trip; anything older than this is deleted.
MAP_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours

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

app = Flask(__name__, static_folder='static')

# Directory for generated maps
MAPS_DIR = os.path.join(os.path.dirname(__file__), 'maps')
os.makedirs(MAPS_DIR, exist_ok=True)


def cleanup_old_maps(max_age_seconds=MAP_MAX_AGE_SECONDS, max_files=100):
    """
    Delete stale generated map files so the maps/ directory does not grow
    without bound. Called periodically from serve_map.
    """
    try:
        files = []
        for fname in os.listdir(MAPS_DIR):
            if not fname.endswith('.html'):
                continue
            fpath = os.path.join(MAPS_DIR, fname)
            try:
                mtime = os.path.getmtime(fpath)
            except OSError:
                continue
            files.append((fpath, mtime))

        now = time.time()
        # Delete oldest files over the count cap.
        if len(files) > max_files:
            files.sort(key=lambda x: x[1])
            for fpath, _ in files[: len(files) - max_files]:
                try:
                    os.remove(fpath)
                except OSError:
                    pass

        # Delete any file older than the max age.
        for fpath, mtime in files:
            if now - mtime > max_age_seconds:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
    except Exception as e:
        print(f"Map cleanup error: {e}")

# --- Simple TTL cache for external API calls ---
def _make_hashable(obj):
    """Recursively convert unhashable types (list, dict) into hashable ones."""
    if isinstance(obj, list):
        return tuple(_make_hashable(item) for item in obj)
    if isinstance(obj, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in obj.items()))
    if isinstance(obj, tuple):
        return tuple(_make_hashable(item) for item in obj)
    return obj


def ttl_cache(seconds=3600):
    """Cache function results for `seconds` seconds."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__, _make_hashable(args), tuple(sorted((k, _make_hashable(v)) for k, v in kwargs.items())))
            now = time.time()
            if key in ttl_cache._store:
                cached_at, result = ttl_cache._store[key]
                if now - cached_at < seconds:
                    return result
            result = func(*args, **kwargs)
            ttl_cache._store[key] = (now, result)
            return result
        return wrapper
    return decorator

ttl_cache._store = {}


# --- Geocoding ---
@ttl_cache(seconds=3600)
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


def get_route(start_coords, end_coords, route_options=None, _retry_attempt=0):
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
        if r.status_code == 429 and _retry_attempt < 2:
            # Rate limited: wait briefly with exponential backoff, then retry.
            backoff = (2 ** _retry_attempt) + 1
            print(f"ORS rate limited (429), retrying in {backoff}s...")
            time.sleep(backoff)
            return get_route(start_coords, end_coords, route_options, _retry_attempt + 1)
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
@ttl_cache(seconds=3600)
def get_state_from_coords(lon, lat):
    """Reverse-geocode [lon, lat] to a US state abbreviation using ORS."""
    if not has_valid_eia_key():
        return None
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
    if not has_valid_eia_key():
        print("  EIA API disabled: no valid EIA_API_KEY provided.")
        return []

    areas = duoarea_codes or ['NUS']
    params = {
        'api_key': EIA_API_KEY,
        'frequency': 'weekly',
        'sort[0][column]': 'period',
        'sort[0][direction]': 'desc',
        'length': str(max(weeks * len(areas) * 4, 40)),
        'facets[product][]': ['EPMR', 'EPMM', 'EPMP', 'EPMD'],
        'facets[duoarea][]': areas,
    }

    try:
        r = requests.get(EIA_BASE_URL, params=params, timeout=10)
        if r.status_code == 429:
            print("  EIA API rate limit exceeded.")
            return []
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


@ttl_cache(seconds=3600)
def get_eia_prices_for_states(state_abbrevs):
    """
    Given a list of state abbreviations, fetch the latest gas prices per state.
    Returns dict: {state_abbrev: {regular: price, midgrade: price, premium: price, diesel: price}}
    """
    if not has_valid_eia_key():
        return {}

    # Map state abbreviations to EIA duoarea codes
    duoarea_codes = []
    state_map = {}  # duoarea_code -> state_abbrev
    for st in set(state_abbrevs):
        if st and st in STATE_TO_EIA and STATE_TO_EIA[st]:
            code = STATE_TO_EIA[st]
            duoarea_codes.append(code)
            state_map[code] = st

    if not duoarea_codes:
        # Fallback to national average if no valid state list.
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


@app.route('/api/fuel_price', methods=['GET'])
def fuel_price():
    """Get all fuel prices (tries EIA national, then legacy, then fallback)."""
    if has_valid_eia_key():
        eia_data = get_eia_prices_for_states([])
        if eia_data and 'US' in eia_data:
            fuels = {k: v for k, v in eia_data['US'].items() if k in ('regular', 'midgrade', 'premium', 'diesel')}
            if fuels:
                return jsonify({'price_per_gallon': fuels, 'source': 'eia', 'eia_enabled': True, 'live_prices': True})

    fuels = get_fuel_prices_legacy()
    if fuels:
        return jsonify({
            'price_per_gallon': fuels,
            'source': 'fueleconomy.gov',
            'eia_enabled': has_valid_eia_key(),
            'live_prices': True
        })

    return jsonify({
        'price_per_gallon': FALLBACK_PRICES,
        'source': 'fallback',
        'eia_enabled': has_valid_eia_key(),
        'live_prices': False,
        'message': 'EIA state pricing disabled or unavailable, using fallback prices.'
    })


# --- Weather forecast (Open-Meteo) ---
@ttl_cache(seconds=1800)
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
    fuel_price_source = data.get('fuel_price_source', 'unknown')
    fuel_price_source_live = data.get('fuel_price_source_live', False)
    eia_enabled = data.get('eia_enabled', False)
    fuel_type = data.get('fuel_type', 'regular')  # default to regular
    if fuel_type == 'mid':
        fuel_type = 'midgrade'
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
    overnight_recommendations = []
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

        leg_data = {
            'from': ordered_cities[i],
            'to': ordered_cities[i+1],
            'distance_km': seg_km,
            'duration_h': seg_h,
            'state': leg_state,
            'state_name': leg_state_name,
            'gas_price': leg_price,
            'fuel_cost': leg_cost
        }
        legs.append(leg_data)
        if seg_h > 10.0:
            warnings.append(f"⚠️ Leg {i+1}: {ordered_cities[i]} → {ordered_cities[i+1]} takes {seg_h:.1f} hours (>10h). Consider breaking this leg with an overnight stop.")
            midpoint = None
            if geometry:
                midpoint = geometry[len(geometry) // 2]
            if midpoint is None:
                # Fallback to geographic midpoint of origin/destination
                midpoint = [
                    (ordered_coords[i][0] + ordered_coords[i + 1][0]) / 2,
                    (ordered_coords[i][1] + ordered_coords[i + 1][1]) / 2
                ]
            lodging = get_lodging_near(midpoint, radius_miles=12, max_results=5)
            overnight_recommendations.append({
                'leg_index': i + 1,
                'from': ordered_cities[i],
                'to': ordered_cities[i+1],
                'duration_h': seg_h,
                'midpoint': {'lat': midpoint[1], 'lon': midpoint[0]},
                'lodging': lodging
            })

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
        'fuel_price_source': fuel_price_source,
        'fuel_price_source_live': fuel_price_source_live,
        'eia_enabled': eia_enabled,
        'legs': legs,
        'warnings': warnings,
        'overnight_recommendations': overnight_recommendations,
        'map_filename': map_filename,
        'route_geometry': full_geometry
    })

@app.route('/map/<filename>')
def serve_map(filename):
    # Prevent path traversal
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        return 'Invalid filename', 400
    filepath = os.path.join(MAPS_DIR, safe_name)
    if not os.path.exists(filepath):
        with open('map_requests.log', 'a') as f:
            f.write(f'File not found: {safe_name}\\n')
        return 'Map not found', 404
    # Opportunistically clean up old maps (cheap: lists a small dir).
    cleanup_old_maps()
    with open('map_requests.log', 'a') as f:
        f.write(f'Serving map: {safe_name} from {request.remote_addr}\\n')
    return send_from_directory(MAPS_DIR, safe_name)

# --- Points of Interest (Overpass API) ---
def overpass_query(query, attempts=1):
    """
    Run an Overpass QL query, returning the response or None.
    Overpass answers 406 without a User-Agent and expects the query in the
    `data` form field; it also returns 429/504 when busy, so retry with backoff.
    """
    for base_url in OVERPASS_URLS:
        for attempt in range(attempts):
            try:
                resp = requests.post(
                    base_url,
                    data={'data': query},
                    headers={'User-Agent': OVERPASS_USER_AGENT},
                    timeout=12
                )
                if resp.status_code == 200:
                    return resp
                print(f"Overpass returned HTTP {resp.status_code} from {base_url}")
                if resp.status_code not in (429, 502, 503, 504):
                    break
            except requests.RequestException as e:
                print(f"Overpass request error from {base_url}: {e}")
                if isinstance(e, (requests.ConnectTimeout, requests.ConnectionError)):
                    break
            if attempt < attempts - 1:
                backoff = 2 ** attempt
                print(f"Retrying Overpass {base_url} in {backoff}s...")
                time.sleep(backoff)
        print(f"Trying next Overpass endpoint after failing {base_url}")
    return None


def get_pois_along_route(coords, radius_miles=5):
    """
    coords: list of [lon, lat] (from ORS)
    Returns dict with keys: 'gas_station', 'restaurant', 'lodging'
    Each value is list of dicts with 'name', 'address', 'lat', 'lon'
    """
    if not coords:
        return {'attraction': [], 'gas_station': [], 'restaurant': [], 'lodging': []}
    # Sample points to avoid too many requests, while covering the route.
    if POI_SAMPLE_POINTS <= 1 or len(coords) <= POI_SAMPLE_POINTS:
        sampled = [coords[len(coords) // 2]]
    else:
        span = len(coords) - 1
        step = span / (POI_SAMPLE_POINTS - 1)
        sampled = []
        for i in range(POI_SAMPLE_POINTS):
            index = int(round(i * step))
            sampled.append(coords[min(index, len(coords) - 1)])
    pois = {'attraction': [], 'gas_station': [], 'restaurant': [], 'lodging': []}

    def parse_element(element):
        tags = element.get('tags', {})
        name = tags.get('name') or 'Unnamed'
        lat_value = element.get('lat') or element.get('center', {}).get('lat')
        lon_value = element.get('lon') or element.get('center', {}).get('lon')
        if lat_value is None or lon_value is None:
            return None
        street = ' '.join(p for p in (tags.get('addr:housenumber'), tags.get('addr:street')) if p)
        addr_parts = [p for p in (street, tags.get('addr:city'), tags.get('addr:state')) if p]
        address = ', '.join(addr_parts)
        return {
            'name': name,
            'address': address,
            'lat': lat_value,
            'lon': lon_value,
            'tags': tags
        }

    for lon, lat in sampled:
        radius_meters = int(radius_miles * 1609.34)
        query = f"""
        [out:json][timeout:20];
        (
          node["amenity"="fuel"](around:{radius_meters},{lat},{lon});
          way["amenity"="fuel"](around:{radius_meters},{lat},{lon});
          relation["amenity"="fuel"](around:{radius_meters},{lat},{lon});

          node["amenity"="restaurant"](around:{radius_meters},{lat},{lon});
          way["amenity"="restaurant"](around:{radius_meters},{lat},{lon});
          relation["amenity"="restaurant"](around:{radius_meters},{lat},{lon});

          node["tourism"~"^(hotel|motel|hostel|guest_house)$"](around:{radius_meters},{lat},{lon});
          way["tourism"~"^(hotel|motel|hostel|guest_house)$"](around:{radius_meters},{lat},{lon});
          relation["tourism"~"^(hotel|motel|hostel|guest_house)$"](around:{radius_meters},{lat},{lon});

          node["tourism"~"^(attraction|viewpoint|museum|zoo|theme_park)$"](around:{radius_meters},{lat},{lon});
          way["tourism"~"^(attraction|viewpoint|museum|zoo|theme_park)$"](around:{radius_meters},{lat},{lon});
          relation["tourism"~"^(attraction|viewpoint|museum|zoo|theme_park)$"](around:{radius_meters},{lat},{lon});

          node["historic"~"^(monument|castle|ruins|memorial)$"](around:{radius_meters},{lat},{lon});
          way["historic"~"^(monument|castle|ruins|memorial)$"](around:{radius_meters},{lat},{lon});
          relation["historic"~"^(monument|castle|ruins|memorial)$"](around:{radius_meters},{lat},{lon});
        );
        out center {POI_QUERY_LIMIT};
        """
        try:
            resp = overpass_query(query)
            if resp is None:
                continue
            data = resp.json()
            for element in data.get('elements', []):
                poi = parse_element(element)
                if poi is None:
                    continue
                tags = poi['tags']
                amenity = tags.get('amenity')
                tourism = tags.get('tourism')
                historic = tags.get('historic')
                if amenity == 'fuel':
                    pois['gas_station'].append(poi)
                elif amenity == 'restaurant':
                    pois['restaurant'].append(poi)
                elif tourism in LODGING_TOURISM_TAGS:
                    pois['lodging'].append(poi)
                elif tourism in ('attraction', 'viewpoint', 'museum', 'zoo', 'theme_park') or historic in ('monument', 'castle', 'ruins', 'memorial'):
                    pois['attraction'].append(poi)
        except Exception as e:
            print(f"POI request error: {e}")
            continue

    # Deduplicate by name+location and sort named places first.
    for key in pois:
        seen = set()
        unique = []
        for p in pois[key]:
            identifier = (p.get('name'), p.get('lat'), p.get('lon'))
            if identifier not in seen:
                seen.add(identifier)
                unique.append(p)
        unique.sort(key=lambda p: p['name'] == 'Unnamed')
        pois[key] = unique[:POI_MAX_PER_CATEGORY]
    return pois


@ttl_cache(seconds=1800)
def get_lodging_near(coord, radius_miles=12, max_results=6):
    """Find lodging near a coordinate using Overpass and OSM tourism tags."""
    if not coord or len(coord) != 2:
        return []
    lon, lat = coord
    radius_meters = int(radius_miles * 1609.34)
    query = f"""
        [out:json][timeout:20];
        (
          node["tourism"~"^(hotel|motel|hostel|guest_house)$"](around:{radius_meters},{lat},{lon});
          way["tourism"~"^(hotel|motel|hostel|guest_house)$"](around:{radius_meters},{lat},{lon});
          relation["tourism"~"^(hotel|motel|hostel|guest_house)$"](around:{radius_meters},{lat},{lon});
        );
        out center {POI_QUERY_LIMIT};
    """
    lodging = []
    try:
        resp = overpass_query(query)
        if resp is None:
            return []
        data = resp.json()
        for element in data.get('elements', []):
            tags = element.get('tags', {})
            name = tags.get('name') or 'Unnamed lodging'
            lat_value = element.get('lat') or element.get('center', {}).get('lat')
            lon_value = element.get('lon') or element.get('center', {}).get('lon')
            if lat_value is None or lon_value is None:
                continue
            street = ' '.join(p for p in (tags.get('addr:housenumber'), tags.get('addr:street')) if p)
            addr_parts = [p for p in (street, tags.get('addr:city'), tags.get('addr:state')) if p]
            address = ', '.join(addr_parts)
            distance_m = int(haversine(coord, [lon_value, lat_value]) * 1000)
            lodging.append({
                'name': name,
                'address': address,
                'lat': lat_value,
                'lon': lon_value,
                'distance_m': distance_m
            })
    except Exception as e:
        print(f"Lodging search error: {e}")
    # Deduplicate by name+location and sort by proximity
    seen = set()
    unique = []
    for p in sorted(lodging, key=lambda p: p['distance_m']):
        identifier = (p['name'], p['lat'], p['lon'])
        if identifier not in seen:
            seen.add(identifier)
            unique.append(p)
            if len(unique) >= max_results:
                break
    return unique


# --- Flask routes for POI ---
@app.route('/api/weather', methods=['POST'])
def weather():
    data = request.get_json(silent=True) or {}
    coords = data.get('coords')  # list of [lon, lat]
    if not isinstance(coords, list) or not coords:
        return jsonify({'weather': []})

    weather_data = get_weather_for_coords(coords)
    return jsonify({'weather': weather_data})


@app.route('/api/pois', methods=['POST'])
def pois():
    data = request.get_json(silent=True) or {}
    coords = data.get('coords')  # list of [lon, lat]
    radius_miles = data.get('radius_miles', 5)
    if not isinstance(coords, list) or not coords:
        return jsonify({'poi': {'attraction': [], 'gas_station': [], 'restaurant': [], 'lodging': []}})

    try:
        pois = get_pois_along_route(coords, radius_miles)
    except Exception as exc:
        print(f'POI route error: {exc}')
        pois = {'attraction': [], 'gas_station': [], 'restaurant': [], 'lodging': []}

    return jsonify({'poi': pois})


if __name__ == '__main__':
    app.run(debug=False, use_reloader=False, port=5000)
