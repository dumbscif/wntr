/* WNTR:\\Project StarFire UFO Sighting Tracker - static port of the original Grok Page ("Dashboard v4").
   Normal document flow only: no sticky/fixed headers, floating panels or overlay readers.
   Data: data/events.json (written by scraper/sweep.py). No framework, no build step. */
(function () {
  "use strict";
  var RED = "#ff2a2a", BLUE = "#2a7fff", YELLOW = "#ffd43b", CYAN = "#39cde0";
  var UNKNOWN_CONT = "Multi-region / At sea / Unknown";
  var CONTINENTS = ["North America", "South America", "Europe", "Asia", "Africa", "Oceania", UNKNOWN_CONT];
  var CONT_CODES = { NA: "North America", SA: "South America", EU: "Europe", AS: "Asia", AF: "Africa", OC: "Oceania", AN: UNKNOWN_CONT };
  var SHAPES = ["Triangle", "Orb/Sphere", "Lights (points or formations of light)", "Disc/Saucer", "Metallic/Solid craft", "Cylinder/Cigar/Elongated", "Fireball/Streak", "Other", "Unknown/Not described"];
  var TABS = [{ id: "map", label: "Map" }, { id: "latest", label: "Latest" }, { id: "archive", label: "Archive" }, { id: "insights", label: "Insights" }, { id: "health", label: "Sources & health" }];

  var META = {}, FLAP = {}, REPORTS = [], CONTEXTS = [], LAST = "", LAST_MS = 0;
  var S = {
    tab: "map", layers: { red: true, blue: true, yellow: true, context: true }, view: "overview", focusId: "", selectedId: "", detailId: "",
    globalQuery: "", globalOpen: false, latestLimit: 12, query: "", reporterFilter: "all", markerFilter: "all", countryFilter: "all",
    continentFilter: "all", sortOrder: "newest", regionQuery: "", dateMode: "swept", fromDate: "", toDate: "", onlyMedia: false,
    expandReports: false, shapeFolder: "all", contextQuery: "", showOsint: true, archiveLimit: 400, mapNonce: 0
  };
  var openDetails = {}; // remembers which <details> the reader opened, across re-renders

  // ------------------------------------------------------------------ helpers
  function esc(v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : "#"; }
  function ext(u, text, cls) { return '<a href="' + esc(safeUrl(u)) + '" target="_blank" rel="noopener noreferrer"' + (cls ? ' class="' + cls + '"' : "") + ">" + text + "</a>"; }
  var DTF = new Intl.DateTimeFormat("en-US", { timeZone: "America/Denver", year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  var DKEY = new Intl.DateTimeFormat("sv-SE", { timeZone: "America/Denver", year: "numeric", month: "2-digit", day: "2-digit" });
  function formatDenver(v) { var t = Date.parse(v); return isFinite(t) ? DTF.format(new Date(t)) : (v || "not recorded"); }
  function publicationTime(v) { if (!v) return "not reported"; var m = String(v).match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/); return m ? formatDenver(m[0]) : v + " · source-native precision"; }
  function inWindow(at) { var t = Date.parse(at); return isFinite(t) && t >= LAST_MS - 86400000 && t <= LAST_MS + 60000; }
  function markerColor(m) { return m === "yellow" ? YELLOW : m === "blue" ? BLUE : RED; }
  function shortShape(s) { return s === "Lights (points or formations of light)" ? "Lights" : s === "Cylinder/Cigar/Elongated" ? "Elongated" : s === "Metallic/Solid craft" ? "Metallic" : s === "Unknown/Not described" ? "Not described" : s; }
  function reporterLabel(e) { return e.marker === "yellow" ? (e.reporterType === "military" ? "Military-confirmed · civilian witness" : "Official confirmation cited") : e.reporterType === "civilian" ? "Civilian" : "Unknown affiliation"; }
  function reporterTag(e) { return e.marker === "yellow" ? "Military-confirmed" : e.reporterType === "civilian" ? "Civilian" : "Unknown affiliation"; }
  function markerLabel(e) { return e.marker === "yellow" ? "Yellow · military-confirmed report" : e.marker === "blue" ? "Blue · alleged unidentified-craft testing" : "Red · sighting claim"; }
  function compactDate(e) { return e.historical ? "historical" : ((e.date || "").match(/^\d{4}-\d{2}-\d{2}/) || [((e.date || "").match(/^\d{4}-\d{2}/) || ["Date not reported"])[0]])[0]; }
  function sightingLabel(e) {
    if (e.timeDenver && !/not reported/i.test(e.timeDenver)) return e.timeDenver + " (America/Denver)";
    if (e.origin === "auto") return (e.date || "date unknown") + " (publication date; the sighting time was not parsed from the source)";
    return (e.date || "not reported") + " (source-local date; no time supplied, so Denver date cannot be established)";
  }
  function srcStatus(s) { return ((s && s.availability && s.availability.status) || "unchecked").toLowerCase(); }
  function availabilityLabel(s) {
    var st = srcStatus(s);
    var state = st === "unavailable" ? "No longer available" : st === "check failed" ? "Check failed (not proof of removal)" : st === "available" ? "Available" : "Not yet checked";
    var when = s.availability && s.availability.lastCheckedAt ? " · checked " + formatDenver(s.availability.lastCheckedAt) : "";
    return state + when + " · swept details kept in the archive";
  }
  function reportUnavailable(e) { return e.sources.some(function (s) { return srcStatus(s) === "unavailable"; }); }
  function reportAvailability(e) {
    var st = e.sources.map(srcStatus);
    if (st.indexOf("unavailable") >= 0) return "No longer available · swept case retained";
    if (st.indexOf("check failed") >= 0) return "Check failed · not proof of removal";
    if (st.some(function (x) { return x !== "available"; })) return "Some links not yet checked";
    return "Available at last link check · case retained";
  }
  function sourceName(s) { return s.name || s.title || "Source"; }
  function sourceHost(u) { return String(u || "").replace(/^https?:\/\//, "").split("/")[0].replace(/^www\./, ""); }
  function normContinent(c) { if (!c) return UNKNOWN_CONT; return CONT_CODES[c] || (CONTINENTS.indexOf(c) >= 0 ? c : UNKNOWN_CONT); }
  function guessShape(t) {
    t = (t || "").toLowerCase();
    if (/triang|boomerang|driehoek|dreieck|triángulo|triangulo|chevron/.test(t)) return "Triangle";
    if (/\bdisc\b|\bdisk\b|saucer|platillo|schijf|disco voador/.test(t)) return "Disc/Saucer";
    if (/cigar|cylind|tic.?tac|sigaar|zigarre|cilindro|elongated|rod-shaped/.test(t)) return "Cylinder/Cigar/Elongated";
    if (/fireball|fire ball|streak|meteor|bola de fuego|vuurbal|feuerball|trail of fire/.test(t)) return "Fireball/Streak";
    if (/\borbs?\b|sphere|esfera|\bball\b|\bbol\b|globe|kugel/.test(t)) return "Orb/Sphere";
    if (/metallic|metal object|solid craft|metálico|metalen/.test(t)) return "Metallic/Solid craft";
    if (/lights?\b|luces|luzes|lichter|lichten|lumières|luci\b|glow|blinking|flash/.test(t)) return "Lights (points or formations of light)";
    return "Unknown/Not described";
  }
  function fmtTime(v) { var t = Date.parse(v); return isFinite(t) ? formatDenver(v) : null; }

  function normalize(r) {
    var e = {
      id: r.id, origin: r.origin || "auto", kind: r.kind, marker: r.marker || "red", markerBasis: r.markerBasis || "",
      title: r.title || r.place || r.id, place: r.place || null,
      label: r.origin === "seed" ? (r.title || r.place || r.id) : (r.place || r.title || r.id),
      lat: typeof r.lat === "number" ? r.lat : null, lon: typeof r.lon === "number" ? r.lon : null,
      country: r.country || "Unknown", continent: normContinent(r.continent), precision: r.precision || "",
      date: r.eventDate || "", timeLocal: r.eventTimeLocal || "", tz: r.tz || "", timeDenver: r.eventTimeDenver || (r.eventAt ? fmtTime(r.eventAt) : ""),
      published: r.publishedText || r.publishedAt || "", sweptAt: r.sweptAt || "", timeBasis: r.timeBasis || "",
      narrative: r.narrative || r.summary || "", appearance: r.appearance || (r.origin !== "seed" && r.place ? r.title || "" : ""), evidence: r.evidence || "",
      explanations: r.explanations || [], sources: (r.sources || []).filter(function (s) { return s && s.url; }), media: r.media || [],
      reporterType: r.reporterType || "unknown", reporterTypeBasis: r.reporterTypeBasis || "", allegedTesting: !!r.allegedTesting,
      testingStatus: r.testingStatus || null, count: Math.max(1, r.reportCount || 1), corrections: r.corrections || [], relevance: r.relevance || "",
      historical: r.id === "evt-starr-county-tx-2026-11"
    };
    e.shape = r.shape && SHAPES.indexOf(r.shape) >= 0 ? r.shape : (r.origin === "seed" && r.shape ? "Other" : guessShape(e.title + " " + (r.appearance || "") + " " + (r.summary || "")));
    e.shapeBasis = r.shape ? "Hand-reviewed category" : "Automatic keyword match on the headline/summary; not verified";
    e.mapped = e.lat !== null && e.lon !== null;
    e.text = [e.id, e.label, e.title, e.narrative, e.appearance, e.country, e.continent, e.shape, e.place || ""].concat(e.sources.map(function (s) { return sourceName(s) + " " + (s.title || "") + " " + s.url + " " + (s.note || ""); })).join(" ").toLowerCase();
    return e;
  }

  // ------------------------------------------------------------------ derived
  function recent() { return REPORTS.filter(function (e) { return inWindow(e.sweptAt); }).sort(function (a, b) { return Date.parse(b.sweptAt) - Date.parse(a.sweptAt) || a.label.localeCompare(b.label); }); }
  function mappedRecent() { return recent().filter(function (e) { return e.mapped; }); }
  function visibleReports() { return mappedRecent().filter(function (e) { return S.layers[e.marker] !== false; }); }
  function eligibleContexts() { return CONTEXTS.filter(function (o) { return o.mapped && inWindow(o.sweptAt); }); }
  function visibleContexts() { return S.layers.context ? eligibleContexts() : []; }
  function findAny(id) { return REPORTS.filter(function (r) { return r.id === id; })[0] || CONTEXTS.filter(function (c) { return c.id === id; })[0]; }
  function dateKey(e, mode) {
    if (mode === "swept") { var t = Date.parse(e.sweptAt); return isFinite(t) ? DKEY.format(new Date(t)) : ""; }
    return ((e.timeDenver || "").match(/^\d{4}-\d{2}-\d{2}/) || (e.date || "").match(/^\d{4}-\d{2}-\d{2}/) || [""])[0];
  }
  function database() {
    var q = S.query.trim().toLowerCase(), rq = S.regionQuery.trim().toLowerCase();
    return REPORTS.filter(function (e) {
      var d = dateKey(e, S.dateMode);
      return (!q || e.text.indexOf(q) >= 0) && (S.reporterFilter === "all" || e.reporterType === S.reporterFilter) &&
        (S.markerFilter === "all" || e.marker === S.markerFilter) && (S.continentFilter === "all" || e.continent === S.continentFilter) &&
        (S.countryFilter === "all" || e.country === S.countryFilter) && (S.shapeFolder === "all" || e.shape === S.shapeFolder) &&
        (!rq || e.label.toLowerCase().indexOf(rq) >= 0) && (!S.fromDate || (d && d >= S.fromDate)) && (!S.toDate || (d && d <= S.toDate)) &&
        (!S.onlyMedia || e.media.length > 0);
    }).sort(function (a, b) { return S.sortOrder === "az" ? a.label.localeCompare(b.label) : (Date.parse(b.sweptAt) || 0) - (Date.parse(a.sweptAt) || 0) || a.label.localeCompare(b.label); });
  }

  // ------------------------------------------------------------------ primitives
  function det(key, summary, body, opts) {
    opts = opts || {};
    var open = openDetails[key] !== undefined ? openDetails[key] : !!opts.open;
    if (opts.force) open = true;
    return '<details data-key="' + esc(key) + '"' + (open ? " open" : "") + (opts.cls ? ' class="' + opts.cls + '"' : "") + '><summary' + (opts.scls ? ' class="' + opts.scls + '"' : "") + ">" + summary + "</summary>" + body + "</details>";
  }
  function btn(label, action, arg, extra) { return '<button type="button" class="btn" data-action="' + action + '"' + (arg != null ? ' data-arg="' + esc(arg) + '"' : "") + (extra || "") + ">" + esc(label) + "</button>"; }
  function toggle(label, key, on) { return '<button type="button" class="toggle" role="switch" aria-checked="' + (on ? "true" : "false") + '" data-action="toggle" data-arg="' + key + '"><span class="track" aria-hidden="true"></span><span>' + esc(label) + "</span></button>"; }
  function seg(key, value, options) {
    return '<div class="seg" role="group">' + options.map(function (o) { return '<button type="button" aria-pressed="' + (o.value === value) + '" data-action="seg" data-key="' + key + '" data-arg="' + esc(o.value) + '">' + esc(o.label) + (o.count != null ? '<span class="count">' + o.count + "</span>" : "") + "</button>"; }).join("") + "</div>";
  }
  function input(label, key, value, ph, wide) { return '<label class="field' + (wide ? " wide" : "") + '"><span>' + esc(label) + '</span><input type="search" id="in-' + key + '" data-input="' + key + '" value="' + esc(value) + '" placeholder="' + esc(ph || "") + '"></label>'; }
  function select(label, key, value, options) { return '<label class="field"><span>' + esc(label) + '</span><select id="sel-' + key + '" data-select="' + key + '">' + options.map(function (o) { return '<option value="' + esc(o.value) + '"' + (o.value === value ? " selected" : "") + ">" + esc(o.label) + "</option>"; }).join("") + "</select></label>"; }
  function section(id, heading, body, collapsibleKey) {
    if (collapsibleKey) return '<section class="section"' + (id ? ' id="' + id + '"' : "") + ">" + det(collapsibleKey, heading, '<div class="stack">' + body + "</div>", { scls: "sec-h" }) + "</section>";
    return '<section class="section"' + (id ? ' id="' + id + '"' : "") + "><h2>" + heading + '</h2><div class="stack">' + body + "</div></section>";
  }
  function text(t, cls) { return '<p class="text' + (cls ? " " + cls : "") + '">' + t + "</p>"; }
  function rows(list) { return '<div class="rows">' + list.map(function (r) { return '<div class="r"><div class="t">' + esc(r.title) + '</div><div class="d">' + esc(r.detail) + "</div>" + (r.meta ? '<div class="m">' + esc(r.meta) + "</div>" : "") + "</div>"; }).join("") + "</div>"; }

  // ------------------------------------------------------------------ map
  function project(lon, lat) { return { x: ((lon + 180) / 360) * 1000, y: ((90 - lat) / 180) * 500 }; }
  function dotRadius(c) { return 5 + Math.min(c, 6) * 2.2; }
  var pendingMap = null;
  function popupHtml(x, isReport) {
    var c = isReport ? markerColor(x.marker) : CYAN;
    return '<div class="lm-pop"><div class="lm-pop-k"><span class="lm-pop-dot" style="' + (isReport ? "background:" + c + ";box-shadow:0 0 8px " + c : "border:2px solid " + c) + '"></span>' + esc(isReport ? reporterLabel(x) : "Context only · not a sighting") + "</div>" +
      "<strong>" + esc(isReport ? x.label : x.title) + "</strong>" +
      (isReport ? "<div>" + esc(sightingLabel(x)) + "</div><div>" + esc(shortShape(x.shape)) + (x.media.length ? " · " + x.media.length + " media" : "") + (x.historical ? " · HISTORICAL" : "") + "</div>" : "<div>" + esc(x.date || "Activity date not reported") + "</div>") +
      "<div>First swept " + esc(formatDenver(x.sweptAt)) + " · " + x.sources.length + " source" + (x.sources.length === 1 ? "" : "s") + "</div>" +
      '<div class="lm-pop-p">' + esc(x.precision || "") + "</div>" +
      '<button type="button" class="lm-open" data-open="' + esc(x.id) + '">Open full record &amp; sources</button></div>';
  }
  function worldMap(events, contexts, focus, mode, selectedId) {
    if (window.WNTRLiveMap) {
      var items = events.map(function (e) { return { id: e.id, lat: e.lat, lon: e.lon, kind: e.marker === "yellow" || e.marker === "blue" ? e.marker : "red", color: markerColor(e.marker), count: e.count, title: e.label + " · " + reporterLabel(e), popup: popupHtml(e, true) }; })
        .concat(contexts.map(function (o) { return { id: o.id, lat: o.lat, lon: o.lon, kind: "context", color: CYAN, count: 1, title: "Context only: " + o.title, popup: popupHtml(o, false) }; }));
      pendingMap = { items: items, selectedId: selectedId, mode: mode, focus: mode === "location" && focus ? { id: focus.id, lat: focus.lat, lon: focus.lon } : null,
        fitKey: mode + "|" + (mode === "location" && focus ? focus.id : "") + "|" + S.layers.red + S.layers.blue + S.layers.yellow + S.layers.context + "|" + S.mapNonce, onOpen: openRecord };
      return '<div class="map-wrap live"><div id="map-slot" class="map-slot"></div></div>' +
        '<p class="muted map-hint">Drag to pan · scroll, pinch or use +/− to zoom · ⤢ fits all markers · layer button (top right) switches Satellite, Dark, Streets and Terrain. Nearby markers group into numbered bubbles; click one to zoom in or spread them out.</p>';
    }
    var vb = "0 0 1000 500";
    if (mode === "location" && focus) { var p = project(focus.lon, focus.lat); vb = (p.x - 80) + " " + (p.y - 45) + " 160 90"; }
    var land = '<path d="' + (window.WNTR_WORLD_BASE || "") + '" fill="var(--land)" stroke="var(--b-subtle)" stroke-width="0.4"/>' +
      (window.WNTR_LAND || []).map(function (d) { return '<path d="' + d + '" fill="var(--land)" stroke="var(--b-subtle)" stroke-width="0.4"/>'; }).join("");
    var grid = [0, 90, 180, 270, 360].map(function (lon) { var x = lon / 360 * 1000; return '<line x1="' + x + '" y1="0" x2="' + x + '" y2="500" stroke="var(--b-subtle)" stroke-width="0.3"/>'; }).join("") +
      [0, 45, 90, 135, 180].map(function (lat) { var y = lat / 180 * 500; return '<line x1="0" y1="' + y + '" x2="1000" y2="' + y + '" stroke="var(--b-subtle)" stroke-width="0.3"/>'; }).join("");
    var dots = events.map(function (e) {
      var q = project(e.lon, e.lat), r = mode === "location" ? Math.max(dotRadius(e.count) * 0.35, 2.2) : dotRadius(e.count), c = markerColor(e.marker), sel = e.id === selectedId;
      return '<g role="button" tabindex="0" data-open="' + esc(e.id) + '" aria-label="' + esc(e.label + " · " + reporterLabel(e) + " · open full record") + '"><title>' + esc(e.label + " · " + reporterLabel(e) + " · swept " + formatDenver(e.sweptAt) + (e.historical ? " · HISTORICAL REPORT" : "")) + "</title>" +
        '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + r * 2.4 + '" fill="' + c + '" opacity="0.18"/>' +
        '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + r * 1.55 + '" fill="' + c + '" opacity="0.35"/>' +
        '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + r + '" fill="' + c + '" stroke="' + (sel ? "#ffffff" : c) + '" stroke-width="' + (sel ? 1.6 : 0.5) + '" opacity="0.95"/>' +
        (sel ? '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + (r + 3.5) + '" fill="none" stroke="' + c + '" stroke-width="1.2" opacity="0.8"/>' : "") + "</g>";
    }).join("");
    var rings = contexts.map(function (o) {
      var q = project(o.lon, o.lat), r = mode === "location" ? 4.5 : 11, sel = o.id === selectedId;
      return '<g role="button" tabindex="0" data-open="' + esc(o.id) + '" aria-label="' + esc("Context only: " + o.title) + '"><title>' + esc(o.title + " · CONTEXT, NOT A SIGHTING · " + (o.date || "") + " · " + o.precision) + "</title>" +
        '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + (r + 4) + '" fill="none" stroke="' + CYAN + '" stroke-width="' + (sel ? 2 : 1) + '" opacity="0.45"/>' +
        '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + r + '" fill="none" stroke="' + CYAN + '" stroke-width="2.2"/>' +
        '<circle cx="' + q.x + '" cy="' + q.y + '" r="' + (r + 6) + '" fill="transparent"/></g>';
    }).join("");
    return '<div class="map-wrap"><svg viewBox="' + vb + '" role="group" aria-label="Interactive 24-hour report map. Markers are keyboard buttons; the location list below offers the same records."><rect x="-200" y="-100" width="1400" height="700" fill="var(--bg)"/>' + land + grid + dots + rings + "</svg></div>";
  }

  // ------------------------------------------------------------------ navigator
  function recRow(e) {
    return '<button type="button" class="rec-row watch-record-row" data-open="' + esc(e.id) + '" title="' + esc("Open full record: " + e.label + " · " + sightingLabel(e)) + '">' +
      '<span class="dot" title="' + esc(markerLabel(e)) + '" style="background:' + markerColor(e.marker) + '"></span><span class="lbl">' + esc(e.label) + "</span><span>" + esc(compactDate(e)) + "</span><span>" + esc(shortShape(e.shape)) + '</span><span class="tag">' + esc(reporterTag(e)) + "</span>" +
      (e.media.length ? "<span>" + e.media.length + " media</span>" : "") + (e.mapped ? "" : '<span class="muted">Not mapped</span>') + (reportUnavailable(e) ? '<span class="warn">No longer available</span>' : "") + "</button>";
  }
  function navigator(list, keyPrefix, expand, searching) {
    var sel = findAny(S.selectedId), all = list.length;
    return CONTINENTS.filter(function (c) { return list.some(function (e) { return e.continent === c; }); }).map(function (cont) {
      var items = list.filter(function (e) { return e.continent === cont; });
      var countries = Array.from(new Set(items.map(function (e) { return e.country; }))).sort();
      var inner = countries.map(function (country) {
        var rs = items.filter(function (e) { return e.country === country; });
        return det(keyPrefix + "|" + cont + "|" + country, esc(country) + " · " + rs.length, rs.map(recRow).join(""), { cls: "nav-country", open: expand || searching || (sel && sel.continent === cont && sel.country === country), force: expand || searching });
      }).join("");
      return det(keyPrefix + "|" + cont, esc(cont) + " · " + items.length, inner, { cls: "nav-cont", open: expand || searching || items.length === all || (sel && sel.continent === cont), force: expand || searching });
    }).join("");
  }

  // ------------------------------------------------------------------ header
  function header() {
    var rc = recent().length, gq = S.globalQuery.trim().toLowerCase();
    var results = gq ? REPORTS.filter(function (e) { return e.text.indexOf(gq) >= 0; }).map(function (e) { return { id: e.id, label: e.label, group: e.continent + " → " + e.country, kind: "Report" }; })
      .concat(CONTEXTS.filter(function (o) { return o.text.indexOf(gq) >= 0; }).map(function (o) { return { id: o.id, label: o.title, group: o.continent + " → " + o.country, kind: "Context only" }; })) : [];
    var shown = results.slice(0, 60);
    var resHtml = gq ? (shown.length ? '<div id="watch-global-results" role="region" aria-label="' + results.length + ' matching records" style="margin-top:12px;display:grid;gap:4px">' + shown.map(function (r) { return '<button type="button" class="control result-btn" data-open="' + esc(r.id) + '"><span>' + esc(r.kind + " · " + r.group) + "</span><br>" + esc(r.label) + "</button>"; }).join("") + (results.length > shown.length ? '<p class="muted">' + (results.length - shown.length) + " more matches · refine the search</p>" : "") + "</div>" : '<p class="muted" style="margin-top:8px">No matching records.</p>') : "";
    return '<header id="watch-dashboard-header" class="watch-header">' +
      '<div class="row g8"><strong class="hdr-title">WNTR:\\\\Project StarFire UFO Sighting Tracker</strong><span class="hdr-checked">Checked ' + esc(formatDenver(LAST)) + '</span><span class="chip">' + rc + " last 24h · " + REPORTS.length + ' total</span><span class="chip" role="status">No confirmed flap</span></div>' +
      '<div class="watch-tabs" role="tablist" aria-label="Dashboard views">' + TABS.map(function (t) { return '<button type="button" class="control tab-btn" role="tab" id="watch-tab-' + t.id + '" aria-selected="' + (S.tab === t.id) + '" aria-controls="watch-panel-' + t.id + '" tabindex="' + (S.tab === t.id ? 0 : -1) + '" data-action="tab" data-arg="' + t.id + '">' + esc(t.label) + "</button>"; }).join("") + "</div>" +
      det("global", "Find a report or context", '<label for="in-globalQuery" style="display:block;margin:8px 0">Search all locations, narratives and sources</label><input id="in-globalQuery" class="search" type="search" data-input="globalQuery" value="' + esc(S.globalQuery) + '" placeholder="Place, shape, source or ID"><div id="global-results">' + resHtml + "</div>") +
      "</header>";
  }

  // ------------------------------------------------------------------ tabs
  function mapTab() {
    var rec = mappedRecent(), vis = visibleReports(), ec = eligibleContexts(), vc = visibleContexts();
    var focus = vis.filter(function (e) { return e.id === S.focusId; })[0] || vc.filter(function (o) { return o.id === S.focusId; })[0] || vis[0] || vc[0] || null;
    var layerDefs = [{ key: "red", color: RED, label: "Red · civilian / unknown affiliation" }, { key: "blue", color: BLUE, label: "Blue · alleged unidentified-craft testing" }, { key: "yellow", color: YELLOW, label: "Yellow · military-confirmed / witness" }];
    var legend = '<div class="row" style="padding:8px 0 12px">' + layerDefs.map(function (l) {
      var n = vis.filter(function (e) { return e.marker === l.key; }).length, t = rec.filter(function (e) { return e.marker === l.key; }).length;
      return '<span class="row g8"><span class="legend-dot" aria-hidden="true" style="background:' + l.color + ";box-shadow:0 0 8px " + l.color + '"></span>' + toggle(l.label + " (" + n + "/" + t + ")", "layer:" + l.key, S.layers[l.key]) + "</span>";
    }).join("") + '<span class="row g8"><span class="legend-ring" aria-hidden="true"></span>' + toggle("Cyan · OSINT / military context (" + vc.length + "/" + ec.length + ")", "layer:context", S.layers.context) + "</span></div>";
    var unmapped = recent().length - rec.length;
    var list = (vis.length ? navigator(vis, "maplist", false, false) : "") + vc.map(function (o) { return '<button type="button" class="control ctx-btn watch-record-row" data-open="' + esc(o.id) + '">Context only · ' + esc(o.country) + " · " + esc(o.title) + "</button>"; }).join("");
    return section("watch-panel-map", "Map · last 24 hours",
      '<div class="row between">' + seg("view", S.view, [{ value: "overview", label: "World" }, { value: "location", label: "Selected location" }]) + btn("Reset map & layers", "resetMap") + "</div>" +
      det("layers", "Layers & legend · " + vis.length + "/" + rec.length + " reports · " + vc.length + "/" + ec.length + " context rings", legend) +
      worldMap(vis, vc, focus, S.view, S.detailId || S.focusId || null) +
      text("First swept: " + esc(formatDenver(new Date(LAST_MS - 86400000).toISOString())) + " → " + esc(formatDenver(LAST)) + ". " + (REPORTS.length - recent().length) + " older reports remain in Archive" + (unmapped ? "; " + unmapped + " recent reports had no place the sweep could map and are listed under Latest" : "") + ". Discovery time is not sighting time; newly found historical reports are labeled.") +
      det("maplist", "Accessible location list · same visible map markers", list || '<p class="muted">No visible markers.</p>'));
  }
  function latestTab() {
    var rec = recent();
    var cards = rec.slice(0, S.latestLimit).map(function (e) {
      var c = markerColor(e.marker);
      return '<button type="button" class="control card-btn watch-record-row" data-open="' + esc(e.id) + '"><span class="row g8"><span aria-hidden="true" class="dot" style="width:9px;height:9px;background:' + c + ";box-shadow:0 0 8px " + c + '"></span><strong style="flex:1 1 240px">' + esc(e.label) + "</strong><span>" + esc(formatDenver(e.sweptAt)) + "</span></span>" +
        '<span class="row g10"><span>' + esc(shortShape(e.shape)) + '</span><span class="tag" style="border-radius:4px;padding:1px 6px">' + esc(reporterLabel(e)) + "</span><span>Sighting: " + esc(compactDate(e)) + "</span>" + (e.media.length ? "<span>" + e.media.length + " media</span>" : "") + (e.mapped ? "" : '<span class="muted">Not mapped</span>') + (e.historical ? "<strong>Historical</strong>" : "") + (reportUnavailable(e) ? '<strong class="warn">No longer available</strong>' : "") + "</span>" +
        (e.appearance ? '<span class="one-line">' + esc(e.appearance) + "</span>" : "") + "</button>";
    }).join("");
    return section("watch-panel-latest", "Latest · recently swept reports",
      text(rec.length + " reports first logged in the last 24 hours before the latest sweep, newest first. Times below are first-swept America/Denver (MST), not the sighting time. Open a card for the full account and citations.") +
      '<div class="grid-gap">' + (cards || '<p class="muted">No reports were first swept in the last 24 hours.</p>') + "</div>" +
      '<div class="row"><span>Showing ' + Math.min(S.latestLimit, rec.length) + " of " + rec.length + "</span>" + (S.latestLimit < rec.length ? btn("Show 12 more", "more") : "") + btn("Browse the full archive", "tab", "archive") + "</div>");
  }
  function archiveTab() {
    var db = database(), matching = CONTINENTS.filter(function (c) { return REPORTS.some(function (e) { return e.continent === c; }); });
    var countries = Array.from(new Set(REPORTS.filter(function (e) { return S.continentFilter === "all" || e.continent === S.continentFilter; }).map(function (e) { return e.country; }))).sort();
    var sel = findAny(S.selectedId) || REPORTS[0];
    var selCountries = Array.from(new Set(REPORTS.filter(function (e) { return e.continent === sel.continent; }).map(function (e) { return e.country; }))).sort();
    var selReports = REPORTS.filter(function (e) { return e.continent === sel.continent && e.country === sel.country; }).sort(function (a, b) { return a.label.localeCompare(b.label); });
    var searching = !!S.query.trim() || !!S.regionQuery.trim();
    return section("watch-panel-archive", "Archive · continent → country → report",
      seg("continentFilter", S.continentFilter, [{ value: "all", label: "All continents", count: REPORTS.length }].concat(matching.map(function (c) { return { value: c, label: c, count: REPORTS.filter(function (e) { return e.continent === c; }).length }; }))) +
      '<div class="row end">' + input("Search archive", "query", S.query, "Place, shape, narrative, source…", true) +
      select("Country", "countryFilter", S.countryFilter, [{ value: "all", label: "All countries" }].concat(countries.map(function (c) { return { value: c, label: c }; }))) +
      select("Shape folder", "shapeFolder", S.shapeFolder, [{ value: "all", label: "All shapes" }].concat(SHAPES.map(function (c) { return { value: c, label: shortShape(c) }; }))) +
      select("Sort", "sortOrder", S.sortOrder, [{ value: "newest", label: "Newest first swept" }, { value: "az", label: "Location A–Z" }]) + btn("Reset filters", "resetDb") + "</div>" +
      det("advanced", "Advanced filters · affiliation, marker, region, dates & media", '<div class="row end" style="padding:10px 0">' +
        select("Reporter", "reporterFilter", S.reporterFilter, [{ value: "all", label: "All affiliations" }, { value: "civilian", label: "Civilian" }, { value: "military", label: "Military-confirmed / witness" }, { value: "unknown", label: "Unknown affiliation" }]) +
        select("Marker", "markerFilter", S.markerFilter, [{ value: "all", label: "All marker types" }, { value: "red", label: "Red · sighting" }, { value: "blue", label: "Blue · alleged testing" }, { value: "yellow", label: "Yellow · military-confirmed" }]) +
        input("Region / state / city", "regionQuery", S.regionQuery, "Wisconsin, Puebla, Seoul…") +
        select("Date basis", "dateMode", S.dateMode, [{ value: "swept", label: "First swept · Denver" }, { value: "sighting", label: "Sighting · Denver when known" }]) +
        input("From · YYYY-MM-DD", "fromDate", S.fromDate, "2026-11-01") + input("Through · YYYY-MM-DD", "toDate", S.toDate, "2026-11-15") +
        toggle("With source-linked media only", "onlyMedia", S.onlyMedia) + "</div>") +
      '<div class="row"><span aria-live="polite">' + db.length + " / " + REPORTS.length + " retained reports" + (S.shapeFolder !== "all" ? " · " + esc(shortShape(S.shapeFolder)) + " folder" : "") + "</span>" + toggle("Expand all folders", "expandReports", S.expandReports) + "</div>" +
      '<div id="archive-nav">' + (db.length ? navigator(db, "archive", S.expandReports, searching) : '<p class="muted">No reports match these filters.</p>') + "</div>" +
      det("finder", "Location finder · unfiltered continent / country / location", '<div class="row end" style="padding:10px 0">' +
        select("Continent", "finderContinent", sel.continent, matching.map(function (c) { return { value: c, label: c }; })) +
        select("Country", "finderCountry", sel.country, selCountries.map(function (c) { return { value: c, label: c }; })) +
        select("Location / report", "finderReport", sel.id, selReports.map(function (e) { return { value: e.id, label: e.label + " · " + compactDate(e) }; })) + btn("Open selected record", "openSelected") + "</div>") +
      text("Continent counts are all-time; every filter intersects. North America includes Central America and the Caribbean; Hawaii is Oceania → USA. Reports the automatic sweep could not place sit under " + UNKNOWN_CONT + " → Unknown. Dates without a time retain source-native precision; no guessed dates or coordinates."));
  }
  function insightsTab() {
    var counts = SHAPES.map(function (c) { return { category: c, count: REPORTS.filter(function (e) { return e.shape === c; }).length }; });
    var ranked = counts.filter(function (s) { return s.category !== "Unknown/Not described" && s.count > 0; }).sort(function (a, b) { return b.count - a.count; });
    var winners = ranked.filter(function (s) { return s.count === (ranked[0] && ranked[0].count); });
    var bars = counts.slice().sort(function (a, b) { return b.count - a.count; });
    var max = Math.max.apply(null, bars.map(function (b) { return b.count; }).concat([1]));
    var summary = !winners.length ? "No described category can be ranked; Unknown/Not described is excluded from most-reported." :
      winners.length > 1 ? "Tied most reported: " + winners.map(function (w) { return w.category; }).join(" and ") + ", " + winners[0].count + " reports each (" + (winners[0].count / REPORTS.length * 100).toFixed(1) + "% of all " + REPORTS.length + "); Unknown/Not described is excluded from the ranking, not the denominator." :
        winners[0].category + " is the most reported category: " + winners[0].count + " of " + REPORTS.length + " archived reports (" + (winners[0].count / REPORTS.length * 100).toFixed(1) + "%); Unknown/Not described is excluded from the ranking, not the denominator.";
    var shapes = section(null, "Reported shapes · permanent archive",
      '<div class="row">' + btn("All shapes · " + REPORTS.length, "shapeFolder", "all") + counts.map(function (s) { return btn(shortShape(s.category) + " · " + s.count, "shapeFolder", s.category, s.count === 0 ? " disabled" : ""); }).join("") + "</div>" +
      '<div class="bars" role="list">' + bars.map(function (b) { var em = winners.length === 1 && b.category === winners[0].category; return '<div class="bar' + (em ? " em" : "") + '" role="listitem"><span class="lab">' + esc(b.category) + '</span><span class="track"><span class="fill" style="display:block;width:' + (b.count / max * 100).toFixed(1) + '%"></span></span><span class="val">' + b.count + " · " + (b.count / Math.max(1, REPORTS.length) * 100).toFixed(1) + "%</span></div>"; }).join("") + "</div>" +
      text(esc(summary)) + text("Each report counts once under its primary reported appearance. Hand-reviewed reports carry a reviewed category; automatic reports are sorted by keywords in their headline, so treat their shape as a rough guide. Shape does not establish identity, material or a flap."));
    var clusters = (FLAP.clusters || []);
    var flap = section(null, "Flap Watch",
      '<div class="status">No flap is currently confirmed</div>' +
      text(clusters.length + " cautious watch clusters · checked " + esc(formatDenver(FLAP.checkedAt || LAST)) + ". Open a cluster to inspect the assessment and its records.") +
      clusters.map(function (c, i) {
        var region = Array.from(new Set((c.places || []).map(function (p) { return String(p).split(/[,(]/)[0].trim(); }))).slice(0, 4).join(" / ") || "Cluster " + (i + 1);
        var assess = "Automatic screening flag: " + c.reports + " archived reports from " + c.independentSources + " different source sites fall within about 150 km and 72 hours (" + formatDenver(c.from) + " → " + formatDenver(c.to) + "). Sources: " + (c.sourceDomains || []).join(", ") + ". This is a keyword-and-distance rule, not a confirmed flap: descriptions, independence and conventional explanations have not been reviewed. Read the linked sources.";
        return det("flap|" + i, esc(region) + " · " + (c.ids || []).length + " archived events under review", "<p>" + esc(assess) + '</p><div class="row">' + (c.ids || []).map(function (id) { var e = findAny(id); return e ? '<button type="button" class="control watch-record-row" data-open="' + esc(id) + '">' + esc(e.label) + "</button>" : ""; }).join("") + "</div>", { cls: "flap-c" });
      }).join("") +
      det("flaprule", "Screening rule & exclusions", "<p>" + esc(FLAP.rule || "") + "</p><p>A flap is only called confirmed after a sourced review of several independent reports; this automatic app never declares one by itself. Known conventional identifications (Starlink, rocket launches) stay archived but do not establish an unidentified-craft flap. Uneven search coverage and OSINT coincidences do not establish a reporting surge." + ((FLAP.setAsideSameStory || []).length ? " " + FLAP.setAsideSameStory.length + " group(s) were set aside as one story retold by several outlets." : "") + "</p>"));
    var cq = S.contextQuery.trim().toLowerCase();
    var ctx = CONTEXTS.filter(function (o) { return !cq || o.text.indexOf(cq) >= 0; });
    var osint = section(null, "OSINT & military context",
      '<div class="row end">' + toggle("Show permanent context list", "showOsint", S.showOsint) + input("Search context", "contextQuery", S.contextQuery, "FAA, Mildenhall, re-entry…") + "</div>" +
      text(ctx.length + " / " + CONTEXTS.length + " permanent context items · " + CONTEXTS.filter(function (o) { return o.mapped; }).length + " source-located · " + CONTEXTS.filter(function (o) { return !o.mapped; }).length + " unmapped. Context is not a sighting or confirmation; map toggles never remove archived context.") +
      (S.showOsint ? CONTINENTS.filter(function (c) { return ctx.some(function (o) { return o.continent === c; }); }).map(function (cont) {
        var items = ctx.filter(function (o) { return o.continent === cont; });
        return det("ctx|" + cont, esc(cont) + " · " + items.length, items.map(function (o) { return '<button type="button" class="control ctx-btn watch-record-row" data-open="' + esc(o.id) + '"><span>' + esc(o.country + " · OSINT / context · " + (o.mapped ? "Approximate public location" : "Unmapped")) + "</span><br><strong>" + esc(o.title) + "</strong>" + (reportUnavailable(o) ? '<span class="warn"> · No longer available</span>' : "") + "</button>"; }).join(""), { cls: "flap-c", force: !!cq });
      }).join("") : ""));
    return '<section class="section" id="watch-panel-insights"><h2>Insights</h2>' + shapes + flap + osint + "</section>";
  }
  function healthTab() {
    var cites = [], ctxCites = [];
    REPORTS.forEach(function (e) { e.sources.forEach(function (s) { cites.push(s); }); });
    CONTEXTS.forEach(function (o) { o.sources.forEach(function (s) { ctxCites.push(s); }); });
    function n(list, st) { return list.filter(function (s) { return srcStatus(s) === st; }).length; }
    var distinct = new Set(cites.map(function (s) { return s.url; })).size;
    var ls = META.lastSweep || {};
    var list = [
      { title: "Archived records", detail: REPORTS.length + " reports + " + CONTEXTS.length + " context records kept permanently", meta: "Narratives, citations and corrections are retained even if a source is removed" },
      { title: "Available sighting citations", detail: n(cites, "available") + " / " + cites.length, meta: distinct + " distinct sighting-source URLs; counts are citation entries, not unique websites" },
      { title: "Check failed", detail: n(cites, "check failed") + " sighting citations · " + n(ctxCites, "check failed") + " context citations", meta: "Blocks, security challenges and timeouts are not proof of removal" },
      { title: "No longer available", detail: n(cites, "unavailable") + " sighting citations · " + n(ctxCites, "unavailable") + " context citations", meta: "Only 404 / 410 responses trigger this flag" },
      { title: "Context citation availability", detail: n(ctxCites, "available") + " available / " + ctxCites.length + " retained citations", meta: "Context has its own denominator and stays separate from sighting counts" },
      { title: "Automatic sweeps", detail: (META.sweepCount || 0) + " sweeps · last " + formatDenver(LAST) + (META.sweepSeconds ? " · " + META.sweepSeconds + " s" : ""), meta: "Last sweep: " + (ls.rawItems || 0) + " feed items read, " + (ls.added || 0) + " new reports, " + (ls.mergedAsExtraSource || 0) + " added as extra sources, " + (ls.linksChecked || 0) + " old links re-checked" }
    ];
    var feeds = (META.sourcesStatus || []).map(function (s) {
      if (s.name === "Link check") return { title: "Old-link re-check", detail: s.items + " links re-checked · " + s.kept + " newly no longer available", meta: "A capped number of the oldest-checked links are re-tested each sweep" };
      return { title: s.name, detail: s.ok + " / " + s.requests + " requests ok · " + s.items + " items · " + s.kept + " kept" + (s.skipped ? " · " + s.skipped + " skipped (time budget)" : ""), meta: (s.errors || []).length ? "Errors: " + s.errors.join(" · ") : "No errors in the last sweep" };
    });
    var idx = Array.from(new Map(cites.concat(ctxCites).map(function (s) { return [s.url, s]; })).values()).sort(function (a, b) { return sourceHost(a.url).localeCompare(sourceHost(b.url)); });
    var cards = '<div class="linkcards">' + idx.map(function (s, i) { return '<a class="lc" href="' + esc(safeUrl(s.url)) + '" target="_blank" rel="noopener noreferrer"><span class="n">' + (i + 1) + '</span><span class="tt">[' + esc(s.role || "source") + "] " + esc(sourceName(s)) + (s.note ? " (" + esc(s.note) + ")" : "") + " · " + esc(availabilityLabel(s)) + '</span><span class="meta">' + esc(sourceHost(s.url)) + " · " + esc(publicationTime(s.published)) + "</span></a>"; }).join("") + "</div>";
    return section("watch-panel-health", "Sources & archive health",
      text("Swept records survive source removals. Link availability is re-checked a few dozen links per sweep; it is separate from the research and 24-hour map clock.") + rows(list) +
      section(null, "Sweep sources · last run", rows(feeds)) +
      section(null, "Methodology & caveats",
        text("Public-source claims are unverified, coverage is bounded and uneven, and this is not an exhaustive census or a private/deep-web search. The site is rebuilt by an automatic sweep about twice a day; it is not a live stream.") +
        text("The map uses first-swept times within the 24 hours ending at the latest sweep, not browser time, sighting dates or availability checks. A historical event can be newly discovered; its source-local date and uncertainty remain visible. Archive and shape totals never age off with map markers.") +
        text("Red: civilian or affiliation-unknown claims. Blue: alleged unidentified-craft testing, never ordinary known aircraft/rocket testing. Yellow: cited military witness or official confirmation of this report, not evidence of an alien or military craft. Cyan: separate OSINT/military context, not corroboration or a live track. Supported distinct reports determine dot size, not witnesses, clips or engagement.") +
        text("Inclusion rule (same as the Grok Page): only concrete, newly reported sightings are logged - a described observation (lights, shape, motion) from a first-hand witness, a witness-report database (UFO Meldpunt, Probed, Aliens.co.il, UFO Hunters, MUFON) or local media relaying a resident's report or footage, tied to a place. General UFO news, politics/disclosure, declassified files, documentaries/TV, explainers, opinion/theories, listicles and historical rehashes are left out; military, launch and airspace items appear only as cyan context. Items the sweep read but left out are kept with their reasons in data/excluded.json.") +
        text("The automatic sweep applies these rules with no AI and no human review. Places can be wrong or only approximate (a town or a state/region centre), and reports with no place found are listed but never given made-up coordinates. Hand-reviewed reports copied from the Grok Page keep their reviewed details.") +
        text("Continent grouping follows recorded geography only. North America includes Central America and the Caribbean; Hawaii is Oceania. Multi-country reports count once. Place names: GeoNames (CC BY 4.0) and OpenStreetMap Nominatim."), "methodology") +
      section(null, "Source index · " + idx.length + " distinct cited URLs", text("Every narrative opens with its own full source links in the shared record reader. This index retains all report and context citations, grouped by source host.") + cards, "sourceindex"));
  }

  // ------------------------------------------------------------------ record reader
  function drawer(id) {
    var e = REPORTS.filter(function (r) { return r.id === id; })[0], o = CONTEXTS.filter(function (c) { return c.id === id; })[0], x = e || o;
    if (!x) return "";
    var canLocate = x.mapped && inWindow(x.sweptAt);
    var facts = e ? [
      ["Sighting · Denver", sightingLabel(e)], ["Source-native sighting", (e.date || "not reported") + (e.timeLocal ? " · " + e.timeLocal : "") + (e.tz ? " (" + e.tz + ")" : "")], ["Published", publicationTime(e.published)],
      ["First swept", formatDenver(e.sweptAt)], ["Reporter basis", e.reporterTypeBasis || "Not recorded"], ["Marker", markerLabel(e) + (e.markerBasis ? " · " + e.markerBasis : "")], ["Distinct supported reports", String(e.count)],
      ["Coordinates", e.mapped ? e.lat + ", " + e.lon + " · " + e.precision : e.precision || "No location found; not mapped"], ["Evidence", e.evidence || "Not assessed (automatic sweep)"], ["Primary reported shape", e.shape], ["Shape basis", e.shapeBasis],
      ["Appearance", e.appearance || "Not recorded"], ["Testing claim", e.testingStatus || (e.allegedTesting ? "Alleged, not confirmed" : "No unidentified-craft testing claim recorded")], ["Origin", e.origin === "seed" ? "Hand-reviewed archive (Nov 2026)" : "Automatic sweep (keyword rules, not reviewed)"], ["Permanent ID", e.id]
    ] : [
      ["Activity date", o.date || "not reported"], ["Published", publicationTime(o.published)], ["First swept", formatDenver(o.sweptAt)], ["Public place", o.place || "Not established"],
      ["Coordinates / precision", o.mapped ? o.lat + ", " + o.lon + " · " + o.precision : o.precision || "No public location; no invented marker"], ["Why listed", o.relevance || o.markerBasis || "OSINT / context"], ["Map treatment", !o.mapped ? "Unmapped: public location not established" : inWindow(o.sweptAt) ? "24-hour first-swept window; activity may be historical" : "Outside map window; permanent archive retained"], ["Permanent ID", o.id]
    ];
    var media = e ? e.media : [];
    var srcs = x.sources;
    var corr = e && e.corrections.length ? det("d-corr|" + id, "Corrections · " + e.corrections.length, "<ul>" + e.corrections.map(function (c) { return "<li>" + esc(formatDenver(c.at)) + " · " + esc(c.note || "") + "</li>"; }).join("") + "</ul>", { scls: "sumline" }) : "";
    return '<aside class="watch-drawer watch-accessible" role="region" aria-labelledby="watch-detail-title">' +
      '<div class="row between" style="padding:8px 0 16px"><strong>Full record · ' + (e ? "Report" : "Context only") + '</strong><button type="button" class="control" id="close-record" data-action="close" aria-label="Close record and return to the location or list">Close record · Esc</button></div>' +
      "<div>" + esc(x.continent) + " → " + esc(x.country) + "</div>" +
      '<h2 id="watch-detail-title">' + esc(e ? e.label : o.title) + "</h2>" +
      '<div class="row g10"><span style="width:10px;height:10px;border-radius:999px;flex-shrink:0;display:inline-block;' + (e ? "background:" + markerColor(e.marker) : "border:2px solid " + CYAN) + '"></span><strong>' + esc(e ? reporterLabel(e) : "Context only · OSINT / military context") + "</strong>" + (e ? "<span>" + esc(shortShape(e.shape)) + "</span>" : "") + (e && e.historical ? "<strong>HISTORICAL</strong>" : "") + "</div>" +
      "<p>" + esc(e ? reportAvailability(e) : "Context is not a sighting, craft confirmation or proof of a relationship.") + "</p>" +
      '<div class="row g10">' + (canLocate ? '<button type="button" class="control" data-action="locate" data-arg="' + esc(id) + '">Locate on 24h map</button>' : "") + "<span>One shared reader · links open separately</span></div>" +
      (e && e.origin === "auto" && e.title !== e.label ? '<h3>Headline</h3><p style="margin:0 0 12px">' + esc(e.title) + "</p>" : "") +
      '<h3>Reported account</h3><p style="margin:0 0 12px">' + esc(x.narrative || "No account text captured; open the source.") + "</p>" +
      (e && e.explanations.length ? det("d-expl|" + id, "Competing explanations", "<ul>" + e.explanations.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul>") : "") +
      det("d-facts|" + id, "Dates, shape & classification provenance", "<dl>" + facts.map(function (f) { return "<div><dt>" + esc(f[0]) + "</dt><dd>" + esc(f[1]) + "</dd></div>"; }).join("") + "</dl>", { scls: "sumline" }) +
      corr +
      (media.length ? det("d-media|" + id, "Media · " + media.length + " source-linked items", '<p>Link presence was checked, not imagery authenticity. No third-party embeds or autoplay.</p>' + media.map(function (m, i) { return '<div style="margin-bottom:16px">' + ext(m.url, (m.type === "photo" ? "Photo" : "Video") + " " + (i + 1) + " · open media ↗") + (m.note ? "<div>" + esc(m.note) + "</div>" : "") + "</div>"; }).join(""), { open: true, scls: "sumline" }) : "") +
      det("d-src|" + id, "Cited sources · " + srcs.length, srcs.map(function (s, i) { return '<div class="src">' + ext(s.url, (i + 1) + ". " + esc(sourceName(s)) + " ↗") + "<div>" + esc(s.role || "source") + " · Published: " + esc(publicationTime(s.published)) + "</div><div>Accessed: " + esc(s.accessed ? formatDenver(s.accessed) : "not recorded") + (s.note ? " · " + esc(s.note) : s.limited ? " · limited / listing only" : "") + (s.via ? " · via " + esc(s.via) : "") + "</div><div" + (srcStatus(s) === "unavailable" ? ' class="warn"' : "") + ">" + esc(availabilityLabel(s)) + "</div></div>"; }).join("") + "<p>Swept details stay in the archive. Source removal never deletes the record.</p>", { open: true, scls: "sumline" }) +
      '<button type="button" class="control" data-action="close" style="margin-top:16px">Close record and return</button></aside>';
  }

  // ------------------------------------------------------------------ render
  var app = document.getElementById("app");
  function render(opts) {
    opts = opts || {};
    var active = document.activeElement, activeId = active && active.id, selStart = null, selEnd = null;
    if (active && active.tagName === "INPUT") { try { selStart = active.selectionStart; selEnd = active.selectionEnd; } catch (err) { } }
    Array.prototype.forEach.call(app.querySelectorAll("details[data-key]"), function (d) { openDetails[d.dataset.key] = d.open; });
    pendingMap = null;
    var panel = S.tab === "map" ? mapTab() : S.tab === "latest" ? latestTab() : S.tab === "archive" ? archiveTab() : S.tab === "insights" ? insightsTab() : healthTab();
    app.innerHTML = header() + panel + (S.detailId ? section("watch-detail-panel", "Record details · inline reader", drawer(S.detailId)) : "") +
      '<footer class="foot">Reports are claims, not verified events. Every entry links to its source. Built automatically by an open-source sweep with no AI.</footer>';
    var slot = document.getElementById("map-slot");
    if (slot && pendingMap && window.WNTRLiveMap) window.WNTRLiveMap.attach(slot, pendingMap);
    if (opts.focusClose) { var c = document.getElementById("close-record"); if (c) { c.focus({ preventScroll: true }); c.scrollIntoView({ block: "center" }); } }
    else if (opts.focusTab) { var t = document.getElementById("watch-tab-" + S.tab); if (t) t.focus(); }
    else if (activeId) { var el = document.getElementById(activeId); if (el) { el.focus({ preventScroll: true }); if (selStart !== null && el.setSelectionRange) { try { el.setSelectionRange(selStart, selEnd); } catch (err) { } } } }
  }
  function openRecord(id) { var x = findAny(id); if (!x) return; if (REPORTS.indexOf(x) >= 0) S.selectedId = id; S.detailId = id; S.globalQuery = ""; render({ focusClose: true }); }
  function resetDb() { S.query = ""; S.reporterFilter = "all"; S.markerFilter = "all"; S.countryFilter = "all"; S.continentFilter = "all"; S.shapeFolder = "all"; S.sortOrder = "newest"; S.regionQuery = ""; S.dateMode = "swept"; S.fromDate = ""; S.toDate = ""; S.onlyMedia = false; }

  app.addEventListener("click", function (ev) {
    var t = ev.target.closest("[data-open],[data-action]");
    if (!t || !app.contains(t)) return;
    if (t.hasAttribute("data-open")) { openRecord(t.getAttribute("data-open")); return; }
    var a = t.getAttribute("data-action"), arg = t.getAttribute("data-arg");
    if (a === "tab") { S.tab = arg; render({ focusTab: t.getAttribute("role") === "tab" }); if (t.getAttribute("role") !== "tab") window.scrollTo(0, 0); return; }
    if (a === "seg") { var k = t.getAttribute("data-key"); S[k] = arg; if (k === "continentFilter") S.countryFilter = "all"; render(); return; }
    if (a === "toggle") { if (arg.indexOf("layer:") === 0) { var L = arg.slice(6); S.layers[L] = !S.layers[L]; } else S[arg] = !S[arg]; render(); return; }
    if (a === "resetMap") { S.layers = { red: true, blue: true, yellow: true, context: true }; S.view = "overview"; S.focusId = ""; S.mapNonce++; render(); return; }
    if (a === "more") { S.latestLimit += 12; render(); return; }
    if (a === "resetDb") { resetDb(); render(); return; }
    if (a === "shapeFolder") { S.shapeFolder = arg; S.tab = "archive"; render(); window.scrollTo(0, 0); return; }
    if (a === "openSelected") { openRecord(S.selectedId); return; }
    if (a === "close") { var back = S.detailId; S.detailId = ""; render(); var b = app.querySelector('[data-open="' + (window.CSS && CSS.escape ? CSS.escape(back) : back) + '"]'); if (b) b.focus(); return; }
    if (a === "locate") { var x = findAny(arg); if (x && x.marker && REPORTS.indexOf(x) >= 0) S.layers[x.marker] = true; else S.layers.context = true; S.focusId = arg; S.view = "location"; S.tab = "map"; S.mapNonce++; S.detailId = ""; render(); window.scrollTo(0, 0); return; }
  });
  app.addEventListener("keydown", function (ev) {
    var t = ev.target;
    if (t.matches && t.matches("g[data-open]") && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); openRecord(t.getAttribute("data-open")); return; }
    if (t.getAttribute && t.getAttribute("role") === "tab") {
      var i = TABS.map(function (x) { return x.id; }).indexOf(S.tab), n = i;
      if (ev.key === "ArrowRight") n = (i + 1) % TABS.length; else if (ev.key === "ArrowLeft") n = (i + TABS.length - 1) % TABS.length; else if (ev.key === "Home") n = 0; else if (ev.key === "End") n = TABS.length - 1; else return;
      ev.preventDefault(); S.tab = TABS[n].id; render({ focusTab: true }); return;
    }
    if (t.id === "in-globalQuery") {
      if (ev.key === "Escape") { S.globalQuery = ""; render(); }
      if (ev.key === "Enter") { var first = app.querySelector("#watch-global-results [data-open]"); if (first) { ev.preventDefault(); openRecord(first.getAttribute("data-open")); } }
    }
  });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && S.detailId && !(ev.target && ev.target.id === "in-globalQuery")) { S.detailId = ""; render(); } });
  app.addEventListener("input", function (ev) {
    var k = ev.target.getAttribute("data-input"); if (!k) return;
    S[k] = ev.target.value; render();
  });
  app.addEventListener("change", function (ev) {
    var k = ev.target.getAttribute("data-select"); if (!k) return;
    var v = ev.target.value;
    if (k === "finderContinent") { var e1 = REPORTS.filter(function (r) { return r.continent === v; })[0]; if (e1) S.selectedId = e1.id; }
    else if (k === "finderCountry") { var cur = findAny(S.selectedId) || REPORTS[0]; var e2 = REPORTS.filter(function (r) { return r.continent === cur.continent && r.country === v; })[0]; if (e2) S.selectedId = e2.id; }
    else if (k === "finderReport") { openRecord(v); return; }
    else S[k] = v;
    render();
  });
  app.addEventListener("toggle", function (ev) { var d = ev.target; if (d.tagName === "DETAILS" && d.dataset.key) openDetails[d.dataset.key] = d.open; }, true);

  fetch("data/events.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (db) {
    META = db.meta || {}; FLAP = db.flapWatch || {};
    LAST = META.lastSweepAt || new Date().toISOString(); LAST_MS = Date.parse(LAST);
    var all = (db.reports || []).map(normalize);
    REPORTS = all.filter(function (e) { return e.kind !== "context"; });
    CONTEXTS = all.filter(function (e) { return e.kind === "context"; });
    S.selectedId = (REPORTS[0] || {}).id || "";
    render();
  }).catch(function (err) { app.innerHTML = '<p class="warn">Could not load the archive (' + esc(err.message) + "). Try reloading the page.</p>"; });
})();
