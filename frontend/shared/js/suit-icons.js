// Simple filled suit glyphs as inline SVG path data (24x24 viewBox).
// Kept as flat solid shapes per THEME_GUIDE.md — no skeuomorphic playing
// cards except on the dedicated card-back screen.

const PATHS = {
  SPADE: 'M12 2C9 6 4 9.5 4 14a4 4 0 0 0 7 2.6c-.3 2.2-1.2 3.7-2.6 4.9a.6.6 0 0 0 .4 1h6.4a.6.6 0 0 0 .4-1c-1.4-1.2-2.3-2.7-2.6-4.9A4 4 0 0 0 20 14c0-4.5-5-8-8-12z',
  CLUB: 'M12 2a3.2 3.2 0 0 0-3.2 3.2c0 .5.1 1 .3 1.4A3.4 3.4 0 1 0 8.6 13c.9 0 1.7-.3 2.4-.9-.5 2.7-1.6 4.6-3.2 6.1a.6.6 0 0 0 .4 1h8a.6.6 0 0 0 .4-1c-1.6-1.5-2.7-3.4-3.2-6.1.7.6 1.5.9 2.4.9A3.4 3.4 0 1 0 14.9 6.6c.2-.4.3-.9.3-1.4A3.2 3.2 0 0 0 12 2z',
  DIAMOND: 'M12 2c2.5 4 5.5 7 8 10-2.5 3-5.5 6-8 10-2.5-4-5.5-7-8-10 2.5-3 5.5-6 8-10z',
  HEART: 'M12 21s-7.5-4.6-10.2-9.3C.3 9 1.4 5.4 4.7 4.4c2-.6 4 .2 5.3 2 .5.7 1 1.6 2 1.6s1.5-.9 2-1.6c1.3-1.8 3.3-2.6 5.3-2 3.3 1 4.4 4.6 2.9 7.3C19.5 16.4 12 21 12 21z',
};

/**
 * @param {'SPADE'|'HEART'|'DIAMOND'|'CLUB'} code
 * @param {object} opts { size }
 */
export function suitIconSVG(code, opts = {}) {
  const size = opts.size || 24;
  const color = code === 'HEART' || code === 'DIAMOND' ? 'red' : 'black';
  const path = PATHS[code] || PATHS.SPADE;
  return `<svg class="suit-icon ${color}" viewBox="0 0 24 24" width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg"><path d="${path}"/></svg>`;
}

export const SUIT_CODES = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'];
