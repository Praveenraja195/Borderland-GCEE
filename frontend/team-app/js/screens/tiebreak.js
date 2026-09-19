import { api, getServerNow } from '../../../shared/js/api.js';
import { suitIconSVG } from '../../../shared/js/suit-icons.js';

// Death Card tiebreaker screen. Shown (instead of the VISA / laser) while a
// team's room_results row is tiebreak_pending. Polls /tiebreak/me every
// second; the server deals rounds and resolves them, this only renders and
// sends the team's pick. When the tiebreak finishes, the normal outcome
// check in home.js takes over (laser or VISA) and removes this overlay.

const OVERLAY_ID = 'tiebreak-overlay';
const POLL_MS = 1000;
const SUIT_SEQ = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'];

let pollTimer = null;
let state = null;
let lastRevealKey = null;   // `${round_number}` of the last reveal we animated
let outcomeRevealAt = null; // when the reveal that decided MY fate was first drawn
let picking = false;
let pickError = '';

function safeVibrate(pattern) {
  try { if (navigator.vibrate) navigator.vibrate(pattern); } catch (_) {}
}

/** ms since the reveal that decided this team was drawn, or null if it hasn't been. */
export function tiebreakRevealAge() {
  return outcomeRevealAt === null ? null : Date.now() - outcomeRevealAt;
}

export function isTiebreakScreenOpen() {
  return !!document.getElementById(OVERLAY_ID);
}

export function removeTiebreakScreen() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  state = null;
  lastRevealKey = null;
  outcomeRevealAt = null;
  const el = document.getElementById(OVERLAY_ID);
  if (el) el.remove();
}

export function showTiebreakScreen() {
  if (document.getElementById(OVERLAY_ID)) return;
  const overlay = document.createElement('div');
  overlay.id = OVERLAY_ID;
  overlay.className = 'tb-overlay';
  overlay.innerHTML = `<div class="tb-frame"><div class="spinner" style="margin:60px auto;"></div></div>`;
  document.body.appendChild(overlay);

  overlay.addEventListener('click', async (e) => {
    const card = e.target.closest('[data-card]');
    if (!card || card.classList.contains('taken') || card.classList.contains('mine') || card.classList.contains('revealed')) return;
    await pick(Number(card.dataset.card));
  });

  refresh();
  pollTimer = setInterval(refresh, POLL_MS);
}

async function refresh() {
  try {
    const next = await api.team.tiebreakState();
    if (next === null) {
      // Not in a tiebreak any more — home.js decides what to show next.
      state = null;
      render();
      return;
    }
    state = next;
    render();
  } catch (_) {
    // keep the last state on screen
  }
}

async function pick(cardIndex) {
  if (picking || !state || state.my_status !== 'ALIVE') return;
  const rnd = state.current_round;
  if (!rnd || rnd.is_resolved) return;
  picking = true;
  pickError = '';
  render();
  try {
    state = await api.team.tiebreakPick(cardIndex);
    safeVibrate([40]);
  } catch (err) {
    pickError = err?.message || 'Could not take that card';
    safeVibrate([20, 40, 20]);
    try { state = await api.team.tiebreakState(); } catch (_) {}
  } finally {
    picking = false;
    render();
  }
}

function secondsLeft(iso) {
  const ms = new Date(iso).getTime() - getServerNow();
  return Math.max(0, Math.ceil(ms / 1000));
}

function render() {
  const overlay = document.getElementById(OVERLAY_ID);
  if (!overlay) return;
  const frame = overlay.querySelector('.tb-frame');
  if (!state) {
    frame.innerHTML = `
      <div class="tb-head">
        <div class="tb-kicker">TIEBREAKER · タイブレーク</div>
        <div class="tb-title">DEATH CARD</div>
      </div>
      <p class="tb-note">Waiting for the game master…</p>`;
    return;
  }

  const me = state.my_status;
  const alive = state.participants.filter(p => p.status === 'ALIVE');
  const rnd = state.current_round;
  const completed = state.status === 'COMPLETED';
  const iWon = completed && me === 'WINNER';
  const iLost = me === 'ELIMINATED';
  // Eliminated teams leave the tiebreak before it ends; either way this is the
  // moment home.js should let sit on screen before the laser / VISA.
  if ((completed || iLost) && outcomeRevealAt === null) outcomeRevealAt = Date.now();

  const rosterHtml = state.participants.map(p => {
    const cls = p.status === 'ALIVE' ? 'alive' : p.status === 'WINNER' ? 'winner' : 'out';
    const mine = p.team_code === state.my_team_code ? 'me' : '';
    return `<span class="tb-chip ${cls} ${mine}">${p.suit_code ? suitIconSVG(p.suit_code, { size: 12 }) : ''}${p.team_code}${p.status === 'ELIMINATED' ? ` · out R${p.eliminated_in_round}` : ''}</span>`;
  }).join('');

  // The decisive banner sits above the last round's cards, so the Joker flip
  // that decided it stays visible.
  const finalBanner = (completed || iLost) ? `
      <div class="tb-final ${iWon ? 'won' : 'lost'}">
        <div class="tb-final-title">${iWon ? 'YOU SURVIVED' : iLost ? 'ELIMINATED' : 'TIEBREAK OVER'}</div>
        <div class="tb-final-sub">${iWon ? 'Your result is on its way…' : iLost ? 'You drew the Joker.' : 'Through: ' + state.winner_team_codes.join(', ')}</div>
      </div>` : '';

  let stage = '';
  if (state.status === 'PENDING' || !rnd) {
    stage = `
      <div class="tb-wait">
        <div class="tb-wait-title">STAND BY</div>
        <div class="tb-note">${alive.length} teams tied at <strong>${state.tie_total.toFixed(1)} pts</strong> for ${state.slots} place${state.slots === 1 ? '' : 's'}.<br>The game master will start the draw.</div>
      </div>`;
  } else {
    const picks = new Map(rnd.picks.map(p => [p.card_index, p]));
    const revealed = rnd.is_resolved;
    const left = revealed ? 0 : secondsLeft(rnd.deadline);
    const cards = [];
    for (let i = 0; i < rnd.card_count; i++) {
      const p = picks.get(i);
      const isMine = state.my_pick === i;
      const isJoker = revealed && rnd.joker_index === i;
      const cls = [
        'tb-card',
        isMine ? 'mine' : '',
        p && !isMine ? 'taken' : '',
        revealed ? 'revealed' : '',
        isJoker ? 'joker' : '',
        revealed && !isJoker ? 'safe' : '',
      ].join(' ');
      const face = isJoker
        ? `<div class="tb-face joker"><span class="tb-joker">🃏</span><span>JOKER</span></div>`
        : `<div class="tb-face"><span class="tb-face-suit">${suitIconSVG(SUIT_SEQ[i % 4], { size: 34 })}</span></div>`;
      cards.push(`
        <button type="button" class="${cls}" data-card="${i}" ${me !== 'ALIVE' || revealed ? 'disabled' : ''}>
          <div class="tb-card-inner">
            <div class="tb-back"><span class="tb-back-mark">V</span><span class="tb-back-idx">${i + 1}</span></div>
            ${face}
          </div>
          <div class="tb-card-label">${isMine ? 'YOUR CARD' : p ? p.team_code : ''}</div>
        </button>`);
    }

    let verdict = '';
    if (revealed) {
      if (lastRevealKey !== String(rnd.round_number)) {
        lastRevealKey = String(rnd.round_number);
        safeVibrate(rnd.eliminated_team_code ? [120, 60, 240] : [60]);
      }
      verdict = rnd.eliminated_team_code
        ? `<div class="tb-verdict out"><strong>${rnd.eliminated_team_code}</strong> drew the Joker${rnd.eliminated_team_code && alive.length > state.slots ? ' — next round soon' : ''}</div>`
        : `<div class="tb-verdict">Nobody drew the Joker — again</div>`;
    } else if (me !== 'ALIVE') {
      verdict = `<div class="tb-verdict out">You are out. Watching the draw…</div>`;
    } else if (state.my_pick !== null && state.my_pick !== undefined) {
      verdict = `<div class="tb-verdict">Card ${state.my_pick + 1} is yours. Waiting for the reveal…</div>`;
    } else {
      verdict = `<div class="tb-verdict hot">Pick a card. One of them is the Joker.</div>`;
    }

    stage = `
      ${finalBanner}
      <div class="tb-round-bar">
        <span>ROUND ${rnd.round_number}</span>
        <span class="tb-timer ${!revealed && left <= 5 ? 'hot' : ''}">${revealed ? 'REVEALED' : `${left}s`}</span>
      </div>
      <div class="tb-cards">${cards.join('')}</div>
      ${completed ? '' : verdict}
      ${pickError ? `<div class="tb-error">${pickError}</div>` : ''}`;
  }

  frame.innerHTML = `
    <div class="tb-head">
      <div class="tb-kicker">TIEBREAKER · タイブレーク · ROOM ${state.room_code || ''}</div>
      <div class="tb-title">DEATH CARD</div>
      <div class="tb-sub">Tied at ${state.tie_total.toFixed(1)} pts · ${state.slots} place${state.slots === 1 ? '' : 's'} · ${alive.length} still in</div>
    </div>
    <div class="tb-roster">${rosterHtml}</div>
    ${stage}
  `;
}
