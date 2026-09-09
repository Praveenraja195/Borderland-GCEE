import { api } from '../../../shared/js/api.js';
import { HEADERS, FIELDS, BUTTONS, STATUS, SUITS, translateError } from '../../../shared/js/copy.js';
import { suitIconSVG, SUIT_CODES } from '../../../shared/js/suit-icons.js';
import { toast, friendlyError } from '../../../shared/js/ui.js';
import { getActiveRoundId, setActiveRoundId } from './settings.js';

const RANK_LABELS = { 1: 'A', 11: 'J', 12: 'Q', 13: 'K' };

function rankLabel(n) {
  return RANK_LABELS[n] || String(n);
}

// Authentic casino deck pip layouts (top%, left%, optional rotation)
const PIP_LAYOUTS = {
  2: [
    { top: 20, left: 50 },
    { top: 80, left: 50, rotate: 180 },
  ],
  3: [
    { top: 20, left: 50 },
    { top: 50, left: 50 },
    { top: 80, left: 50, rotate: 180 },
  ],
  4: [
    { top: 20, left: 28 }, { top: 20, left: 72 },
    { top: 80, left: 28, rotate: 180 }, { top: 80, left: 72, rotate: 180 },
  ],
  5: [
    { top: 20, left: 28 }, { top: 20, left: 72 },
    { top: 50, left: 50 },
    { top: 80, left: 28, rotate: 180 }, { top: 80, left: 72, rotate: 180 },
  ],
  6: [
    { top: 20, left: 28 }, { top: 20, left: 72 },
    { top: 50, left: 28 }, { top: 50, left: 72 },
    { top: 80, left: 28, rotate: 180 }, { top: 80, left: 72, rotate: 180 },
  ],
  7: [
    { top: 20, left: 28 }, { top: 20, left: 72 },
    { top: 35, left: 50 },
    { top: 50, left: 28 }, { top: 50, left: 72 },
    { top: 80, left: 28, rotate: 180 }, { top: 80, left: 72, rotate: 180 },
  ],
  8: [
    { top: 20, left: 28 }, { top: 20, left: 72 },
    { top: 35, left: 50 },
    { top: 50, left: 28 }, { top: 50, left: 72 },
    { top: 65, left: 50, rotate: 180 },
    { top: 80, left: 28, rotate: 180 }, { top: 80, left: 72, rotate: 180 },
  ],
  9: [
    { top: 19, left: 28 }, { top: 19, left: 72 },
    { top: 39, left: 28 }, { top: 39, left: 72 },
    { top: 50, left: 50 },
    { top: 61, left: 28, rotate: 180 }, { top: 61, left: 72, rotate: 180 },
    { top: 81, left: 28, rotate: 180 }, { top: 81, left: 72, rotate: 180 },
  ],
  10: [
    { top: 18, left: 28 }, { top: 18, left: 72 },
    { top: 28, left: 50 },
    { top: 38, left: 28 }, { top: 38, left: 72 },
    { top: 62, left: 28, rotate: 180 }, { top: 62, left: 72, rotate: 180 },
    { top: 72, left: 50, rotate: 180 },
    { top: 82, left: 28, rotate: 180 }, { top: 82, left: 72, rotate: 180 },
  ],
};

function buildCourtCardSVG(suit, rankNum, label) {
  const isRed = suit === 'HEART' || suit === 'DIAMOND';
  const primaryColor = isRed ? '#c81e2b' : '#1a1d24';
  const secondaryColor = isRed ? '#8a111b' : '#393e4a';
  const gold = '#c5a059';
  const goldLight = '#e5c986';

  let title = 'JACK';
  let crownPath = '';
  let emblemPath = '';

  if (rankNum === 11) {
    title = 'JACK';
    crownPath = `
      <path d="M-14 -12 L-10 -4 L0 -14 L10 -4 L14 -12 L12 2 L-12 2 Z" fill="${gold}" stroke="${secondaryColor}" stroke-width="1"/>
      <circle cx="-14" cy="-13" r="1.5" fill="${goldLight}"/>
      <circle cx="0" cy="-15" r="1.8" fill="${goldLight}"/>
      <circle cx="14" cy="-13" r="1.5" fill="${goldLight}"/>
      <path d="M-18 -18 Q-12 -22 -8 -14 Q-14 -12 -18 -18 Z" fill="${primaryColor}" opacity="0.9"/>
    `;
    emblemPath = `
      <path d="M-10 6 L10 6 L8 22 L-8 22 Z" fill="${primaryColor}" stroke="${gold}" stroke-width="1"/>
      <path d="M-16 10 L-10 10 L-8 20 L-14 16 Z" fill="${secondaryColor}"/>
      <path d="M16 10 L10 10 L8 20 L14 16 Z" fill="${secondaryColor}"/>
      <path d="M-13 -2 L-13 22" stroke="${gold}" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M-16 2 L-10 2" stroke="${gold}" stroke-width="1.5"/>
    `;
  } else if (rankNum === 12) {
    title = 'QUEEN';
    crownPath = `
      <path d="M-15 -14 L-11 -3 L-5 -12 L0 -2 L5 -12 L11 -3 L15 -14 L12 2 L-12 2 Z" fill="${gold}" stroke="${secondaryColor}" stroke-width="1"/>
      <circle cx="-15" cy="-15" r="1.5" fill="${goldLight}"/>
      <circle cx="-5" cy="-13" r="1.5" fill="${goldLight}"/>
      <circle cx="5" cy="-13" r="1.5" fill="${goldLight}"/>
      <circle cx="15" cy="-15" r="1.5" fill="${goldLight}"/>
      <path d="M-12 -2 Q-16 12 -12 20 Q-8 8 -10 0 Z" fill="${primaryColor}" opacity="0.7"/>
      <path d="M12 -2 Q16 12 12 20 Q8 8 10 0 Z" fill="${primaryColor}" opacity="0.7"/>
    `;
    emblemPath = `
      <path d="M-10 6 Q0 12 10 6 L8 22 L-8 22 Z" fill="${primaryColor}" stroke="${gold}" stroke-width="1"/>
      <path d="M0 6 L0 22" stroke="${gold}" stroke-width="1" stroke-dasharray="2,2"/>
      <circle cx="0" cy="14" r="3" fill="${gold}"/>
      <path d="M12 4 Q16 14 14 22 L11 22 Z" fill="${gold}"/>
      <circle cx="14" cy="4" r="2.5" fill="${goldLight}" stroke="${secondaryColor}" stroke-width="0.8"/>
    `;
  } else {
    title = 'KING';
    crownPath = `
      <path d="M-16 -12 L-12 -3 L0 -16 L12 -3 L16 -12 L13 2 L-13 2 Z" fill="${gold}" stroke="${secondaryColor}" stroke-width="1"/>
      <path d="M-4 -16 L4 -16 L0 -22 Z" fill="${goldLight}"/>
      <circle cx="-16" cy="-13" r="1.5" fill="${goldLight}"/>
      <circle cx="0" cy="-23" r="2" fill="${goldLight}"/>
      <circle cx="16" cy="-13" r="1.5" fill="${goldLight}"/>
      <path d="M-13 2 Q-10 10 0 10 Q10 10 13 2 Q0 5 -13 2 Z" fill="${secondaryColor}"/>
    `;
    emblemPath = `
      <path d="M-12 6 L12 6 L9 22 L-9 22 Z" fill="${primaryColor}" stroke="${gold}" stroke-width="1"/>
      <path d="M-16 8 L-11 6 L-9 22 L-15 18 Z" fill="${gold}"/>
      <path d="M16 8 L11 6 L9 22 L15 18 Z" fill="${gold}"/>
      <path d="M-13 -6 L-13 22" stroke="${primaryColor}" stroke-width="2" stroke-linecap="square"/>
      <path d="M-16 -2 L-10 -2" stroke="${gold}" stroke-width="1.5"/>
      <circle cx="0" cy="14" r="3.5" fill="${goldLight}" stroke="${secondaryColor}" stroke-width="0.8"/>
    `;
  }

  return `
    <svg class="court-graphic" viewBox="0 0 100 130" xmlns="http://www.w3.org/2000/svg">
      <!-- Ornate Card Court Border -->
      <rect x="3" y="3" width="94" height="124" rx="4" fill="none" stroke="${gold}" stroke-width="1.2"/>
      <rect x="5.5" y="5.5" width="89" height="119" rx="3" fill="none" stroke="${primaryColor}" stroke-width="0.8" opacity="0.6"/>
      <path d="M3 10 L10 3 M97 10 L90 3 M3 120 L10 127 M97 120 L90 127" stroke="${gold}" stroke-width="1"/>

      <!-- Upper Figure -->
      <g transform="translate(50, 34)">
        <ellipse cx="0" cy="0" rx="9" ry="11" fill="#f8eedb" stroke="${secondaryColor}" stroke-width="0.8"/>
        ${crownPath}
        ${emblemPath}
      </g>

      <!-- Center Heraldic Title Banner -->
      <g transform="translate(50, 65)">
        <rect x="-42" y="-9" width="84" height="18" rx="3" fill="${gold}" stroke="${secondaryColor}" stroke-width="1"/>
        <rect x="-39" y="-6.5" width="78" height="13" rx="2" fill="#faf8f5" stroke="${gold}" stroke-width="0.6"/>
        <text x="0" y="3.5" font-family="'Cinzel', 'Playfair Display', Georgia, serif" font-size="9" font-weight="900" fill="${primaryColor}" text-anchor="middle" letter-spacing="1.5">${title}</text>
        <circle cx="-32" cy="0" r="2.5" fill="${primaryColor}"/>
        <circle cx="32" cy="0" r="2.5" fill="${primaryColor}"/>
      </g>

      <!-- Lower Inverted Figure -->
      <g transform="translate(50, 96) rotate(180)">
        <ellipse cx="0" cy="0" rx="9" ry="11" fill="#f8eedb" stroke="${secondaryColor}" stroke-width="0.8"/>
        ${crownPath}
        ${emblemPath}
      </g>
    </svg>
  `;
}

function buildAceCenterHTML(suit) {
  return `
    <div class="ace-centerpiece">
      <div class="ace-ornament-ring"></div>
      <div class="ace-main-pip">${suitIconSVG(suit, { size: 44 })}</div>
      <div class="ace-label-text">ACE</div>
    </div>
  `;
}

function buildCardFrontHTML(suit, rankNum) {
  const label = rankLabel(rankNum);
  const cornerIcon = suitIconSVG(suit, { size: 12 });
  const isRed = suit === 'HEART' || suit === 'DIAMOND';
  const suitClass = isRed ? 'suit-red' : 'suit-black';

  const corner = `
    <div class="corner top ${suitClass}">
      <span class="rank">${label}</span>
      <span class="corner-suit-glyph">${cornerIcon}</span>
    </div>
    <div class="corner bottom ${suitClass}">
      <span class="rank">${label}</span>
      <span class="corner-suit-glyph">${cornerIcon}</span>
    </div>
  `;

  let middleHTML = '';
  if (rankNum === 1) {
    middleHTML = buildAceCenterHTML(suit);
  } else if (rankNum >= 11) {
    middleHTML = `<div class="court-card-wrapper">${buildCourtCardSVG(suit, rankNum, label)}</div>`;
  } else {
    const positions = PIP_LAYOUTS[rankNum] || [];
    middleHTML = `
      <div class="pips-container">
        ${positions
          .map((p) => {
            const rotStyle = p.rotate ? `transform: translate(-50%, -50%) rotate(${p.rotate}deg);` : 'transform: translate(-50%, -50%);';
            return `<span class="pip ${suitClass}" style="top:${p.top}%;left:${p.left}%;${rotStyle}">${suitIconSVG(suit, { size: 16 })}</span>`;
          })
          .join('')}
      </div>
    `;
  }

  return `
    <div class="card-border-frame"></div>
    ${corner}
    <div class="card-middle">${middleHTML}</div>
  `;
}

export async function renderSelection(root, navigate) {
  function showNoRoundView() {
    root.innerHTML = `
      <div class="bracket-header"><span class="jp">${HEADERS.selection.jp}</span><span class="en">${HEADERS.selection.en}</span></div>
      <div class="scroll-area">
        <p class="status-note error">No round configured yet. Please wait for an event admin to start Round 1.</p>
      </div>
      <div class="cta-dock"><button class="cta-btn ghost" id="go-retry">再読み込み / Refresh</button></div>
    `;
    root.querySelector('#go-retry').addEventListener('click', () => renderSelection(root, navigate));
  }

  root.innerHTML = `<div class="spinner-center" style="display:flex;justify-content:center;align-items:center;height:60vh;"><div class="spinner"></div></div>`;

  let roundId = null;
  try {
    const activeRound = await api.team.getActiveRound();
    if (activeRound && activeRound.round_id) {
      roundId = activeRound.round_id;
      setActiveRoundId(roundId);
    }
  } catch (e) {
    roundId = getActiveRoundId();
  }

  if (!roundId) {
    showNoRoundView();
    return;
  }

  // Block on mySelection check BEFORE building the picker UI so teams with existing selections never see the picker
  try {
    const existingSel = await api.team.mySelection(roundId);
    if (existingSel) {
      if (existingSel.room_id) {
        localStorage.setItem('bl_room_id', existingSel.room_id);
      }
      if (existingSel.suit_code) {
        localStorage.setItem('bl_team_suit', existingSel.suit_code.toUpperCase());
      }
      navigate('#/waiting');
      return;
    }
  } catch (err) {
    if (err.status === 404 && err.message && err.message.includes('Round not found')) {
      const active = await api.team.getActiveRound().catch(() => null);
      if (active && active.round_id && active.round_id !== roundId) {
        setActiveRoundId(active.round_id);
        return renderSelection(root, navigate);
      }
    }
  }

  let state = { suit: null, number: null, availability: null, loading: false };

  root.innerHTML = `
    <div class="bracket-header"><span class="jp">${HEADERS.selection.jp}</span><span class="en">${HEADERS.selection.en}</span></div>
    <div class="scroll-area">
      <label class="tier-label" style="display:block;text-align:center;"><span class="primary">${FIELDS.suitSelect.jp}</span><span class="secondary">${FIELDS.suitSelect.en}</span></label>
      <div class="suit-row" id="suit-row"></div>

      <div id="number-section" style="display:none;">
        <label class="tier-label" style="display:block;text-align:center;margin-top:var(--gap-md);"><span class="primary">${FIELDS.numberSelect.jp}</span><span class="secondary">${FIELDS.numberSelect.en}</span></label>
        <div class="number-grid" id="number-grid"></div>
      </div>
      <div id="err" class="status-note error" style="display:none;"></div>
    </div>
    <div class="cta-dock">
      <button id="submit-btn" class="cta-btn" disabled>${BUTTONS.confirm.jp} / ${BUTTONS.confirm.en}</button>
    </div>
  `;

  const suitRow = root.querySelector('#suit-row');
  const numberSection = root.querySelector('#number-section');
  const numberGrid = root.querySelector('#number-grid');
  const submitBtn = root.querySelector('#submit-btn');
  const errBox = root.querySelector('#err');

  SUIT_CODES.forEach((code) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'suit-chip';
    chip.dataset.suit = code;
    chip.innerHTML = `${suitIconSVG(code, { size: 26 })}<span>${SUITS[code].en}</span>`;
    chip.addEventListener('click', () => selectSuit(code));
    suitRow.appendChild(chip);
  });

  async function selectSuit(code) {
    state.suit = code;
    state.number = null;
    submitBtn.disabled = true;
    [...suitRow.children].forEach((c) => c.classList.toggle('selected', c.dataset.suit === code));
    numberSection.style.display = 'block';
    numberGrid.innerHTML = `<div class="card-loading-spinner"><div class="spinner"></div></div>`;
    try {
      const avail = await api.team.availability(roundId, code);
      state.availability = avail;
      renderNumbers(avail.numbers);
    } catch (err) {
      if (err.status === 404 || (err.message && err.message.includes('Round not found'))) {
        const active = await api.team.getActiveRound().catch(() => null);
        if (active && active.round_id && active.round_id !== roundId) {
          setActiveRoundId(active.round_id);
          renderSelection(root, navigate);
          return;
        }
      }
      showError(err);
    }
  }

  function renderNumbers(numbers) {
    numberGrid.innerHTML = '';

    numbers.sort((a, b) => a.number - b.number).forEach((n) => {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.dataset.num = n.number;

      if (n.is_taken) {
        cell.className = 'playing-card taken';
        cell.disabled = true;
        cell.setAttribute('aria-label', `${rankLabel(n.number)} of ${state.suit} (Taken)`);
        cell.innerHTML = `
          <div class="card-inner flipped">
            <div class="card-face card-front">
              ${buildCardFrontHTML(state.suit, n.number)}
            </div>
            <div class="card-face card-back">
              <div class="card-back-pattern"></div>
              <div class="card-taken-overlay">
                <div class="taken-stamp">TAKEN</div>
              </div>
            </div>
          </div>
        `;
      } else {
        cell.className = 'playing-card';
        cell.setAttribute('aria-label', `${rankLabel(n.number)} of ${state.suit}`);
        cell.innerHTML = `
          <div class="card-inner">
            <div class="card-face card-front">
              ${buildCardFrontHTML(state.suit, n.number)}
              <div class="card-selected-ribbon">
                <svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>
                <span>CHOSEN</span>
              </div>
            </div>
            <div class="card-face card-back">
              <div class="card-back-pattern"></div>
            </div>
          </div>
        `;
        cell.addEventListener('click', () => {
          state.number = n.number;
          [...numberGrid.querySelectorAll('.playing-card')].forEach((c) => {
            c.classList.remove('selected');
          });
          cell.classList.add('selected');
          submitBtn.disabled = false;
        });
      }
      numberGrid.appendChild(cell);
    });
  }

  function showError(err) {
    errBox.textContent = friendlyError(err, translateError);
    errBox.style.display = 'block';
  }

  submitBtn.addEventListener('click', async () => {
    if (!state.suit || state.number == null) return;
    submitBtn.disabled = true;
    submitBtn.textContent = '…';
    errBox.style.display = 'none';
    try {
      const res = await api.team.select(roundId, state.suit, state.number);
      if (res && res.room_id) {
        localStorage.setItem('bl_room_id', res.room_id);
      }
      if (state.suit || (res && res.suit_code)) {
        localStorage.setItem('bl_team_suit', (state.suit || res.suit_code).toUpperCase());
      }
      toast(STATUS.submitted.en);
      navigate('#/waiting');
    } catch (err) {
      if (err.status === 409) {
        const detail = (err.detail || err.message || '').toLowerCase();
        if (detail.includes('already made a selection') || detail.includes('already_selected')) {
          toast('You already have a room assignment.', { error: false });
          navigate('#/waiting');
          return;
        }
        const msg = err.detail || 'That spot was just taken — pick another.';
        toast(msg, { error: true });
        selectSuit(state.suit);
      } else if (err.status === 404 || (err.message && err.message.includes('Round not found'))) {
        const active = await api.team.getActiveRound().catch(() => null);
        if (active && active.round_id && active.round_id !== roundId) {
          setActiveRoundId(active.round_id);
          renderSelection(root, navigate);
          return;
        }
        showError(err);
      } else {
        showError(err);
      }
      submitBtn.disabled = false;
      submitBtn.textContent = `${BUTTONS.confirm.jp} / ${BUTTONS.confirm.en}`;
    }
  });
}