// Full-screen mode for the team app.
//
// Browsers grant requestFullscreen() only from a user gesture, so it is
// called synchronously inside the login tap (before the network call) and,
// from then on, re-armed on the next tap whenever the app finds itself out
// of full screen while a team is logged in — Android's back gesture, an
// incoming call, or reopening the app with a saved login all drop out of it.
//
// iOS Safari has no Fullscreen API for pages at all. There the only
// full-screen route is "Add to Home Screen": the manifest + the
// apple-mobile-web-app meta tags in index.html make an installed copy launch
// full screen, and the login page shows a hint on iPhones.

import { getToken } from '../../shared/js/api.js';

const root = () => document.documentElement;

export function isFullscreenSupported() {
  const el = root();
  return !!(el.requestFullscreen || el.webkitRequestFullscreen);
}

export function isFullscreen() {
  return !!(document.fullscreenElement || document.webkitFullscreenElement);
}

/** Installed to the home screen (already full screen, nothing to request). */
export function isStandalone() {
  try {
    return (
      window.matchMedia('(display-mode: fullscreen)').matches ||
      window.matchMedia('(display-mode: standalone)').matches ||
      navigator.standalone === true
    );
  } catch (_) {
    return false;
  }
}

export function isIOS() {
  const ua = navigator.userAgent || '';
  return /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

let pending = null;

/** Must be called from inside a user-gesture handler. Never throws. */
export function enterFullscreen() {
  if (isFullscreen() || isStandalone() || !isFullscreenSupported()) return Promise.resolve(false);
  if (pending) return pending; // a tap fires pointerup and click; one request is enough
  const el = root();
  try {
    const p = el.requestFullscreen
      ? el.requestFullscreen({ navigationUI: 'hide' })
      : el.webkitRequestFullscreen();
    pending = Promise.resolve(p).then(() => true).catch(() => false).finally(() => { pending = null; });
    return pending;
  } catch (_) {
    return Promise.resolve(false);
  }
}

export function exitFullscreen() {
  if (!isFullscreen()) return Promise.resolve();
  try {
    const p = document.exitFullscreen ? document.exitFullscreen() : document.webkitExitFullscreen?.();
    return Promise.resolve(p).catch(() => {});
  } catch (_) {
    return Promise.resolve();
  }
}

let armed = false;
function onTap() {
  if (!getToken('team') || isFullscreen()) return;
  enterFullscreen();
}

/** Re-enter full screen on the next tap whenever a logged-in team is out of it. */
export function keepFullscreen() {
  if (armed) return;
  armed = true;
  // pointerup is the earliest event that still counts as an activating
  // gesture on every mobile browser; click covers keyboard activation.
  document.addEventListener('pointerup', onTap, { passive: true });
  document.addEventListener('click', onTap, { passive: true });
}
