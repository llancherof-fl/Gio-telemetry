/**
 * GIO Telemetry — Spline Interpolation Module
 * Douglas-Peucker simplification + Catmull-Rom spline for smooth polyline fallback.
 *
 * When OSRM fails, this creates a visually smooth path through the GPS points
 * that looks like it follows a road, instead of ugly straight-line segments.
 */

// ══════════════════════════════════════════
//  DOUGLAS–PEUCKER SIMPLIFICATION
//  Removes redundant points (GPS noise on straight lines)
// ══════════════════════════════════════════

/**
 * Perpendicular distance from a point to a line segment.
 * @param {Array} point  [lat, lon]
 * @param {Array} start  [lat, lon]
 * @param {Array} end    [lat, lon]
 * @returns {number} distance in degrees (sufficient for comparison)
 */
function perpendicularDistance(point, start, end) {
    var dx = end[1] - start[1];
    var dy = end[0] - start[0];
    var mag = Math.sqrt(dx * dx + dy * dy);
    if (mag === 0) return Math.sqrt(Math.pow(point[0] - start[0], 2) + Math.pow(point[1] - start[1], 2));

    // Normalized distance
    var u = ((point[1] - start[1]) * dx + (point[0] - start[0]) * dy) / (mag * mag);
    u = Math.max(0, Math.min(1, u));

    var closestX = start[1] + u * dx;
    var closestY = start[0] + u * dy;
    return Math.sqrt(Math.pow(point[0] - closestY, 2) + Math.pow(point[1] - closestX, 2));
}

/**
 * Douglas-Peucker line simplification.
 * @param {Array} points  Array of [lat, lon]
 * @param {number} epsilon Tolerance in degrees (~0.00005 ≈ 5 meters)
 * @returns {Array} Simplified array of [lat, lon]
 */
function douglasPeucker(points, epsilon) {
    if (points.length <= 2) return points.slice();

    // Find the point with the maximum distance from the line (first→last)
    var maxDist = 0;
    var maxIdx = 0;
    var end = points.length - 1;

    for (var i = 1; i < end; i++) {
        var d = perpendicularDistance(points[i], points[0], points[end]);
        if (d > maxDist) {
            maxDist = d;
            maxIdx = i;
        }
    }

    // If max distance exceeds epsilon, recursively simplify
    if (maxDist > epsilon) {
        var left = douglasPeucker(points.slice(0, maxIdx + 1), epsilon);
        var right = douglasPeucker(points.slice(maxIdx), epsilon);
        return left.slice(0, -1).concat(right);
    }

    // All points are within tolerance — keep only endpoints
    return [points[0], points[end]];
}


// ══════════════════════════════════════════
//  CATMULL–ROM SPLINE INTERPOLATION
//  Creates smooth curves through GPS points
// ══════════════════════════════════════════

/**
 * Catmull-Rom spline interpolation for a set of control points.
 * The curve passes through ALL original points (unlike Bezier).
 *
 * @param {Array} points  Array of [lat, lon]
 * @param {number} segments Number of interpolated points between each pair (8-12 is good)
 * @param {number} tension  0.0 = sharp, 0.5 = standard, 1.0 = very smooth
 * @returns {Array} Interpolated array of [lat, lon]
 */
function catmullRomSpline(points, segments, tension) {
    if (!points || points.length < 2) return points ? points.slice() : [];
    if (points.length === 2) return points.slice();

    segments = segments || 10;
    tension = tension !== undefined ? tension : 0.5;

    var result = [];

    for (var i = 0; i < points.length - 1; i++) {
        // Get the 4 control points (clamp at edges)
        var p0 = points[Math.max(0, i - 1)];
        var p1 = points[i];
        var p2 = points[i + 1];
        var p3 = points[Math.min(points.length - 1, i + 2)];

        // Calculate tangent vectors
        var t1Lat = tension * (p2[0] - p0[0]);
        var t1Lon = tension * (p2[1] - p0[1]);
        var t2Lat = tension * (p3[0] - p1[0]);
        var t2Lon = tension * (p3[1] - p1[1]);

        for (var t = 0; t < segments; t++) {
            var s = t / segments;
            var s2 = s * s;
            var s3 = s2 * s;

            // Hermite basis functions
            var h1 = 2 * s3 - 3 * s2 + 1;
            var h2 = s3 - 2 * s2 + s;
            var h3 = -2 * s3 + 3 * s2;
            var h4 = s3 - s2;

            var lat = h1 * p1[0] + h2 * t1Lat + h3 * p2[0] + h4 * t2Lat;
            var lon = h1 * p1[1] + h2 * t1Lon + h3 * p2[1] + h4 * t2Lon;

            result.push([lat, lon]);
        }
    }

    // Always include the last point
    result.push(points[points.length - 1]);

    return result;
}


// ══════════════════════════════════════════
//  PUBLIC API — Combined Pipeline
// ══════════════════════════════════════════

/**
 * Full spline pipeline: simplify → smooth → output.
 * This is the main function to use as OSRM fallback.
 *
 * @param {Array} rawPoints  Array of [lat, lon] GPS points
 * @param {Object} options   { epsilon, segments, tension }
 * @returns {Array} Smooth array of [lat, lon]
 */
function smoothPath(rawPoints, options) {
    if (!rawPoints || rawPoints.length < 2) return rawPoints ? rawPoints.slice() : [];

    var opts = options || {};
    var epsilon = opts.epsilon !== undefined ? opts.epsilon : 0.00003;  // ~3 meters
    var segments = opts.segments || 10;
    var tension = opts.tension !== undefined ? opts.tension : 0.5;

    // Step 1: Simplify (remove GPS noise on straight roads)
    var simplified = douglasPeucker(rawPoints, epsilon);

    // Step 2: If too few points after simplification, use originals
    if (simplified.length < 3 && rawPoints.length >= 3) {
        simplified = rawPoints;
    }

    // Step 3: Limit points for performance (spline on 500+ points is slow)
    if (simplified.length > 100) {
        simplified = samplePoints(simplified, 100);
    }

    // Step 4: Generate smooth spline
    return catmullRomSpline(simplified, segments, tension);
}
