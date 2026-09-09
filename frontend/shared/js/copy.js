// Bilingual copy, sourced verbatim from THEME_GUIDE.md.
// Raw data that round-trips to the API (team codes, room codes, suit_code /
// game_code request values, scores, timestamps) is NEVER translated here —
// only the on-screen label *next to* that value uses this dictionary.

export const HEADERS = {
  teamLogin: { jp: '【ログイン】', en: 'Login' },
  teamRegister: { jp: '【チーム登録】', en: 'Team Registration' },
  adminLogin: { jp: '【管理者ログイン】', en: 'Admin Login' },
  round: { jp: '【ラウンド】', en: 'Round' },
  leaderboard: { jp: '【順位表】', en: 'Leaderboard' },
  hub: { jp: '【ゲーム】', en: 'Game' },
  selection: { jp: '【選択】', en: 'Selection' },
  settings: { jp: '【設定】', en: 'Settings' },
  account: { jp: '【アカウント】', en: 'Account' },
};

export const FIELDS = {
  teamCode: { jp: 'チームコード', en: 'Team Code' },
  teamName: { jp: 'チーム名', en: 'Team Name' },
  password: { jp: 'パスワード', en: 'Password' },
  adminUser: { jp: 'ユーザー名', en: 'Username' },
  suitSelect: { jp: 'スート選択', en: 'Select Suit' },
  numberSelect: { jp: '数字選択', en: 'Select Number' },
  roundName: { jp: 'ラウンド名', en: 'Round Name' },
  apiHost: { jp: 'サーバー', en: 'API Host' },
};

export const BUTTONS = {
  start: { jp: '始める', en: 'Start' },
  login: { jp: 'ログイン', en: 'Log In' },
  register: { jp: '登録する', en: 'Register' },
  submit: { jp: '送信', en: 'Submit' },
  confirm: { jp: '確認', en: 'Confirm' },
};

export const STATUS = {
  waitingToStart: { jp: '開始をお待ちください', en: 'Waiting to start' },
  timeRemaining: { jp: '残り時間', en: 'Time Remaining' },
  roundClosed: { jp: 'ラウンド終了', en: 'Round Closed' },
  submitted: { jp: '送信完了', en: 'Submitted' },
  alreadySubmitted: { jp: '送信済みです', en: 'Already submitted' },
  locked: { jp: '選択はロックされています', en: 'Selection is locked' },
  qualified: { jp: '通過', en: 'Qualified' },
  eliminated: { jp: '敗退', en: 'Eliminated' },
  paused: { jp: '一時停止中', en: 'Paused by admin' },
};

// Demo (practice) rounds. A practice round is played on the *same* screens as
// the real game, so this wording is the only thing separating "this counts"
// from "this doesn't" — it is kept here, in one place, rather than inlined at
// each of the four screens that show it.
export const DEMO = {
  banner: { jp: '練習ラウンド', en: 'PRACTICE ROUND' },
  bannerSub: { jp: 'この得点は記録されません', en: 'Scores here are not recorded' },
  notRecorded: { jp: '練習ラウンド — 得点は記録されません', en: 'Practice round — this score is not recorded' },
  tag: { jp: 'デモ', en: 'DEMO' },
  attempt: { jp: '回目', en: 'ATTEMPT' },
  scoring: { jp: '集計中…', en: 'Scoring the practice round…' },
  scoringNote: {
    jp: '他チームの回答が揃うと練習結果が表示されます。',
    en: 'Practice standings appear once every team has answered or the timer runs out.',
  },
};

/** The "not recorded" note shown on every screen that reports a practice
 *  score. Returns '' for a real round so call sites can interpolate it
 *  unconditionally. */
export function demoNoteHTML(isDemo) {
  if (!isDemo) return '';
  return `<div class="demo-inline-note">${DEMO.notRecorded.jp}<span>${DEMO.notRecorded.en}</span></div>`;
}

export const SUITS = {
  SPADE: { jp: 'スペード', en: 'Spade', glyph: '♠', color: 'black' },
  HEART: { jp: 'ハート', en: 'Heart', glyph: '♥', color: 'red' },
  DIAMOND: { jp: 'ダイヤ', en: 'Diamond', glyph: '♦', color: 'red' },
  CLUB: { jp: 'クラブ', en: 'Club', glyph: '♣', color: 'black' },
};

export const GAMES = {
  MINDMAZE: { jp: 'マインドメイズ', en: 'MindMaze' },
  ACE_SPADE: { jp: 'エース・オブ・スペード', en: 'Ace of Spades' },
  KING_DIAMOND: { jp: 'キング・オブ・ダイヤ', en: 'King of Diamonds' },
  JACK_HEART: { jp: 'ジャック・オブ・ハート', en: 'Jack of Hearts' },
};

// Known backend error strings (app/core/exceptions.py) mapped to Japanese,
// per THEME_GUIDE.md "Where NOT to use Japanese". Anything not in this table
// is shown in English, untranslated, exactly as returned by the API.
export const ERROR_JP = {
  'This team has already made a selection for this round.': '既にこのラウンドの選択を行っています',
  'This session is paused by an admin': 'このセッションは管理者により一時停止されています',
};

export function translateError(detail) {
  return ERROR_JP[detail] || null;
}

/** Render a two-tier <span> pair for a copy entry: { jp, en }. */
export function tierLabelHTML(entry) {
  return `<span class="primary">${entry.jp}</span><span class="secondary">${entry.en}</span>`;
}

/** Render a bracket header: 【 LABEL 】 with EN subline. */
export function bracketHeaderHTML(entry) {
  return `<div class="bracket-header"><span class="jp">${entry.jp}</span><span class="en">${entry.en}</span></div>`;
}

export const INSTRUCTIONS = {
  MINDMAZE: {
    jp: 'マインドメイズ',
    en: 'MindMaze — How to Play',
    steps: [
      {
        en: 'A 16×16 grid appears. <strong>Lit tiles flash briefly</strong> — focus and memorise their positions.',
        jp: '16×16のグリッドが表示され、タイルが一瞬点灯します。位置を記憶してください。',
      },
      {
        en: 'After the flash, all tiles <strong>go dark</strong>. Tap every tile you remember being lit.',
        jp: '点滅後、全タイルが暗くなります。記憶した位置をタップしてください。',
      },
      {
        en: '<strong>Correct tiles</strong> = +1.0 pt each. <strong>Mistakes</strong> = −0.5 pts each (min 0 pts). Speed also counts.',
        jp: '正解タイル1枚につき+1.0点、ミス1枚につき-0.5点（最低0点）。速さも評価されます。',
      },
    ],
  },
  ACE_SPADE: {
    jp: 'エース・オブ・スペード',
    en: 'Ace of Spades — How to Play',
    steps: [
      {
        en: '<strong>8 cards</strong> (suit + number) appear in order. Memorise both the <strong>symbol and number</strong> of each, and the order they appear in — you have <strong>30 seconds</strong>.',
        jp: '8枚のカード（スートと数字）が表示されます。各カードの絵柄と数字、そして並び順を30秒間で記憶してください。',
      },
      {
        en: 'Cards flip face-down, <strong>4 decoy cards</strong> are mixed in, and all 12 are reshuffled and shown face-up again in random positions.',
        jp: 'カードが裏返り、<strong>4枚のダミーカード</strong>が追加されます。12枚がシャッフルされ、ランダムな位置で再び表向きに表示されます。',
      },
      {
        en: 'Tap the cards back in the <strong>order you memorised</strong> them. Each tap marks a number (1, 2, 3…) — tap a marked card again to remove it and change your path.',
        jp: '記憶した<strong>順番通り</strong>にカードをタップしてください。タップするたびに番号（1、2、3…）が付きます。マークされたカードを再度タップすると解除され、選び直せます。',
      },
      {
        en: '<strong>Correct card in the correct position = +2.0 pts.</strong> Wrong card, wrong position, or a decoy card = −0.5 pts (min 0 pts). <strong>40 seconds</strong> to select.',
        jp: '正しい位置の正解カード：+2.0点。不正解・順番違い・ダミーカード：−0.5点（最低0点）。選択時間は40秒です。',
      },
    ],
  },
  KING_DIAMOND: {
    jp: 'キング・オブ・ダイヤ',
    en: 'King of Diamonds — How to Play',
    steps: [
      {
        en: 'Every team submits a number from <strong>0 to 100</strong>. You cannot see others\' picks.',
        jp: '各チームは0〜100の数字を選択。他チームの選択は非公開です。',
      },
      {
        en: 'The <strong>target</strong> is 80% of the average of all submitted numbers.',
        jp: '目標値は全提出数の平均×0.8です。',
      },
      {
        en: 'The team whose number is <strong>closest to the target</strong> wins. <strong>Rank 1 (closest) = +20 pts</strong>. Each rank further away loses points. Think strategically!',
        jp: '目標値に最も近い数字を出したチームが勝利。順位に応じて加点が決まります。他チームの行動を読んでください。',
      },
      {
        en: 'Submit before the round closes. <strong>Late submissions are invalid.</strong>',
        jp: 'ラウンド終了前に送信。遅れた場合は無効です。',
      },
    ],
  },
  JACK_HEART: {
    jp: 'ジャック・オブ・ハート',
    en: 'Jack of Hearts — How to Play',
    steps: [
      {
        en: 'Each team belongs to a specific suit (♠, ♥, ♦, ♣). Your assigned hidden card is <strong>strictly from your own suit</strong> (Ace, 2–10).',
        jp: '各チームには固有のスート（♠・♥・♦・♣）があり、割り当てられる隠しカードは<strong>必ず自チームのスート（A〜10）</strong>から選ばれます。',
      },
      {
        en: 'You can see all <strong>other teams\' cards and suits</strong> on screen, but your own card rank is hidden.',
        jp: '画面上には<strong>他チームのカードとスート</strong>が見えますが、自分のカードの数字は隠されています。',
      },
      {
        en: '<strong>Communicate</strong> with other teams to deduce the exact rank/number of your card.',
        jp: '他のチームと話し合い、自分のカードの数字（A〜10）を特定してください。',
      },
      {
        en: 'Select your card before time expires — <strong>Correct = +10.0 pts</strong>, <strong>Wrong = 0 pts</strong> (no point penalty).',
        jp: '制限時間内にカードを選択: 正解なら+10.0点、不正解なら0点（減点なし）。',
      },
    ],
  },
};
