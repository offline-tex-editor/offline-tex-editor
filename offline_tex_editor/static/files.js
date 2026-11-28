// The file list: tree, filter, new/rename/delete, upload (button or drag and drop), image and PDF previews.
import { $, el, app, state, project, store, pkey, api, post, setStatus, dirOf, baseName, icon } from './util.js';
import { currentFolder, followRename, stillListed } from './folders.js';
import { figureFolder, pastedName, texSafeName, includeGraphics } from './paths.js';

const IMAGE = /\.(png|jpe?g|gif|svg|webp|bmp)$/i;
const fileIcon = p => icon(IMAGE.test(p) ? 'image' : /\.bib$/i.test(p) ? 'bib' : /\.(tex|ltx|sty|cls)$/i.test(p) ? 'tex' : 'file');
// The folder that Add files, New file and New folder work in (see folders.js); it follows renames and is forgotten when
// what was clicked is gone.
let clicked = null;   // { path, dir } of the last row clicked
const currentDir = () => currentFolder(clicked, state.current);

export async function loadFiles() {
  const r = await api('/api/files');
  if (!r.ok) return setStatus('cannot list files: ' + (r.error || r.status), 'err');
  Object.assign(project, { root: r.root, main: r.main, files: r.files || [], assets: r.assets || [], dirs: r.dirs || [] });
  clicked = stillListed(clicked, [...project.files, ...project.assets], project.dirs);
  $('mainDoc').textContent = project.main;
  renderFiles();
}

function tree() {
  const root = { dirs: new Map(), files: [] };
  const node = d => {
    let n = root;
    if (d) for (const part of d.split('/')) { if (!n.dirs.has(part)) n.dirs.set(part, { dirs: new Map(), files: [] }); n = n.dirs.get(part); }
    return n;
  };
  (project.dirs || []).forEach(d => node(d));
  project.files.forEach(f => node(dirOf(f)).files.push({ path: f, asset: false }));
  project.assets.forEach(f => node(dirOf(f)).files.push({ path: f, asset: true }));
  return root;
}

export function renderFiles() {
  const q = $('filter').value.toLowerCase().trim(), box = $('files');
  const collapsed = new Set(store.get(pkey('collapsed'), []));
  const rows = [];
  const fileRow = (f, depth) => {
    const row = el('div', { className: 'f' + (f.asset ? ' asset' : '') + (f.path === state.current ? ' active' : '') + (app.isDirty?.(f.path) ? ' mod' : ''),
                            title: f.path, dataset: { path: f.path }, onclick: () => { clicked = { path: f.path, dir: false }; f.asset ? preview(f.path) : app.openFile(f.path); } },
      fileIcon(f.path), el('span', { className: 'nm' }, baseName(f.path)),
      f.path === project.main ? el('span', { className: 'badge', title: 'Main document' }, 'main') : null,
      actions(f.path, false));
    row.style.paddingLeft = (24 + depth * 14) + 'px';
    rows.push(row);
  };
  const walk = (n, path, depth) => {
    const files = n.files.filter(f => !q || f.path.toLowerCase().includes(q))
      .sort((a, b) => (a.path === project.main ? -1 : b.path === project.main ? 1 : 0) || a.asset - b.asset || a.path.localeCompare(b.path));
    files.forEach(f => fileRow(f, depth));
    for (const name of [...n.dirs.keys()].sort((a, b) => a.localeCompare(b))) {
      const d = path ? `${path}/${name}` : name, child = n.dirs.get(name);
      if (q && !hasMatch(child, q)) continue;
      const open = q || !collapsed.has(d);
      const head = el('div', { className: 'dir toggle' + (open ? ' open' : '') + (clicked?.dir && clicked.path === d ? ' cur' : ''), title: d, dataset: { dir: d }, onclick: () => {
        clicked = { path: d, dir: true };
        const s = new Set(store.get(pkey('collapsed'), [])); s.has(d) ? s.delete(d) : s.add(d); store.set(pkey('collapsed'), [...s]); renderFiles();
      } }, icon('chevron', 'chev'), icon('folder', 'fold'), el('span', { className: 'nm' }, name), actions(d, true));
      head.style.paddingLeft = (6 + depth * 14) + 'px';
      rows.push(head);
      if (open) walk(child, d, depth + 1);
    }
  };
  walk(tree(), '', 0);
  box.replaceChildren(...rows);
}
// a click below the rows makes the project folder the current folder again
$('files').addEventListener('click', e => { if (e.target === $('files')) { clicked = { path: '', dir: true }; renderFiles(); } });
const hasMatch = (n, q) => n.files.some(f => f.path.toLowerCase().includes(q)) || [...n.dirs.values()].some(c => hasMatch(c, q));
$('filter').oninput = renderFiles;

function actions(path, isDir) {
  const stop = fn => e => { e.stopPropagation(); fn(e); };
  return el('span', { className: 'acts' },
    isDir ? el('button', { className: 'icon', title: 'New file here', onclick: stop(() => openForm('file', path + '/')) }, icon('plus')) : null,
    el('button', { className: 'icon', title: 'Rename or move', onclick: stop(() => openForm('rename', path)) }, icon('pencil')),
    path === project.main ? null : el('button', { className: 'icon del', title: 'Delete (moves it to build/.editor-trash)',
                                                  onclick: stop(e => confirmDelete(e.currentTarget.closest('.f, .dir'), path)) }, icon('trash')));
}

function confirmDelete(row, path) {
  const acts = row.querySelector('.acts');
  row.classList.add('confirm');
  acts.replaceChildren(el('span', { className: 'muted' }, 'Delete? '),
    el('button', { className: 'danger', onclick: async e => { e.stopPropagation(); await remove(path); } }, 'Yes'),
    el('button', { onclick: e => { e.stopPropagation(); renderFiles(); } }, 'No'));
}

async function remove(path) {
  const r = await post('/api/fs/delete', { path });
  if (!r.ok) { renderFiles(); return setStatus(`could not delete ${path}: ${r.error}`, 'err'); }
  app.dropDoc(path); await loadFiles(); app.filesChanged?.();
  setStatus(`moved ${path} to ${r.trash}`, 'ok');
}

// ---------- new / rename form ----------
let form = null;   // { kind: 'file' | 'folder' | 'rename', from }
function openForm(kind, value) {
  form = { kind, from: kind === 'rename' ? value : null };
  $('fsForm').hidden = false;
  const input = $('fsInput');
  input.value = value || (currentDir() ? currentDir() + '/' : '');
  $('fsHint').textContent = kind === 'rename' ? 'New path (Enter to rename, Esc to cancel)'
    : kind === 'folder' ? 'Folder path (Enter to create, Esc to cancel)' : 'File path, e.g. chapters/intro.tex (Enter to create)';
  input.focus();
  if (kind === 'rename') { const b = value.lastIndexOf('/') + 1, dot = value.lastIndexOf('.'); input.setSelectionRange(b, dot > b ? dot : value.length); }
  else input.setSelectionRange(input.value.length, input.value.length);
}
function closeForm() { form = null; $('fsForm').hidden = true; }
$('fsInput').addEventListener('keydown', async e => {
  if (e.key === 'Escape') return closeForm();
  if (e.key !== 'Enter' || !form) return;
  e.preventDefault();
  const path = $('fsInput').value.trim().replace(/^\/+|\/+$/g, '');
  if (!path) return;
  if (form.kind === 'rename') {
    if (path === form.from) return closeForm();
    if (!(await app.saveAll())) return;
    const r = await post('/api/fs/rename', { from: form.from, to: path });
    if (!r.ok) return ($('fsHint').textContent = r.error);
    app.renameDoc(form.from, r.path);
    clicked = followRename(clicked, form.from, r.path);
    if (r.main !== project.main) { project.main = r.main; app.refreshSettings?.(); }
    closeForm(); await loadFiles(); app.filesChanged?.();
    setStatus(`renamed to ${r.path}`, 'ok');
  } else {
    const kind = form.kind;
    const r = await post('/api/fs/new', { path: kind === 'file' && !/\.[A-Za-z0-9]+$/.test(path) ? path + '.tex' : path, kind });
    if (!r.ok) return ($('fsHint').textContent = r.error);
    closeForm(); await loadFiles(); app.filesChanged?.();
    if (kind === 'file') app.openFile(r.path);
    setStatus(`created ${r.path}`, 'ok');
  }
});
$('newFileBtn').onclick = () => openForm('file');
$('newFolderBtn').onclick = () => openForm('folder');

// ---------- upload ----------
const readBase64 = f => new Promise((res, rej) => {
  const r = new FileReader();
  r.onload = () => res(String(r.result).split(',', 2)[1] || '');
  r.onerror = () => rej(r.error);
  r.readAsDataURL(f);
});
const ask = text => new Promise(res => app.showBanner(text, 'Replace', () => { app.hideBanner(); res(true); }, 'Skip', () => { app.hideBanner(); res(false); }));

// Adds files to the project folder `dir` and returns the paths added. names: a name for each file instead of its own.
async function upload(files, dir, names) {
  const added = [];
  for (const [i, f] of files.entries()) {
    const path = (dir ? dir + '/' : '') + (names ? names[i] : f.name);
    const data = await readBase64(f);
    let r = await post('/api/fs/upload', { path, data });
    if (r.status === 409 && r.exists && await ask(`${path} already exists.`)) r = await post('/api/fs/upload', { path, data, replace: true });
    if (r.ok) added.push(r.path); else if (r.status !== 409) setStatus(`could not add ${path}: ${r.error}`, 'err');
  }
  const n = added.length;
  if (n) { await loadFiles(); app.filesChanged?.(); setStatus(`added ${n} file${n > 1 ? 's' : ''}${dir ? ' to ' + dir : ''}`, 'ok'); }
  return added;
}
$('uploadBtn').onclick = () => $('uploadInput').click();
// the tooltip names the folder at the time it is shown (opening a file from a tab changes it too)
const uploadTitle = () => { $('uploadBtn').title = `Add files to ${currentDir() || 'the project folder'} (or drop them on a folder)`; };
$('uploadBtn').addEventListener('pointerenter', uploadTitle);
$('uploadBtn').addEventListener('focus', uploadTitle);
$('uploadInput').onchange = async () => {
  const files = [...$('uploadInput').files]; $('uploadInput').value = '';
  await upload(files, currentDir());
};
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
$('files').addEventListener('dragover', e => {
  if (!hasFiles(e)) return;
  e.preventDefault(); $('files').classList.add('drop');
  document.querySelectorAll('#files .dir.drop').forEach(d => d.classList.remove('drop'));
  e.target.closest?.('.dir')?.classList.add('drop');
});
$('files').addEventListener('dragleave', e => { if (!$('files').contains(e.relatedTarget)) $('files').classList.remove('drop'); });
$('files').addEventListener('drop', e => {
  if (!hasFiles(e)) return;
  e.preventDefault(); $('files').classList.remove('drop');
  const t = e.target.closest?.('[data-dir], [data-path]');
  upload([...e.dataTransfer.files], t ? (t.dataset.dir ?? dirOf(t.dataset.path)) : '');
});

// ---------- images pasted or dropped into the editor ----------
// They are added to the project like uploaded files, and an \includegraphics for each goes where they were put.
const GRAPHIC = /\.(pdf|png|jpe?g|eps)$/i;   // what \includegraphics reads
const texOpen = () => /\.tex$/i.test(state.current || '');
async function insertImages(files, pos, pasted) {
  const dir = figureFolder(project.dirs || [], project.main), now = new Date();
  const ext = f => f.type === 'image/jpeg' ? 'jpg' : 'png';
  const names = files.map((f, i) => pasted ? pastedName(now, ext(f), files.length > 1 ? i + 1 : 0) : texSafeName(f.name));
  // The upload takes a while: the \includegraphics goes where the files were put, in that document, even after
  // typing elsewhere or switching to another document in the meantime.
  const path = state.current, doc = app.cm.getDoc(), mark = doc.setBookmark(pos);
  const added = await upload(files, dir, names);
  const at = mark.find();
  mark.clear();
  if (!added.length) return;   // nothing uploaded (refused, or replacing skipped): nothing to put in
  const renamed = pasted ? [] : files.map((f, i) => [f.name, names[i]]).filter(([a, b]) => a !== b).map(([a, b]) => `${a} as ${b}`);
  const why = renamed.length ? `; saved ${renamed.join(', ')}, since \\includegraphics cannot read # % " \\ { } or repeated spaces` : '';
  if (app.docOf(path) !== doc || !at) return setStatus(`added ${added.join(', ')}, but ${path} was closed, so no \\includegraphics was put in${why}`, 'err');
  // on lines of their own, with the paths as LaTeX sees them, from the main document's folder
  const line = doc.getLine(at.line), before = line.slice(0, at.ch).trim() ? '\n' : '', after = line.slice(at.ch).trim() ? '\n' : '';
  doc.replaceRange(before + added.map(p => includeGraphics(p, project.main)).join('\n') + after, at);
  app.refreshDirty?.();
  if (why || path !== state.current) setStatus(`added ${added.length} file${added.length > 1 ? 's' : ''} and put \\includegraphics in ${path}${why}`, 'ok');
  if (path === state.current) app.cm.focus();
}
app.cm.on('paste', (cm, e) => {
  const d = e.clipboardData;
  // Copied text often comes with a picture of itself (from word processors and web pages); then paste the text.
  if (!texOpen() || !d || d.getData('text/plain')) return;
  const files = [...d.files].filter(f => f.type === 'image/png' || f.type === 'image/jpeg');
  if (!files.length) return;
  e.preventDefault();
  insertImages(files, cm.getCursor(), true);
});
app.cm.on('drop', (cm, e) => {
  const files = [...(e.dataTransfer?.files || [])].filter(f => GRAPHIC.test(f.name));
  if (!texOpen() || !files.length) return;
  e.preventDefault();
  insertImages(files, cm.coordsChar({ left: e.clientX, top: e.clientY }, 'window'), false);
});

// ---------- previews ----------
export async function preview(path) {
  const body = $('previewBody');
  body.replaceChildren(el('div', { className: 'muted' }, 'Loading…'));
  $('previewTitle').textContent = path; $('preview').hidden = false;
  const url = '/api/raw?path=' + encodeURIComponent(path);
  if (IMAGE.test(path)) body.replaceChildren(el('img', { src: url, alt: path }));
  else if (/\.pdf$/i.test(path)) {
    const canvas = await app.renderPdfPage(url).catch(() => null);
    body.replaceChildren(canvas || el('div', { className: 'muted' }, 'Cannot show this PDF.'));
  } else body.replaceChildren(el('div', { className: 'muted' }, 'No preview for this file type.'));
}
export function closePreview() { $('preview').hidden = true; }
$('previewClose').onclick = closePreview;

Object.assign(app, { loadFiles, renderFiles, preview, closePreview });
