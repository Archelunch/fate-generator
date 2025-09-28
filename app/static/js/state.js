// Simple client-side state for the character sheet
export const DEFAULT_SKILL_BANK = [
  'Athletics', 'Burglary', 'Contacts', 'Crafts', 'Deceive', 'Drive', 'Empathy',
  'Fight', 'Investigate', 'Lore', 'Notice', 'Physique', 'Provoke', 'Rapport',
  'Resources', 'Shoot', 'Stealth', 'Will'
];
const listeners = new Set();
const state = {
  meta: { idea: '', setting: '', ladderType: '1-4', skillBank: DEFAULT_SKILL_BANK.slice() },
  aspects: [
    { id: 'aspect-high-concept', name: 'High Concept', description: '', locked: false, userEdited: false },
    { id: 'aspect-trouble', name: 'Trouble', description: '', locked: false, userEdited: false }
  ],
  skills: [],
  stunts: []
};

function notify() {
  for (const fn of listeners) {
    try { fn(state); } catch (err) { console.error(err); }
  }
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getState() {
  return JSON.parse(JSON.stringify(state));
}

export function setMeta(partial) {
  state.meta = { ...state.meta, ...partial };
  notify();
}

export function setSkillBank(list) {
  const next = Array.isArray(list)
    ? list.map(v => String(v || '').trim()).filter(Boolean)
    : DEFAULT_SKILL_BANK.slice();
  state.meta = { ...state.meta, skillBank: next };
  notify();
}

export function setSkills(nextSkills) {
  state.skills = Array.isArray(nextSkills)
    ? nextSkills
        .filter(s => s && s.id && s.name != null && s.rank != null)
        .map(s => {
          const userEdited = s.userEdited != null ? !!s.userEdited : false;
          return { id: s.id, name: s.name, rank: s.rank, userEdited };
        })
    : [];
  notify();
}

export function setAspects(nextAspects) {
  state.aspects = Array.isArray(nextAspects)
    ? nextAspects.filter(a => a && a.id && a.name != null)
                 .map(a => ({
                   id: a.id,
                   name: a.name,
                   description: a.description || '',
                   locked: !!a.locked,
                   userEdited: !!a.userEdited
                 }))
    : state.aspects;
  notify();
}

export function setStunts(nextStunts) {
  if (!Array.isArray(nextStunts)) {
    notify();
    return;
  }
  const sanitized = nextStunts
    .filter(s => s && (s.id || (s.name != null)) )
    .map(s => ({
      id: s.id || `stunt-${Math.random().toString(36).slice(2, 10)}`,
      name: s.name || 'Stunt',
      description: (s.description || '').trim(),
      locked: !!s.locked,
      userEdited: !!s.userEdited
    }));
  // Deduplicate by id only (preserve multiple stunts even if text repeats)
  const byId = new Map();
  for (const s of sanitized) byId.set(s.id, s);
  state.stunts = Array.from(byId.values());
  notify();
}

export function toggleSkillLock(id) {
  // removed
}

function findAspect(id) {
  return state.aspects.find(a => a.id === id);
}

export function setAspectDescription(id, description, markEdited = true) {
  const a = findAspect(id);
  if (!a) return;
  a.description = description;
  if (markEdited) a.userEdited = true;
  notify();
}

export function toggleAspectLock(id) {
  const a = findAspect(id);
  if (!a) return;
  a.locked = !a.locked;
  notify();
}

export function removeAspect(id) {
  // Prevent removing High Concept and Trouble
  if (id === 'aspect-high-concept' || id === 'aspect-trouble') return;
  const before = state.aspects.length;
  state.aspects = (state.aspects || []).filter(a => a.id !== id);
  if (state.aspects.length !== before) notify();
}

function findStunt(id) {
  return state.stunts.find(s => s.id === id);
}

export function setStuntDescription(id, description, markEdited = true) {
  const s = findStunt(id);
  if (!s) return;
  s.description = description;
  if (markEdited) s.userEdited = true;
  notify();
}

export function toggleStuntLock(id) {
  const s = findStunt(id);
  if (!s) return;
  s.locked = !s.locked;
  notify();
}

export function removeStunt(id) {
  const before = state.stunts.length;
  state.stunts = (state.stunts || []).filter(s => s.id !== id);
  if (state.stunts.length !== before) {
    notify();
  }
}

export function clearForNewCharacter() {
  // Reset aspects to only High Concept and Trouble (empty content, unlocked)
  state.aspects = [
    { id: 'aspect-high-concept', name: 'High Concept', description: '', locked: false, userEdited: false },
    { id: 'aspect-trouble', name: 'Trouble', description: '', locked: false, userEdited: false }
  ];
  // Clear skills and stunts
  state.skills = [];
  state.stunts = [];
  notify();
}

export function resetState(next) {
  if (!next) return;
  state.meta = next.meta || state.meta;
  state.aspects = next.aspects || state.aspects;
  state.skills = next.skills || state.skills;
  state.stunts = next.stunts || state.stunts;
  notify();
}


