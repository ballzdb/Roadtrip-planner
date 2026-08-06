document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('trip-form');
    const tripInfo = document.getElementById('trip-info');
    const tripMap = document.getElementById('trip-map');
    const submitBtn = document.getElementById('submit-btn');
    const tripWarnings = document.getElementById('trip-warnings');
    const tripActions = document.getElementById('trip-actions');
    const shareSection = document.getElementById('share-section');
    const shareLinkInput = document.getElementById('share-link');
    const copyLinkBtn = document.getElementById('copy-link-btn');
    const saveTripBtn = document.getElementById('save-trip-btn');
    const shareLinkBtn = document.getElementById('share-link-btn');
    const exportGpxBtn = document.getElementById('export-gpx-btn');
    const exportJsonBtn = document.getElementById('export-json-btn');
    const savedTripsSelect = document.getElementById('saved-trips-select');
    const loadTripBtn = document.getElementById('load-trip-btn');
    const themeLightBtn = document.getElementById('theme-light');
    const themeDarkBtn = document.getElementById('theme-dark');
    const themeAutoBtn = document.getElementById('theme-auto');
    const resultsSection = document.getElementById('trip-results-section');
    const mapContainer = document.getElementById('map-container');
    const poiSection = document.getElementById('pois-section');

    // Initialize theme from localStorage or system preference
    const savedTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    applyTheme(savedTheme);

    // Theme handling
    themeLightBtn.addEventListener('click', () => {
        applyTheme('light');
        localStorage.setItem('theme', 'light');
    });
    themeDarkBtn.addEventListener('click', () => {
        applyTheme('dark');
        localStorage.setItem('theme', 'dark');
    });
    themeAutoBtn.addEventListener('click', () => {
        const systemPref = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        applyTheme(systemPref);
        localStorage.setItem('theme', systemPref);
    });

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        // Update active button
        [themeLightBtn, themeDarkBtn, themeAutoBtn].forEach(btn => {
            btn.classList.remove('active');
        });
        if (theme === 'light') themeLightBtn.classList.add('active');
        else if (theme === 'dark') themeDarkBtn.classList.add('active');
        else themeAutoBtn.classList.add('active');
    }

    // Load saved trips from localStorage
    function loadSavedTrips() {
        const trips = JSON.parse(localStorage.getItem('savedTrips') || '[]');
        savedTripsSelect.innerHTML = '<option value="">Select a saved trip...</option>';
        trips.forEach((trip, index) => {
            const option = document.createElement('option');
            option.value = index;
            option.textContent = trip.name;
            savedTripsSelect.appendChild(option);
        });
    }

    // Save trip to localStorage
    function saveTrip(tripData) {
        const trips = JSON.parse(localStorage.getItem('savedTrips') || '[]');
        trips.push({
            name: tripData.name || `Trip ${new Date().toLocaleString()}`,
            data: tripData,
            timestamp: Date.now()
        });
        // Keep only last 10 trips
        if (trips.length > 10) {
            trips.splice(0, trips.length - 10);
        }
        localStorage.setItem('savedTrips', JSON.stringify(trips));
        loadSavedTrips();
    }

    // Load trip from localStorage by index
    function loadTrip(index) {
        const trips = JSON.parse(localStorage.getItem('savedTrips') || '[]');
        const trip = trips[index];
        if (!trip) return;
        // Populate form
        document.getElementById('cities').value = trip.data.cities.join('\n');
        document.getElementById('car-type').value = trip.data.car_type;
        document.getElementById('fuel-type').value = trip.data.fuel_type;
        applyRouteOptions(trip.data.route_type, trip.data.avoid);
        // Trigger form submission to compute again
        form.dispatchEvent(new Event('submit'));
    }

    // Restore the Route Options controls from saved/shared trip data
    function applyRouteOptions(routeType, avoid) {
        if (routeType) {
            document.getElementById('route-type').value = routeType;
        }
        const selected = avoid || {};
        document.getElementById('avoid-tolls').checked = !!selected.tolls;
        document.getElementById('avoid-highways').checked = !!selected.highways;
        document.getElementById('avoid-ferries').checked = !!selected.ferries;
    }

    // Generate shareable URL from current trip data
    function createShareUrl(tripData) {
        const params = new URLSearchParams();
        params.set('cities', tripData.cities.join('|'));
        params.set('car', tripData.car_type);
        params.set('fuel', tripData.fuel_type);
        params.set('route', tripData.route_type);
        const avoid = Object.entries(tripData.avoid || {})
            .filter(([, enabled]) => enabled)
            .map(([name]) => name);
        if (avoid.length > 0) {
            params.set('avoid', avoid.join('|'));
        }
        const baseUrl = window.location.origin + window.location.pathname;
        return `${baseUrl}?${params.toString()}`;
    }

    // Parse URL parameters and populate form if present
    function initFromUrl() {
        const params = new URLSearchParams(window.location.search);
        const citiesParam = params.get('cities');
        const carParam = params.get('car');
        const fuelParam = params.get('fuel');
        if (citiesParam && carParam && fuelParam) {
            document.getElementById('cities').value = citiesParam.split('|').join('\n');
            document.getElementById('car-type').value = carParam;
            document.getElementById('fuel-type').value = fuelParam === 'mid' ? 'midgrade' : fuelParam;
            const avoidParam = (params.get('avoid') || '').split('|').filter(Boolean);
            applyRouteOptions(params.get('route'), {
                tolls: avoidParam.includes('tolls'),
                highways: avoidParam.includes('highways'),
                ferries: avoidParam.includes('ferries')
            });
            // Auto-submit after a short delay to let UI settle
            setTimeout(() => form.dispatchEvent(new Event('submit')), 500);
        }
    }

    // Export trip as GPX
    function exportAsGpx(tripData) {
        // Create GPX XML
        let gpx = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Road Trip Planner" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>${tripData.name || 'Road Trip'}</name>
    <desc>Generated by Road Trip Planner</desc>
  </metadata>`;

        // Waypoints for each city
        tripData.ordered_cities.forEach((city, index) => {
            const coord = tripData.ordered_coords[index];
            // Note: coords are [lon, lat]; GPX expects lat, lon
            gpx += `
  <wpt lat="${coord[1]}" lon="${coord[0]}">
    <name>${city}</name>
    <sym>Waypoint</sym>
  </wpt>`;
        });

        // Track (ordered route)
        gpx += `
  <trk>
    <name>Route</name>
    <trkseg>`;
        // We don't have detailed geometry in tripData; we'll approximate with ordered_coords
        // For better accuracy, we would need to store the full geometry from backend.
        // We'll just use the city coordinates as track points (straight lines).
        tripData.ordered_coords.forEach(coord => {
            gpx += `
    <trkpt lat="${coord[1]}" lon="${coord[0]}">
      <ele>0</ele>
    </trkpt>`;
        });
        gpx += `
  </trkseg>
  </trk>
</gpx>`;

        // Trigger download
        const blob = new Blob([gpx], { type: 'application/gpx+xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `trip_${Date.now()}.gpx`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // Export trip as JSON
    function exportAsJson(tripData) {
        const dataStr = JSON.stringify(tripData, null, 2);
        const blob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${tripData.name || 'trip'}_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Planning...';
        // Hide previous results
        tripInfo.classList.add('d-none');
        tripWarnings.classList.add('d-none');
        tripActions.classList.add('d-none');
        shareSection.classList.add('d-none');
        resultsSection.classList.add('d-none');
        tripMap.srcdoc = '<p>Loading map...</p>';
        mapContainer.classList.add('loading');

        const citiesText = document.getElementById('cities').value.trim();
        const carType = document.getElementById('car-type').value;
        const rawFuelType = document.getElementById('fuel-type').value;
        const fuelType = rawFuelType === 'mid' ? 'midgrade' : rawFuelType;
        const routeType = document.getElementById('route-type').value;
        const avoidTolls = document.getElementById('avoid-tolls').checked;
        const avoidHighways = document.getElementById('avoid-highways').checked;
        const avoidFerries = document.getElementById('avoid-ferries').checked;
        const poiEnabled = document.getElementById('poi-toggle').checked;

        if (!citiesText) {
            alert('Please enter at least two cities.');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-play-circle me-2"></i>Plan Trip';
            mapContainer.classList.remove('loading');
            return;
        }

        // Parse cities (one per line)
        const cities = citiesText.split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0);

        if (cities.length < 2) {
            alert('Please enter at least two cities.');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-play-circle me-2"></i>Plan Trip';
            mapContainer.classList.remove('loading');
            return;
        }

        try {
            // Geocode all cities
            const coordsPromises = cities.map(city =>
                fetch('/api/geocode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ city })
                }).then(res => res.json())
            );
            const geoResponses = await Promise.all(coordsPromises);
            const coords = [];
            for (let i = 0; i < geoResponses.length; i++) {
                const resp = geoResponses[i];
                if (!resp.coords) {
                    throw new Error(resp.error || `Could not geocode city: ${cities[i]}`);
                }
                coords.push(resp.coords);
            }

            // Get car type MPG
            const carTypeRes = await fetch(`/api/car-types/${carType}`);
            const carTypeData = await carTypeRes.json();
            const mpg = carTypeData.mpg;

            // Get fuel price (all types)
            const fuelPriceRes = await fetch('/api/fuel_price');
            const fuelPriceData = await fuelPriceRes.json(); // Expects {price_per_gallon: {...}}
            // The backend returns {price_per_gallon: {regular:..., mid:..., premium:..., diesel:...}}

            // Optimize route
            const optimizeRes = await fetch('/api/optimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    cities,
                    coords,
                    car_type: carType,
                    mpg,
                    fuel_price: fuelPriceData.price_per_gallon,
                    fuel_type: fuelType,
                    route_type: routeType,
                    avoid: {
                        tolls: avoidTolls,
                        highways: avoidHighways,
                        ferries: avoidFerries
                    }
                })
            });
            const optimizeData = await optimizeRes.json();
            if (!optimizeData.success) {
                throw new Error(optimizeData.error || 'Optimization failed');
            }

            // Store current trip data for export/share
            window.currentTripData = {
                cities: cities,
                car_type: carType,
                fuel_type: fuelType,
                route_type: routeType,
                avoid: {
                    tolls: avoidTolls,
                    highways: avoidHighways,
                    ferries: avoidFerries
                },
                poi_enabled: poiEnabled,
                ordered_cities: optimizeData.ordered_cities,
                ordered_coords: optimizeData.ordered_coords,
                total_distance_km: optimizeData.total_distance_km,
                total_duration_h: optimizeData.total_duration_h,
                estimated_fuel_cost: optimizeData.estimated_fuel_cost,
                fuel_price_per_gallon: optimizeData.fuel_price_per_gallon,
                fuel_price_all: optimizeData.fuel_price_all,
                method: optimizeData.method,
                mpg: optimizeData.mpg,
                warnings: optimizeData.warnings || [],
                legs: optimizeData.legs || []
            };

            // Fetch POIs if enabled
            if (poiEnabled) {
                // POIs
                fetch('/api/pois', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        coords: optimizeData.ordered_coords,
                        radius_miles: 5
                    })
                })
                    .then(res => res.json())
                    .then(poisData => {
                        displayPOIs(poisData.poi);
                        poiSection.classList.remove('d-none');
                    })
                    .catch(err => {
                        console.error('POI fetch error:', err);
                    });
            } else {
                poiSection.classList.add('d-none');
            }


            // Show results section
            resultsSection.classList.remove('d-none');

            // Display results
            tripInfo.innerHTML = `
                <div><strong>Optimized Route:</strong> ${optimizeData.ordered_cities.join(' → ')}</div>
                <div><strong>Total Distance:</strong> ${optimizeData.total_distance_km.toFixed(2)} km</div>
                <div><strong>Estimated Time:</strong> ${optimizeData.total_duration_h.toFixed(2)} hours</div>
                <div><strong>Fuel Cost:</strong> $${optimizeData.estimated_fuel_cost.toFixed(2)}</div>
                <div><strong>Fuel Prices:</strong></div>
                <div class="fuel-prices">
                    ${Object.entries(optimizeData.fuel_price_all)
                    .map(([type, price]) => `
                            <div class="fuel-price-item ${type === optimizeData.fuel_type ? 'active' : ''}">
                                <span class="fuel-type">${type.toUpperCase()}:</span>
                                <span class="fuel-price">$${price.toFixed(2)}/gal</span>
                            </div>
                        `)
                    .join('')}
                </div>
                <div><strong>Car Type:</strong> ${optimizeData.car_type} (${optimizeData.mpg} MPG)</div>
                <div><strong>Optimization Method:</strong> ${optimizeData.method}</div>
                <div><strong>Road vs Straight Distance:</strong> ${optimizeData.road_overhead_percent.toFixed(1)}% longer</div>
                <div><strong>Fuel Used:</strong> ${optimizeData.total_gallons.toFixed(1)} gal</div>
                <div><strong>CO₂ Emissions:</strong> ${optimizeData.co2_kg.toFixed(1)} kg</div>
                ${legsTable(optimizeData.legs)}
            `;
            tripInfo.classList.remove('d-none');

            // Display warnings
            if (optimizeData.warnings && optimizeData.warnings.length > 0) {
                tripWarnings.innerHTML = optimizeData.warnings.map(w => `<div class="alert alert-warning d-flex align-items-center"><i class="bi bi-exclamation-triangle me-2"></i>${w}</div>`).join('');
                tripWarnings.classList.remove('d-none');
            } else {
                tripWarnings.classList.add('d-none');
            }

            // Show actions
            tripActions.classList.remove('d-none');

            // Update share link
            const shareUrl = createShareUrl(window.currentTripData);
            shareLinkInput.value = shareUrl;
            shareSection.classList.remove('d-none');

            // Update map iframe
            const mapUrl = `/map/${optimizeData.map_filename}`;
            fetch(mapUrl)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`Failed to load map: ${response.status} ${response.statusText}`);
                    }
                    return response.text();
                })
                .then(html => {
                    tripMap.srcdoc = html;
                })
                .catch(error => {
                    console.error('Error loading map:', error);
                    tripMap.srcdoc = `<p style="color:red; text-align:center; padding:20px;">Failed to load map: ${error.message}</p>`;
                });

            // Add entrance animations to results
            const resultElements = [
                tripInfo, tripWarnings, tripActions, shareSection,
                document.querySelector('#trip-results-section .card')
            ];
            resultElements.forEach((el, index) => {
                if (el) {
                    el.style.opacity = '0';
                    el.style.transform = 'translateY(20px)';
                    setTimeout(() => {
                        el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
                        el.style.opacity = '1';
                        el.style.transform = 'translateY(0)';
                    }, index * 100);
                }
            });

        } catch (error) {
            console.error('Error:', error);
            alert(`An error occurred: ${error.message}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-play-circle me-2"></i>Plan Trip';
            mapContainer.classList.remove('loading');
        }
    });

    // Save trip button
    saveTripBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            alert('Please plan a trip first.');
            return;
        }
        const name = prompt('Enter a name for this trip:', 'My Road Trip');
        if (name === null) return;
        const tripData = { ...window.currentTripData, name };
        saveTrip(tripData);
        alert('Trip saved!');
    });

    // Share link button
    shareLinkBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            alert('Please plan a trip first.');
            return;
        }
        const shareUrl = createShareUrl(window.currentTripData);
        navigator.clipboard.writeText(shareUrl).then(() => {
            alert('Link copied to clipboard!');
        }).catch(err => {
            alert('Failed to copy: ' + err);
        });
    });

    // Load trip button
    loadTripBtn.addEventListener('click', () => {
        const index = savedTripsSelect.value;
        if (index === '') {
            alert('Please select a saved trip.');
            return;
        }
        loadTrip(parseInt(index));
    });

    // Export GPX button
    exportGpxBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            alert('Please plan a trip first.');
            return;
        }
        const name = prompt('Enter a name for the GPX file:', 'trip');
        if (name === null) return;
        const tripData = { ...window.currentTripData, name };
        exportAsGpx(tripData);
    });

    // Export JSON button
    exportJsonBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            alert('Please plan a trip first.');
            return;
        }
        const name = prompt('Enter a name for the JSON file:', 'trip_data');
        if (name === null) return;
        const tripData = { ...window.currentTripData, name };
        exportAsJson(tripData);
    });

    // Per-leg breakdown table
    function legsTable(legs) {
        if (!legs || legs.length === 0) return '';
        const rows = legs.map(leg => `
        <tr>
            <td>${leg.from} → ${leg.to}</td>
            <td>${leg.distance_km.toFixed(1)} km</td>
            <td>${leg.duration_h.toFixed(2)} h</td>
            <td>${leg.state_name || leg.state || '—'}</td>
            <td>$${leg.gas_price.toFixed(2)}/gal</td>
            <td>$${leg.fuel_cost.toFixed(2)}</td>
        </tr>
    `).join('');
        return `
        <div class="mt-3"><strong>Legs:</strong></div>
        <div class="table-responsive">
            <table class="table table-sm align-middle">
                <thead>
                    <tr><th>Leg</th><th>Distance</th><th>Time</th><th>Gas priced in</th><th>Price</th><th>Cost</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
    }

    // POI and Elevation Functions
    function displayPOIs(poisData) {
        const poisList = document.getElementById('pois-list');
        poisList.innerHTML = '';
        const poiTypes = ['gas_station', 'restaurant', 'lodging'];
        const total = poiTypes.reduce((sum, type) => sum + (poisData[type] || []).length, 0);
        if (total === 0) {
            poisList.innerHTML = '<div class="col-12 text-muted">No points of interest found — OpenStreetMap may be rate limiting, try again in a moment.</div>';
            return;
        }
        poiTypes.forEach(type => {
            const pois = poisData[type] || [];
            if (pois.length === 0) return;
            const typeDiv = document.createElement('div');
            typeDiv.className = 'col-12 mb-3';
            typeDiv.innerHTML = `<h6>${type.replace('_', ' ').toUpperCase()}</h6>`;
            const listGroup = document.createElement('div');
            listGroup.className = 'list-group';
            pois.forEach(poi => {
                const item = document.createElement('div');
                item.className = 'list-group-item list-group-item-action';
                item.innerHTML = `<strong>${poi.name || 'Unnamed'}</strong><br><small class="text-muted">${poi.address || ''}</small>`;
                listGroup.appendChild(item);
            });
            typeDiv.appendChild(listGroup);
            poisList.appendChild(typeDiv);
        });
    }


    // Initial load: check for URL params and load saved trips list
    loadSavedTrips();
    initFromUrl();

    // Add floating elements animation
    const floatingElements = document.querySelector('.floating-elements');
    if (floatingElements) {
        floatingElements.style.setProperty('--count', '5');
    }
});
