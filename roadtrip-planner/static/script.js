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
    const weatherSection = document.getElementById('weather-section');
    const weatherList = document.getElementById('weather-list');
    const itinerarySection = document.getElementById('itinerary-section');
    const itineraryList = document.getElementById('itinerary-list');
    const avoidTolls = document.getElementById('avoid-tolls');
    const avoidHighways = document.getElementById('avoid-highways');
    const avoidFerries = document.getElementById('avoid-ferries');
    const printTripBtn = document.getElementById('print-trip-btn');
    const toastContainer = document.getElementById('toast-container');

    // --- Toast notification helper (replaces browser alert) ---
    function showToast(message, type = 'info', title = '') {
        const icons = {
            info: 'bi-info-circle',
            success: 'bi-check-circle',
            warning: 'bi-exclamation-triangle',
            error: 'bi-x-circle'
        };
        const icon = icons[type] || icons.info;
        const toastEl = document.createElement('div');
        toastEl.className = `toast align-items-center text-bg-${type === 'info' ? 'dark' : type} border-0`;
        toastEl.setAttribute('role', 'alert');
        toastEl.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    ${title ? `<strong>${title}</strong><br>` : ''}
                    <i class="bi ${icon} me-1"></i>${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;
        toastContainer.appendChild(toastEl);
        const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
        toast.show();
        toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
    }

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

    // Return the current avoid settings from the checkboxes
    function getAvoidSettings() {
        return {
            tolls: avoidTolls.checked,
            highways: avoidHighways.checked,
            ferries: avoidFerries.checked
        };
    }

    // Restore the Route Options controls from saved/shared trip data
    function applyRouteOptions(routeType, avoid) {
        if (routeType) {
            document.getElementById('route-type').value = routeType;
        }
        avoidTolls.checked = !!(avoid && avoid.tolls);
        avoidHighways.checked = !!(avoid && avoid.highways);
        avoidFerries.checked = !!(avoid && avoid.ferries);
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

        // Track (ordered route) using real road geometry if available
        gpx += `
  <trk>
    <name>Route</name>
    <trkseg>`;
        // Use the actual road geometry from the backend if we have it;
        // otherwise fall back to straight lines between city coords.
        const gpxPoints = (tripData.route_geometry && tripData.route_geometry.length > 0)
            ? tripData.route_geometry.map(pt => ({ lat: pt[1], lon: pt[0] }))
            : tripData.ordered_coords.map(coord => ({ lat: coord[1], lon: coord[0] }));
        gpxPoints.forEach(pt => {
            gpx += `
    <trkpt lat="${pt.lat}" lon="${pt.lon}">
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
        poiSection.classList.add('d-none');
        weatherSection.classList.add('d-none');
        itinerarySection.classList.add('d-none');
        tripMap.srcdoc = '<p>Loading map...</p>';
        mapContainer.classList.add('loading');

        const citiesText = document.getElementById('cities').value.trim();
        const carType = document.getElementById('car-type').value;
        const rawFuelType = document.getElementById('fuel-type').value;
        const fuelType = rawFuelType === 'mid' ? 'midgrade' : rawFuelType;
        const routeType = document.getElementById('route-type').value;
        const poiEnabled = document.getElementById('poi-toggle').checked;
        const avoidSettings = getAvoidSettings();

        if (!citiesText) {
            showToast('Please enter at least two cities.', 'warning');
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
            showToast('Please enter at least two cities.', 'warning');
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
            const fuelPriceData = await fuelPriceRes.json(); // Expects {price_per_gallon: {...}, source: '...', eia_enabled: bool}

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
                    fuel_price_source: fuelPriceData.source,
                    fuel_price_source_live: !!fuelPriceData.live_prices,
                    eia_enabled: fuelPriceData.eia_enabled,
                    route_type: routeType,
                    avoid: avoidSettings
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
                avoid: avoidSettings,
                poi_enabled: poiEnabled,
                fuel_price_source: fuelPriceData.source,
                fuel_price_source_live: !!fuelPriceData.live_prices,
                eia_enabled: fuelPriceData.eia_enabled,
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
                legs: optimizeData.legs || [],
                route_geometry: optimizeData.route_geometry || [],
                road_overhead_percent: optimizeData.road_overhead_percent,
                straight_line_km: optimizeData.straight_line_km
            };

            // Fetch weather for each stop
            fetch('/api/weather', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ coords: optimizeData.ordered_coords })
            })
                .then(res => res.json())
                .then(weatherData => {
                    displayWeather(weatherData.weather, optimizeData.ordered_cities);
                })
                .catch(err => {
                    console.error('Weather fetch error:', err);
                });

            // Fetch POIs if enabled
            if (poiEnabled) {
                const poisList = document.getElementById('pois-list');
                poiSection.classList.remove('d-none');
                poisList.innerHTML = '<div class="col-12 text-muted">Loading points of interest...</div>';
                fetch('/api/pois', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        coords: optimizeData.ordered_coords,
                        radius_miles: 5
                    })
                })
                    .then(res => {
                        if (!res.ok) {
                            throw new Error(`POI request failed with status ${res.status}`);
                        }
                        return res.json();
                    })
                    .then(poisData => {
                        displayPOIs(poisData.poi);
                        poiSection.classList.remove('d-none');
                    })
                    .catch(err => {
                        console.error('POI fetch error:', err);
                        displayPOIs({ gas_station: [], restaurant: [], lodging: [] });
                        poiSection.classList.remove('d-none');
                    });
            } else {
                poiSection.classList.add('d-none');
            }


            // Show results section
            resultsSection.classList.remove('d-none');

            // Trip duration in days (use the configurable max hours/day)
            const maxHoursPerDay = Math.max(1, parseFloat(document.getElementById('max-hours-per-day').value) || 8);
            const totalDays = Math.max(1, Math.ceil(optimizeData.total_duration_h / maxHoursPerDay));
            const overnightCount = totalDays - 1;

            // Display results
            const comparisonHtml = buildComparisonHtml(cities, optimizeData);
            tripInfo.innerHTML = `
                <div><strong>Optimized Route:</strong> ${optimizeData.ordered_cities.join(' → ')}</div>
                <div><strong>Total Distance:</strong> ${optimizeData.total_distance_km.toFixed(2)} km</div>
                <div><strong>Estimated Time:</strong> ${optimizeData.total_duration_h.toFixed(2)} hours</div>
                <div><strong>Trip Length:</strong> ~${totalDays} day${totalDays > 1 ? 's' : ''}${overnightCount > 0 ? `, ${overnightCount} night${overnightCount > 1 ? 's' : ''}` : ''}</div>
                <div><strong>Fuel Cost:</strong> $${optimizeData.estimated_fuel_cost.toFixed(2)}</div>
                <div><strong>Fuel Price Source:</strong> ${optimizeData.fuel_price_source || 'unknown'}${optimizeData.fuel_price_source_live ? ' (live)' : ''}</div>
                <div><strong>State-level pricing:</strong> ${optimizeData.eia_enabled ? 'enabled' : 'disabled'}</div>
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
                ${comparisonHtml}
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

            // Display overnight recommendations for legs over 10h
            displayOvernightRecommendations(optimizeData.overnight_recommendations || []);

            // Display day-by-day itinerary
            displayItinerary(optimizeData.legs, optimizeData.total_duration_h);

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
            showToast(error.message, 'error', 'Planning failed');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-play-circle me-2"></i>Plan Trip';
            mapContainer.classList.remove('loading');
        }
    });

    // Save trip button
    saveTripBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            showToast('Please plan a trip first.', 'warning');
            return;
        }
        const name = prompt('Enter a name for this trip:', 'My Road Trip');
        if (name === null) return;
        const tripData = { ...window.currentTripData, name };
        saveTrip(tripData);
        showToast('Trip saved!', 'success');
    });

    // Share link button
    shareLinkBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            showToast('Please plan a trip first.', 'warning');
            return;
        }
        const shareUrl = createShareUrl(window.currentTripData);
        navigator.clipboard.writeText(shareUrl).then(() => {
            showToast('Link copied to clipboard!', 'success');
        }).catch(err => {
            showToast('Failed to copy: ' + err, 'error');
        });
    });

    // Copy link button
    copyLinkBtn.addEventListener('click', () => {
        if (!shareLinkInput.value) {
            showToast('Please plan a trip first.', 'warning');
            return;
        }
        navigator.clipboard.writeText(shareLinkInput.value).then(() => {
            showToast('Link copied to clipboard!', 'success');
        }).catch(err => {
            showToast('Failed to copy: ' + err, 'error');
        });
    });

    // Example trip button
    const exampleBtn = document.getElementById('example-nyc-chi');
    if (exampleBtn) {
        exampleBtn.addEventListener('click', () => {
            document.getElementById('cities').value = 'New York\nChicago';
            document.getElementById('car-type').value = 'sedan';
            document.getElementById('fuel-type').value = 'regular';
            document.getElementById('route-type').value = 'fastest';
            avoidTolls.checked = false;
            avoidHighways.checked = false;
            avoidFerries.checked = false;
            document.getElementById('poi-toggle').checked = false;
            form.dispatchEvent(new Event('submit'));
        });
    }

    // Reset form button
    const resetBtn = document.getElementById('reset-form');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            form.reset();
            if (tripInfo) tripInfo.classList.add('d-none');
            if (tripWarnings) tripWarnings.classList.add('d-none');
            if (tripActions) tripActions.classList.add('d-none');
            if (shareSection) shareSection.classList.add('d-none');
            if (resultsSection) resultsSection.classList.add('d-none');
            if (poiSection) poiSection.classList.add('d-none');
            if (weatherSection) weatherSection.classList.add('d-none');
            if (itinerarySection) itinerarySection.classList.add('d-none');
            tripMap.srcdoc = '<p>Loading map...</p>';
            window.currentTripData = null;
            showToast('Form reset.', 'info');
        });
    }

    // Load trip button
    loadTripBtn.addEventListener('click', () => {
        const index = savedTripsSelect.value;
        if (index === '') {
            showToast('Please select a saved trip.', 'warning');
            return;
        }
        loadTrip(parseInt(index));
    });

    // Export GPX button
    exportGpxBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            showToast('Please plan a trip first.', 'warning');
            return;
        }
        const name = prompt('Enter a name for the GPX file:', 'trip');
        if (name === null) return;
        const tripData = { ...window.currentTripData, name };
        exportAsGpx(tripData);
        showToast('GPX file downloaded.', 'success');
    });

    // Export JSON button
    exportJsonBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            showToast('Please plan a trip first.', 'warning');
            return;
        }
        const name = prompt('Enter a name for the JSON file:', 'trip_data');
        if (name === null) return;
        const tripData = { ...window.currentTripData, name };
        exportAsJson(tripData);
        showToast('JSON file downloaded.', 'success');
    });

    // Print itinerary button
    printTripBtn.addEventListener('click', () => {
        if (!window.currentTripData) {
            showToast('Please plan a trip first.', 'warning');
            return;
        }
        window.print();
    });

    // Build the day-by-day itinerary view (use configurable max hours/day)
    function displayItinerary(legs, totalHours) {
        if (!legs || legs.length < 2) {
            itinerarySection.classList.add('d-none');
            return;
        }
        const maxHoursPerDay = Math.max(1, parseFloat(document.getElementById('max-hours-per-day').value) || 8);
        const days = [];
        let currentDay = { legs: [], totalHours: 0, totalKm: 0 };
        days.push(currentDay);
        legs.forEach(leg => {
            if (currentDay.totalHours + leg.duration_h > maxHoursPerDay && currentDay.legs.length > 0) {
                currentDay = { legs: [], totalHours: 0, totalKm: 0 };
                days.push(currentDay);
            }
            currentDay.legs.push(leg);
            currentDay.totalHours += leg.duration_h;
            currentDay.totalKm += leg.distance_km;
        });

        itineraryList.innerHTML = days.map((day, idx) => {
            const stops = day.legs.map(leg => `${leg.from} → ${leg.to}`).join('<br>');
            return `
                <div class="itinerary-day mb-2">
                    <div class="d-flex align-items-center justify-content-between">
                        <strong>Day ${idx + 1}</strong>
                        <span class="text-muted small">${day.totalHours.toFixed(1)} h • ${day.totalKm.toFixed(0)} km</span>
                    </div>
                    <div class="itinerary-stops mt-1">${stops}</div>
                </div>
            `;
        }).join('');
        itinerarySection.classList.remove('d-none');
    }

    // Build the "your order vs optimized order" comparison view
    function buildComparisonHtml(originalCities, optimizeData) {
        if (originalCities.length < 3) return '';  // no meaningful comparison for 2 cities
        const optimized = optimizeData.ordered_cities;
        const sameOrder = originalCities.every((c, i) => c.toLowerCase() === optimized[i].toLowerCase());
        if (sameOrder) return '<div class="mt-3"><strong>Route optimization:</strong> Your input order was already optimal!</div>';

        const typedRoute = originalCities.join(' → ');
        const optimizedRoute = optimized.join(' → ');
        return `
            <div class="mt-3 comparison-view">
                <div><strong>Route Comparison:</strong></div>
                <div class="table-responsive">
                    <table class="table table-sm align-middle">
                        <thead>
                            <tr><th>Your order</th><th>Optimized order</th></tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td class="text-muted">${typedRoute}</td>
                                <td class="text-success">${optimizedRoute}</td>
                            </tr>
                        </tbody>
                    </table>
                    <small class="text-muted">Optimization saved ${(optimizeData.road_overhead_percent || 0).toFixed(1)}% vs straight-line, and reordered your stops to minimize total driving distance.</small>
                </div>
            </div>
        `;
    }

    // Weather code -> emoji + label
    function weatherLabel(code) {
        const map = {
            0: ['☀️', 'Clear'],
            1: ['🌤️', 'Mostly clear'],
            2: ['⛅', 'Partly cloudy'],
            3: ['☁️', 'Overcast'],
            45: ['🌫️', 'Fog'],
            48: ['🌫️', 'Rime fog'],
            51: ['🌦️', 'Light drizzle'],
            53: ['🌦️', 'Drizzle'],
            55: ['🌧️', 'Heavy drizzle'],
            61: ['🌧️', 'Light rain'],
            63: ['🌧️', 'Rain'],
            65: ['🌧️', 'Heavy rain'],
            71: ['🌨️', 'Light snow'],
            73: ['🌨️', 'Snow'],
            75: ['❄️', 'Heavy snow'],
            80: ['🌦️', 'Light showers'],
            81: ['🌧️', 'Showers'],
            82: ['⛈️', 'Heavy showers'],
            95: ['⛈️', 'Thunderstorm'],
            96: ['⛈️', 'Thunderstorm with hail'],
            99: ['⛈️', 'Thunderstorm with hail']
        };
        return map[code] || ['🌡️', 'Unknown'];
    }

    // Display weather forecast cards next to city names
    function displayWeather(weatherData, cityNames) {
        weatherList.innerHTML = '';
        if (!weatherData || weatherData.length === 0) {
            weatherSection.classList.add('d-none');
            return;
        }

        const hasAnyData = weatherData.some(w => w.days && w.days.length > 0);
        if (!hasAnyData) {
            weatherSection.classList.add('d-none');
            return;
        }

        weatherData.forEach((w, idx) => {
            const cityName = cityNames[idx] || `Stop ${idx + 1}`;
            if (!w.days || w.days.length === 0) return;

            const dayCards = w.days.map(day => {
                const [emoji, label] = weatherLabel(day.weather_code);
                return `
                    <div class="weather-day">
                        <small class="text-muted">${day.date}</small>
                        <div class="weather-icon">${emoji} ${label}</div>
                        <div class="weather-temp">
                            <span class="text-danger">${day.high_f !== null && day.high_f !== undefined ? Math.round(day.high_f) + '°F' : '—'}</span>
                            /
                            <span class="text-info">${day.low_f !== null && day.low_f !== undefined ? Math.round(day.low_f) + '°F' : '—'}</span>
                        </div>
                        ${day.precip_in ? `<small class="text-muted">💧 ${day.precip_in.toFixed(2)} in</small>` : ''}
                    </div>
                `;
            }).join('');

            const col = document.createElement('div');
            col.className = 'col-md-6 col-lg-4';
            col.innerHTML = `
                <div class="weather-card">
                    <div class="weather-city"><strong>${cityName}</strong></div>
                    <div class="d-flex flex-wrap gap-2 mt-2">${dayCards}</div>
                </div>
            `;
            weatherList.appendChild(col);
        });

        weatherSection.classList.remove('d-none');
    }

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
        const poiTypes = ['attraction', 'gas_station', 'restaurant', 'lodging'];
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

    function displayOvernightRecommendations(recommendations) {
        const recSection = document.getElementById('overnight-recommendations');
        const recList = document.getElementById('overnight-recommendations-list');
        recList.innerHTML = '';
        if (!recommendations || recommendations.length === 0) {
            recSection.classList.add('d-none');
            return;
        }

        recommendations.forEach(rec => {
            const card = document.createElement('div');
            card.className = 'col-12';
            const lodgingItems = rec.lodging && rec.lodging.length > 0
                ? rec.lodging.map(hotel => `
                    <li><strong>${hotel.name}</strong>${hotel.address ? ` — ${hotel.address}` : ''}${hotel.distance_m ? ` (${(hotel.distance_m / 1609.34).toFixed(1)} mi from midpoint)` : ''}</li>
                `).join('')
                : '<li class="text-muted">No nearby lodging found in OpenStreetMap for this segment.</li>';

            card.innerHTML = `
                <div class="overnight-card card bg-dark bg-opacity-20 border border-white border-opacity-10 p-3">
                    <div class="d-flex align-items-center justify-content-between mb-2">
                        <div>
                            <strong>Leg ${rec.leg_index}:</strong> ${rec.from} → ${rec.to}
                        </div>
                        <div class="text-muted">${rec.duration_h.toFixed(1)} h</div>
                    </div>
                    <div><small class="text-muted">Suggested search near midpoint</small></div>
                    <ul class="mt-2 mb-0 overnight-list list-unstyled">${lodgingItems}</ul>
                </div>
            `;
            recList.appendChild(card);
        });

        recSection.classList.remove('d-none');
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
