console.log('Fate Generator loaded');

import {
  getState,
  setMeta,
  setSkills,
  setAspectDescription,
  toggleAspectLock,
  removeAspect,
  setStuntDescription,
  toggleStuntLock,
  removeStunt,
  setAspects,
  setStunts,
  subscribe,
  clearForNewCharacter
} from './state.js';
import { renderSkills, initSkillsDnD, fitToPyramid, DEFAULT_SKILLS } from './skills.js';
import { setSkillBank, DEFAULT_SKILL_BANK } from './state.js';

const REQUEST_TIMEOUT_MS = 30000; // 10s
const HINTS_TIMEOUT_MS = 30000; // 30s for GM hints only

// Simple toast API for UX feedback
function ensureToastRoot() {
  let root = document.getElementById('toast-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'toast-root';
    root.className = 'toast-container';
    document.body.appendChild(root);
  }
  return root;
}

function showToast({ message, type = 'info', timeout = 3000 } = {}) {
  const root = ensureToastRoot();
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message || '';
  root.appendChild(el);
  window.setTimeout(() => { try { el.remove(); } catch {} }, Math.max(1500, timeout));
}

// Expose simple global for other modules
try { window.toast = showToast; } catch {}

// Animated status helper: renders spinner + cycling ellipsis until stopped
function startWaitFeedback(statusEl, base = 'Generating') {
  if (!statusEl) return () => {};
  try { if (statusEl.__waitTimer) { clearInterval(statusEl.__waitTimer); } } catch {}
  statusEl.classList.add('status-inline');
  statusEl.setAttribute('data-busy', 'true');
  // Ensure structure
  let content = statusEl.querySelector('.status-content');
  if (!content) {
    content = document.createElement('span');
    content.className = 'status-content';
    const spin = document.createElement('span');
    spin.className = 'spinner';
    const text = document.createElement('span');
    text.className = 'status-text';
    content.appendChild(spin);
    content.appendChild(text);
    statusEl.innerHTML = '';
    statusEl.appendChild(content);
  }
  const textEl = statusEl.querySelector('.status-text');
  let dots = 0;
  const update = () => {
    dots = (dots + 1) % 4;
    if (textEl) textEl.textContent = `${base}${'.'.repeat(dots)}`;
  };
  update();
  const timer = setInterval(update, 500);
  statusEl.__waitTimer = timer;
  return (finalText) => {
    try { if (statusEl.__waitTimer) clearInterval(statusEl.__waitTimer); } catch {}
    try { delete statusEl.__waitTimer; } catch {}
    statusEl.removeAttribute('data-busy');
    if (typeof finalText === 'string') {
      statusEl.innerHTML = '';
      const done = document.createElement('span');
      done.textContent = finalText;
      statusEl.appendChild(done);
    }
  };
}

function $(selector) {
  return document.querySelector(selector);
}

function setText(el, text) {
  if (el) el.textContent = text;
}

// Small helper used by generators
function cloneStunts(arr) {
  return Array.isArray(arr)
    ? arr.map(s => ({ id: s.id, name: s.name, description: s.description }))
    : [];
}

function ensureLockButtonGeneric(listItemEl, locked, onToggle) {
  if (!listItemEl) return;
  // Ensure only one toggle-lock button exists
  const all = listItemEl.querySelectorAll('button[data-role="toggle-lock"]');
  // Remove duplicates beyond the first
  if (all.length > 1) {
    for (let i = 1; i < all.length; i++) {
      try { all[i].remove(); } catch {}
    }
  }
  let btn = listItemEl.querySelector('button[data-role="toggle-lock"]');
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn lock';
    btn.setAttribute('data-role', 'toggle-lock');
    const fieldEl = listItemEl.querySelector('.field');
    if (fieldEl && fieldEl.nextSibling) {
      listItemEl.insertBefore(btn, fieldEl.nextSibling);
    } else {
      listItemEl.appendChild(btn);
    }
    if (typeof onToggle === 'function') {
      btn.addEventListener('click', onToggle);
    }
  }
  btn.textContent = locked ? '🔒' : '🔓';
  btn.innerHTML = locked ? '<i class="fa-solid fa-lock"></i>' : '<i class="fa-solid fa-lock-open"></i>';
  btn.classList.toggle('locked', !!locked);
  btn.setAttribute('aria-pressed', locked ? 'true' : 'false');
  btn.setAttribute('aria-label', locked ? 'Unlock' : 'Lock');
}

function ensureHelpButton(listItemEl, targetType, targetId) {
  if (!listItemEl) return;
  let btn = listItemEl.querySelector(`button.icon-btn.help[data-help-id="${targetId}"]`);
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn help';
    btn.dataset.helpType = targetType;
    btn.dataset.helpId = targetId;
    btn.title = 'How to use?';
    btn.setAttribute('aria-label', 'How to use?');
    btn.innerHTML = '<i class="fa-regular fa-circle-question"></i>';
    const fieldEl = listItemEl.querySelector('.field');
    if (fieldEl && fieldEl.nextSibling) {
      listItemEl.insertBefore(btn, fieldEl.nextSibling.nextSibling || fieldEl.nextSibling);
    } else {
      listItemEl.appendChild(btn);
    }
  }
  // Update enabled/disabled state based on sibling field content
  try {
    const fieldEl = listItemEl.querySelector('.field');
    const raw = (fieldEl && fieldEl.textContent) || '';
    const cleaned = raw.replace(/[•\u2022]/g, '').trim();
    const shouldDisable = cleaned.length === 0;
    btn.disabled = shouldDisable;
    if (shouldDisable) {
      btn.setAttribute('aria-disabled', 'true');
      btn.title = 'Add text first to get examples';
    } else {
      btn.removeAttribute('aria-disabled');
      btn.title = 'How to use?';
    }
  } catch {}
}

// Render skills/pool using the dedicated module
function renderSkillsPyramidFromState() { renderSkills(); }

function ensureLockButton(listItemEl, aspectId, locked) {
  return ensureLockButtonGeneric(listItemEl, locked, () => toggleAspectLock(aspectId));
}

function ensureStuntLockButton(listItemEl, stuntId, locked) {
  return ensureLockButtonGeneric(listItemEl, locked, () => toggleStuntLock(stuntId));
}

function render() {
  const state = getState();
  setText($('#idea-field'), state.meta.idea || '');
  setText($('#setting-field'), state.meta.setting || '');
  const ladderDisplay = $('#ladder-type-display');
  if (ladderDisplay) ladderDisplay.textContent = (state.meta?.ladderType || '1-4').replace('-', '–');

  const highConcept = state.aspects.find(a => a.id === 'aspect-high-concept');
  const trouble = state.aspects.find(a => a.id === 'aspect-trouble');
  const highEl = $('#high-concept-field');
  const troubleEl = $('#trouble-field');

  setText(highEl, (highConcept && highConcept.description) || '');
  setText(troubleEl, (trouble && trouble.description) || '');

  if (highEl) {
    highEl.contentEditable = highConcept && !highConcept.locked ? 'true' : 'false';
  }
  if (troubleEl) {
    troubleEl.contentEditable = trouble && !trouble.locked ? 'true' : 'false';
  }

  const highLi = highEl ? highEl.closest('li') : null;
  const troubleLi = troubleEl ? troubleEl.closest('li') : null;
  // Locks removed

  // Render additional aspects (beyond High/Trouble)
  const aspectsSection = document.querySelector('.section.aspects');
  if (aspectsSection) {
    const items = Array.from(aspectsSection.querySelectorAll('ul.list > li'));
    const listEl = aspectsSection.querySelector('ul.list');
    // Remove any extra aspect rows beyond the first two
    while (items.length > 2) {
      const li = items.pop();
      if (li) li.remove();
    }
    const extras = (state.aspects || []).filter(a => a && a.id !== 'aspect-high-concept' && a.id !== 'aspect-trouble');
    for (const a of extras) {
      const li = document.createElement('li');
      const label = document.createElement('label');
      label.className = 'label';
      label.textContent = 'Aspect';
      const field = document.createElement('div');
      field.className = 'field';
      field.textContent = a.description || '••••';
      field.contentEditable = a.locked ? 'false' : 'true';
      li.appendChild(label);
      li.appendChild(field);
      // Remove button
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'delete-btn';
      delBtn.textContent = '✕';
      delBtn.setAttribute('aria-label', 'Remove aspect');
      delBtn.addEventListener('click', () => removeAspect(a.id));
      li.appendChild(delBtn);
      // Locks removed
      ensureHelpButton(li, 'aspect', a.id);
      field.addEventListener('blur', () => setAspectDescription(a.id, field.textContent || '', true));
      listEl.appendChild(li);
    }
  }

  // Stunts: render dynamic list
  const stuntsList = document.getElementById('stunts-list');
  if (stuntsList) {
    stuntsList.innerHTML = '';
    const stunts = Array.isArray(state.stunts) ? state.stunts : [];
    console.log('stunts', stunts);
    for (const s of stunts) {
      const li = document.createElement('li');
      // Stunt name label
      const nameEl = document.createElement('div');
      nameEl.className = 'stunt-name label';
      nameEl.textContent = s.name || 'Stunt';
      li.appendChild(nameEl);
      const field = document.createElement('div');
      field.className = 'field';
      field.setAttribute('aria-label', s.name || 'Stunt');
      field.textContent = s.description || '••••';
      field.contentEditable = s.locked ? 'false' : 'true';
      li.appendChild(field);
      // Remove button
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'delete-btn';
      delBtn.textContent = '✕';
      delBtn.setAttribute('aria-label', 'Remove stunt');
      delBtn.addEventListener('click', () => removeStunt(s.id));
      li.appendChild(delBtn);
      // Locks removed
      ensureHelpButton(li, 'stunt', s.id);
      if (!field.dataset.listenerAttached) {
        field.dataset.listenerAttached = '1';
        field.addEventListener('blur', () => setStuntDescription(s.id, field.textContent || '', true));
      }
      stuntsList.appendChild(li);
    }
  }

  renderSkillsPyramidFromState();
  // Refresh help button states after render in aspects and stunts
  try {
    const aspectItems = document.querySelectorAll('.section.aspects ul.list > li');
    aspectItems.forEach(li => {
      const idAttr = li.querySelector('button.icon-btn.help')?.dataset?.helpId;
      if (idAttr) ensureHelpButton(li, 'aspect', idAttr);
    });
    const stuntItems = document.querySelectorAll('.section.stunts ul.list > li');
    stuntItems.forEach(li => {
      const idAttr = li.querySelector('button.icon-btn.help')?.dataset?.helpId;
      if (idAttr) ensureHelpButton(li, 'stunt', idAttr);
    });
  } catch {}
}

function attachInlineEditingHandlers() {
  const highEl = $('#high-concept-field');
  const troubleEl = $('#trouble-field');

  if (highEl) {
    highEl.addEventListener('blur', () => setAspectDescription('aspect-high-concept', highEl.textContent || '', true));
  }
  if (troubleEl) {
    troubleEl.addEventListener('blur', () => setAspectDescription('aspect-trouble', troubleEl.textContent || '', true));
  }

  const stuntsSection = document.querySelector('.section.stunts');
  if (stuntsSection) {
    const list = document.getElementById('stunts-list');
    if (list) {
      // listeners are attached per item in render()
    }
  }
}

async function generateSkeleton() {
  const ideaInput = $('#idea-input');
  const settingInput = $('#setting-input');
  const statusEl = $('#status-message');
  const btn = document.getElementById('generate-skeleton-btn');

  const idea = (ideaInput?.value || '').trim();
  const setting = (settingInput?.value || '').trim();

  if (!idea) {
    setText(statusEl, 'Please enter a character idea.');
    return;
  }

  // Disable button and show progress
  const previousBtnLabel = btn ? btn.textContent : '';
  if (btn) {
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    btn.setAttribute('aria-disabled', 'true');
    btn.textContent = 'Generating...';
  }
  setText(statusEl, 'Generating...');

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    const res = await fetch('/api/generate_skeleton', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idea, setting: setting || null, skillList: null }),
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      let serverMsg = '';
      try {
        const errJson = await res.json();
        serverMsg = errJson?.message || errJson?.detail || '';
      } catch (parseErr) {
        console.warn('Failed to parse error response JSON', { status: res.status, error: parseErr });
      }
      const msg = serverMsg
        ? `Server error (${res.status}): ${serverMsg}`
        : `Server error (${res.status}).`;
      throw new Error(msg);
    }
    const data = await res.json();
    // Clear previous content (skills, extra aspects, stunts, history)
    clearForNewCharacter();
    // Defensive: deep-clone to avoid accidental shared object references
    const cloneStunts = (arr) => (Array.isArray(arr) ? arr.map(s => ({ id: s.id, name: s.name, description: s.description })) : []);
    const { highConcept, trouble, skills } = data;

    setMeta({ idea, setting: setting || '' });
    setAspectDescription('aspect-high-concept', highConcept || '', false);
    setAspectDescription('aspect-trouble', trouble || '', false);
    // Normalize server skills into 1-4 pyramid so UI always has valid rows
    const normalized = fitToPyramid(Array.isArray(skills) ? skills : []);
    setSkills(normalized);

    setText(statusEl, 'Done.');
    showToast({ message: 'Skeleton generated', type: 'success' });
  } catch (err) {
    console.error(err);
    if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') {
      setText(statusEl, `Timed out after ${Math.round(REQUEST_TIMEOUT_MS / 1000)}s. Please try again.`);
      showToast({ message: 'Request timed out', type: 'error' });
    } else {
      const msg = (err && typeof err.message === 'string' && err.message) || 'Unknown error';
      setText(statusEl, `Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  }
  finally {
    if (btn) {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.removeAttribute('aria-disabled');
      btn.textContent = previousBtnLabel || 'Generate Skeleton';
    }
  }
}

async function generateDetails() {
  const statusEl = document.getElementById('details-status-message');
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  // Read form controls
  const mode = (document.querySelector('input[name="gen-mode"]:checked')?.value || 'stunts');
  const countInput = document.getElementById('stunt-count-input');
  const count = countInput ? Math.max(1, parseInt(countInput.value || '1', 10)) : 1;
  const targetSkillId = document.getElementById('target-skill-select')?.value || '';
  const actionType = document.getElementById('action-type-select')?.value || '';
  const allowOverwrite = !!document.getElementById('allow-overwrite-toggle')?.checked;

  const character = getState();
  // Provide richer context to server by ensuring latest aspects/skills/meta are included (already in state)
    const body = {
    character,
    allowOverwriteUserEdits: allowOverwrite,
    options: {
      mode,
      count: mode === 'stunts' ? count : (mode === 'single_stunt' ? 1 : null),
      targetSkillId: targetSkillId || null,
      actionType: actionType || null,
        note: (document.getElementById('stunt-add-note')?.value || '').trim() || null,
        skillBank: (getState().meta?.skillBank && getState().meta.skillBank.length) ? getState().meta.skillBank : DEFAULT_SKILLS
    }
  };

  const stopWait = startWaitFeedback(statusEl, 'Generating');
  try {
    const res = await fetch('/api/generate_remaining', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      let serverMsg = '';
      try { serverMsg = (await res.json())?.message || ''; } catch {}
      throw new Error(serverMsg || `Server error (${res.status}).`);
    }
    const data = await res.json();

    // Apply to state
    if (Array.isArray(data.aspects)) {
      const current = getState();
      const flags = new Map((current.aspects || []).map(a => [a.id, { locked: !!a.locked, userEdited: !!a.userEdited }]));
      const merged = (data.aspects || []).map((a, idx) => {
        const id = a.id || `aspect-${Date.now()}-${idx}`;
        const f = flags.get(id) || { locked: false, userEdited: false };
        return {
          id,
          name: a.name || 'Aspect',
          description: a.description || '',
          locked: f.locked,
          userEdited: f.userEdited
        };
      });
      setAspects(merged);
    }

    if (Array.isArray(data.stunts)) {
      // If mode is 'stunts', replace full list with returned stunts + keep flags by id.
      const modeSel = (document.querySelector('input[name="gen-mode"]:checked')?.value || 'stunts');
      const current = getState();
      const flagMap = new Map((current.stunts || []).map(s => [s.id, { locked: !!s.locked, userEdited: !!s.userEdited }]));
      // Filter out empty placeholder items and clamp client-side to requested count
      const countInput = document.getElementById('stunt-count-input');
      const requested = modeSel === 'single_stunt' ? 1 : Math.max(1, parseInt(countInput?.value || '1', 10));
      const cleaned = cloneStunts(data.stunts || []).filter(s => (s && ((s.description && s.description.trim()) || (s.name && s.name.trim())))).slice(0, requested);
      const mapped = cleaned.map((s, i) => {
        const id = s.id || `stunt-${Date.now()}-${i}`;
        const f = flagMap.get(id) || { locked: false, userEdited: false };
        return { id, name: s.name || 'Stunt', description: s.description || '', locked: f.locked, userEdited: f.userEdited };
      });
      if (modeSel === 'stunts') {
        setStunts(mapped);
      } else {
        // single_stunt: append all returned (defensive)
        const next = (current.stunts || []).slice();
        for (const one of mapped) if (one) next.push(one);
        setStunts(next);
      }
    }

    if (Array.isArray(data.skills)) {
      // Only update skills if user explicitly generated skills
      if (mode === 'skills') {
        // Respect server proposal to preserve locked constraints
        setSkills(Array.isArray(data.skills) ? data.skills : []);
      }
    }

    stopWait('Done.');
    showToast({ message: 'Details generated', type: 'success' });
  } catch (err) {
    console.error(err);
    if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') {
      stopWait(`Timed out after ${Math.round(REQUEST_TIMEOUT_MS / 1000)}s. Please try again.`);
      showToast({ message: 'Request timed out', type: 'error' });
    } else {
      const msg = (err && typeof err.message === 'string' && err.message) || 'Unknown error';
      stopWait(`Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  }
}

function hydrateInitialStateFromDOM() {
  const idea = ($('#idea-field')?.textContent || '').trim();
  const setting = ($('#setting-field')?.textContent || '').trim();
  const high = ($('#high-concept-field')?.textContent || '').trim();
  const trouble = ($('#trouble-field')?.textContent || '').trim();

  setMeta({ idea, setting });
  setAspectDescription('aspect-high-concept', high, false);
  setAspectDescription('aspect-trouble', trouble, false);

  const grid = $('#skills-grid');
  if (grid) {
    const rows = Array.from(grid.querySelectorAll('.skills-row'));
    const parsedSkills = [];
    const slugCounts = new Map();
    const slugify = (str) => (str || '')
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    for (const row of rows) {
      const rankText = row.querySelector('.rank')?.textContent || '';
      const m = /\+(\d+)/.exec(rankText);
      const rank = m ? parseInt(m[1], 10) : 0;
      const cells = Array.from(row.querySelectorAll('.cell'));
      for (const cell of cells) {
        const name = (cell.textContent || '').trim();
        if (name) {
          const base = slugify(name);
          const next = (slugCounts.get(base) || 0) + 1;
          slugCounts.set(base, next);
          const uniqueId = `skill-${base}${next > 1 ? `-${next}` : ''}`;
          parsedSkills.push({ id: uniqueId, name, rank });
        }
      }
    }
    setSkills(parsedSkills);
  }

  const stuntsSection = document.querySelector('.section.stunts');
  if (stuntsSection) {
    const items = Array.from(stuntsSection.querySelectorAll('ul.list > li'));
    items.forEach((li, idx) => {
      const field = li.querySelector('.field');
      const id = `stunt-${idx + 1}`;
      if (field) {
        const txt = (field.textContent || '').trim();
        setStuntDescription(id, txt, false);
      }
    });
  }
}

window.addEventListener('DOMContentLoaded', () => {
  subscribe(() => render());
  hydrateInitialStateFromDOM();
  attachInlineEditingHandlers();
  render();

  const btn = document.getElementById('generate-skeleton-btn');
  if (btn) btn.addEventListener('click', generateSkeleton);
  initSkillsDnD();

  const ladderSelect = document.getElementById('ladder-type-select');
  if (ladderSelect) {
    ladderSelect.addEventListener('change', () => {
      const val = ladderSelect.value || '1-4';
      setMeta({ ladderType: val });
      // Re-normalize existing skills to respect new shape (keep names)
      const cur = getState().skills || [];
      const normalized = fitToPyramid(cur);
      setSkills(normalized);
    });
  }

  // Populate target skill select from state
  const targetSelect = document.getElementById('target-skill-select');
  if (targetSelect) {
    const refreshSkillsOptions = () => {
      const s = (getState().skills || [])
        .slice()
        .sort((a, b) => (b.rank - a.rank) || String(a.name).localeCompare(String(b.name)));
      const current = targetSelect.value;
      targetSelect.innerHTML = '';
      const optAuto = document.createElement('option');
      optAuto.value = '';
      optAuto.textContent = 'Auto';
      targetSelect.appendChild(optAuto);
      for (const sk of s) {
        const opt = document.createElement('option');
        opt.value = sk.id;
        opt.textContent = `${sk.name} (+${sk.rank})`;
        targetSelect.appendChild(opt);
      }
      // try keep selection if exists
      if (Array.from(targetSelect.options).some(o => o.value === current)) {
        targetSelect.value = current;
      }
    };
    subscribe(refreshSkillsOptions);
    refreshSkillsOptions();
  }

  // Populate Add Stunt skill select from state
  const addStuntSkillSelect = document.getElementById('stunt-add-skill');
  if (addStuntSkillSelect) {
    const refresh = () => {
      const s = (getState().skills || [])
        .slice()
        .sort((a, b) => (b.rank - a.rank) || String(a.name).localeCompare(String(b.name)));
      const current = addStuntSkillSelect.value;
      addStuntSkillSelect.innerHTML = '';
      const optAuto = document.createElement('option');
      optAuto.value = '';
      optAuto.textContent = 'Auto';
      addStuntSkillSelect.appendChild(optAuto);
      for (const sk of s) {
        const opt = document.createElement('option');
        opt.value = sk.id;
        opt.textContent = `${sk.name} (+${sk.rank})`;
        addStuntSkillSelect.appendChild(opt);
      }
      if (Array.from(addStuntSkillSelect.options).some(o => o.value === current)) {
        addStuntSkillSelect.value = current;
      }
    };
    subscribe(refresh);
    refresh();
  }

  // ===== Skills Editor (modal) =====
  const skillsEditor = document.getElementById('skills-editor');
  const openEditorBtn = document.getElementById('edit-skills-open');
  const closeEditorBtn = document.getElementById('skills-editor-close');
  const cancelEditorBtn = document.getElementById('skills-editor-cancel');
  const applyEditorBtn = document.getElementById('skills-editor-apply');
  const resetEditorBtn = document.getElementById('skills-editor-reset');
  const addEditorBtn = document.getElementById('skills-editor-add');
  const editorList = document.getElementById('skills-editor-list');

  function openSkillsEditor() {
    if (!skillsEditor) return;
    // populate list from current bank
    const bank = (getState().meta?.skillBank && getState().meta.skillBank.length) ? getState().meta.skillBank : DEFAULT_SKILL_BANK;
    editorList.innerHTML = '';
    for (const name of bank) {
      const li = document.createElement('li');
      li.className = 'skills-editor-item';
      const input = document.createElement('input');
      input.type = 'text';
      input.value = String(name || '');
      const actions = document.createElement('div');
      actions.className = 'skills-editor-actions';
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'icon-btn';
      del.setAttribute('aria-label', 'Remove');
      del.textContent = '✕';
      del.addEventListener('click', () => { try { li.remove(); } catch {} });
      actions.appendChild(del);
      li.appendChild(input);
      li.appendChild(actions);
      editorList.appendChild(li);
    }
    skillsEditor.hidden = false;
  }

  function closeSkillsEditor() { if (skillsEditor) skillsEditor.hidden = true; }

  if (openEditorBtn) openEditorBtn.addEventListener('click', openSkillsEditor);
  if (closeEditorBtn) closeEditorBtn.addEventListener('click', closeSkillsEditor);
  if (cancelEditorBtn) cancelEditorBtn.addEventListener('click', closeSkillsEditor);
  if (skillsEditor) skillsEditor.addEventListener('click', (e) => {
    const t = e.target;
    if (t && t.getAttribute && t.getAttribute('data-close') === 'skills-editor') closeSkillsEditor();
  });
  if (resetEditorBtn) resetEditorBtn.addEventListener('click', () => {
    if (!editorList) return;
    editorList.innerHTML = '';
    for (const name of DEFAULT_SKILL_BANK) {
      const li = document.createElement('li');
      li.className = 'skills-editor-item';
      const input = document.createElement('input');
      input.type = 'text';
      input.value = String(name || '');
      const actions = document.createElement('div');
      actions.className = 'skills-editor-actions';
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'icon-btn';
      del.setAttribute('aria-label', 'Remove');
      del.textContent = '✕';
      del.addEventListener('click', () => { try { li.remove(); } catch {} });
      actions.appendChild(del);
      li.appendChild(input);
      li.appendChild(actions);
      editorList.appendChild(li);
    }
  });
  if (addEditorBtn) addEditorBtn.addEventListener('click', () => {
    const li = document.createElement('li');
    li.className = 'skills-editor-item';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'New skill';
    const actions = document.createElement('div');
    actions.className = 'skills-editor-actions';
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'icon-btn';
    del.setAttribute('aria-label', 'Remove');
    del.textContent = '✕';
    del.addEventListener('click', () => { try { li.remove(); } catch {} });
    actions.appendChild(del);
    li.appendChild(input);
    li.appendChild(actions);
    editorList.appendChild(li);
    input.focus();
  });
  if (applyEditorBtn) applyEditorBtn.addEventListener('click', () => {
    const inputs = Array.from(editorList.querySelectorAll('input[type="text"]'));
    const list = inputs.map(i => (i.value || '').trim()).filter(Boolean);
    // Deduplicate (case-insensitive), preserve order
    const seen = new Set();
    const unique = [];
    for (const n of list) {
      const key = n.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      unique.push(n);
    }
    setSkillBank(unique);
    closeSkillsEditor();
    showToast({ message: 'Skill bank updated', type: 'success' });
  });

  // ===== About Modal =====
  const aboutModal = document.getElementById('about-modal');
  const aboutOpen = document.getElementById('about-open');
  const aboutClose = document.getElementById('about-close');
  const aboutOk = document.getElementById('about-ok');
  if (aboutOpen) aboutOpen.addEventListener('click', () => { if (aboutModal) aboutModal.hidden = false; });
  if (aboutClose) aboutClose.addEventListener('click', () => { if (aboutModal) aboutModal.hidden = true; });
  if (aboutOk) aboutOk.addEventListener('click', () => { if (aboutModal) aboutModal.hidden = true; });
  if (aboutModal) aboutModal.addEventListener('click', (e) => {
    const t = e.target;
    if (t && t.getAttribute && t.getAttribute('data-close') === 'about') aboutModal.hidden = true;
  });

  // Wire Add Stunt button (single stunt generator using the add controls)
  const addStuntBtn = document.getElementById('add-stunt-btn');
  if (addStuntBtn) addStuntBtn.addEventListener('click', async () => {
    const skillId = document.getElementById('stunt-add-skill')?.value || '';
    const action = document.getElementById('stunt-add-action')?.value || '';
    const note = document.getElementById('stunt-add-note')?.value || '';
    const allowOverwrite = !!document.getElementById('allow-overwrite-toggle')?.checked;

    const character = getState();
    const body = {
      character,
      allowOverwriteUserEdits: allowOverwrite,
      options: { mode: 'single_stunt', count: 1, targetSkillId: skillId || null, actionType: action || null, note: note || null }
    };
    const statusEl = document.getElementById('details-status-message');
    const stopWait = startWaitFeedback(statusEl, 'Generating');
    try {
      const res = await fetch('/api/generate_remaining', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) {
        let msg = ''; try { msg = (await res.json())?.message || ''; } catch {}
        throw new Error(msg || `Server error (${res.status}).`);
      }
      const data = await res.json();
      if (Array.isArray(data.stunts)) {
        const current = getState();
        const next = (current.stunts || []).slice();
        for (let i = 0; i < data.stunts.length; i++) {
          const s = data.stunts[i];
          if (!s) continue;
          next.push({ id: s.id || `stunt-${Date.now()}-${i}`, name: s.name || 'Stunt', description: s.description || '', locked: false, userEdited: false });
        }
        setStunts(next);
      }
      stopWait('Done.');
      showToast({ message: 'Stunt added', type: 'success' });
    } catch (err) {
      console.error(err);
      const msg = (err && typeof err.message === 'string' && err.message) || 'Unknown error';
      stopWait(`Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  });

  // Wire New Aspect button
  const addAspectBtn = document.getElementById('add-aspect-btn');
  if (addAspectBtn) addAspectBtn.addEventListener('click', async () => {
    const note = document.getElementById('aspect-add-note')?.value || '';
    const allowOverwrite = !!document.getElementById('allow-overwrite-toggle')?.checked;

    const character = getState();
    const body = {
      character,
      allowOverwriteUserEdits: allowOverwrite,
      options: { mode: 'aspects', count: 1, note: note || null }
    };
    const statusEl = document.getElementById('aspects-status-message');
    const stopWait = startWaitFeedback(statusEl, 'Generating');
    console.log('body', body);
    console.log('note', note);
    console.log('Generate Aspects');
    try {
      const res = await fetch('/api/generate_remaining', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) {
        let msg = ''; try { msg = (await res.json())?.message || ''; } catch {}
        throw new Error(msg || `Server error (${res.status}).`);
      }
      const data = await res.json();
      if (Array.isArray(data.aspects)) {
        const current = getState();
        const currentIds = new Set((current.aspects || []).map(a => a.id));
        const currentNorm = new Set((current.aspects || []).map(a => (a.description || '').toLowerCase().replace(/\s+/g,' ').trim()));
        const incoming = (data.aspects || []).filter(a => a && a.name !== 'High Concept' && a.name !== 'Trouble');
        const mapped = [];
        for (let i = 0; i < incoming.length; i++) {
          const a = incoming[i];
          const id = a.id || `aspect-${Date.now()}-${i}`;
          const desc = (a.description || '').trim();
          const norm = desc.toLowerCase().replace(/\s+/g,' ').trim();
          if (currentIds.has(id) || currentNorm.has(norm)) continue; // skip duplicates
          mapped.push({ id, name: a.name || 'Aspect', description: desc, locked: false, userEdited: false });
        }
        if (mapped.length) setAspects([...(current.aspects || []), ...mapped]);
      }
      stopWait('Done.');
      showToast({ message: 'Aspect added', type: 'success' });
    } catch (err) {
      console.error(err);
      const msg = (err && typeof err.message === 'string' && err.message) || 'Unknown error';
      stopWait(`Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  });

  // Wire Generate Details
  const genDetailsBtn = document.getElementById('generate-details-btn');
  if (genDetailsBtn) genDetailsBtn.addEventListener('click', generateDetails);

  // Wire Regenerate High Concept
  const regenHighBtn = document.getElementById('regen-high-btn');
  if (regenHighBtn) regenHighBtn.addEventListener('click', async () => {
    const statusEl = document.getElementById('aspects-status-message');
    const character = getState();
    const allowOverwrite = !!document.getElementById('allow-overwrite-toggle')?.checked;
    const body = { character, allowOverwriteUserEdits: allowOverwrite, options: { mode: 'high_concept' } };
    const stopWait = startWaitFeedback(statusEl, 'Generating');
    try {
      const res = await fetch('/api/generate_remaining', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json())?.message || `Server error (${res.status}).`);
      const data = await res.json();
      if (Array.isArray(data.aspects)) {
        const current = getState();
        const flags = new Map((current.aspects || []).map(a => [a.id, { locked: !!a.locked, userEdited: !!a.userEdited }]));
        const mapped = (data.aspects || []).map(a => {
          const f = flags.get(a.id) || { locked: false, userEdited: false };
          return { id: a.id, name: a.name || 'Aspect', description: a.description || '', locked: f.locked, userEdited: f.userEdited };
        });
        setAspects(mapped);
      }
      stopWait('Done.');
      showToast({ message: 'High Concept updated', type: 'success' });
    } catch (err) {
      const msg = (err && err.message) || 'Unknown error';
      stopWait(`Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  });

  // Wire Regenerate Trouble
  const regenTroubleBtn = document.getElementById('regen-trouble-btn');
  if (regenTroubleBtn) regenTroubleBtn.addEventListener('click', async () => {
    const statusEl = document.getElementById('aspects-status-message');
    const character = getState();
    const allowOverwrite = !!document.getElementById('allow-overwrite-toggle')?.checked;
    const body = { character, allowOverwriteUserEdits: allowOverwrite, options: { mode: 'trouble' } };
    const stopWait = startWaitFeedback(statusEl, 'Generating');
    try {
      const res = await fetch('/api/generate_remaining', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json())?.message || `Server error (${res.status}).`);
      const data = await res.json();
      if (Array.isArray(data.aspects)) {
        const current = getState();
        const flags = new Map((current.aspects || []).map(a => [a.id, { locked: !!a.locked, userEdited: !!a.userEdited }]));
        const mapped = (data.aspects || []).map(a => {
          const f = flags.get(a.id) || { locked: false, userEdited: false };
          return { id: a.id, name: a.name || 'Aspect', description: a.description || '', locked: f.locked, userEdited: f.userEdited };
        });
        setAspects(mapped);
      }
      stopWait('Done.');
      showToast({ message: 'Trouble updated', type: 'success' });
    } catch (err) {
      const msg = (err && err.message) || 'Unknown error';
      stopWait(`Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  });

  // Wire Regenerate Skills (respecting locks server-side)
  const regenSkillsBtn = document.getElementById('regen-skills-btn');
  if (regenSkillsBtn) regenSkillsBtn.addEventListener('click', async () => {
    const statusEl = document.getElementById('details-status-message');
    const character = getState();
    const allowOverwrite = !!document.getElementById('allow-overwrite-toggle')?.checked;
    const body = { character, allowOverwriteUserEdits: allowOverwrite, options: { mode: 'skills', skillBank: (getState().meta?.skillBank && getState().meta.skillBank.length) ? getState().meta.skillBank : DEFAULT_SKILLS } };
    const stopWait = startWaitFeedback(statusEl, 'Generating');
    try {
      const res = await fetch('/api/generate_remaining', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json())?.message || `Server error (${res.status}).`);
      const data = await res.json();
      if (Array.isArray(data.skills)) {
        // Deduplicate by name to avoid collapsing due to ID differences
        const seen = new Set();
        const unique = [];
        for (const s of (data.skills || [])) {
          const key = String(s.name || '').trim().toLowerCase();
          if (!key || seen.has(key)) continue;
          seen.add(key);
          unique.push(s);
        }
        // Cap to 10 by highest rank
        const sorted = unique.slice().sort((a,b) => (b.rank||0)-(a.rank||0));
        const MAX_TOTAL = 10;
        setSkills(sorted.slice(0, MAX_TOTAL));
      }
      stopWait('Done.');
      showToast({ message: 'Skills updated', type: 'success' });
    } catch (err) {
      const msg = (err && err.message) || 'Unknown error';
      stopWait(`Request failed: ${msg}`);
      showToast({ message: `Failed: ${msg}`, type: 'error' });
    }
  });

  // Wire History drawer
  const historyBtn = document.getElementById('history-btn');
  const historyClose = document.getElementById('history-close');
  if (historyBtn) historyBtn.addEventListener('click', openHistoryDrawer);
  if (historyClose) historyClose.addEventListener('click', closeHistoryDrawer);
  // Clear history on new character
  const statusEl = document.getElementById('status-message');
  if (statusEl) {
    const observer = new MutationObserver(() => {
      // When we show "Done." after generation, reset history entries
      if ((statusEl.textContent || '').includes('Done.')) {
        historyEntries = [];
        renderHistory();
      }
    });
    try { observer.observe(statusEl, { childList: true, subtree: true, characterData: true }); } catch {}
  }

  // Delegate help icon clicks
  document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest ? e.target.closest('button.icon-btn.help') : null;
    if (!btn) return;
    if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') { e.preventDefault(); return; }
    const type = btn.dataset.helpType;
    const id = btn.dataset.helpId;
    if (!type || !id) return;
    openGmPopover(btn, type, id);
  });

  // Footer year
  const yearEl = document.getElementById('year');
  if (yearEl) {
    try { yearEl.textContent = String(new Date().getFullYear()); } catch {}
  }
});

// ===== GM Assistant: Popover and History =====

const gmPopoverEl = document.getElementById('gm-popover');
const gmPopoverTitleEl = document.getElementById('gm-popover-title');
const gmPopoverBodyEl = document.getElementById('gm-popover-body');
const gmPopoverCloseEl = document.getElementById('gm-popover-close');
const gmPopoverMoreEl = document.getElementById('gm-popover-more');

let currentPopoverTarget = null; // { type, id, anchor }
let historyEntries = [];

if (gmPopoverCloseEl) gmPopoverCloseEl.addEventListener('click', () => hideGmPopover());
if (gmPopoverMoreEl) gmPopoverMoreEl.addEventListener('click', async () => {
  if (!currentPopoverTarget) return;
  await loadHintsIntoPopover(currentPopoverTarget);
});

function getAspectById(id) {
  const s = getState();
  return (s.aspects || []).find(a => a.id === id);
}
function getStuntById(id) {
  const s = getState();
  return (s.stunts || []).find(x => x.id === id);
}

function titleForTarget(target) {
  if (!target) return '';
  if (target.type === 'aspect') {
    const a = getAspectById(target.id);
    const isTrouble = a && ((a.name || '').toLowerCase() === 'trouble' || a.id === 'aspect-trouble');
    const label = isTrouble ? 'Trouble' : (a?.name || 'Aspect');
    const desc = (a?.description || '').trim();
    return `${label}: ${desc || '(no text)'}`;
  }
  if (target.type === 'stunt') {
    const st = getStuntById(target.id);
    const name = st?.name || 'Stunt';
    return `${name}`;
  }
  return '';
}

function positionPopover(anchor) {
  if (!gmPopoverEl || !anchor) return;
  const rect = anchor.getBoundingClientRect();
  const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
  const margin = 12;
  const gap = 8;
  const width = Math.min(420, vw - margin * 2);

  gmPopoverEl.style.position = 'fixed';
  gmPopoverEl.style.width = `${width}px`;

  // Horizontal: clamp within viewport
  let left = rect.left;
  if (left + width + margin > vw) left = Math.max(margin, vw - width - margin);
  if (left < margin) left = margin;

  // Measure height after width is set
  const popRect = gmPopoverEl.getBoundingClientRect();
  const popH = popRect.height || 0;

  // Prefer below; flip above if not enough space; clamp otherwise
  let top = rect.bottom + gap;
  const spaceBelow = vh - (rect.bottom + gap) - margin;
  const spaceAbove = rect.top - gap - margin;
  if (popH && popH > spaceBelow && spaceAbove > spaceBelow) {
    // place above
    top = Math.max(margin, rect.top - popH - gap);
  } else if (popH && top + popH + margin > vh) {
    // clamp within viewport
    top = Math.max(margin, vh - popH - margin);
  }

  gmPopoverEl.style.left = `${left}px`;
  gmPopoverEl.style.top = `${top}px`;
}

function showGmPopover() {
  if (!gmPopoverEl) return;
  gmPopoverEl.hidden = false;
}
function hideGmPopover() {
  if (!gmPopoverEl) return;
  gmPopoverEl.hidden = true;
  currentPopoverTarget = null;
}

async function openGmPopover(anchorEl, targetType, targetId) {
  currentPopoverTarget = { anchor: anchorEl, type: targetType, id: targetId };
  gmPopoverTitleEl.textContent = titleForTarget(currentPopoverTarget);
  gmPopoverBodyEl.innerHTML = '<div class="gm-loading">Loading hints...</div>';
  showGmPopover();
  positionPopover(anchorEl);
  await loadHintsIntoPopover(currentPopoverTarget);
}

async function loadHintsIntoPopover(target) {
  try {
    const { hints } = await fetchGmHints(target.type, target.id);
    gmPopoverBodyEl.innerHTML = '';
    for (const h of (hints || [])) {
      gmPopoverBodyEl.appendChild(renderHintCard(h));
    }
    // Add to history
    const entry = buildHistoryEntry(target, hints || []);
    historyEntries.unshift(entry);
    renderHistory();
  } catch (err) {
    gmPopoverBodyEl.innerHTML = `<div class="gm-error">${(err && err.message) || 'Failed to load hints.'}</div>`;
  }
  positionPopover(target.anchor);
}

function renderHintCard(hint) {
  const card = document.createElement('div');
  card.className = 'gm-hint';
  const header = document.createElement('div');
  header.className = 'gm-hint-header';
  const pill = document.createElement('span');
  pill.className = `pill pill-${(hint.type || '').replace(/_/g,'-')}`;
  pill.textContent = (hint.type || '').replace(/_/g,' ').trim() || 'hint';
  const title = document.createElement('div');
  title.className = 'gm-hint-title';
  title.textContent = hint.title || '';
  header.appendChild(pill);
  header.appendChild(title);
  const narrative = document.createElement('div');
  narrative.className = 'gm-hint-narrative';
  narrative.textContent = hint.narrative || '';
  const mechanics = document.createElement('div');
  mechanics.className = 'gm-hint-mechanics';
  mechanics.textContent = hint.mechanics || '';
  const actions = document.createElement('div');
  actions.className = 'gm-hint-actions';
  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.className = 'btn-link';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', async () => {
    try {
      const text = `${hint.title}\n${hint.narrative}\nMechanics: ${hint.mechanics}`;
      await navigator.clipboard.writeText(text);
      showToast({ message: 'Copied', type: 'success' });
    } catch {}
  });
  actions.appendChild(copyBtn);
  card.appendChild(header);
  card.appendChild(narrative);
  card.appendChild(mechanics);
  card.appendChild(actions);
  return card;
}

async function fetchGmHints(type, id) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), HINTS_TIMEOUT_MS);
  try {
    const character = getState();
    const res = await fetch('/api/hints', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character, target: { type, id }, options: {} }),
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    if (!res.ok) {
      let msg = ''; try { msg = (await res.json())?.message || ''; } catch {}
      throw new Error(msg || `Server error (${res.status}).`);
    }
    return await res.json();
  } finally {
    try { clearTimeout(timeoutId); } catch {}
  }
}

function buildHistoryEntry(target, hints) {
  let label = '';
  if (target.type === 'aspect') {
    const a = getAspectById(target.id);
    const isTrouble = a && ((a.name || '').toLowerCase() === 'trouble' || a.id === 'aspect-trouble');
    label = `${isTrouble ? 'Trouble' : (a?.name || 'Aspect')}: ${(a?.description || '').trim()}`;
  } else if (target.type === 'stunt') {
    const st = getStuntById(target.id);
    label = `Stunt: ${st?.name || 'Stunt'}`;
  }
  return { id: `${Date.now()}-${Math.random().toString(36).slice(2,8)}`, ts: new Date(), target, label, hints };
}

function openHistoryDrawer() {
  const drawer = document.getElementById('history-drawer');
  if (!drawer) return;
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
}
function closeHistoryDrawer() {
  const drawer = document.getElementById('history-drawer');
  if (!drawer) return;
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
}

function renderHistory() {
  const list = document.getElementById('history-list');
  if (!list) return;
  list.innerHTML = '';
  for (const entry of historyEntries) {
    const item = document.createElement('div');
    item.className = 'history-item';
    const head = document.createElement('div');
    head.className = 'history-item-head';
    const title = document.createElement('div');
    title.className = 'history-item-title';
    title.textContent = entry.label || '';
    const time = document.createElement('div');
    time.className = 'history-item-time';
    try { time.textContent = entry.ts.toLocaleTimeString(); } catch { time.textContent = ''; }
    head.appendChild(title);
    head.appendChild(time);
    const body = document.createElement('div');
    body.className = 'history-item-body';
    for (const h of (entry.hints || [])) {
      body.appendChild(renderHintCard(h));
    }
    item.appendChild(head);
    item.appendChild(body);
    list.appendChild(item);
  }
}

// Reposition popover on window resize/scroll if open
window.addEventListener('resize', () => { if (currentPopoverTarget && !gmPopoverEl.hidden) positionPopover(currentPopoverTarget.anchor); });
window.addEventListener('scroll', () => { if (currentPopoverTarget && !gmPopoverEl.hidden) positionPopover(currentPopoverTarget.anchor); }, true);

