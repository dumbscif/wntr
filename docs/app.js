/* UFO Sighting Archive: WNTR - static front end. Loads data/events.json (relative path). */
(function () {
  "use strict";
  var DATA = null, map = null, layer = null, archivePage = 1, PAGE = 50;
  var COLORS = { red: "#ff4d5e", blue: "#4da3ff", yellow: "#ffd23f", cyan: "#3ff0ff" };
  var LABEL = { red: "Civilian / unknown", blue: "Alleged testing", yellow: "Official confirmation cited", cyan: "OSINT / context" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : null; }
  function toDate(s) { if (!s || !/^\d{4}-\d\d-\d\dT/.test(s)) return null; var d = new Date(s); return isNaN(d) ? null : d; }
  function fmtIn(d, tz) {
    try {
      return new Intl.DateTimeFormat("en-US", { timeZone: tz, month: "short", day: "numeric", year: "numeric",
        hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(d);
    } catch (e) { return null; }
  }
  // America/Denver first, local time in parentheses when the place's time zone is known
  function fmtTime(iso, tz) {
    var d = toDate(iso); if (!d) return iso ? esc(iso) : "";
    var den = fmtIn(d, "America/Denver");
    if (tz && tz !== "America/Denver") { var loc = fmtIn(d, tz); if (loc) return esc(den + " (" + loc + " local)"); }
    return esc(den);
  }
  function sweptTime(r) { var d = toDate(r.sweptAt); return d ? d.getTime() : 0; }

  function eventLine(r) {
    if (r.origin === "seed") {
      var parts = [];
      if (r.eventTimeDenver) parts.push("Sighting: " + esc(r.eventTimeDenver) + (r.eventTimeLocal ? " (" + esc(r.eventTimeLocal) + " local)" : ""));
      else if (r.eventDate) parts.push("Date: " + esc(r.eventDate));
      if (r.publishedText) parts.push("Published: " + esc(r.publishedText));
      return parts.join(" · ");
    }
    if (r.eventAt) return "Sighting (witness-reported): " + fmtTime(r.eventAt, r.tz);
    if (r.publishedAt) return "Published: " + fmtTime(r.publishedAt, r.tz) + " <span class='badge'>sighting time not parsed</span>";
    return "";
  }

  function sourcesHtml(r) {
    var out = (r.sources || []).map(function (s) {
      var u = safeUrl(s.url), gone = s.availability && s.availability.status === "unavailable";
      var name = esc(s.name || "source") + (s.title && s.title !== r.title ? ": " + esc(s.title) : "");
      var link = u ? "<a href='" + esc(u) + "' target='_blank' rel='noopener nofollow'>" + name + "</a>" : name;
      return "<li>" + link + (s.role ? " <span class='badge'>" + esc(s.role) + "</span>" : "") +
        (gone ? " <span class='badge gone'>no longer available" + (s.availability.httpStatus ? " (HTTP " + esc(s.availability.httpStatus) + ")" : "") + "</span>" : "") +
        (s.published ? " <span class='meta'>" + (toDate(s.published) ? fmtTime(s.published) : esc(s.published)) + "</span>" : "") + "</li>";
    });
    return out.length ? "<ul class='sources'>" + out.join("") + "</ul>" : "<p class='meta'>No source link recorded.</p>";
  }

  function card(r) {
    var text = r.narrative || r.summary || "";
    var short = text.length > 420 ? text.slice(0, 420) + "…" : text;
    return "<article class='card' id='r-" + esc(r.id) + "'>" +
      "<h3><span class='dot d-" + esc(r.marker) + "'></span>" + esc(r.title) + "</h3>" +
      "<div class='meta'>" + (r.place ? esc(r.place) : "<b>No location found</b> (not mapped)") +
      (r.origin === "seed" ? " <span class='badge'>hand-reviewed</span>" : " <span class='badge'>automatic</span>") +
      " <span class='badge'>" + esc(LABEL[r.marker] || r.marker) + "</span></div>" +
      "<div class='meta'>" + eventLine(r) + "</div>" +
      "<div class='meta'>First swept: " + fmtTime(r.sweptAt) + "</div>" +
      (short ? "<p class='sum'>" + esc(short) + "</p>" : "") +
      "<details><summary>Details and sources (" + (r.sources || []).length + ")</summary>" +
      (text.length > 420 ? "<p>" + esc(text) + "</p>" : "") +
      (r.appearance ? "<p><b>Appearance:</b> " + esc(r.appearance) + "</p>" : "") +
      (r.evidence ? "<p><b>Evidence:</b> " + esc(r.evidence) + "</p>" : "") +
      (r.explanations && r.explanations.length ? "<p><b>Possible explanations noted:</b> " + esc(r.explanations.join("; ")) + "</p>" : "") +
      "<p class='meta'><b>Why this colour:</b> " + esc(r.markerBasis || "") + "</p>" +
      (r.precision ? "<p class='meta'><b>Location precision:</b> " + esc(r.precision) + "</p>" : "") +
      sourcesHtml(r) + "</details></article>";
  }

  function last24(reports) {
    var ref = toDate(DATA.meta.lastSweepAt) || new Date();
    var start = ref.getTime() - 24 * 3600 * 1000;
    return reports.filter(function (r) { return sweptTime(r) >= start; });
  }

  function renderMap() {
    var items = last24(DATA.reports).filter(function (r) { return typeof r.lat === "number" && typeof r.lon === "number"; });
    var counts = { red: 0, blue: 0, yellow: 0, cyan: 0 };
    items.forEach(function (r) { counts[r.marker] = (counts[r.marker] || 0) + 1; });
    document.getElementById("legend").innerHTML = ["red", "blue", "yellow", "cyan"].map(function (k) {
      return "<span><span class='dot d-" + k + "'></span>" + LABEL[k] + " (" + counts[k] + ")</span>";
    }).join("");
    if (!window.L) { document.getElementById("map").innerHTML = "<p class='note' style='padding:20px'>Map library failed to load.</p>"; return; }
    if (!map) {
      map = L.map("map", { worldCopyJump: true, minZoom: 2 }).setView([25, 0], 2);
      L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        attribution: "&copy; OpenStreetMap contributors &copy; CARTO", subdomains: "abcd", maxZoom: 18 }).addTo(map);
      layer = L.layerGroup().addTo(map);
    }
    layer.clearLayers();
    items.forEach(function (r) {
      var hollow = r.marker === "cyan";
      var m = L.circleMarker([r.lat, r.lon], { radius: 7, color: COLORS[r.marker] || "#fff", weight: hollow ? 2 : 1,
        fillColor: COLORS[r.marker] || "#fff", fillOpacity: hollow ? 0 : 0.9, className: "glow-" + r.marker });
      var src = (r.sources || [])[0], u = src && safeUrl(src.url);
      m.bindPopup("<b>" + esc(r.title) + "</b><br>" + esc(r.place || "") + "<br><span class='meta'>" + eventLine(r) + "</span>" +
        (u ? "<br><a href='" + esc(u) + "' target='_blank' rel='noopener nofollow'>Source: " + esc(src.name) + "</a>" : ""));
      m.addTo(layer);
    });
    document.getElementById("mapNote").innerHTML = items.length ?
      items.length + " mapped report(s) first swept in the 24 hours before the last sweep. Dots mark approximate town or region centres, not object positions. Everything stays in the Archive tab." :
      "No new mapped reports in the 24 hours before the last sweep. Everything ever swept is in the Archive tab.";
    document.getElementById("mapList").innerHTML = items.map(card).join("");
    setTimeout(function () { map.invalidateSize(); }, 50);
  }

  function renderLatest() {
    var items = last24(DATA.reports);
    var mapped = items.filter(function (r) { return r.lat != null; }), none = items.filter(function (r) { return r.lat == null; });
    document.getElementById("latestNote").textContent = items.length + " report(s): " + mapped.length + " with a location, " + none.length + " with no location found (listed after, never given made-up coordinates).";
    document.getElementById("latestList").innerHTML = mapped.map(card).join("") +
      (none.length ? "<h2>No location found</h2>" + none.map(card).join("") : "") ||
      "<p class='note'>Nothing new in the last 24 hours.</p>";
  }

  function filtered() {
    var q = document.getElementById("q").value.trim().toLowerCase();
    var fm = document.getElementById("fMarker").value, fl = document.getElementById("fLoc").value, fo = document.getElementById("fOrigin").value;
    return DATA.reports.filter(function (r) {
      if (fm && r.marker !== fm) return false;
      if (fl === "mapped" && r.lat == null) return false;
      if (fl === "none" && r.lat != null) return false;
      if (fo && r.origin !== fo) return false;
      if (!q) return true;
      var hay = [r.id, r.title, r.place, r.country, r.summary, r.narrative, r.appearance].concat((r.sources || []).map(function (s) { return (s.name || "") + " " + (s.title || ""); })).join(" ").toLowerCase();
      return q.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
    });
  }
  function renderArchive() {
    var list = filtered();
    document.getElementById("archiveCount").textContent = list.length + " of " + DATA.reports.length + " archived reports (newest first by first-swept time). Reports are never deleted.";
    document.getElementById("archiveList").innerHTML = list.slice(0, archivePage * PAGE).map(card).join("");
    document.getElementById("more").hidden = list.length <= archivePage * PAGE;
  }

  function renderFlap() {
    var f = DATA.flapWatch || {}, el = document.getElementById("flap");
    var byId = {}; DATA.reports.forEach(function (r) { byId[r.id] = r; });
    if (!f.confirmed) {
      el.innerHTML = "<div class='card'><h3>No confirmed flap</h3><p class='meta'>Checked " + fmtTime(f.checkedAt) + "</p><p>" + esc(f.rule || "") + "</p></div>";
      return;
    }
    el.innerHTML = "<div class='card'><h3>Rule-flagged cluster(s)</h3><p>" + esc(f.summary || "") + "</p><p class='note'>Flagged by the automatic rule below. A flag is a prompt to look closer, not confirmation that anything unusual happened. Checked " + fmtTime(f.checkedAt) + ".</p><p class='note'>" + esc(f.rule || "") + "</p></div>" + (f.clusters || []).map(function (c) {
      return "<div class='card'><h3>" + esc(c.places.slice(0, 4).join(" · ")) + "</h3><p class='meta'>" + c.reports + " reports from " + c.independentSources +
        " different source sites, " + fmtTime(c.from) + " to " + fmtTime(c.to) + "</p><ul class='sources'>" +
        c.ids.map(function (id) { var r = byId[id]; return r ? "<li><a href='#' data-goto='" + esc(id) + "'>" + esc(r.title) + "</a> <span class='meta'>" + esc(r.place || "") + "</span></li>" : ""; }).join("") +
        "</ul></div>";
    }).join("");
  }

  function renderAbout() {
    var m = DATA.meta || {}, ls = m.lastSweep || {};
    var repo = "";
    if (/\.github\.io$/.test(location.hostname)) {
      var user = location.hostname.split(".")[0], name = location.pathname.split("/")[1];
      repo = "https://github.com/" + user + "/" + (name || user + ".github.io");
    }
    var rows = (m.sourcesStatus || []).map(function (s) {
      return "<tr><td>" + esc(s.name) + "</td><td class='" + (s.ok ? "ok" : "bad") + "'>" + s.ok + "/" + s.requests + "</td><td>" + s.items + "</td><td>" + s.kept + "</td><td class='meta'>" + esc((s.errors || []).join("; ")) + "</td></tr>";
    }).join("");
    document.getElementById("about").innerHTML =
      "<div class='card'><h3>How it works</h3><p>A free GitHub Actions job runs a Python script about 4 AM and 4 PM MST. It reads public news and report feeds, keeps items that describe UFO/UAP sightings, finds the place name with an offline gazetteer, and saves them here. No AI and no paid services are used. Every entry keeps its source link; old links are re-checked and marked <span class='badge gone'>no longer available</span> when the source returns 404/410.</p>" +
      "<p><b>Marker colours</b> come from simple keyword rules, so read the sources: <span class='dot d-red'></span>red = civilian/unknown claim, <span class='dot d-blue'></span>blue = article alleges testing of secret/experimental craft, <span class='dot d-yellow'></span>yellow = article says officials, military or police confirmed or identified something (not that it was alien), <span class='dot d-cyan'></span>hollow cyan = OSINT/context news. The map shows only reports first swept in the last 24 hours; the archive keeps everything.</p>" +
      "<p>Times show America/Denver (MST/MDT) with local time in parentheses when the place's time zone is known.</p>" +
      (repo ? "<p>Code and data: <a href='" + esc(repo) + "' target='_blank' rel='noopener'>" + esc(repo) + "</a></p>" : "") + "</div>" +
      "<div class='card'><h3>Last sweep</h3><p class='meta'>" + fmtTime(m.lastSweepAt) + " · sweep #" + esc(m.sweepCount || 0) + "</p><p>Read " + esc(ls.rawItems || 0) + " feed items, added " + esc(ls.added || 0) +
      " new reports, attached " + esc(ls.mergedAsExtraSource || 0) + " as extra sources on existing reports, set aside " + esc(ls.droppedNotRelevant || 0) + " as not about a sighting, and re-checked " + esc(ls.linksChecked || 0) + " old links (" + esc(ls.linksNewlyUnavailable || 0) + " newly unavailable).</p>" +
      "<table><tr><th>Source</th><th>Requests OK</th><th>Items read</th><th>New reports kept</th><th>Errors</th></tr>" + rows + "</table></div>" +
      "<div class='card'><h3>Limits</h3><p>Automatic keyword rules make mistakes: some items are off-topic and some places are wrong or only approximate (a state or region centre). Nothing here is verified. Some sites block automated reading (for example NUFORC), so they are not included. Reports from the hand-reviewed November 2026 archive are marked “hand-reviewed”.</p></div>";
  }

  function showTab(name) {
    document.querySelectorAll(".tabs button").forEach(function (b) { b.classList.toggle("active", b.dataset.tab === name); });
    document.querySelectorAll(".tab").forEach(function (s) { s.classList.toggle("active", s.id === "tab-" + name); });
    if (name === "map" && map) setTimeout(function () { map.invalidateSize(); }, 50);
    if (history.replaceState) history.replaceState(null, "", "#" + name);
  }

  function init() {
    document.querySelectorAll(".tabs button").forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });
    ["q", "fMarker", "fLoc", "fOrigin"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", function () { archivePage = 1; renderArchive(); });
    });
    document.getElementById("more").addEventListener("click", function () { archivePage++; renderArchive(); });
    document.addEventListener("click", function (e) {
      var g = e.target.closest && e.target.closest("[data-goto]");
      if (g) { e.preventDefault(); document.getElementById("q").value = g.dataset.goto; archivePage = 1; renderArchive(); showTab("archive"); }
    });
    fetch("data/events.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (d) {
      DATA = d; DATA.reports = (d.reports || []).slice().sort(function (a, b) { return sweptTime(b) - sweptTime(a); });
      document.getElementById("lastSweep").innerHTML = "Last sweep: " + fmtTime(d.meta && d.meta.lastSweepAt) + ".";
      var tab = (location.hash || "#map").slice(1);
      showTab(["map", "latest", "archive", "flap", "about"].indexOf(tab) >= 0 ? tab : "map");
      [renderLatest, renderArchive, renderFlap, renderAbout, renderMap].forEach(function (fn) {
        try { fn(); } catch (err) { if (window.console) console.error(fn.name, err); }
      });
    }).catch(function (e) {
      document.getElementById("lastSweep").textContent = "Could not load data/events.json (" + e + ").";
    });
  }
  document.addEventListener("DOMContentLoaded", init);
})();
