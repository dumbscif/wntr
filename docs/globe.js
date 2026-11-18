/* WNTR 3D globe for the Map tab: MapLibre GL JS v5 (bundled in docs/vendor, no CDN, no API key, no sign-in)
   with globe projection + free keyless raster tiles (Esri World Imagery and reference labels, CARTO dark, Esri streets).
   Same interface as livemap.js (window.WNTRLiveMap.attach). If WebGL is unavailable (or ?map=2d), this file does
   nothing and livemap.js loads the Leaflet 2D map instead. */
(function () {
  "use strict";
  function hasWebGL() {
    try { var c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; }
  }
  if (!window.maplibregl || /[?&]map=2d\b/.test(location.search) || !hasWebGL()) return;
  var M = window.maplibregl;
  var BASE = location.href.replace(/[#?].*$/, "").replace(/[^\/]*$/, "");   // works under a project subpath
  var REDUCE = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var PHONE = window.matchMedia && matchMedia("(max-width: 600px)").matches;
  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  var ESRI_ATTR = 'Imagery &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a>, Maxar, Earthstar Geographics, GIS User Community';
  var OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
  var COLORS = { red: "#ff2a2a", blue: "#2a7fff", yellow: "#ffd43b", context: "#39cde0" };
  var BASES = [["sat", "Satellite"], ["dark", "Dark"], ["street", "Streets"]];

  function esri(path, maxzoom, attr) { return { type: "raster", tiles: [ESRI + path + "/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: maxzoom, attribution: attr }; }
  function style(base) {
    var vis = function (b) { return { visibility: base === b ? "visible" : "none" }; };
    return {
      version: 8,
      projection: { type: "globe" },
      glyphs: BASE + "vendor/glyphs/{fontstack}/{range}.pbf",
      sky: { "sky-color": "#000719", "horizon-color": "#1b3b6f", "fog-color": "#0b1530", "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, 1, 7, 0] },
      sources: {
        sat: esri("World_Imagery", 19, ESRI_ATTR),
        labels: esri("Reference/World_Boundaries_and_Places", 19, "Labels &copy; Esri"),
        roads: esri("Reference/World_Transportation", 19, "Roads &copy; Esri"),
        street: esri("World_Street_Map", 19, "Tiles &copy; Esri, HERE, Garmin, " + OSM_ATTR),
        dark: esri("Canvas/World_Dark_Gray_Base", 16, "Tiles &copy; Esri, HERE, Garmin, " + OSM_ATTR),
        darklabels: esri("Canvas/World_Dark_Gray_Reference", 16, "Labels &copy; Esri"),
        rep: { type: "geojson", data: fc([]), cluster: true, clusterRadius: 38, clusterMaxZoom: 8,
               clusterProperties: { y: ["+", ["case", ["==", ["get", "kind"], "yellow"], 1, 0]], b: ["+", ["case", ["==", ["get", "kind"], "blue"], 1, 0]], r: ["+", ["case", ["==", ["get", "kind"], "red"], 1, 0]] } },
        ctx: { type: "geojson", data: fc([]) }
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": "#05070d" } },
        { id: "sat", type: "raster", source: "sat", layout: vis("sat"), paint: { "raster-fade-duration": 150 } },
        { id: "dark", type: "raster", source: "dark", layout: vis("dark"), paint: { "raster-fade-duration": 150 } },
        { id: "darklabels", type: "raster", source: "darklabels", layout: vis("dark") },
        { id: "street", type: "raster", source: "street", layout: vis("street"), paint: { "raster-fade-duration": 150 } },
        { id: "roads", type: "raster", source: "roads", minzoom: 10, layout: vis("sat") },
        { id: "labels", type: "raster", source: "labels", layout: vis("sat") },
        // OSINT context: hollow cyan rings (never clustered with sightings)
        { id: "ctx-o", type: "circle", source: "ctx", paint: { "circle-radius": 13, "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": 1, "circle-stroke-color": "rgba(57,205,224,.55)", "circle-pitch-alignment": "map" } },
        { id: "ctx-i", type: "circle", source: "ctx", paint: { "circle-radius": 7, "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": ["case", ["==", ["get", "id"], ""], 3.5, 2.4], "circle-stroke-color": COLORS.context, "circle-pitch-alignment": "map" } },
        // clusters: colour of the most frequent kind inside
        { id: "cl-glow", type: "circle", source: "rep", filter: ["has", "point_count"], paint: { "circle-radius": ["step", ["get", "point_count"], 26, 5, 32, 15, 40], "circle-color": clusterColor(), "circle-blur": 0.9, "circle-opacity": 0.55 } },
        { id: "cl", type: "circle", source: "rep", filter: ["has", "point_count"], paint: { "circle-radius": ["step", ["get", "point_count"], 15, 5, 18, 15, 23], "circle-color": clusterColor(), "circle-opacity": 0.9, "circle-stroke-width": 1.5, "circle-stroke-color": "rgba(255,255,255,.75)" } },
        { id: "cl-n", type: "symbol", source: "rep", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": ["Open Sans Semibold"], "text-size": 13, "text-allow-overlap": true },
          paint: { "text-color": ["case", [">=", ["get", "y"], ["max", ["get", "r"], ["get", "b"]]], "#111", "#fff"] } },
        // single reports: glow halo + core; size by supported report count
        { id: "pt-glow", type: "circle", source: "rep", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": ["*", 2.3, size()], "circle-color": ["get", "color"], "circle-blur": 1, "circle-opacity": 0.6 } },
        { id: "pt", type: "circle", source: "rep", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": size(), "circle-color": ["get", "color"], "circle-stroke-width": 1.5, "circle-stroke-color": "rgba(255,255,255,.6)" } },
        { id: "pt-sel", type: "circle", source: "rep", filter: ["==", ["get", "id"], "__none__"], paint: { "circle-radius": ["+", 6, size()], "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": 3, "circle-stroke-color": "#fff" } }
      ]
    };
  }
  function size() { return ["+", 6, ["*", 1.6, ["min", ["get", "count"], 6]]]; }
  function clusterColor() {
    return ["case", ["all", [">=", ["get", "y"], ["get", "r"]], [">=", ["get", "y"], ["get", "b"]]], COLORS.yellow,
                    [">=", ["get", "b"], ["get", "r"]], COLORS.blue, COLORS.red];
  }
  function fc(items) {
    return { type: "FeatureCollection", features: items.map(function (it) {
      return { type: "Feature", geometry: { type: "Point", coordinates: [it.lon, it.lat] }, properties: { id: it.id, kind: it.kind, color: it.color, count: it.count || 1 } };
    }) };
  }

  var host, map, ready = false, queued = null, items = [], byId = {}, onOpen = function () {}, lastSig = null, lastFitKey = "", popup = null;
  var base = "sat", spin = false, interacted = false, visibleOnScreen = true;
  try { base = localStorage.getItem("wntr-globe-base") || "sat"; } catch (e) { }
  if (!BASES.some(function (b) { return b[0] === base; })) base = "sat";

  function button(label, title, onClick, cls) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "gl-btn" + (cls ? " " + cls : ""); b.title = title; b.setAttribute("aria-label", title); b.textContent = label;
    b.addEventListener("click", function (e) { e.stopPropagation(); onClick(b); });
    return b;
  }
  function control(nodes, cls) {
    return { onAdd: function () { var d = document.createElement("div"); d.className = "maplibregl-ctrl gl-ctrl " + (cls || ""); nodes.forEach(function (n) { d.appendChild(n); }); return d; }, onRemove: function () { } };
  }

  function setBase(b) {
    base = b; try { localStorage.setItem("wntr-globe-base", b); } catch (e) { }
    ["sat", "dark", "street"].forEach(function (id) { map.setLayoutProperty(id, "visibility", id === b ? "visible" : "none"); });
    map.setLayoutProperty("darklabels", "visibility", b === "dark" ? "visible" : "none");
    ["roads", "labels"].forEach(function (id) { map.setLayoutProperty(id, "visibility", b === "sat" ? "visible" : "none"); });
    Array.prototype.forEach.call(host.querySelectorAll("[data-base]"), function (n) { n.setAttribute("aria-pressed", n.getAttribute("data-base") === b ? "true" : "false"); });
  }

  function create() {
    host = document.createElement("div");
    host.className = "live-map globe-map";
    host.setAttribute("role", "region");
    host.setAttribute("aria-label", "3D globe of 24-hour reports. Drag to rotate, scroll or pinch to zoom from the whole Earth to street level; markers open a summary. The location list below offers the same records.");
    map = new M.Map({
      container: host, style: style(base), center: [0, 20], zoom: PHONE ? 0.9 : 1.75, minZoom: 0, maxZoom: 18.5, maxPitch: 60,
      attributionControl: { compact: true }, fadeDuration: 0, pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      renderWorldCopies: false, dragRotate: true, touchPitch: false
    });
    map.addControl(new M.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new M.GlobeControl(), "top-right");
    map.addControl(new M.ScaleControl({ unit: "metric" }), "bottom-left");
    var reset = button("🌐", "Reset view: whole Earth", function () { resetView(); });
    var fit = button("⤢", "Zoom to all 24-hour markers", function () { stopSpin(); fitAll(); });
    var spinB = button("⟳", "Slow auto-rotate on/off", function () { spin = !spin; interacted = !spin; spinB.setAttribute("aria-pressed", spin ? "true" : "false"); if (spin) spinStep(); });
    spinB.setAttribute("aria-pressed", "false"); spinB.classList.add("gl-spin");
    map.addControl(control([reset, fit, spinB]), "top-left");
    var seg = BASES.map(function (b) { var n = button(b[1], "Base map: " + b[1], function () { setBase(b[0]); }, "gl-seg"); n.setAttribute("data-base", b[0]); n.setAttribute("aria-pressed", b[0] === base ? "true" : "false"); return n; });
    map.addControl(control(seg, "gl-bases"), "bottom-right");

    map.on("load", function () {
      ready = true;
      var at = host.querySelector(".maplibregl-ctrl-attrib"); if (at && PHONE) at.classList.remove("maplibregl-compact-show");
      ["pt", "cl", "ctx-i", "ctx-o"].forEach(function (id) {
        map.on("mouseenter", id, function () { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", id, function () { map.getCanvas().style.cursor = ""; });
      });
      map.on("click", "cl", function (e) {
        var f = e.features.filter(function (x) { return frontSide(x.geometry.coordinates); })[0]; if (!f) return;
        map.getSource("rep").getClusterExpansionZoom(f.properties.cluster_id).then(function (z) { go({ center: f.geometry.coordinates, zoom: Math.min(z + 0.5, 12) }); });
      });
      map.on("click", function (e) {
        var hit = map.queryRenderedFeatures([[e.point.x - 8, e.point.y - 8], [e.point.x + 8, e.point.y + 8]], { layers: ["pt", "ctx-i", "ctx-o"] });
        hit = hit.filter(function (f) { return frontSide(f.geometry.coordinates); });
        if (hit.length) showPopup(hit[0].properties.id);
      });
      if (queued) { var q = queued; queued = null; update(q); }
    });
    ["mousedown", "touchstart", "wheel"].forEach(function (ev) { host.addEventListener(ev, function (e) { if (e.target.closest && e.target.closest(".gl-spin")) return; stopSpin(); }, { passive: true }); });
    map.on("moveend", function () { if (spin) spinStep(); });
    if ("IntersectionObserver" in window) new IntersectionObserver(function (en) { visibleOnScreen = en[0].isIntersecting; if (visibleOnScreen && spin) spinStep(); }).observe(host);
    document.addEventListener("visibilitychange", function () { if (!document.hidden && spin) spinStep(); });
  }

  // On a globe, points on the far side still project onto the disc; keep only points facing the viewer.
  function frontSide(c) {
    var back = map.unproject(map.project(c));
    var d = Math.abs(((back.lng - c[0]) + 540) % 360 - 180) + Math.abs(back.lat - c[1]);
    return d < 0.5;
  }
  function go(opts) { if (REDUCE) map.jumpTo(opts); else map.easeTo(Object.assign({ duration: 900 }, opts)); }
  function stopSpin() { if (spin) { spin = false; var b = host.querySelector(".gl-spin"); if (b) b.setAttribute("aria-pressed", "false"); } interacted = true; }
  function spinStep() {
    if (!spin || REDUCE || document.hidden || !visibleOnScreen || map.getZoom() > 3.5 || map.isMoving()) return;
    var c = map.getCenter(); c.lng -= 6;
    map.easeTo({ center: c, duration: 2000, easing: function (n) { return n; } });
  }
  function meanLon(pts) {
    var x = 0, y = 0; pts.forEach(function (p) { x += Math.cos(p.lon * Math.PI / 180); y += Math.sin(p.lon * Math.PI / 180); });
    return pts.length ? Math.atan2(y, x) * 180 / Math.PI : 0;
  }
  function resetView() { stopSpin(); if (popup) popup.remove(); go({ center: [items.length ? meanLon(items) : 0, 20], zoom: PHONE ? 0.9 : 1.75, bearing: 0, pitch: 0 }); }
  function fitAll() {
    if (!items.length) { resetView(); return; }
    if (items.length === 1) { go({ center: [items[0].lon, items[0].lat], zoom: 5 }); return; }
    var lons = items.map(function (p) { return p.lon; }), lats = items.map(function (p) { return p.lat; });
    var spread = Math.max.apply(null, lons) - Math.min.apply(null, lons);
    if (spread > 150) { go({ center: [meanLon(items), Math.max(-50, Math.min(50, lats.reduce(function (a, b) { return a + b; }, 0) / lats.length))], zoom: PHONE ? 0.9 : 1.75, bearing: 0, pitch: 0 }); return; }
    var b = new M.LngLatBounds(); items.forEach(function (p) { b.extend([p.lon, p.lat]); });
    map.fitBounds(b, { padding: PHONE ? 40 : 70, maxZoom: 5, duration: REDUCE ? 0 : 900 });
  }
  function showPopup(id) {
    var it = byId[id]; if (!it) return;
    stopSpin();
    if (popup) popup.remove();
    var px = map.project([it.lon, it.lat]), cv = map.getCanvas();
    if (px.y > cv.clientHeight * 0.35 || px.y < 60 || px.x < 60 || px.x > cv.clientWidth - 60) map.easeTo({ center: [it.lon, it.lat], offset: [0, -cv.clientHeight * 0.22], duration: REDUCE ? 0 : 400 });
    popup = new M.Popup({ maxWidth: "300px", className: "lm-popup gl-popup", focusAfterOpen: true, offset: 14 }).setLngLat([it.lon, it.lat]).setHTML(it.popup).addTo(map);
    var el = popup.getElement();
    Array.prototype.forEach.call(el.querySelectorAll("[data-open]"), function (b) {
      b.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); popup.remove(); onOpen(b.getAttribute("data-open"), b.hasAttribute("data-sky")); });
    });
  }

  // items: [{id, lat, lon, kind: red|blue|yellow|context, color, count, title, popup}]
  function update(opts) {
    if (!ready) { queued = opts; return; }
    onOpen = opts.onOpen || onOpen;
    var sig = opts.items.map(function (it) { return it.id + ":" + it.kind + ":" + it.lat + ":" + it.lon; }).join(",");
    if (sig !== lastSig) {
      lastSig = sig; items = opts.items; byId = {};
      items.forEach(function (it) { byId[it.id] = it; });
      map.getSource("rep").setData(fc(items.filter(function (it) { return it.kind !== "context"; })));
      map.getSource("ctx").setData(fc(items.filter(function (it) { return it.kind === "context"; })));
    }
    map.setFilter("pt-sel", ["==", ["get", "id"], opts.selectedId || "__none__"]);
    map.setPaintProperty("ctx-i", "circle-stroke-width", ["case", ["==", ["get", "id"], opts.selectedId || "__none__"], 3.5, 2.4]);
    if (opts.fitKey !== lastFitKey) {
      var first = lastFitKey === "";
      lastFitKey = opts.fitKey;
      map.resize();
      if (opts.mode === "location" && opts.focus) {
        stopSpin();
        go({ center: [opts.focus.lon, opts.focus.lat], zoom: 9 });
        map.once("moveend", function () { showPopup(opts.focus.id); });
      } else if (first) {
        map.jumpTo({ center: [items.length ? meanLon(items) : 0, 20] });
        spin = !REDUCE && !interacted; var sb = host.querySelector(".gl-spin"); if (sb) sb.setAttribute("aria-pressed", spin ? "true" : "false");
        if (spin) setTimeout(spinStep, 1200);
      } else fitAll();
    }
  }

  window.WNTRLiveMap = {
    kind: "globe",
    attach: function (slot, opts) {
      if (!host) create();
      if (host.parentNode !== slot) slot.appendChild(host);
      setTimeout(function () { map.resize(); }, 0);
      update(opts);
    },
    map: function () { return map; },
    frontSide: function (c) { return frontSide(c); }
  };
})();
