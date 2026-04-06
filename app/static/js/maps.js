/**
 * GIO Telemetry — Map Initialization & Helpers
 * Creates Leaflet maps, marker icons, and shared map utilities.
 */

var mapRT = null;
var mapHist = null;

/**
 * Initialize both maps (real-time and historical).
 */
function initMaps() {
    var tileUrl = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    var tileOpts = { attribution: '&copy; OpenStreetMap', maxZoom: 19 };

    mapRT = L.map('map-rt').setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapRT);

    mapHist = L.map('map-hist').setView([10.9878, -74.7889], 13);
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
 * @returns {Promise<Array|null>} Array of [lat, lon] for the smooth route, or null
 */
function fetchOSRMRoute(points) {
    // Sample down to 25 waypoints max (OSRM limit)
    var sampled = samplePoints(points, 25);
    var coords = sampled.map(function(p) { return p[1] + ',' + p[0]; }).join(';');

    return fetch('/api/osrm-proxy?coords=' + encodeURIComponent(coords))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok && data.geometry) {
                return data.geometry.coordinates.map(function(c) {
                    return [c[1], c[0]];
                });
            }
            return null;
        })
        .catch(function() {
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
 * @returns {Promise<L.Polyline>}
 */
function drawSmartRoute(map, points, style) {
    var defaultStyle = {
        color: '#748ffc',
        weight: 3.5,
        opacity: 0.85
    };
    var mergedStyle = Object.assign({}, defaultStyle, style || {});

    if (points.length < 2) {
        return Promise.resolve(null);
    }

    return fetchOSRMRoute(points).then(function(osrmRoute) {
        var drawPoints;
        if (osrmRoute && osrmRoute.length > 1) {
            // OSRM success — use real road route
            drawPoints = osrmRoute;
        } else {
            // OSRM failed — use Catmull-Rom spline fallback
            drawPoints = smoothPath(points, {
                epsilon: 0.00003,
                segments: 10,
                tension: 0.5
            });
        }
        return L.polyline(drawPoints, mergedStyle).addTo(map);
    });
}
