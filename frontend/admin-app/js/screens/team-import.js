import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';

/**
 * Bulk team registration, as a three-step modal.
 *
 *   pick  ->  review  ->  done
 *
 * The review step is the point of the whole flow: the server has already
 * worked out every team code and password and found every bad row, but has
 * written nothing. The admin confirms what they can see, and only then does
 * anything get created. Deselecting a row here just leaves it out of the
 * commit payload — there's no separate "skip" concept on the server.
 *
 * Step three shows the passwords once. They're the first 4 digits of each
 * leader's own phone number so they're recoverable by hand, but the
 * credentials sheet is the thing to actually hand out.
 */

const STATUS_LABEL = {
  OK: 'Ready',
  MISSING_TEAM_NAME: 'No team name',
  INVALID_PHONE: 'Bad phone',
  DUPLICATE_IN_FILE: 'Duplicate in file',
  DUPLICATE_IN_DB: 'Already exists',
  OVER_CAPACITY: 'Over 40-team limit',
};

const FIELD_LABEL = {
  team_name: 'Team Name',
  leader_name: 'Leader Name',
  leader_phone: 'Phone Number',
  leader_email: 'Email',
};

const REQUIRED_FIELDS = ['team_name', 'leader_phone'];

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/**
 * @param {() => void} onImported called after teams are actually created, so
 *                                the caller can refresh its list.
 */
export function openTeamImportModal(onImported) {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `<div class="modal import-modal"><div id="import-step"></div></div>`;
  document.body.appendChild(backdrop);

  const step = backdrop.querySelector('#import-step');
  const close = () => backdrop.remove();

  // Clicking the dimmed area closes, but only from the pick step — losing a
  // reviewed 40-row preview to a stray click would be infuriating.
  let closeOnBackdropClick = true;
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop && closeOnBackdropClick) close();
  });

  let selectedFile = null;
  let preview = null;
  let overrides = {};

  // ── Step 1: pick a file ────────────────────────────────────────────────
  function renderPick(errorMessage) {
    closeOnBackdropClick = true;
    step.innerHTML = `
      <h3>Import Teams from a Spreadsheet</h3>
      <p class="import-lede">
        Upload your registration sheet (<strong>.xlsx</strong> or <strong>.csv</strong>).
        Each team gets a generated code like <code>B@GCEE-1234#</code>, and its
        password is the <strong>first 4 digits of the leader's phone number</strong>.
        Nothing is created until you review the preview.
      </p>

      <div class="import-drop" id="drop-zone" tabindex="0" role="button">
        <span class="mi import-drop-icon">upload_file</span>
        <div class="import-drop-main" id="drop-label">Choose a file or drag it here</div>
        <div class="import-drop-sub">.xlsx, .xlsm or .csv — up to 5 MB</div>
        <input type="file" id="file-input" accept=".xlsx,.xlsm,.csv,.txt" hidden />
      </div>

      ${errorMessage ? `<p class="status-note error">${esc(errorMessage)}</p>` : ''}

      <p class="import-hint">
        Column order doesn't matter — columns are matched by their header names,
        so an existing Google Form export usually works as-is.
        <a href="#" id="dl-template">Download a blank template</a>
      </p>

      <div class="btn-row">
        <button type="button" class="btn primary" id="upload-btn" disabled>
          <span class="mi">search</span> Preview Import
        </button>
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
      </div>
    `;

    const input = step.querySelector('#file-input');
    const zone = step.querySelector('#drop-zone');
    const label = step.querySelector('#drop-label');
    const uploadBtn = step.querySelector('#upload-btn');

    function accept(file) {
      selectedFile = file;
      label.textContent = file.name;
      zone.classList.add('has-file');
      uploadBtn.disabled = false;
    }

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    input.addEventListener('change', () => {
      if (input.files && input.files[0]) accept(input.files[0]);
    });
    ['dragenter', 'dragover'].forEach((evt) => zone.addEventListener(evt, (e) => {
      e.preventDefault(); zone.classList.add('dragging');
    }));
    ['dragleave', 'drop'].forEach((evt) => zone.addEventListener(evt, (e) => {
      e.preventDefault(); zone.classList.remove('dragging');
    }));
    zone.addEventListener('drop', (e) => {
      const file = e.dataTransfer?.files?.[0];
      if (file) accept(file);
    });

    step.querySelector('#dl-template').addEventListener('click', async (e) => {
      e.preventDefault();
      try { await api.admin.teams.importTemplate(); }
      catch (err) { toast(err.message, { error: true }); }
    });

    step.querySelector('#cancel-btn').addEventListener('click', close);
    uploadBtn.addEventListener('click', () => runPreview());
  }

  async function runPreview() {
    if (!selectedFile) return;
    step.innerHTML = `<h3>Reading the sheet…</h3><div class="spinner"></div>`;
    try {
      preview = await api.admin.teams.importPreview(selectedFile, overrides);
      renderReview();
    } catch (err) {
      renderPick(err.message);
    }
  }

  // ── Step 2: review what would be created ───────────────────────────────
  function renderReview() {
    closeOnBackdropClick = false;

    if (preview.unmapped_required.length) {
      renderColumnFix();
      return;
    }

    const rows = preview.rows;
    const ready = rows.filter((r) => r.status === 'OK');

    step.innerHTML = `
      <h3>Review Import</h3>
      <p class="import-lede">
        Found <strong>${rows.length}</strong> row(s) in
        ${preview.sheet_name ? `<em>${esc(preview.sheet_name)}</em>` : 'the sheet'}
        (headers on row ${preview.header_row_number}).
        <strong>${ready.length}</strong> ready to import,
        <strong>${rows.length - ready.length}</strong> skipped.
        ${preview.existing_team_count} team(s) already registered —
        room for ${preview.capacity_remaining} more.
      </p>

      <div class="import-mapping">
        ${Object.keys(FIELD_LABEL).map((f) => {
          const col = preview.column_map[f];
          const header = col !== undefined ? preview.headers[col] : null;
          return `<span class="import-chip ${header ? 'mapped' : 'unmapped'}">
            ${FIELD_LABEL[f]} <span class="mi">arrow_right_alt</span>
            <strong>${header ? esc(header) : 'not found'}</strong>
          </span>`;
        }).join('')}
        <button type="button" class="btn tiny" id="remap-btn">
          <span class="mi">tune</span> Change columns
        </button>
      </div>

      ${ready.length === 0 ? `
        <p class="status-note error">
          No row in this sheet can be imported. Fix the issues below and upload again.
        </p>` : ''}

      <div class="import-table-wrap">
        <table class="dtable import-table">
          <thead>
            <tr>
              <th class="tick-col">
                <input type="checkbox" id="check-all" ${ready.length ? 'checked' : ''}
                       ${ready.length ? '' : 'disabled'} title="Select all importable rows" />
              </th>
              <th>Row</th><th>Team Name</th><th>Team Code</th><th>Password</th>
              <th>Leader</th><th>Phone</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((r, i) => `
              <tr class="${r.status === 'OK' ? '' : 'row-skipped'}">
                <td class="tick-col">
                  <input type="checkbox" data-row="${i}"
                         ${r.status === 'OK' ? 'checked' : 'disabled'} />
                </td>
                <td class="mono">${r.row_number}</td>
                <td>${esc(r.team_name) || '<span class="muted">—</span>'}</td>
                <td class="mono">${esc(r.team_code) || '<span class="muted">—</span>'}</td>
                <td class="mono">${esc(r.password) || '<span class="muted">—</span>'}</td>
                <td>${esc(r.leader_name) || '<span class="muted">—</span>'}</td>
                <td class="mono">${esc(r.leader_phone) || '<span class="muted">—</span>'}</td>
                <td>
                  <span class="pill ${r.status === 'OK' ? 'ACTIVE' : 'NOT_STARTED'}"
                        title="${esc(r.message)}">${STATUS_LABEL[r.status] || r.status}</span>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <div class="btn-row">
        <button type="button" class="btn primary" id="confirm-btn" ${ready.length ? '' : 'disabled'}>
          <span class="mi">group_add</span> Import <span id="confirm-count">${ready.length}</span> team(s)
        </button>
        <button type="button" class="btn" id="back-btn"><span class="mi">arrow_back</span> Choose another file</button>
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
      </div>
    `;

    const boxes = () => Array.from(step.querySelectorAll('tbody input[data-row]:not(:disabled)'));
    const countEl = step.querySelector('#confirm-count');
    const confirmBtn = step.querySelector('#confirm-btn');

    function refreshCount() {
      const n = boxes().filter((b) => b.checked).length;
      countEl.textContent = n;
      confirmBtn.disabled = n === 0;
    }

    step.querySelector('#check-all')?.addEventListener('change', (e) => {
      boxes().forEach((b) => { b.checked = e.target.checked; });
      refreshCount();
    });
    boxes().forEach((b) => b.addEventListener('change', refreshCount));

    step.querySelector('#remap-btn').addEventListener('click', renderColumnFix);
    step.querySelector('#back-btn').addEventListener('click', () => { overrides = {}; renderPick(); });
    step.querySelector('#cancel-btn').addEventListener('click', close);

    confirmBtn.addEventListener('click', async () => {
      const chosen = boxes().filter((b) => b.checked).map((b) => preview.rows[Number(b.dataset.row)]);
      if (!chosen.length) return;

      confirmBtn.disabled = true;
      confirmBtn.innerHTML = `<span class="mi spin">progress_activity</span> Importing…`;
      try {
        const result = await api.admin.teams.importCommit(chosen.map((r) => ({
          team_name: r.team_name,
          leader_name: r.leader_name,
          leader_phone: r.leader_phone,
          leader_email: r.leader_email,
          team_code: r.team_code,
          password: r.password,
        })));
        renderDone(result);
        if (typeof onImported === 'function') onImported();
      } catch (err) {
        toast(err.message, { error: true });
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = `<span class="mi">group_add</span> Import <span id="confirm-count">${chosen.length}</span> team(s)`;
      }
    });
  }

  // ── Step 2b: fix the column mapping by hand ────────────────────────────
  function renderColumnFix() {
    closeOnBackdropClick = false;
    const missing = preview.unmapped_required;

    step.innerHTML = `
      <h3>Which column is which?</h3>
      <p class="import-lede">
        ${missing.length
          ? `Couldn't work out which column holds
             <strong>${missing.map((f) => FIELD_LABEL[f]).join('</strong> and <strong>')}</strong>.
             Pick them below.`
          : 'Pick a different column for any field the auto-detection got wrong.'}
      </p>

      ${Object.keys(FIELD_LABEL).map((f) => `
        <div class="field">
          <label class="tier-label">
            <span class="primary">${FIELD_LABEL[f]}</span>
            <span class="secondary">${REQUIRED_FIELDS.includes(f) ? 'Required' : 'Optional'}</span>
          </label>
          <select data-field="${f}">
            <option value="">${REQUIRED_FIELDS.includes(f) ? '— choose a column —' : '— not in this sheet —'}</option>
            ${preview.headers.map((h, i) => `
              <option value="${i}" ${preview.column_map[f] === i ? 'selected' : ''}>
                ${esc(h) || `(column ${i + 1})`}
              </option>
            `).join('')}
          </select>
        </div>
      `).join('')}

      <div class="btn-row">
        <button type="button" class="btn primary" id="apply-btn"><span class="mi">check</span> Apply</button>
        <button type="button" class="btn" id="back-btn">Choose another file</button>
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
      </div>
    `;

    step.querySelector('#apply-btn').addEventListener('click', async () => {
      overrides = {};
      step.querySelectorAll('select[data-field]').forEach((sel) => {
        if (sel.value !== '') overrides[sel.dataset.field] = sel.value;
      });
      const stillMissing = REQUIRED_FIELDS.filter((f) => !(f in overrides));
      if (stillMissing.length) {
        toast(`Pick a column for ${stillMissing.map((f) => FIELD_LABEL[f]).join(' and ')}`, { error: true });
        return;
      }
      await runPreview();
    });
    step.querySelector('#back-btn').addEventListener('click', () => { overrides = {}; renderPick(); });
    step.querySelector('#cancel-btn').addEventListener('click', close);
  }

  // ── Step 3: done — hand over the credentials ───────────────────────────
  function renderDone(result) {
    closeOnBackdropClick = false;
    const teams = result.teams || [];

    step.innerHTML = `
      <h3><span class="mi ok-icon">check_circle</span> ${result.created_count} team(s) created</h3>
      <p class="import-lede">
        Download the login sheet and share it with the teams. Each password is
        the first 4 digits of that team leader's phone number, so it's
        recoverable — but the sheet is the easiest thing to forward.
      </p>

      <div class="import-table-wrap">
        <table class="dtable import-table">
          <thead><tr><th>Team Code</th><th>Password</th><th>Team Name</th><th>Leader</th><th>Phone</th></tr></thead>
          <tbody>
            ${teams.map((t) => `
              <tr>
                <td class="mono"><strong>${esc(t.team_code)}</strong></td>
                <td class="mono">${esc(t.password)}</td>
                <td>${esc(t.team_name)}</td>
                <td>${esc(t.leader_name) || '<span class="muted">—</span>'}</td>
                <td class="mono">${esc(t.leader_phone) || '<span class="muted">—</span>'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <div class="btn-row">
        <button type="button" class="btn primary" id="dl-btn">
          <span class="mi">download</span> Download login sheet (.xlsx)
        </button>
        <button type="button" class="btn" id="done-btn">Done</button>
      </div>
    `;

    step.querySelector('#dl-btn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await api.admin.teams.credentialsExport(result);
        toast('Login sheet downloaded');
      } catch (err) {
        toast(err.message, { error: true });
      } finally {
        btn.disabled = false;
      }
    });
    step.querySelector('#done-btn').addEventListener('click', close);
  }

  renderPick();
}
