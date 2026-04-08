/**
 * GIO Telemetry — Map Initialization & Helpers
 * Creates Leaflet maps, marker icons, and shared map utilities.
 */

var mapRT = null;
var mapHist = null;

function distanceKm(a, b) {
    var toRad = Math.PI / 180;
    var dLat = (b[0] - a[0]) * toRad;
    var dLon = (b[1] - a[1]) * toRad;
    var lat1 = a[0] * toRad;
    var lat2 = b[0] * toRad;
    var sinLat = Math.sin(dLat / 2);
    var sinLon = Math.sin(dLon / 2);
    var aa = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;
    var c = 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
    return 6371.0088 * c;
}

function splitByLargeJumps(points, maxJumpKm) {
    if (!points || points.length < 2) return [];

    var segments = [];
    var current = [points[0]];

    for (var i = 1; i < points.length; i++) {
        var prev = points[i - 1];
        var curr = points[i];
        if (distanceKm(prev, curr) > maxJumpKm) {
            if (current.length > 1) {
                segments.push(current);
            }
            current = [curr];
            continue;
        }
        current.push(curr);
    }

    if (current.length > 1) {
        segments.push(current);
    }

    return segments;
}

/**
 * Initialize both maps (real-time and historical).
 */
function initMaps() {
    var tileUrl = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    var tileOpts = { attribution: '&copy; OpenStreetMap', maxZoom: 19 };
    var mapOpts = {
        preferCanvas: true,
        zoomControl: true
    };

    mapRT = L.map('map-rt', mapOpts).setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapRT);

    mapHist = L.map('map-hist', mapOpts).setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapHist);
}

/**
 * Create the vehicle icon for the real-time map.
 */
function makeCarIcon() {
    return L.divIcon({
        html: '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
            + '<rect x="3" y="8" width="18" height="9" rx="3" fill="#339af0" stroke="#0a0e1a" stroke-width="1.2"/>'
            + '<rect x="5" y="4.5" width="14" height="7" rx="2.5" fill="#4dabf7" stroke="#0a0e1a" stroke-width="1.2"/>'
            + '<circle cx="7" cy="17.5" r="2.2" fill="#0a0e1a" stroke="#4dabf7" stroke-width="1.5"/>'
            + '<circle cx="17" cy="17.5" r="2.2" fill="#0a0e1a" stroke="#4dabf7" stroke-width="1.5"/>'
            + '<rect x="7" y="6" width="4" height="3.5" rx="0.8" fill="rgba(255,255,255,0.4)"/>'
            + '<rect x="13" y="6" width="4" height="3.5" rx="0.8" fill="rgba(255,255,255,0.4)"/>'
            + '<circle cx="12" cy="11" r="1" fill="#ffa94d"/>'
            + '</svg>',
        iconSize: [32, 32],
        iconAnchor: [16, 22],
        className: ''
    });
}

/**
 * Create a start pin icon (green).
 */
function makeStartIcon() {
    return L.divIcon({
        html: SVG_PIN_GREEN,
        iconSize: [28, 36],
        iconAnchor: [14, 36],
        popupAnchor: [0, -36],
        className: ''
    });
}

/**
 * Create an end pin icon (red).
 */
function makeEndIcon() {
    return L.divIcon({
        html: SVG_PIN_RED,
        iconSize: [28, 36],
        iconAnchor: [14, 36],
        popupAnchor: [0, -36],
        className: ''
    });
}

/**
 * Request an OSRM route through our backend proxy.
 * Returns a promise that resolves with the route geometry or null.
 *
 * @param {Array} points Array of [lat, lon]
 * @param {Object} options { signal?: AbortSignal }
 * @returns {Promise<Array|null>} Array of [lat, lon] for the smooth route, or null
 */
function fetchOSRMRoute(points, options) {
    var opts = options || {};
    // Sample down to 25 waypoints max (OSRM limit)
    var sampled = samplePoints(points, 25);
    var coords = sampled.map(function(p) { return p[1] + ',' + p[0]; }).join(';');

    return fetch('/api/osrm-proxy?coords=' + encodeURIComponent(coords), { signal: opts.signal })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok && data.geometry) {
                return data.geometry.coordinates.map(function(c) {
                    return [c[1], c[0]];
                });
            }
            return null;
        })
        .catch(function(err) {
            if (err && err.name === 'AbortError') {
                return null;
            }
            return null;
        });
}

/**
 * Draw a polyline on a map with OSRM route or spline fallback.
 * Returns a promise that resolves with the Leaflet polyline.
 *
 * @param {L.Map} map  Leaflet map instance
 * @param {Array} points  Raw GPS points [lat, lon]
 * @param {Object} style  Polyline style options
 * @param {Object} options { signal?: AbortSignal }
 * @returns {Promise<L.Polyline>}
 */
function drawSmartRoute(map, points, style, options) {
    var opts = options || {};
    var maxJumpKm = Math.max(40, Number(opts.maxJumpKm || 350));
    var defaultStyle = {
        color: '#748ffc',
        weight: 3.5,
        opacity: 0.85
    };
    var mergedStyle = Object.assign({}, defaultStyle, style || {});

    if (points.length < 2) {
        return Promise.resolve(null);
    }
    if (opts.signal && opts.signal.aborted) {
        return Promise.resolve(null);
    }

    var segments = splitByLargeJumps(points, maxJumpKm);
    var osrmInput = points;
    if (segments.length > 1) {
        osrmInput = segments.reduce(function(best, segment) {
            return segment.length > best.length ? segment : best;
        }, segments[0]);
    }

    return fetchOSRMRoute(osrmInput, opts).then(function(osrmRoute) {
        if (opts.signal && opts.signal.aborted) {
            return null;
        }

        var drawPoints;
        if (osrmRoute && osrmRoute.length > 1) {
            // OSRM success — use real road route
            drawPoints = osrmRoute;
        } else {
            // OSRM failed — use Catmull-Rom spline fallback
            var base = points.length > 450 ? samplePoints(points, 450) : points;
            var safeSegments = splitByLargeJumps(base, maxJumpKm);
            if (!safeSegments.length) {
                safeSegments = [base];
            }

            var smoothed = safeSegments
                .map(function(segment) {
                    return smoothPath(segment, {
                        epsilon: 0.00003,
                        segments: 8,
                        tension: 0.45
                    });
                })
                .filter(function(segment) {
                    return segment && segment.length > 1;
                });

            if (smoothed.length === 1) {
                drawPoints = smoothed[0];
            } else {
                drawPoints = smoothed;
            }
        }
        if (!drawPoints || drawPoints.length < 2) {
            return null;
        }
        return L.polyline(drawPoints, mergedStyle).addTo(map);
    });
}
