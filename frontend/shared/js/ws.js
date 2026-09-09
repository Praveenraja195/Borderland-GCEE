// Thin reconnecting-WebSocket wrapper for the leaderboard broadcast channels.
// The backend sends a full JSON array on connect and again on every recompute
// (see API reference §5).
//
// Fix §1.2: token is now passed as ?token=<jwt> in the WebSocket URL.
// Browsers cannot set WebSocket headers, so the query-param approach is the
// standard pattern. The backend validates the token before calling accept()
// and closes with 4001 on failure — this wrapper treats a 4001 close as a
// non-retriable auth failure rather than a transient reconnect case.

import { getWsBase, getToken } from './api.js';

const WS_AUTH_FAILURE_CODE = 4001;
const WS_FORBIDDEN_CODE = 4003;

export class LiveChannel {
  /**
   * @param {string} path     e.g. '/rooms/{room_id}/leaderboard' or '/leaderboard/overall'
   * @param {(data:any)=>void} onMessage
   * @param {'team'|'admin'} [tokenKind]  which stored token to attach (default: 'team')
   */
  constructor(path, onMessage, tokenKind = 'team') {
    this.path = path;
    this.onMessage = onMessage;
    this.tokenKind = tokenKind;
    this.sock = null;
    this.closedByUser = false;
    this.authFailed = false;
    this.attempt = 0;
    this.keepAliveTimer = null;
    this.connect();
  }

  connect() {
    if (this.authFailed) return; // do not retry after an auth rejection

    const token = getToken(this.tokenKind);
    const tokenSuffix = token ? `?token=${encodeURIComponent(token)}` : '';
    const url = `${getWsBase()}${this.path}${tokenSuffix}`;

    try {
      this.sock = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.sock.onopen = () => {
      this.attempt = 0;
      // keep-alive ping; server ignores client-sent text but some proxies
      // close idle sockets without traffic in either direction
      this.keepAliveTimer = setInterval(() => {
        if (this.sock && this.sock.readyState === WebSocket.OPEN) this.sock.send('ping');
      }, 25000);
    };

    this.sock.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        this.onMessage(data);
      } catch {
        // ignore malformed frames
      }
    };

    this.sock.onclose = (evt) => {
      clearInterval(this.keepAliveTimer);
      if (evt.code === WS_AUTH_FAILURE_CODE || evt.code === WS_FORBIDDEN_CODE) {
        // Fix §1.2: auth/permission rejection — do not retry, bubble error.
        this.authFailed = true;
        if (typeof this.onAuthError === 'function') {
          this.onAuthError(evt.code, evt.reason);
        }
        return;
      }
      if (!this.closedByUser) this.scheduleReconnect();
    };

    this.sock.onerror = () => {
      if (this.sock) this.sock.close();
    };
  }

  scheduleReconnect() {
    this.attempt += 1;
    const delay = Math.min(1000 * 2 ** this.attempt, 15000);
    setTimeout(() => { if (!this.closedByUser && !this.authFailed) this.connect(); }, delay);
  }

  close() {
    this.closedByUser = true;
    clearInterval(this.keepAliveTimer);
    if (this.sock) this.sock.close();
  }
}
