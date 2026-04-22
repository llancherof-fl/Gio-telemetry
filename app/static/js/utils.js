/**
 * GIO Telemetry — Shared Utilities
 * Toast notifications, date formatting, SVG icons, shared constants.
 */

// ── SVG Icons (shared across modules) ──
var SVG_PIN_GREEN = '<svg width="28" height="36" viewBox="0 0 28 36" fill="none"><path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.27 21.73 0 14 0z" fill="#51cf66"/><circle cx="14" cy="13" r="5" fill="#0a0e1a" opacity="0.25"/><circle cx="14" cy="13" r="4" fill="white" opacity="0.9"/></svg>';
var SVG_PIN_RED = '<svg width="28" height="36" viewBox="0 0 28 36" fill="none"><path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.27 21.73 0 14 0z" fill="#ff6b6b"/><circle cx="14" cy="13" r="5" fill="#0a0e1a" opacity="0.25"/><circle cx="14" cy="13" r="4" fill="white" opacity="0.9"/></svg>';
var SVG_PIN_ORANGE = '<svg width="28" height="36" viewBox="0 0 28 36" fill="none"><path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.27 21.73 0 14 0z" fill="#ffb457"/><circle cx="14" cy="13" r="5" fill="#0a0e1a" opacity="0.25"/><circle cx="14" cy="13" r="4" fill="white" opacity="0.9"/></svg>';
var SVG_SEARCH = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
var SVG_INBOX = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"><path d="M22 12h-6l-2 3H10l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>';
var SVG_PACKAGE = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>';

/**
 * Convert a Date to local ISO string (YYYY-MM-DDTHH:MM:SS).
 */
function toLocalISO(d) {
    var pad = function(n) { return String(n).padStart(2, '0'); };
    // === CORRECCIÓN PROFESOR A4: Segundos siempre 00 ===
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
           'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':00';
}

/**
 * Show a toast notification.
 */
function showToast(msg) {
    var t = document.getElementById('toast');
    t.innerHTML = msg;
    t.classList.add('show');
    setTimeout(function() { t.classList.remove('show'); }, 3000);
}

/**
 * Haversine distance between two [lat, lon] points in meters.
 */
function haversineDistance(p1, p2) {
    var R = 6371000;
    var dLat = (p2[0] - p1[0]) * Math.PI / 180;
    var dLon = (p2[1] - p1[1]) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(p1[0] * Math.PI / 180) * Math.cos(p2[0] * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * Sample an array of points down to maxPoints using uniform spacing.
 * Always keeps first and last point.
 */
function samplePoints(points, maxPoints) {
    if (points.length <= maxPoints) return points;
    var step = Math.ceil(points.length / (maxPoints - 1));
    var sampled = [points[0]];
    for (var i = step; i < points.length - 1; i += step) {
        sampled.push(points[i]);
    }
    sampled.push(points[points.length - 1]);
    return sampled;
}
