/* Small page-view counter for the public GitHub and GitLab sites.
   Uses Count API (https://countapi.mileshilliard.com): no signup, no key, CORS-enabled.
   Each platform has its own counter; a combined total is shown when the other is available.
   Increments once per production page load. Hidden if the API is down. No IP or org logging. */
(function () {
  "use strict";
  var el = document.getElementById("page-views");
  if (!el) return;

  var BASE = "https://countapi.mileshilliard.com/api/v1";
  var KEYS = {
    github: "wntr-project-starfire-github-pageviews",
    gitlab: "wntr-project-starfire-gitlab-pageviews"
  };
  var host = (location && location.hostname) || "";
  var platform = /(?:^|\.)github\.io$/i.test(host) ? "github"
    : /(?:^|\.)gitlab\.io$/i.test(host) ? "gitlab"
    : "";
  var myKey = platform ? KEYS[platform] : "";
  var otherKey = platform === "github" ? KEYS.gitlab : platform === "gitlab" ? KEYS.github : "";

  function parseValue(data) {
    var n = Number(data && data.value);
    return isFinite(n) ? n : null;
  }

  function request(path, signal) {
    return fetch(BASE + path, { signal: signal, cache: "no-store" }).then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    });
  }

  function hit(key, signal) {
    return request("/hit/" + encodeURIComponent(key), signal).then(parseValue);
  }

  function get(key, signal) {
    return request("/get/" + encodeURIComponent(key), signal).then(parseValue);
  }

  function fmt(n) {
    return n.toLocaleString("en-US");
  }

  // Local previews (localhost, file://, etc.) must not inflate the live counts.
  var isLive = !!myKey;
  if (!isLive) return;

  var ctrl = new AbortController();
  var timer = setTimeout(function () { ctrl.abort(); }, 5000);

  var mineP = hit(myKey, ctrl.signal);
  var otherP = otherKey
    ? get(otherKey, ctrl.signal).catch(function () { return null; })
    : Promise.resolve(null);

  mineP.then(function (mine) {
    if (mine == null) return;
    var text = "Page views: " + fmt(mine);
    return otherP.then(function (other) {
      if (other != null) text += " · " + fmt(mine + other) + " total";
      el.textContent = text;
      el.hidden = false;
    });
  }).catch(function () {
    /* API down or blocked: leave the counter hidden. */
  }).then(function () {
    clearTimeout(timer);
  });
})();
