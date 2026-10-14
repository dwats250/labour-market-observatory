(function () {
  "use strict";
  var doc = document.documentElement;
  doc.classList.add("js");

  // ---- geography selector (URL hash keeps a bookmarkable choice)
  var radios = Array.prototype.slice.call(document.querySelectorAll('input[name="geo"]'));
  var sections = Array.prototype.slice.call(document.querySelectorAll("section.geo"));
  var keys = sections.map(function (s) { return s.getAttribute("data-geo"); });
  var fallback = (radios.filter(function (r) { return r.defaultChecked; })[0] || radios[0] || {}).value || keys[0];

  function show(key) {
    if (keys.indexOf(key) < 0) key = fallback;
    sections.forEach(function (s) { s.classList.toggle("active", s.getAttribute("data-geo") === key); });
    radios.forEach(function (r) { r.checked = r.value === key; });
  }
  radios.forEach(function (r) {
    r.addEventListener("change", function () {
      show(r.value);
      try { history.replaceState(null, "", "#" + r.value); } catch (e) { /* file:// or sandboxed */ }
    });
  });
  show((location.hash || "").replace("#", "") || fallback);
  window.addEventListener("hashchange", function () { show(location.hash.replace("#", "")); });

  // ---- overdue warning, computed in the viewer's browser so it works without a new deployment
  var days = Number(document.body.getAttribute("data-stale-days")) || 14;
  var late = [];
  Array.prototype.forEach.call(document.querySelectorAll("[data-last-success]"), function (li) {
    var ts = li.getAttribute("data-last-success");
    var t = Date.parse(ts);
    if (!ts || isNaN(t) || Date.now() - t > days * 864e5) late.push(li.getAttribute("data-name"));
  });
  if (late.length) {
    var el = document.getElementById("overdue");
    el.textContent = "Collection check overdue: no successful check in the last " + days +
      " days for " + late.join(" and ") + ". Values below may be out of date.";
    el.hidden = false;
  }

  // ---- print: expand disclosures for the selected geography, restore afterwards
  var opened = [];
  window.addEventListener("beforeprint", function () {
    Array.prototype.forEach.call(
      document.querySelectorAll("section.geo.active details, section.sources details"),
      function (d) { if (!d.open) { d.open = true; opened.push(d); } });
  });
  window.addEventListener("afterprint", function () {
    opened.forEach(function (d) { d.open = false; });
    opened = [];
  });
  var btn = document.getElementById("print");
  if (btn) btn.addEventListener("click", function () { window.print(); });
})();
