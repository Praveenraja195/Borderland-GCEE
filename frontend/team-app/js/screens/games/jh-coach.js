// Jack of Hearts practice-round walkthrough.
//
// During a demo the board gets a pointing hand that "taps" each section in
// turn with a caption: the OTHER TEAM CARDS tray, a card inside it, then the
// choose button. Every step completes the moment the player actually does
// the action (tray opens / a card flips / a card is chosen), or on "Next".
// The overlay never blocks the board: it is pointer-events:none except for
// its own two buttons, and it re-measures its target a few times a second
// because the board re-renders on every interaction.

const OVERLAY_ID = 'jh-coach';
const SEEN_KEY = (attempt) => `bl_jh_coach_seen_${attempt || 1}`;
const MEASURE_MS = 200;

const STEPS = [
  {
    target: () => document.getElementById('tray-toggle'),
    done: () => document.getElementById('tray-panel')?.classList.contains('open'),
    en: 'Tap here to view the other teams’ cards',
    jp: 'ここをタップして他チームのカードを見る',
  },
  {
    target: () => document.querySelector('#tray-grid .jh-flip-card'),
    done: () => !!document.querySelector('#tray-grid .jh-flip-card.flipped'),
    en: 'Tap a card to flip it and see that team’s card',
    jp: 'カードをタップしてめくる',
    optional: true, // a practice round with no other teams has no cards to flip
  },
  {
    target: () => document.getElementById('btn-confirm'),
    done: () => document.getElementById('btn-confirm')?.classList.contains('is-selected'),
    en: 'Browse with ❮ ❯, then tap here to choose your card',
    jp: '❮ ❯ で選び、ここをタップして決定',
  },
];

let active = null; // { stop }

export function stopJHCoach() {
  if (active) active.stop();
  active = null;
}

/**
 * Start the walkthrough for a practice round. Returns a stop() function.
 * No-op if this attempt's walkthrough was already completed or skipped.
 */
export function startJHCoach(container, ctx) {
  stopJHCoach();
  try {
    if (sessionStorage.getItem(SEEN_KEY(ctx.demoAttempt))) return () => {};
  } catch (_) {}

  const overlay = document.createElement('div');
  overlay.id = OVERLAY_ID;
  overlay.className = 'jh-coach';
  overlay.innerHTML = `
    <div class="jh-coach-spot" hidden></div>
    <div class="jh-coach-hand" hidden><span class="jh-coach-ripple"></span></div>
    <div class="jh-coach-bubble" hidden>
      <div class="jh-coach-step"></div>
      <div class="jh-coach-en"></div>
      <div class="jh-coach-jp"></div>
      <div class="jh-coach-actions">
        <button type="button" class="jh-coach-skip">Skip / スキップ</button>
        <button type="button" class="jh-coach-next">Next ›</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const spot = overlay.querySelector('.jh-coach-spot');
  const hand = overlay.querySelector('.jh-coach-hand');
  const bubble = overlay.querySelector('.jh-coach-bubble');
  const stepEl = overlay.querySelector('.jh-coach-step');
  const enEl = overlay.querySelector('.jh-coach-en');
  const jpEl = overlay.querySelector('.jh-coach-jp');

  let index = -1;
  let scrolledFor = -1;
  let timer = null;
  let finishing = false;
  let stopped = false;

  function markSeen() {
    try { sessionStorage.setItem(SEEN_KEY(ctx.demoAttempt), '1'); } catch (_) {}
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    if (timer) clearInterval(timer);
    window.removeEventListener('resize', measure);
    window.removeEventListener('scroll', measure, true);
    overlay.remove();
  }

  function finish() {
    if (finishing) return;
    finishing = true;
    markSeen();
    spot.hidden = true;
    hand.hidden = true;
    stepEl.textContent = 'PRACTICE';
    enEl.textContent = 'You’re ready — play the round!';
    jpEl.textContent = '準備完了 — ラウンドをプレイ！';
    overlay.querySelector('.jh-coach-actions').hidden = true;
    bubble.hidden = false;
    bubble.classList.add('done');
    placeBubbleCentered();
    setTimeout(stop, 2200);
  }

  function next() {
    index += 1;
    scrolledFor = -1;
    // Skip steps whose target isn't on this board (e.g. no other teams).
    while (index < STEPS.length && STEPS[index].optional && !STEPS[index].target()) index += 1;
    if (index >= STEPS.length) { finish(); return; }
    const step = STEPS[index];
    stepEl.textContent = `STEP ${index + 1} / ${STEPS.length}`;
    enEl.textContent = step.en;
    jpEl.textContent = step.jp;
    measure();
  }

  function placeBubbleCentered() {
    bubble.style.left = '50%';
    bubble.style.top = '50%';
    bubble.style.transform = 'translate(-50%, -50%)';
  }

  function measure() {
    if (stopped || finishing) return;
    if (!container.isConnected) { stop(); return; }
    const step = STEPS[index];
    if (!step) return;
    if (step.done()) { next(); return; }

    const target = step.target();
    if (!target) {
      // Board mid-re-render (or the tray closed again): keep the caption,
      // hide the pointer until the target is back.
      spot.hidden = true;
      hand.hidden = true;
      bubble.hidden = false;
      placeBubbleCentered();
      return;
    }
    if (scrolledFor !== index) {
      scrolledFor = index;
      try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (_) {}
    }
    const r = target.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) { spot.hidden = true; hand.hidden = true; return; }

    const pad = 6;
    spot.hidden = false;
    spot.style.left = `${r.left - pad}px`;
    spot.style.top = `${r.top - pad}px`;
    spot.style.width = `${r.width + pad * 2}px`;
    spot.style.height = `${r.height + pad * 2}px`;

    // Hand fingertip lands a little right of centre so the target text stays readable.
    hand.hidden = false;
    hand.style.left = `${r.left + r.width * 0.62}px`;
    hand.style.top = `${r.top + r.height * 0.55}px`;

    // Bubble below the target, or above it when there is no room.
    bubble.hidden = false;
    bubble.style.transform = 'none';
    const bw = Math.min(window.innerWidth - 24, 340);
    const bh = bubble.offsetHeight || 120;
    let left = r.left + r.width / 2 - bw / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - bw - 12));
    let top = r.bottom + 46;
    if (top + bh > window.innerHeight - 12) top = r.top - bh - 18;
    if (top < 12) top = 12;
    bubble.style.width = `${bw}px`;
    bubble.style.left = `${left}px`;
    bubble.style.top = `${top}px`;
  }

  overlay.querySelector('.jh-coach-skip').addEventListener('click', () => { markSeen(); stop(); });
  overlay.querySelector('.jh-coach-next').addEventListener('click', next);
  window.addEventListener('resize', measure);
  window.addEventListener('scroll', measure, true);

  next();
  timer = setInterval(measure, MEASURE_MS);
  active = { stop };
  return stop;
}
