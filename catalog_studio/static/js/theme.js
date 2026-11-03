// static/js/theme.js
//
// Wires the navbar light/dark toggle. The theme itself is applied by the small
// inline script in base.html before first paint; this file only handles the
// switch, icons, cross-tab sync and the no-explicit-choice fallback.
(function () {
    "use strict";

    var STORAGE_KEY = "catalogStudioTheme";
    var root = document.documentElement;
    var query = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

    function stored() {
        try {
            return localStorage.getItem(STORAGE_KEY);
        } catch (error) {
            return null;
        }
    }

    function systemTheme() {
        return query && query.matches ? "dark" : "light";
    }

    function currentTheme() {
        return root.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
    }

    function paint(theme) {
        var dark = theme === "dark";
        root.setAttribute("data-bs-theme", theme);

        var button = document.getElementById("themeToggle");
        if (!button) return;
        button.setAttribute("aria-pressed", dark ? "true" : "false");
        button.title = dark ? "Switch to light mode" : "Switch to dark mode";

        var icon = button.querySelector(".theme-icon");
        var label = button.querySelector(".theme-label");
        if (icon) icon.textContent = dark ? "\u2600" : "\u263D";
        if (label) label.textContent = dark ? "Light" : "Dark";
    }

    function toggle() {
        var next = currentTheme() === "dark" ? "light" : "dark";
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (error) {
            // Private mode: the theme still applies for this page load.
        }
        paint(next);
    }

    function start() {
        paint(currentTheme());
        var button = document.getElementById("themeToggle");
        if (button) button.addEventListener("click", toggle);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }

    if (query && query.addEventListener) {
        query.addEventListener("change", function () {
            if (!stored()) paint(systemTheme());
        });
    }

    window.addEventListener("storage", function (event) {
        if (event.key !== STORAGE_KEY) return;
        paint(event.newValue === "dark" ? "dark" : "light");
    });
})();
