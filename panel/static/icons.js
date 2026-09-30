"use strict";
/*
 * ICON THEME. Every icon in the panel follows the style of the tag icons:
 *   - one 24x24 grid, outline only (no fills), 2px stroke with round caps and joins
 *   - drawn with currentColor, so an icon takes the color of the text next to it
 *   - no colors, sizes or stroke settings inside an individual icon: the shared wrapper below owns them
 *   - decorative (aria-hidden): the button or label next to it carries the accessible name
 * To add an icon: add its shapes to ICON_SHAPES (simple paths, circles, rects), then use iconSvg("name").
 * A feature's brand tint is applied with CSS (see .ico-youtube in style.css), never inside the icon.
 * tests/panel/test_icon_theme.py fails if an icon breaks these rules.
 */
const ICON_SHAPES = {
  local: '<path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/>', // shield with a check
  network: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>', // globe
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 11v6M14 11v6"/>',
  youtube: '<rect x="2" y="5" width="20" height="14" rx="4"/><path d="M10 9l5 3-5 3z"/>', // rounded screen with a play triangle
};

function iconSvg(name, size = 16) {
  const shapes = ICON_SHAPES[name];
  if (!shapes) return "";
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes}</svg>`;
}
