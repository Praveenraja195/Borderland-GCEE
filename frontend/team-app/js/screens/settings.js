// Fix §1.4: removed the editable "API Host" field. The backend serves the
// team app same-origin; api.js DEFAULT_BASE is computed automatically.
// The field was confusing for non-technical event volunteers and a potential
// credential-harvesting vector if pointed at a look-alike origin.
import { renderAccount } from './account.js';

const ROUND_KEY = 'bl_active_round_id';
export function getActiveRoundId() { return localStorage.getItem(ROUND_KEY) || ''; }
export function setActiveRoundId(v) { localStorage.setItem(ROUND_KEY, v); }

export function renderSettings(root, navigate) {
  renderAccount(root, navigate);
}
