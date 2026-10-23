/* Haus-KI: Hell / Dunkel. Wird im <head> geladen, damit kein falsches Design aufblitzt. */
(function () {
  "use strict";
  var KEY = "hauski-theme";
  function read() { try { return localStorage.getItem(KEY) === "dark" ? "dark" : "light"; } catch (e) { return "light"; } }
  var theme = read();
  var listeners = [];
  function apply() {
    document.documentElement.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#161616" : "#ffffff");
  }
  apply();
  window.addEventListener("storage", function (e) { if (e.key === KEY) { theme = read(); apply(); listeners.forEach(function (f) { f(theme); }); } });
  window.HKTheme = {
    get: function () { return theme; },
    set: function (t) {
      theme = t === "dark" ? "dark" : "light";
      try { localStorage.setItem(KEY, theme); } catch (e) { /* ohne Speicher gilt die Wahl bis zum Neuladen */ }
      apply();
      listeners.forEach(function (f) { f(theme); });
    },
    onChange: function (f) { listeners.push(f); },
  };
})();
