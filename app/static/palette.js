// Builds a whole app theme in shades of one colour (a person's favourite colour).
// Loaded in <head> so the right colours show before the page draws.
(function () {
  function hsl(hex) {
    var r = parseInt(hex.slice(1, 3), 16) / 255, g = parseInt(hex.slice(3, 5), 16) / 255, b = parseInt(hex.slice(5, 7), 16) / 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, h = 0, s = 0, d = mx - mn;
    if (d) {
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h *= 60;
    }
    return [h, s * 100, l * 100];
  }
  function rgb(h, s, l) {  // -> "r g b"
    s /= 100; l /= 100;
    var k = function (n) { return (n + h / 30) % 12; }, a = s * Math.min(l, 1 - l);
    var f = function (n) { return Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1)))); };
    return f(0) + " " + f(8) + " " + f(4);
  }
  function c(h, s, l) { return "rgb(" + rgb(h, s, l) + ")"; }
  function vars(hex, light) {
    var p = hsl(hex), h = p[0], s = p[1], grey = s < 12;
    var bs = grey ? 10 : Math.min(55, s * 0.6);  // background: tinted with the colour, never loud
    if (light) {
      var al = Math.min(Math.max(p[2], 30), 42);
      return { "--accent": c(h, s, al), "--accent-strong": c(h, s, al - 8), "--accent-soft": c(h, Math.min(s, 80), 93),
        "--on-accent": "#ffffff", "--g-needle": c(h, s, al), "--fav-rgb": rgb(h, s, al) };
    }
    var L = Math.min(Math.max(p[2], 55), 68), h2 = (h + 12) % 360;  // a lighter, close shade for second highlights
    var fav = rgb(h, s, L), fav2 = rgb(h2, Math.max(s, 55), 76);
    return {
      "--bg": c(h, bs, 5), "--card": c(h, bs, 10), "--inset": c(h, bs, 7.5), "--raised": c(h, bs, 13),
      "--text": c(h, 40, 97), "--muted": c(h, grey ? 8 : 28, 72), "--border": c(h, bs, 24),
      "--accent": "rgb(" + fav + ")", "--accent-strong": c(h, s, Math.min(L + 15, 85)), "--accent-soft": c(h, bs, 13),
      "--on-accent": c(h, 60, 8),
      "--neon-cyan": "rgb(" + fav2 + ")", "--series-1": "rgb(" + fav2 + ")",
      "--g-face-1": c(h, bs, 12), "--g-face-2": c(h, bs, 3), "--g-bezel": c(h, bs, 24),
      "--g-needle": "rgb(" + fav + ")", "--g-glow": "rgb(" + fav2 + ")",
      "--fav-rgb": fav, "--fav2-rgb": fav2, "--fav2-light": c(h2, 90, 88), "--fav-glow-bg": c(h, bs, 15),
      "--shadow": "0 0 0 1px rgb(" + fav2 + " / .08), 0 0 18px rgb(" + fav2 + " / .07), 0 10px 28px rgba(0, 0, 0, .55)"
    };
  }
  var KEYS = Object.keys(vars("#3d7bff", false));
  window.favPalette = {
    vars: vars,
    bg: function (hex) { var p = hsl(hex); return c(p[0], p[1] < 12 ? 10 : Math.min(55, p[1] * 0.6), 5); },
    apply: function (hex) {  // null removes it
      var st = document.documentElement.style;
      KEYS.forEach(function (k) { st.removeProperty(k); });
      if (!hex) return;
      var v = vars(hex, document.documentElement.getAttribute("data-theme") === "light");
      Object.keys(v).forEach(function (k) { st.setProperty(k, v[k]); });
    }
  };
  try {
    var sc = localStorage.getItem("scheme"), fc = localStorage.getItem("favColor");
    if (sc && sc !== "orange") document.documentElement.setAttribute("data-scheme", sc);
    if (sc === "custom" && fc) window.favPalette.apply(fc);
  } catch (e) {}
})();
