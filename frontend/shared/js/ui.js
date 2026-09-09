export function toast(message, opts = {}) {
  const el = document.createElement('div');
  el.className = `toast${opts.error ? ' error' : ''}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), opts.duration || 3200);
}

/** Format seconds remaining as HH:MM:SS (theme-guide "digital clock" face). */
export function formatCountdown(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

import { api } from './api.js';

/**
 * Drive a countdown element from an ISO deadline string.
 * Uses api.getServerNow() so that all devices in a room tick down synchronously
 * even if their individual device clocks are slightly off.
 * @returns {() => void} stop function
 */
export function startCountdown(deadlineIso, onTick, onExpire) {
  let stopped = false;
  let timerId = null;
  const deadline = new Date(deadlineIso).getTime();

  function tick() {
    if (stopped) return;
    const now = typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now();
    const remainingMs = deadline - now;
    if (remainingMs <= 0) {
      onTick(0);
      if (onExpire) onExpire();
      return;
    }
    // Round to 2 decimal places for consistency to avoid floating-point precision issues
    onTick(Math.round(remainingMs / 10) / 100);
    timerId = setTimeout(tick, 50);  // Reduced from 200ms to 50ms for smoother countdown display without visual skips
  }

  tick();
  return () => {
    stopped = true;
    if (timerId) clearTimeout(timerId);
  };
}

export function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function friendlyError(err, translateFn) {
  const jp = translateFn ? translateFn(err.detail) : null;
  return jp ? `${jp} / ${err.message}` : err.message;
}

export function enterFullscreen() {
  try {
    const doc = document;
    const elem = doc.documentElement;
    const isFullscreen = doc.fullscreenElement || doc.webkitFullscreenElement || doc.mozFullScreenElement || doc.msFullscreenElement;
    if (!isFullscreen) {
      if (elem.requestFullscreen) {
        elem.requestFullscreen().catch(() => {});
      } else if (elem.webkitRequestFullscreen) {
        elem.webkitRequestFullscreen();
      } else if (elem.mozRequestFullScreen) {
        elem.mozRequestFullScreen();
      } else if (elem.msRequestFullscreen) {
        elem.msRequestFullscreen();
      }
    }
  } catch (_) {}
}

