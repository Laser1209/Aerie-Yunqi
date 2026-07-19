"use strict";
/* Theme switcher: loads CSS themes from styles/themes/ */
class ThemeSwitcher {
  constructor() {
    this.current = localStorage.getItem("aerie-theme") || "yita-pink";
    this.link = document.getElementById("theme-css");
  }

  init() {
    this.apply(this.current);
  }

  apply(themeName) {
    if (!this.link) {
      this.link = document.createElement("link");
      this.link.id = "theme-css";
      this.link.rel = "stylesheet";
      document.head.appendChild(this.link);
    }
    this.link.href = `styles/themes/${themeName}.css`;
    this.current = themeName;
    localStorage.setItem("aerie-theme", themeName);
  }

  getCurrent() {
    return this.current;
  }

  list() {
    return [
      { id: "yita-pink", name: "伊塔粉", color: "#FFB6C1" },
      { id: "midnight-purple", name: "深夜紫", color: "#6A0DAD" },
      { id: "sakura-white", name: "樱白", color: "#FFF0F5" },
      { id: "ocean-blue", name: "海蓝", color: "#1E90FF" },
      { id: "forest-green", name: "森绿", color: "#228B22" },
    ];
  }
}

// Singleton
window.themeSwitcher = new ThemeSwitcher();
