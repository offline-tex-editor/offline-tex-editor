// The ⚙ popover: main document, engine, compile only one chapter, draft mode, spell check, word count, shortcuts.
import { $, el, app, state, project, api, post, setStatus, store } from './util.js';

const SOURCES = {
  default: 'the default. To use XeLaTeX or LuaLaTeX, put "% !TEX program = xelatex" (or lualatex) on the first line of the main file.',
  '% !TEX program': 'set by "% !TEX program" in the main file.',
  latexmkrc: "chosen by the project's latexmkrc ($pdf_mode).",
  '--engine': 'set with --engine when the editor was started.',
};

export async function refreshSettings() {
  const s = await api('/api/settings');
  if (!s.ok) return;
  state.settings = s;
  project.main = s.main; $('mainDoc').textContent = s.main;
  const roots = s.roots.includes(s.main) ? s.roots : [s.main, ...s.roots];
  $('mainSelect').replaceChildren(...roots.map(r => el('option', { value: r, selected: r === s.main }, r)));
  $('onlySelect').replaceChildren(el('option', { value: '' }, 'Whole document'),
    ...s.includes.map(i => el('option', { value: i, selected: i === s.only }, i)));
  $('onlySelect').disabled = !s.includes.length;
  $('onlySelect').title = s.includes.length ? 'Compile just one \\include\'d file; page numbers and references of the others are kept'
                                            : 'The main document has no \\include{…} files';
  $('draftChk').checked = !!s.draft;
  $('engineNote').textContent = `Engine: ${s.engine || 'from latexmkrc'}, ${SOURCES[s.engine_source] || s.engine_source}`;
  $('shellNote').textContent = s.shell_escape
    ? 'Shell escape is on (--shell-escape): this project can run programs when it compiles.'
    : 'Shell escape is off. Packages such as minted (before v3) or svg need --shell-escape.';
  const missing = Object.entries(s.tools).filter(([, ok]) => !ok).map(([t]) => t);
  if (missing.length) $('shellNote').textContent += ` Not installed: ${missing.join(', ')}.`;
}

async function change(body, what) {
  const r = await post('/api/settings', body);
  if (!r.ok) { setStatus(r.error, 'err'); return refreshSettings(); }
  await refreshSettings();
  setStatus(what, 'ok');
  return r;
}
$('mainSelect').onchange = async () => {
  const r = await change({ main: $('mainSelect').value }, `main document: ${$('mainSelect').value}`);
  if (!r) return;
  app.resetPdf(); app.renderFiles(); app.refreshOutline(); app.compile();
};
$('onlySelect').onchange = async () => { if (await change({ only: $('onlySelect').value || null }, $('onlySelect').value ? `compiling only ${$('onlySelect').value}` : 'compiling the whole document')) app.compile(); };
$('draftChk').onchange = async () => { if (await change({ draft: $('draftChk').checked }, $('draftChk').checked ? 'draft mode: images are boxes' : 'draft mode off')) app.compile(); };
$('spellChk').onchange = () => app.setSpellcheck($('spellChk').checked);
$('spellChk').checked = store.get('spellcheck', false);

// The project's sources as a .zip, named after its folder. Open files are saved first, so the .zip has what is on
// screen; if one cannot be saved, nothing is downloaded. The server tells about a missing or out-of-date .bbl.
$('exportBtn').onclick = async () => {
  const note = $('exportNote');
  note.textContent = 'saving…';
  if (!(await app.saveAll())) { note.textContent = 'Not downloaded: an open file could not be saved.'; return; }
  const r = await fetch('/api/export');
  if (!r.ok) { note.textContent = `Not downloaded: ${(await r.json().catch(() => ({}))).error || r.status}`; return; }
  const url = URL.createObjectURL(await r.blob()), name = project.root.split(/[\\/]/).filter(Boolean).pop() || 'project';
  el('a', { href: url, download: name + '.zip' }).click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  const said = r.headers.get('X-Export-Note');
  note.textContent = said ? decodeURIComponent(said) : 'Downloaded the saved sources.';
};

$('wcBtn').onclick = async () => {
  $('wcNote').textContent = 'counting…';
  const r = await api('/api/wordcount');
  $('wcNote').textContent = r.ok ? `in ${project.main} and the files it includes` : '';
  if (!r.ok) { $('wcOut').replaceChildren(el('div', { className: 'note' }, r.error)); return; }
  const rows = [['Words in text', r.text], ['Words in headings', r.headers], ['Words in captions and the like', r.outside],
                ['Headings', r.n_headers], ['Figures and tables', r.floats], ['Inline formulas', r.math_inline], ['Displayed formulas', r.math_display]];
  $('wcOut').replaceChildren(el('table', {}, ...rows.filter(([, v]) => v !== undefined).map(([k, v]) => el('tr', {}, el('td', {}, k), el('td', {}, String(v))))));
};

// ---------- open and close ----------
export function openTools() {
  const t = $('tools'), r = $('toolsBtn').getBoundingClientRect();
  t.hidden = false;
  t.style.top = (r.bottom + 6) + 'px';
  t.style.left = Math.max(8, Math.min(innerWidth - t.offsetWidth - 8, r.right - t.offsetWidth)) + 'px';
  $('toolsBtn').setAttribute('aria-expanded', 'true');
  refreshSettings();
}
export function closeTools() { $('tools').hidden = true; $('toolsBtn').setAttribute('aria-expanded', 'false'); }
$('toolsBtn').onclick = () => $('tools').hidden ? openTools() : closeTools();
document.addEventListener('mousedown', e => { if (!$('tools').hidden && !$('tools').contains(e.target) && e.target !== $('toolsBtn')) closeTools(); });

Object.assign(app, { refreshSettings, openTools, closeTools });
