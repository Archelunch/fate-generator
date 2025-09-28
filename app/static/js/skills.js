// Skills UI: rendering, pool footer, and drag-and-drop with pyramid enforcement
// No external libs; vanilla HTML5 DnD

import { getState, setSkills } from './state.js';

// Mirror backend defaults for client-only pool rendering
export const DEFAULT_SKILLS = [
  'Athletics', 'Burglary', 'Contacts', 'Crafts', 'Deceive', 'Drive', 'Empathy',
  'Fight', 'Investigate', 'Lore', 'Notice', 'Physique', 'Provoke', 'Rapport',
  'Resources', 'Shoot', 'Stealth', 'Will'
];

function $(selector) {
  return document.querySelector(selector);
}

function slugify(str) {
  return (str || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// Ladder definitions
function getLadderType() {
  const { meta } = getState();
  return (meta?.ladderType || '1-4').toString();
}

function getRanks() {
  const type = getLadderType();
  if (type === '1-5') return [5, 4, 3, 2, 1];
  return [4, 3, 2, 1];
}

function countByRank(skills) {
  const counts = new Map();
  for (const r of getRanks()) counts.set(r, 0);
  for (const s of skills) counts.set(s.rank, (counts.get(s.rank) || 0) + 1);
  return counts;
}

function isDistributionValid(skills) {
  const ranks = getRanks();
  const counts = countByRank(skills);
  // Pyramid chain rule only; lowest rank can be unlimited
  for (let i = 0; i < ranks.length - 1; i++) {
    const higher = ranks[i];
    const lower = ranks[i + 1];
    if ((counts.get(higher) || 0) > (counts.get(lower) || 0)) return false;
  }
  return true;
}

// ===== Touch-friendly fallback (tap-to-place) =====
const TOUCH_MODE = (typeof window !== 'undefined' && (('ontouchstart' in window) || (navigator.maxTouchPoints > 0))) || false;
let selected = null; // { type: 'pool'|'ladder', id?, name }
let selectedEl = null;

function clearSelection() {
  selected = null;
  try { selectedEl && selectedEl.classList.remove('selected'); } catch {}
  selectedEl = null;
}

function selectChip(el, data) {
  if (!el || !data) return;
  if (selectedEl === el) { clearSelection(); return; }
  clearSelection();
  selected = data;
  selectedEl = el;
  el.classList.add('selected');
}

function applySelectionToRank(rank) {
  if (!selected) return;
  const state = getState();
  const current = state.skills || [];
  let next = current.slice();
  if (selected.type === 'pool') {
    // Avoid duplicates by name
    if (current.some(s => (s.name || '').toLowerCase() === selected.name.toLowerCase())) { return; }
    const newSkill = { id: uniqueIdForSkillName(selected.name, current), name: selected.name, rank };
    next = current.concat([newSkill]);
  } else {
    const dragged = current.find(s => s.id === selected.id);
    if (dragged && dragged.locked) { return; }
    next = current.map(s => s.id === selected.id ? { ...s, rank } : s);
  }
  if (!isDistributionValid(next)) { return; }
  setSkills(next);
  clearSelection();
}

function applySelectionToPool() {
  if (!selected || selected.type !== 'ladder') return;
  const current = getState().skills || [];
  const dragged = current.find(s => s.id === selected.id);
  if (dragged && dragged.locked) { return; }
  const next = current.filter(s => s.id !== selected.id);
  setSkills(next);
  clearSelection();
}

function uniqueIdForSkillName(name, existing) {
  const base = slugify(name);
  let n = 1;
  let candidate = `skill-${base}`;
  const existingIds = new Set(existing.map(s => s.id));
  while (existingIds.has(candidate)) {
    n += 1;
    candidate = `skill-${base}-${n}`;
  }
  return candidate;
}

function computePool() {
  const state = getState();
  const taken = new Set((state.skills || []).map(s => (s?.name || '').toLowerCase()));
  const bank = Array.isArray(state?.meta?.skillBank) && state.meta.skillBank.length ? state.meta.skillBank : DEFAULT_SKILLS;
  return bank.filter(n => !taken.has(String(n).toLowerCase()));
}

function makeChip({ id, name, rank, removable, locked }) {
  const chip = document.createElement('div');
  chip.className = 'skill-chip';
  chip.draggable = true;
  chip.setAttribute('role', 'button');
  chip.setAttribute('aria-grabbed', 'false');
  chip.dataset.skillId = id || '';
  chip.dataset.skillName = name || '';
  if (rank != null) chip.dataset.rank = String(rank);

  const label = document.createElement('span');
  label.className = 'name';
  label.textContent = name;
  chip.appendChild(label);

  // (Locks removed)

  if (removable) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn remove';
    btn.title = 'Remove from ladder';
    btn.setAttribute('aria-label', `Remove ${name}`);
    btn.textContent = '✕';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const current = getState().skills || [];
      const target = current.find(s => s.id === id);
      const next = current.filter(s => s.id !== id);
      setSkills(next);
    });
    chip.appendChild(btn);
  }

  chip.addEventListener('dragstart', (ev) => {
    chip.setAttribute('aria-grabbed', 'true');
    const payload = JSON.stringify({
      type: rank != null ? 'ladder' : 'pool',
      id,
      name,
      rank
    });
    ev.dataTransfer?.setData('text/plain', payload);
    if (ev.dataTransfer) ev.dataTransfer.effectAllowed = 'move';
    ev.dataTransfer?.setDragImage(chip, 8, 8);
  });
  chip.addEventListener('dragend', () => {
    chip.setAttribute('aria-grabbed', 'false');
  });

  // Tap-to-place selection
  chip.addEventListener('click', () => {
    if (!TOUCH_MODE) return; // on desktop, rely on DnD
    if (rank != null) {
      // from ladder
      selectChip(chip, { type: 'ladder', id, name });
    } else {
      selectChip(chip, { type: 'pool', name });
    }
  });

  return chip;
}

function attachDropHandlers(targetEl, rank) {
  if (!targetEl) return;
  targetEl.addEventListener('dragover', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    targetEl.classList.add('drop-ok');
  });
  targetEl.addEventListener('dragleave', () => targetEl.classList.remove('drop-ok'));
  targetEl.addEventListener('drop', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    targetEl.classList.remove('drop-ok');
    const txt = ev.dataTransfer?.getData('text/plain') || '';
    let data;
    try { data = JSON.parse(txt); } catch { data = null; }
    if (!data || !data.name) return;

    const state = getState();
    const current = state.skills || [];

    // From pool → add; from ladder → update rank
    let next;
    if (data.type === 'pool') {
      // Avoid duplicates by name
      if (current.some(s => (s.name || '').toLowerCase() === data.name.toLowerCase())) {
        flashInvalid(targetEl);
        return;
      }
      const newSkill = {
        id: uniqueIdForSkillName(data.name, current),
        name: data.name,
        rank
      };
      next = current.concat([newSkill]);
    } else {
      // Prevent moving locked items
      const dragged = current.find(s => s.id === data.id);
      if (dragged && dragged.locked) {
        flashInvalid(targetEl);
        return;
      }
      next = current.map(s => s.id === data.id ? { ...s, rank } : s);
    }

    if (!isDistributionValid(next)) {
      flashInvalid(targetEl);
      return;
    }
    setSkills(next);
  });

  // Tap-to-place handler
  targetEl.addEventListener('click', () => {
    if (!TOUCH_MODE) return;
    applySelectionToRank(rank);
  });
}

function attachPoolDrop(poolEl) {
  if (!poolEl) return;
  poolEl.addEventListener('dragover', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    poolEl.classList.add('drop-ok');
  });
  poolEl.addEventListener('dragleave', () => poolEl.classList.remove('drop-ok'));
  poolEl.addEventListener('drop', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    poolEl.classList.remove('drop-ok');
    const txt = ev.dataTransfer?.getData('text/plain') || '';
    let data;
    try { data = JSON.parse(txt); } catch { data = null; }
    if (!data || data.type !== 'ladder') return;
    const current = getState().skills || [];
    const dragged = current.find(s => s.id === data.id);
    if (dragged && dragged.locked) {
      flashInvalid(poolEl);
      return;
    }
    const next = current.filter(s => s.id !== data.id);
    // Always valid when removing; but keep pyramid validity (removing can only help)
    setSkills(next);
  });

  // Tap-to-remove handler (selected chip from ladder → pool)
  poolEl.addEventListener('click', () => {
    if (!TOUCH_MODE) return;
    applySelectionToPool();
  });
}

function flashInvalid(el) {
  if (!el) return;
  el.classList.add('drop-bad');
  setTimeout(() => el.classList.remove('drop-bad'), 500);
  try {
    if (typeof window !== 'undefined' && typeof window.toast === 'function') {
      window.toast({ message: 'Invalid move: violates pyramid rule or duplicates.', type: 'error' });
    }
  } catch {}
}

export function renderSkills() {
  const grid = $('#skills-grid');
  if (!grid) return;

  const { skills } = getState();
  const byRank = new Map();
  for (const r of getRanks()) byRank.set(r, []);
  for (const s of (skills || [])) {
    if (!byRank.has(s.rank)) byRank.set(s.rank, []);
    byRank.get(s.rank).push(s);
  }

  grid.innerHTML = '';
  for (const r of getRanks()) {
    const row = document.createElement('div');
    row.className = 'skills-row';
    row.dataset.rank = String(r);
    const rankEl = document.createElement('div');
    rankEl.className = 'rank';
    const list = byRank.get(r) || [];
    const lowerList = byRank.get(r - 1) || [];
    const maxAllowedByRule = r === 1 ? Infinity : lowerList.length;
    const countEl = document.createElement('span');
    countEl.className = 'rank-count';
    countEl.textContent = r === 1 ? `${list.length}/∞` : `${list.length}/≤${maxAllowedByRule}`;
    rankEl.textContent = `+${r}`;
    rankEl.appendChild(countEl);
    const cells = document.createElement('div');
    cells.className = 'cells';
    cells.dataset.rank = String(r);
    // Allow dropping anywhere on the rank container (helps on mobile when empty slots are hidden)
    attachDropHandlers(cells, r);
    // Determine how many slots to render (tighter, fewer placeholders)
    const ladderType = getLadderType();
    const baseMinForOne = ladderType === '1-5' ? 4 : 3;
    let slots;
    if (r === 1) {
      // keep minimal growth to avoid tall empty rows
      slots = Math.max(list.length + 1, baseMinForOne);
    } else {
      const allowed = maxAllowedByRule;
      // show at most current length + 1 and at least 1, capped by allowed
      const desired = Math.max(1, Math.min(list.length + 1, allowed || 1));
      slots = desired;
    }
    cells.style.setProperty('--cols', String(Math.max(1, slots)));

    // Render slots
    for (let i = 0; i < slots; i++) {
      const slot = document.createElement('div');
      slot.className = 'slot';
      if (i >= list.length) slot.classList.add('empty');
      attachDropHandlers(slot, r);
      if (i < list.length) {
        const s = list[i];
        const chip = makeChip({ id: s.id, name: s.name, rank: s.rank, removable: true, locked: !!s.locked });
        slot.appendChild(chip);
      }
      cells.appendChild(slot);
    }
    row.appendChild(rankEl);
    row.appendChild(cells);
    grid.appendChild(row);
  }

  // Footer + Pool
  let footer = $('#skills-footer');
  if (!footer) {
    footer = document.createElement('div');
    footer.id = 'skills-footer';
    footer.className = 'skills-footer';
    grid.parentElement?.appendChild(footer);
  }
  footer.innerHTML = '';

  const hint = document.createElement('div');
  hint.className = 'hint';
  hint.textContent = 'Higher ranks cannot exceed the count of the rank below.';
  footer.appendChild(hint);

  const poolTitle = document.createElement('div');
  poolTitle.className = 'pool-title';
  poolTitle.textContent = 'Skill Pool';
  // Collapsible pool for better mobile UX
  const poolDetails = document.createElement('details');
  poolDetails.className = 'skills-pool-details';
  const poolSummary = document.createElement('summary');
  poolSummary.textContent = 'Skill Pool';
  poolDetails.appendChild(poolSummary);

  const pool = document.createElement('div');
  pool.className = 'skills-pool';
  pool.id = 'skills-pool';
  const poolList = computePool();
  for (const name of poolList) {
    const chip = makeChip({ id: '', name, rank: null, removable: false, locked: false });
    pool.appendChild(chip);
  }
  attachPoolDrop(pool);
  poolDetails.appendChild(pool);
  // Default open on desktop, collapsed on mobile
  try {
    if (window.matchMedia && window.matchMedia('(min-width: 768px)').matches) {
      poolDetails.open = true;
    }
  } catch {}
  footer.appendChild(poolDetails);
}

export function initSkillsDnD() {
  // Wire Clear button if present
  const clearBtn = document.getElementById('clear-skills-btn');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      const current = getState().skills || [];
      const next = current.filter(s => s && s.locked);
      setSkills(next);
    });
  }
}

// Convert an arbitrary ranked skills list into the fixed 1-4 pyramid
export function fitToPyramid(inputSkills) {
  const type = getLadderType();
  const ranks = getRanks();
  const sorted = Array.isArray(inputSkills)
    ? [...inputSkills].sort((a, b) => (b?.rank || 0) - (a?.rank || 0))
    : [];
  const seenNames = new Set();
  const result = [];

  // Initial quotas: fill 1-4 by default; if 1-5, leave +5 empty initially
  const quotas = new Map();
  if (type === '1-5') {
    quotas.set(5, 0);
    quotas.set(4, 1);
    quotas.set(3, 2);
    quotas.set(2, 3);
  } else {
    quotas.set(4, 1);
    quotas.set(3, 2);
    quotas.set(2, 3);
  }

  // Fill quotas top-down
  for (const r of ranks) {
    const need = quotas.get(r) || 0;
    let taken = 0;
    while (taken < need && sorted.length) {
      const next = sorted.shift();
      const name = (next?.name || '').trim();
      if (!name) continue;
      const key = name.toLowerCase();
      if (seenNames.has(key)) continue;
      seenNames.add(key);
      result.push({ id: uniqueIdForSkillName(name, result), name, rank: r });
      taken += 1;
    }
  }

  // Remaining skills: seed only the first 4 into rank +1; leave the rest in the pool
  const lowest = 1;
  let seededAtLowest = 0;
  const LOWEST_SEED_LIMIT = 4;
  while (sorted.length && seededAtLowest < LOWEST_SEED_LIMIT) {
    const next = sorted.shift();
    const name = (next?.name || '').trim();
    if (!name) continue;
    const key = name.toLowerCase();
    if (seenNames.has(key)) continue;
    seenNames.add(key);
    result.push({ id: uniqueIdForSkillName(name, result), name, rank: lowest });
    seededAtLowest += 1;
  }
  return result;
}


