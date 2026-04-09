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
 * Create an "open trip" icon (orange).
 */
function makeOpenIcon() {
    return L.divIcon({
        html: SVG_PIN_ORANGE,
        iconSize: [28, 36],
        iconAnchor: [14, 36],
        popupAnchor: [0, -36],
        className: ''
    });
}

function normalizeOsrmMethod(method) {
    return method === 'match' ? 'match' : 'route';
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
    var method = normalizeOsrmMethod(opts.osrmMethod || opts.method);
    // Sample down to 25 waypoints max (OSRM limit)
    var sampled = samplePoints(points, 25);
    var coords = sampled.map(function(p) { return p[1] + ',' + p[0]; }).join(';');
    var url = '/api/osrm-proxy?coords=' + encodeURIComponent(coords) + '&method=' + encodeURIComponent(method);

    return fetch(url, { signal: opts.signal })
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

function dedupeConsecutivePoints(points, minDistanceMeters) {
    if (!points || points.length < 2) return points ? points.slice() : [];

    var thresholdKm = Math.max(0, Number(minDistanceMeters || 0)) / 1000;
    var out = [points[0]];

    for (var i = 1; i < points.length; i++) {
        var prev = out[out.length - 1];
        var curr = points[i];
        if (thresholdKm > 0 && distanceKm(prev, curr) <= thresholdKm) {
            continue;
        }
        out.push(curr);
    }

    if (out.length === 1 && points.length > 1) {
        out.push(points[points.length - 1]);
    }

    return out;
}

function buildWaypointChunks(points, maxWaypoints, overlap) {
    if (!points || points.length < 2) return [];
    if (points.length <= maxWaypoints) return [points.slice()];

    var safeOverlap = Math.max(1, Math.min(maxWaypoints - 1, overlap || 1));
    var chunks = [];
    var start = 0;

    while (start < (points.length - 1)) {
        var end = Math.min(points.length, start + maxWaypoints);
        var chunk = points.slice(start, end);
        if (chunk.length > 1) {
            chunks.push(chunk);
        }
        if (end >= points.length) {
            break;
        }
        start = end - safeOverlap;
    }

    return chunks;
}

function limitChunkCount(points, maxWaypoints, overlap, maxChunks) {
    var chunks = buildWaypointChunks(points, maxWaypoints, overlap);
    if (!maxChunks || chunks.length <= maxChunks) {
        return { points: points, chunks: chunks };
    }

    var targetPoints = maxWaypoints + Math.max(0, maxChunks - 1) * (maxWaypoints - Math.max(1, overlap || 1));
    var sampled = samplePoints(points, Math.max(maxWaypoints, targetPoints));
    return {
        points: sampled,
        chunks: buildWaypointChunks(sampled, maxWaypoints, overlap)
    };
}

function mergeRoutePaths(paths) {
    if (!paths || !paths.length) return [];
    var merged = [];
    var joinThresholdKm = 0.03; // 30 meters

    for (var i = 0; i < paths.length; i++) {
        var path = paths[i];
        if (!path || path.length < 2) continue;

        if (!merged.length) {
            merged = path.slice();
            continue;
        }

        var prev = merged[merged.length - 1];
        var first = path[0];
        if (distanceKm(prev, first) <= joinThresholdKm) {
            merged = merged.concat(path.slice(1));
        } else {
            merged = merged.concat(path);
        }
    }

    return merged;
}

function buildFallbackRoute(points, maxJumpKm) {
    var safeSegments = splitByLargeJumps(points, maxJumpKm);
    if (!safeSegments.length) {
        safeSegments = [points];
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

    if (!smoothed.length) return null;
    if (smoothed.length === 1) return smoothed[0];
    return smoothed;
}

function fetchSegmentRouteChunked(segment, opts) {
    var maxWaypoints = Math.max(2, Math.min(25, Number(opts.chunkWaypoints || 25)));
    var overlap = Math.max(1, Math.min(maxWaypoints - 1, Number(opts.chunkOverlap || 1)));
    var maxChunksPerSegment = Math.max(1, Number(opts.maxChunksPerSegment || 8));
    var bounded = limitChunkCount(segment, maxWaypoints, overlap, maxChunksPerSegment);
    var chunks = bounded.chunks;

    if (!chunks.length) {
        return Promise.resolve(null);
    }

    var paths = [];
    var idx = 0;

    function processChunk() {
        if (opts.signal && opts.signal.aborted) {
            return Promise.resolve(null);
        }
        if (idx >= chunks.length) {
            if (!paths.length) return Promise.resolve(null);
            return Promise.resolve(mergeRoutePaths(paths));
        }

        var chunk = chunks[idx++];
        return fetchOSRMRoute(chunk, opts).then(function(route) {
            if (route && route.length > 1) {
                paths.push(route);
            } else {
                var fallbackChunk = smoothPath(chunk, { segments: 6, tension: 0.42 });
                if (fallbackChunk && fallbackChunk.length > 1) {
                    paths.push(fallbackChunk);
                }
            }
            if (typeof opts.onPartialChunk === 'function') {
                var partialSegmentRoute = mergeRoutePaths(paths);
                if (partialSegmentRoute && partialSegmentRoute.length > 1) {
                    try {
                        opts.onPartialChunk(partialSegmentRoute, {
                            chunkIndex: idx,
                            totalChunks: chunks.length
                        });
                    } catch (e) {
                        // ignore callback errors
                    }
                }
            }
            return processChunk();
        });
    }

    return processChunk();
}

function fetchSegmentedRoute(points, options) {
    var opts = options || {};
    if (!points || points.length < 2) return Promise.resolve(null);
    if (opts.signal && opts.signal.aborted) return Promise.resolve(null);

    var maxJumpKm = Math.max(20, Number(opts.maxJumpKm || 120));
    var maxInputPoints = Math.max(40, Number(opts.maxInputPoints || 220));
    var minPointDistanceMeters = Math.max(0, Number(opts.minPointDistanceMeters || 2));
    var osrmMethod = normalizeOsrmMethod(opts.osrmMethod || opts.method);

    var prepared = dedupeConsecutivePoints(points, minPointDistanceMeters);
    if (prepared.length > maxInputPoints) {
        prepared = samplePoints(prepared, maxInputPoints);
    }

    var segments = splitByLargeJumps(prepared, maxJumpKm).filter(function(segment) {
        return segment && segment.length > 1;
    });
    if (!segments.length && prepared.length > 1) {
        segments = [prepared];
    }
    if (!segments.length) {
        return Promise.resolve(null);
    }

    var routedSegments = [];
    var segIdx = 0;

    function processSegment() {
        if (opts.signal && opts.signal.aborted) {
            return Promise.resolve(null);
        }
        if (segIdx >= segments.length) {
            if (!routedSegments.length) return Promise.resolve(null);
            if (routedSegments.length === 1) return Promise.resolve(routedSegments[0]);
            return Promise.resolve(routedSegments);
        }

        var segment = segments[segIdx++];
        var segmentNumber = segIdx;
        var segmentOpts = Object.assign({}, opts, {
            osrmMethod: osrmMethod,
            onPartialChunk: function(partialSegmentRoute, chunkMeta) {
                if (typeof opts.onPartialRoute !== 'function') return;
                var aggregate = routedSegments.slice();
                aggregate.push(partialSegmentRoute);
                var partialGlobal = aggregate.length === 1 ? aggregate[0] : aggregate;
                try {
                    opts.onPartialRoute(partialGlobal, {
                        segmentIndex: segmentNumber,
                        totalSegments: segments.length,
                        chunkIndex: chunkMeta ? chunkMeta.chunkIndex : null,
                        totalChunks: chunkMeta ? chunkMeta.totalChunks : null,
                    });
                } catch (e) {
                    // ignore callback errors
                }
            }
        });
        var routePromise = opts.chunked
            ? fetchSegmentRouteChunked(segment, segmentOpts)
            : fetchOSRMRoute(segment, segmentOpts);

        return routePromise.then(function(route) {
            if (route && route.length > 1) {
                routedSegments.push(route);
                if (typeof opts.onPartialRoute === 'function') {
                    var globalRoute = routedSegments.length === 1 ? routedSegments[0] : routedSegments.slice();
                    try {
                        opts.onPartialRoute(globalRoute, {
                            segmentIndex: segmentNumber,
                            totalSegments: segments.length,
                            chunkIndex: null,
                            totalChunks: null,
                        });
                    } catch (e) {
                        // ignore callback errors
                    }
                }
            }
            return processSegment();
        });
    }

    return processSegment();
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
    var maxJumpKm = Math.max(20, Number(opts.maxJumpKm || 120));
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

    var routeOpts = Object.assign({}, opts, { maxJumpKm: maxJumpKm });

    return fetchSegmentedRoute(points, routeOpts).then(function(osrmRoute) {
        if (opts.signal && opts.signal.aborted) {
            return null;
        }

        var drawPoints;
        if (osrmRoute && osrmRoute.length > 1) {
            // OSRM success — use real road route
            drawPoints = osrmRoute;
        } else {
            // OSRM failed — use segmented Catmull-Rom spline fallback
            var base = points.length > 450 ? samplePoints(points, 450) : points.slice();
            drawPoints = buildFallbackRoute(base, maxJumpKm);
        }

        var isMulti = Array.isArray(drawPoints)
            && drawPoints.length
            && Array.isArray(drawPoints[0])
            && Array.isArray(drawPoints[0][0]);

        if (isMulti) {
            drawPoints = drawPoints.filter(function(segment) {
                return Array.isArray(segment) && segment.length > 1;
            });
            if (!drawPoints.length) {
                return null;
            }
        } else {
            if (!drawPoints || drawPoints.length < 2) {
                return null;
            }
        }

        return L.polyline(drawPoints, mergedStyle).addTo(map);
    });
}
