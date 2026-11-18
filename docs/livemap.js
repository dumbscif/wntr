/* WNTR live map: a real zoomable map (Leaflet + free, keyless tile servers) for the Map tab.
   Leaflet and Leaflet.markercluster are bundled in docs/vendor (no CDN, no API key, no sign-in).
   The map element is created once and re-attached after every page render, so zoom/pan survive. */
(function () {
  "use strict";
  if (!window.L) return; // app.js falls back to the built-in SVG outline map
  var L = window.L;
  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  var ESRI_ATTR = 'Imagery &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a>, Maxar, Earthstar Geographics, and the GIS User Community';
  var OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';

  function esriLayer(path, opts) { return L.tileLayer(ESRI + path + "/MapServer/tile/{z}/{y}/{x}", Object.assign({ maxZoom: 19, maxNativeZoom: 18, attribution: ESRI_ATTR }, opts || {})); }
  function makeBases() {
    var labels = function () { return esriLayer("Reference/World_Boundaries_and_Places", { attribution: "Labels &copy; Esri", pane: "labels" }); };
    return {
      "Satellite (Earth view)": L.layerGroup([esriLayer("World_Imagery"), labels()]),
      "Dark map": L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", { subdomains: "abcd", maxZoom: 19, attribution: OSM_ATTR + ' &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>' }),
      "Streets": esriLayer("World_Street_Map", { attribution: "Tiles &copy; Esri, HERE, Garmin, " + OSM_ATTR }),
      "Terrain": esriLayer("World_Topo_Map", { attribution: "Tiles &copy; Esri, HERE, Garmin, USGS, " + OSM_ATTR })
    };
  }

  var host = null, map = null, cluster = null, bases = null, lastFitKey = "", lastSig = null, onOpen = function () {}, markersById = {};

  function create() {
    host = document.createElement("div");
    host.className = "live-map";
    host.setAttribute("role", "region");
    host.setAttribute("aria-label", "Zoomable 24-hour report map. Drag to pan, scroll or pinch to zoom; markers open a summary with a link to the full record. The location list below offers the same records.");
    map = L.map(host, { worldCopyJump: true, minZoom: 1, zoomControl: true, scrollWheelZoom: true, zoomSnap: 0.5, wheelPxPerZoomLevel: 90, maxBounds: [[-85, -400], [85, 400]], maxBoundsViscosity: 0.6 });
    map.createPane("labels");
    map.getPane("labels").style.zIndex = 450;
    map.getPane("labels").style.pointerEvents = "none";
    bases = makeBases();
    var saved = null; try { saved = localStorage.getItem("wntr-base"); } catch (e) { }
    (bases[saved] || bases["Satellite (Earth view)"]).addTo(map);
    L.control.layers(bases, null, { position: "topright", collapsed: true }).addTo(map);
    map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>');
    L.control.scale({ position: "bottomleft", imperial: true, metric: true }).addTo(map);
    map.on("baselayerchange", function (e) { try { localStorage.setItem("wntr-base", e.name); } catch (err) { } host.classList.toggle("is-dark", e.name === "Dark map"); });
    host.classList.toggle("is-dark", saved === "Dark map");
    var Fit = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var b = L.DomUtil.create("button", "lm-fit");
        b.type = "button"; b.title = "Zoom to all 24-hour markers"; b.setAttribute("aria-label", b.title); b.textContent = "⤢";
        L.DomEvent.disableClickPropagation(b);
        L.DomEvent.on(b, "click", function () { fitAll(); });
        return b;
      }
    });
    map.addControl(new Fit());
    cluster = L.markerClusterGroup({
      maxClusterRadius: 34, spiderfyOnMaxZoom: true, showCoverageOnHover: false, zoomToBoundsOnClick: true, disableClusteringAtZoom: 11, spiderfyDistanceMultiplier: 1.6,
      iconCreateFunction: function (c) {
        var kids = c.getAllChildMarkers(), tally = { red: 0, blue: 0, yellow: 0, context: 0 };
        kids.forEach(function (m) { tally[m.options.wntrKind] = (tally[m.options.wntrKind] || 0) + 1; });
        var top = ["yellow", "blue", "red", "context"].filter(function (k) { return tally[k]; }).sort(function (a, b) { return tally[b] - tally[a]; })[0] || "red";
        var n = kids.length, size = n < 5 ? 34 : n < 15 ? 40 : 48;
        return L.divIcon({ className: "lm-cluster lm-" + top, iconSize: [size, size], html: '<span>' + n + "</span>" });
      }
    });
    cluster.addTo(map);
    map.on("popupopen", function (e) {
      var el = e.popup.getElement(); if (!el) return;
      Array.prototype.forEach.call(el.querySelectorAll("[data-open]"), function (b) {
        b.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); map.closePopup(); onOpen(b.getAttribute("data-open")); });
      });
    });
  }

  var currentPoints = [];
  function fitAll() {
    if (!map) return;
    if (!currentPoints.length) { map.setView([25, 0], 2); return; }
    if (currentPoints.length === 1) { map.setView(currentPoints[0], 5); return; }
    map.fitBounds(L.latLngBounds(currentPoints), { paddingTopLeft: [56, 48], paddingBottomRight: [48, 56], maxZoom: 5 });
  }

  function dotIcon(color, kind, px, selected) {
    var s = Math.round(px);
    return L.divIcon({ className: "lm-dot lm-" + kind + (selected ? " is-sel" : ""), iconSize: [s, s], html: '<span style="--c:' + color + '"></span>' });
  }
  function ringIcon(selected) {
    return L.divIcon({ className: "lm-ring" + (selected ? " is-sel" : ""), iconSize: [30, 30], html: '<span class="lm-ring-o"></span><span class="lm-ring-i"></span><span class="lm-hit"></span>' });
  }

  // items: [{id, lat, lon, kind: red|blue|yellow|context, color, count, title, popup}]
  function update(opts) {
    if (!map) create();
    onOpen = opts.onOpen || onOpen;
    var sig = opts.selectedId + "|" + opts.items.map(function (it) { return it.id + ":" + it.kind + ":" + it.lat + ":" + it.lon; }).join(",");
    if (sig === lastSig && opts.fitKey === lastFitKey) return;
    var rebuild = sig !== lastSig; lastSig = sig;
    if (rebuild) {
    cluster.clearLayers(); markersById = {};
    var layers = [];
    currentPoints = [];
    opts.items.forEach(function (it) {
      var sel = it.id === opts.selectedId, m;
      if (it.kind === "context") m = L.marker([it.lat, it.lon], { icon: ringIcon(sel), title: it.title, alt: it.title, zIndexOffset: -500, wntrKind: "context", keyboard: true, riseOnHover: false });
      else m = L.marker([it.lat, it.lon], { icon: dotIcon(it.color, it.kind, 14 + Math.min(it.count || 1, 6) * 3, sel), title: it.title, alt: it.title, zIndexOffset: sel ? 1000 : 0, wntrKind: it.kind, keyboard: true, riseOnHover: true });
      m.bindPopup(it.popup, { maxWidth: 300, minWidth: 220, autoPanPadding: [24, 24], className: "lm-popup" });
      markersById[it.id] = m; layers.push(m); currentPoints.push([it.lat, it.lon]);
    });
    cluster.addLayers(layers);
    }
    if (opts.fitKey !== lastFitKey) {
      lastFitKey = opts.fitKey;
      setTimeout(function () {
        map.invalidateSize();
        if (opts.mode === "location" && opts.focus) {
          var fm = markersById[opts.focus.id];
          map.setView([opts.focus.lat, opts.focus.lon], 10, { animate: false });
          if (fm) cluster.zoomToShowLayer(fm, function () { fm.openPopup(); });
        } else fitAll();
      }, 0);
    }
  }

  window.WNTRLiveMap = {
    attach: function (slot, opts) {
      if (!host) create();
      if (host.parentNode !== slot) { slot.appendChild(host); }
      setTimeout(function () { map.invalidateSize(); }, 0);
      update(opts);
    },
    map: function () { return map; }
  };
})();
