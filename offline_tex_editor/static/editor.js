// The source editor: CodeMirror, open documents and their tabs, saving, error and conflict marks, spell check.
import { $, el, app, state, store, pkey, api, post, setStatus, baseName, debounce } from './util.js';
import { toggleWrap } from './wrap.js';

const TEX = /\.(tex|sty|cls|bib|bst|tikz|bbx|cbx|lbx|dtx|ins|ltx|cfg|def|clo)$/;
const modeFor = p => p.endsWith('.py') ? 'python' : p.endsWith('.md') ? 'markdown' : TEX.test(p) ? 'stex' : 'text/plain';

// contenteditable input is what lets the browser spell-check; spell check itself is a separate, switchable option.
export const cm = CodeMirror.fromTextArea($('ed'), {
  lineNumbers: true, lineWrapping: true, matchBrackets: true, styleActiveLine: true, indentUnit: 2,
  inputStyle: 'contenteditable', spellcheck: false,
  extraKeys: {
    'Ctrl-S': () => save(), 'Cmd-S': () => save(),
    'Ctrl-Enter': () => app.compile(), 'Cmd-Enter': () => app.compile(),
    'Ctrl-J': () => app.syncToPdf(), 'Cmd-J': () => app.syncToPdf(),
    'Ctrl-/': c => toggleComment(c), 'Cmd-/': c => toggleComment(c),
    'Ctrl-B': c => toggleCommand(c, 'textbf'), 'Cmd-B': c => toggleCommand(c, 'textbf'),
    'Ctrl-I': c => toggleCommand(c, 'textit'), 'Cmd-I': c => toggleCommand(c, 'textit'),
    'Ctrl-Space': () => app.complete(true),
    'Ctrl-F': () => app.openFindBar(false), 'Cmd-F': () => app.openFindBar(false),
    'Ctrl-H': () => app.openFindBar(true), 'Cmd-Alt-F': () => app.openFindBar(true),
    'F3': () => app.findNext(1), 'Shift-F3': () => app.findNext(-1),
    'Ctrl-G': () => app.findNext(1), 'Shift-Ctrl-G': () => app.findNext(-1),
    'Cmd-G': () => app.findNext(1), 'Shift-Cmd-G': () => app.findNext(-1),
    'Shift-Ctrl-F': () => app.showSearch(), 'Shift-Cmd-F': () => app.showSearch(),
  },
});
app.cm = cm;
// Grammar-checking browser extensions attach to contenteditable areas and rewrite their DOM, which corrupts a
// CodeMirror document. These attributes are their documented opt-out.
for (const [k, v] of [['data-gramm', 'false'], ['data-gramm_editor', 'false'], ['data-enable-grammarly', 'false'], ['data-lt-active', 'false']])
  cm.getInputField().setAttribute(k, v);

function toggleComment(c) {
  const from = c.getCursor('from').line, to = c.getCursor('to').line;
  const lines = []; for (let l = from; l <= to; l++) lines.push(c.getLine(l));
  const all = lines.every(s => /^\s*%/.test(s) || !s.trim());
  c.operation(() => { for (let l = from; l <= to; l++) {
    const s = c.getLine(l);
    if (all) { const m = s.match(/^(\s*)% ?/); if (m) c.replaceRange(m[1], { line: l, ch: 0 }, { line: l, ch: m[0].length }); }
    else if (s.trim()) c.replaceRange('% ', { line: l, ch: 0 });
  } });
}

// Ctrl/Cmd+B and Ctrl/Cmd+I: put the selection in \textbf{} or \textit{}, or take it out again.
function toggleCommand(c, cmd) {
  const from = c.getCursor('from'), to = c.getCursor('to');
  const e = toggleWrap(cmd, c.getLine(from.line).slice(0, from.ch), c.getRange(from, to), c.getLine(to.line).slice(to.ch));
  const start = { line: from.line, ch: from.ch - e.cutBefore };
  c.operation(() => {
    c.replaceRange(e.text, start, { line: to.line, ch: to.ch + e.cutAfter });
    const at = i => c.posFromIndex(c.indexFromPos(start) + i);
    c.setSelection(at(e.select[0]), at(e.select[1]));
  });
}

// ---------- spell check ----------
// LaTeX commands, math and brackets are not words: mark them so the browser does not underline them.
const NO_SPELL = /\bcm-(tag|builtin|keyword|atom|number|bracket|meta|variable-2|variable-3|string-2|qualifier|def)\b/;
cm.on('renderLine', (_cm, _line, elt) => {
  for (const s of elt.querySelectorAll('span[class*="cm-"]')) if (NO_SPELL.test(s.className)) s.spellcheck = false;
});
export function setSpellcheck(on) { cm.setOption('spellcheck', !!on); store.set('spellcheck', !!on); }
setSpellcheck(store.get('spellcheck', false));

// ---------- documents and tabs ----------
const docs = new Map();   // path -> { doc, mtime, gen, encoding }
let tabs = [];

export const isDirty = p => { const d = docs.get(p); return !!d && !d.doc.isClean(d.gen); };
const anyDirty = () => [...docs.keys()].some(isDirty);
const saveTabs = () => store.set(pkey('tabs'), tabs);

export function refreshDirty() {
  document.querySelectorAll('#files .f[data-path]').forEach(e => e.classList.toggle('mod', isDirty(e.dataset.path)));
  document.querySelectorAll('#tabs .tab').forEach(e => e.classList.toggle('mod', isDirty(e.dataset.path)));
  document.title = (anyDirty() ? '● ' : '') + 'Offline TeX Editor';
}
cm.on('change', debounce(refreshDirty, 120));

function renderTabs() {
  $('tabs').replaceChildren(...tabs.map(p => el('div', {
    className: 'tab' + (p === state.current ? ' on' : '') + (isDirty(p) ? ' mod' : ''), title: p, role: 'tab',
    dataset: { path: p }, onclick: () => openFile(p), onauxclick: e => { if (e.button === 1) closeTab(p); },
  }, baseName(p), el('button', { className: 'x', title: 'Close', onclick: e => { e.stopPropagation(); closeTab(p); } },
    el('span', {}, '×')))));
  $('tabs').querySelector('.on')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

async function loadDoc(path) {
  const r = await api('/api/file?path=' + encodeURIComponent(path));
  if (!r.ok) { setStatus(`cannot open ${path}: ${r.error || r.status}`, 'err'); return null; }
  const doc = CodeMirror.Doc(r.content, modeFor(path), 0, r.eol === '\r\n' ? '\r\n' : null);
  const d = { doc, mtime: r.mtime, gen: doc.changeGeneration(), encoding: r.encoding || 'utf-8' };
  docs.set(path, d);
  return d;
}

// Open a file, optionally at a line; opts.ch/opts.len select a range on that line (a search match).
export async function openFile(path, line, opts = {}) {
  if (!docs.has(path)) { if (!(await loadDoc(path))) return false; }
  else checkExternalChange(path);
  app.closePreview?.();
  if (state.current !== path) { cm.swapDoc(docs.get(path).doc); state.current = path; store.set(pkey('lastFile'), path); }
  if (!tabs.includes(path)) { tabs.push(path); saveTabs(); }
  renderTabs(); hideBanner(); markErrors(); markConflicts(); refreshDirty();
  document.querySelectorAll('#files .f').forEach(e => e.classList.toggle('active', e.dataset.path === path));
  if (line) {
    const l = Math.min(cm.lineCount() - 1, Math.max(0, line - 1));
    if (opts.ch !== undefined) cm.setSelection({ line: l, ch: opts.ch }, { line: l, ch: opts.ch + (opts.len || 0) });
    else cm.setCursor({ line: l, ch: 0 });
    cm.scrollIntoView({ line: l, ch: 0 }, cm.getScrollInfo().clientHeight / 2);
    if (opts.flash) { const h = cm.addLineClass(l, 'background', 'line-hit'); setTimeout(() => cm.removeLineClass(h, 'background', 'line-hit'), 1600); }
  }
  app.onFileOpened?.(path);
  cm.focus();
  return true;
}

export function closeTab(path, force = false) {
  if (isDirty(path) && !force) {
    if (path !== state.current) openFile(path);
    showBanner(`${path} has unsaved changes.`, 'Save and close', async () => { if (await save(path, { compile: false })) closeTab(path, true); },
               'Discard changes', () => closeTab(path, true), 'Cancel', hideBanner);
    return;
  }
  const i = tabs.indexOf(path);
  tabs = tabs.filter(t => t !== path); saveTabs(); docs.delete(path); hideBanner();
  if (state.current === path) {
    state.current = null;
    const next = tabs[i] || tabs[i - 1] || app.project?.main;
    if (next) openFile(next); else renderTabs();
  } else renderTabs();
}

export async function restoreTabs(main) {
  tabs = store.get(pkey('tabs'), []).filter(p => app.project.files.includes(p));
  const last = store.get(pkey('lastFile'), null);
  await openFile(app.project.files.includes(last) ? last : main);
}

// After a rename or move on disk: keep open documents and tabs (also those inside a renamed folder).
export function renameDoc(from, to) {
  const map = p => p === from ? to : p.startsWith(from + '/') ? to + p.slice(from.length) : p;
  for (const [p, d] of [...docs]) { const q = map(p); if (q !== p) { docs.delete(p); docs.set(q, d); } }
  tabs = tabs.map(map); saveTabs();
  if (state.current) state.current = map(state.current);
  renderTabs();
}
// After a delete: close the documents without asking (the file is in the trash).
export function dropDoc(path) {
  for (const p of [...docs.keys()]) if (p === path || p.startsWith(path + '/')) { docs.delete(p); tabs = tabs.filter(t => t !== p); }
  saveTabs();
  if (state.current === path || state.current?.startsWith(path + '/')) { state.current = null; openFile(tabs[0] || app.project.main); }
  else renderTabs();
}

// ---------- saving ----------
export async function save(path = state.current, { force = false, compile = true } = {}) {
  if (!path || !docs.has(path)) return true;
  const d = docs.get(path);
  if (!isDirty(path) && !force) { if (compile && $('auto').checked) app.compile(); return true; }
  const r = await post('/api/file', { path, content: d.doc.getValue(), mtime: d.mtime, force, encoding: d.encoding });
  if (r.status === 409) {
    if (path !== state.current) await openFile(path);
    showBanner(`${path} changed on disk since you opened it.`, 'Overwrite with mine', () => save(path, { force: true }),
               'Load disk version', () => reloadFromDisk(path));
    return false;
  }
  if (!r.ok) { setStatus(`could not save ${path}: ${r.error || r.status}`, 'err'); return false; }
  d.mtime = r.mtime; d.gen = d.doc.changeGeneration(); refreshDirty(); hideBanner();
  setStatus('saved ' + path, 'ok');
  app.onSaved?.(path);
  if (compile && $('auto').checked) app.compile();
  return true;
}
export async function saveAll() {
  for (const p of [...docs.keys()]) if (isDirty(p) && !(await save(p, { compile: false }))) return false;
  return true;
}
export async function reloadFromDisk(path) {
  const d = docs.get(path); if (!d) return;
  const r = await api('/api/file?path=' + encodeURIComponent(path));
  if (!r.ok) return;
  const cur = path === state.current ? cm.getCursor() : null, top = path === state.current ? cm.getScrollInfo().top : null;
  d.doc.setValue(r.content); d.mtime = r.mtime; d.encoding = r.encoding; d.gen = d.doc.changeGeneration();
  if (cur) { cm.setCursor(cur); cm.scrollTo(null, top); }
  hideBanner(); refreshDirty(); markConflicts();
}
// Open documents that are not modified pick up changes made on disk (after a git pull or a replace-all).
export async function reloadClean() { for (const p of [...docs.keys()]) if (!isDirty(p)) await reloadFromDisk(p); }

// Another editor (or git) changed the file: reload it when we have no edits, else ask.
export async function checkExternalChange(path = state.current) {
  const d = path && docs.get(path); if (!d) return;
  const r = await api('/api/mtime?path=' + encodeURIComponent(path));
  if (r.status === 404 || (r.ok && r.mtime === null)) return;
  if (r.ok && r.mtime && Math.abs(r.mtime - d.mtime) > 1e-6) {
    if (!isDirty(path)) reloadFromDisk(path);
    else if (path === state.current && !$('banner').classList.contains('show'))
      showBanner(`${path} was changed on disk (another editor, git, or a replace).`, 'Load disk version', () => reloadFromDisk(path),
                 'Keep mine', () => { d.mtime = r.mtime; hideBanner(); });
  }
}

// ---------- banner ----------
export function showBanner(text, a, fa, b, fb, c, fc) {
  $('bannerText').textContent = text;
  [['bannerA', a, fa], ['bannerB', b, fb], ['bannerC', c, fc]].forEach(([id, label, fn]) => {
    $(id).hidden = !label; $(id).textContent = label || ''; $(id).onclick = fn || null;
  });
  $('banner').classList.add('show');
}
export function hideBanner() { $('banner').classList.remove('show'); }

// ---------- error and conflict marks ----------
let errorMarks = [];
export function markErrors() {
  errorMarks.forEach(h => cm.removeLineClass(h, 'background', 'line-error')); errorMarks = [];
  if (!state.lastResult || !state.current) return;
  (state.lastResult.errors || []).filter(e => e.file === state.current && e.line).forEach(e => {
    const h = cm.getLineHandle(e.line - 1); if (h) { cm.addLineClass(h, 'background', 'line-error'); errorMarks.push(h); }
  });
}

let conflictMarks = [];
// Highlight git conflict blocks: <<<<<<< ours ======= theirs >>>>>>>
export function markConflicts() {
  conflictMarks.forEach(([h, cls]) => cm.removeLineClass(h, 'background', cls)); conflictMarks = [];
  if (!cm.getValue().includes('<<<<<<<')) return;
  let mode = null;
  const add = (h, cls) => { cm.addLineClass(h, 'background', cls); conflictMarks.push([h, cls]); };
  cm.eachLine(h => {
    const t = h.text;
    if (t.startsWith('<<<<<<<')) { add(h, 'cf-marker'); mode = 'ours'; }
    else if (mode && t.startsWith('|||||||')) { add(h, 'cf-marker'); mode = 'base'; }
    else if (mode && t.startsWith('=======')) { add(h, 'cf-marker'); mode = 'theirs'; }
    else if (mode && t.startsWith('>>>>>>>')) { add(h, 'cf-marker'); mode = null; }
    else if (mode === 'ours') add(h, 'cf-ours');
    else if (mode === 'theirs') add(h, 'cf-theirs');
  });
}
cm.on('change', debounce(markConflicts, 300));
cm.on('cursorActivity', debounce(() => app.onCursor?.(), 150));

window.addEventListener('beforeunload', e => { if (anyDirty()) { e.preventDefault(); e.returnValue = ''; } });

Object.assign(app, { openFile, closeTab, restoreTabs, renameDoc, dropDoc, save, saveAll, reloadFromDisk, reloadClean,
                     checkExternalChange, showBanner, hideBanner, markErrors, markConflicts, refreshDirty, isDirty,
                     setSpellcheck });
