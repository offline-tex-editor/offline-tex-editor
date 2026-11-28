// Autocompletion: \ref labels, \cite keys, environments, file names and commands (built-in and the project's own).
import { el, app, project, api } from './util.js';
import { fromMain } from './paths.js';
import { refArgument, argumentEdit } from './refs.js';

// [name, number of {} arguments]
const BUILTIN = [
  ['section', 1], ['subsection', 1], ['subsubsection', 1], ['chapter', 1], ['part', 1], ['paragraph', 1],
  ['section*', 1], ['subsection*', 1], ['chapter*', 1], ['label', 1], ['ref', 1], ['eqref', 1], ['pageref', 1],
  ['autoref', 1], ['cref', 1], ['Cref', 1], ['cite', 1], ['citep', 1], ['citet', 1], ['parencite', 1], ['textcite', 1],
  ['autocite', 1], ['nocite', 1], ['footnote', 1], ['footnotemark', 0], ['url', 1], ['href', 2], ['emph', 1],
  ['textbf', 1], ['textit', 1], ['texttt', 1], ['textsc', 1], ['textrm', 1], ['textsf', 1], ['underline', 1],
  ['mathbf', 1], ['mathrm', 1], ['mathit', 1], ['mathcal', 1], ['mathbb', 1], ['mathfrak', 1], ['mathsf', 1],
  ['boldsymbol', 1], ['operatorname', 1], ['text', 1], ['frac', 2], ['dfrac', 2], ['tfrac', 2], ['sqrt', 1],
  ['binom', 2], ['overline', 1], ['underbrace', 1], ['overbrace', 1], ['hat', 1], ['bar', 1], ['tilde', 1],
  ['vec', 1], ['dot', 1], ['ddot', 1], ['widehat', 1], ['widetilde', 1], ['left', 0], ['right', 0], ['sum', 0],
  ['prod', 0], ['int', 0], ['iint', 0], ['oint', 0], ['lim', 0], ['infty', 0], ['partial', 0], ['nabla', 0],
  ['cdot', 0], ['cdots', 0], ['ldots', 0], ['dots', 0], ['times', 0], ['leq', 0], ['geq', 0], ['neq', 0],
  ['approx', 0], ['equiv', 0], ['sim', 0], ['propto', 0], ['in', 0], ['notin', 0], ['subset', 0], ['subseteq', 0],
  ['cup', 0], ['cap', 0], ['forall', 0], ['exists', 0], ['rightarrow', 0], ['leftarrow', 0], ['Rightarrow', 0],
  ['Leftrightarrow', 0], ['mapsto', 0], ['to', 0], ['alpha', 0], ['beta', 0], ['gamma', 0], ['delta', 0],
  ['epsilon', 0], ['varepsilon', 0], ['zeta', 0], ['eta', 0], ['theta', 0], ['vartheta', 0], ['iota', 0],
  ['kappa', 0], ['lambda', 0], ['mu', 0], ['nu', 0], ['xi', 0], ['pi', 0], ['rho', 0], ['sigma', 0], ['tau', 0],
  ['upsilon', 0], ['phi', 0], ['varphi', 0], ['chi', 0], ['psi', 0], ['omega', 0], ['Gamma', 0], ['Delta', 0],
  ['Theta', 0], ['Lambda', 0], ['Xi', 0], ['Pi', 0], ['Sigma', 0], ['Phi', 0], ['Psi', 0], ['Omega', 0],
  ['begin', 1], ['end', 1], ['item', 0], ['includegraphics', 1], ['caption', 1], ['centering', 0], ['input', 1],
  ['include', 1], ['includeonly', 1], ['usepackage', 1], ['documentclass', 1], ['newcommand', 2],
  ['renewcommand', 2], ['DeclareMathOperator', 2], ['title', 1], ['author', 1], ['date', 1], ['maketitle', 0],
  ['tableofcontents', 0], ['listoffigures', 0], ['listoftables', 0], ['bibliography', 1],
  ['bibliographystyle', 1], ['printbibliography', 0], ['addbibresource', 1], ['appendix', 0], ['clearpage', 0],
  ['newpage', 0], ['noindent', 0], ['vspace', 1], ['hspace', 1], ['quad', 0], ['qquad', 0], ['hline', 0],
  ['toprule', 0], ['midrule', 0], ['bottomrule', 0], ['multicolumn', 3], ['multirow', 3], ['textwidth', 0],
  ['linewidth', 0], ['small', 0], ['footnotesize', 0], ['large', 0], ['Large', 0], ['todo', 1], ['verb', 0],
];
const ENVS = ['itemize', 'enumerate', 'description', 'figure', 'figure*', 'table', 'table*', 'tabular', 'tabularx',
  'equation', 'equation*', 'align', 'align*', 'gather', 'gather*', 'multline', 'multline*', 'split', 'cases',
  'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'array', 'center', 'flushleft', 'flushright', 'quote', 'quotation',
  'verbatim', 'minipage', 'abstract', 'theorem', 'lemma', 'proof', 'definition', 'corollary', 'proposition',
  'remark', 'example', 'frame', 'columns', 'column', 'block', 'tikzpicture', 'lstlisting', 'minted', 'subfigure',
  'algorithm', 'algorithmic', 'thebibliography', 'document', 'appendices', 'landscape'];
const IMAGE = /\.(pdf|png|jpe?g|eps|svg)$/i;

let data = { labels: [], bib: [], commands: [] };
export async function refreshCompletions() { const r = await api('/api/labels'); if (r.ok) data = r; }

// What can be completed at the cursor: { kind, token, from } or null.
function context(cm) {
  const cur = cm.getCursor(), before = cm.getLine(cur.line).slice(0, cur.ch);
  const at = (kind, token, extra) => ({ kind, token, from: cur.ch - token.length, ...extra });
  const last = s => s.slice(s.lastIndexOf(',') + 1).trimStart();
  let m;
  const ref = refArgument(before);
  if (ref) return at('ref', last(ref.typed), { close: ref.close });
  if ((m = before.match(/\\(?:[a-zA-Z]*cite[a-zA-Z]*|nocite)\*?(?:\[[^\]]*\]){0,2}\{([^{}]*)$/))) return at('cite', last(m[1]));
  if ((m = before.match(/\\(begin|end)\{([a-zA-Z*]*)$/))) return at(m[1], m[2]);
  if ((m = before.match(/\\(input|include|subfile|includegraphics|bibliography|addbibresource|includeonly)(?:\[[^\]]*\])?\{([^{}]*)$/))) {
    const cmd = m[1], token = cmd === 'bibliography' || cmd === 'includeonly' ? last(m[2]) : m[2];
    const rel = f => fromMain(f, project.main);   // LaTeX runs in the main document's folder
    let files;
    if (cmd === 'includegraphics') files = project.assets.filter(f => IMAGE.test(f)).map(rel);
    else if (cmd === 'bibliography') files = project.files.filter(f => f.endsWith('.bib')).map(f => rel(f).slice(0, -4));
    else if (cmd === 'addbibresource') files = project.files.filter(f => f.endsWith('.bib')).map(rel);
    else if (cmd === 'input') files = project.files.filter(f => /\.(tex|tikz)$/.test(f)).map(rel);
    else files = project.files.filter(f => f.endsWith('.tex')).map(f => rel(f).slice(0, -4))
      // \include writes an .aux under the name it is given, and TeX Live refuses to write to ../ (openout_any = p)
      .filter(f => cmd === 'subfile' || !f.startsWith('../'));
    return at('file', token, { files });
  }
  if ((m = before.match(/\\([a-zA-Z@]*\*?)$/))) return at('cmd', m[1]);
  return null;
}

function candidates(ctx) {
  let all;
  if (ctx.kind === 'ref') all = data.labels.map(l => ({ text: l.key, detail: l.context || `${l.file}:${l.line}` }));
  else if (ctx.kind === 'cite') all = data.bib.map(b => ({ text: b.key, detail: [b.author.split(/\s+and\s+/)[0], b.year, b.title].filter(Boolean).join(' · ') }));
  else if (ctx.kind === 'begin' || ctx.kind === 'end') all = [...new Set([...ENVS, ...data.commands.filter(c => c.env).map(c => c.name)])].map(text => ({ text }));
  else if (ctx.kind === 'file') all = ctx.files.map(text => ({ text }));
  else {
    const own = data.commands.filter(c => !c.env).map(c => ({ text: c.name, args: c.args, detail: `defined in ${c.file}` }));
    const seen = new Set(own.map(c => c.text));
    all = [...own, ...BUILTIN.filter(([n]) => !seen.has(n)).map(([text, args]) => ({ text, args }))];
  }
  const t = ctx.token.toLowerCase(), out = [];
  for (const it of all) {
    const i = it.text.toLowerCase().indexOf(t);
    // citations also match on author and title
    const rank = i === 0 ? 0 : i > 0 ? 1 : ctx.kind === 'cite' && t && it.detail.toLowerCase().includes(t) ? 2 : -1;
    if (rank >= 0 && !(ctx.kind === 'cmd' && it.text === ctx.token)) out.push([rank, it.text.length, it]);
  }
  return out.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2].text.localeCompare(b[2].text)).slice(0, 200).map(x => x[2]);
}

// ---------- the dropdown ----------
let box = null, active = null;   // active: { ctx, list, sel, line }
const keys = {
  Up: () => move(-1), Down: () => move(1), PageUp: () => move(-8), PageDown: () => move(8),
  Enter: () => accept(), Tab: () => accept(), Esc: () => close(),
};

function render() {
  box.replaceChildren(...active.list.map((it, i) => el('li', {
    className: i === active.sel ? 'on' : '', role: 'option', onmousedown: e => { e.preventDefault(); active.sel = i; accept(); },
  }, el('span', {}, it.text), it.detail ? el('span', { className: 'd' }, it.detail) : null)));
  box.children[active.sel]?.scrollIntoView({ block: 'nearest' });
}
function move(d) { active.sel = Math.max(0, Math.min(active.list.length - 1, active.sel + d)); render(); }

export function close() {
  if (!active) return;
  box.hidden = true; app.cm.removeKeyMap(keys); active = null;
}

// explicit: Ctrl-Space (show even with nothing typed); otherwise only when the context is worth a popup.
export function complete(explicit = false) {
  const cm = app.cm, ctx = context(cm);
  if (!ctx || (!explicit && ctx.kind === 'cmd' && ctx.token.length < 2)) return close();
  const list = candidates(ctx);
  if (!list.length) return close();
  if (!box) box = document.body.appendChild(el('ul', { className: 'complete', role: 'listbox' }));
  const wasOpen = !!active;
  active = { ctx, list, sel: 0, line: cm.getCursor().line };
  if (!wasOpen) cm.addKeyMap(keys);
  box.hidden = false; render();
  const pos = cm.cursorCoords({ line: active.line, ch: ctx.from }, 'window');
  box.style.left = Math.min(pos.left, innerWidth - box.offsetWidth - 8) + 'px';
  box.style.top = (pos.bottom + box.offsetHeight + 4 > innerHeight ? pos.top - box.offsetHeight - 2 : pos.bottom + 2) + 'px';
}

function accept() {
  const cm = app.cm, it = active.list[active.sel], ctx = active.ctx, cur = cm.getCursor(), line = cm.getLine(cur.line);
  const word = ctx.kind === 'cmd' ? /[a-zA-Z@*]/ : /[^\s,{}]/;
  let to = cur.ch; while (to < line.length && word.test(line[to])) to++;
  const from = { line: cur.line, ch: ctx.from };
  close();
  if (ctx.kind === 'cmd') {
    cm.replaceRange(it.text + '{}'.repeat(it.args || 0), from, { line: cur.line, ch: to });
    if (it.args) cm.setCursor({ line: cur.line, ch: ctx.from + it.text.length + 1 });
    if (it.text === 'begin') setTimeout(() => complete(true), 0);
  } else if (ctx.kind === 'begin') {
    const indent = line.match(/^\s*/)[0], end = to + (line[to] === '}' ? 1 : 0);
    cm.replaceRange(`${it.text}}\n${indent}  \n${indent}\\end{${it.text}}`, from, { line: cur.line, ch: end });
    cm.setCursor({ line: cur.line + 1, ch: indent.length + 2 });
  } else {
    const e = argumentEdit(line, ctx.from, cur.ch, it.text, ctx.close);
    cm.replaceRange(e.insert, from, { line: cur.line, ch: e.to });
  }
  cm.focus();
}

// Typing keeps the list up to date, and opens it after "\ref{", "\cite{", "\begin{", a "," in a key list, or two
// letters of a command.
app.cm.on('inputRead', (cm, change) => {
  if (change.origin !== '+input' && change.origin !== '+delete') return;
  const ch = change.text.join('');
  if (active || /[{,]$/.test(ch) || /[a-zA-Z]$/.test(ch)) complete(false);
});
app.cm.on('cursorActivity', cm => {
  if (!active) return;
  const ctx = context(cm);
  if (!ctx || cm.getCursor().line !== active.line || ctx.kind !== active.ctx.kind) close(); else complete(true);
});
app.cm.on('blur', () => setTimeout(close, 100));

Object.assign(app, { complete, refreshCompletions, closeComplete: close });
