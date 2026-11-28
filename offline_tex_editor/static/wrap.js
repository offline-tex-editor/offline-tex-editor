// Wrapping the selection in a command such as \textbf{...}, or unwrapping it. Pure functions, tested with
// `node --test tests/`.

// Index of the comment on the last line, or s.length. Escaped percent signs are literal text.
function trailingComment(s) {
  for (let i = s.lastIndexOf('\n') + 1; i < s.length; i++) {
    if (s[i] === '\\') i++;
    else if (s[i] === '%') return i;
  }
  return s.length;
}

// Whether the braces in `s` pair up (escaped braces and braces in comments do not count).
function balanced(s) {
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\') i++;
    else if (s[i] === '%') { const end = s.indexOf('\n', i); i = end < 0 ? s.length : end; }
    else if (s[i] === '{') depth++;
    else if (s[i] === '}' && --depth < 0) return false;
  }
  return depth === 0;
}

// Whether `s` is one \cmd{...} group (`open` is "\cmd{") and nothing else.
const isWrapped = (open, s) => s.startsWith(open) && s.endsWith('}') && balanced(s) && balanced(s.slice(open.length, -1));

const wrap = (open, s) => {
  const end = trailingComment(s);
  return open + s.slice(0, end) + '}' + s.slice(end);
};
const unwrap = (open, s) => {
  const end = trailingComment(s), body = s.slice(0, end);
  return isWrapped(open, body) ? body.slice(open.length, -1) + s.slice(end) : null;
};

function escaped(s, at) {
  let slashes = 0;
  for (let i = at - 1; i >= 0 && s[i] === '\\'; i--) slashes++;
  return slashes % 2 !== 0;
}

// The selection fills a chain of groups, \cmd{ is one of them: where in `before` it starts, and how many groups are
// inside it. With "x" selected in \textbf{\textit{x}}, \textbf{ is found one group out. Null when it is not there.
function enclosing(open, before, after) {
  let rest = before;
  for (let inner = 0; after[inner] === '}'; inner++) {
    const m = rest.match(/\\[a-zA-Z]+\{$/);
    if (!m) return null;
    const start = rest.length - m[0].length;
    if (escaped(rest, start) || trailingComment(rest) < start) return null;
    if (m[0] === open) return { start: rest.length - open.length, inner };
    rest = rest.slice(0, -m[0].length);
  }
  return null;
}

// A blank line ends a paragraph, and \textbf{...} cannot go across one ("Paragraph ended before \text@command was
// complete"), so each paragraph of a selection is wrapped by itself.
const PARAGRAPH_BREAK = /(\n[ \t]*\n\s*)/;

// The edit that toggles \cmd{...} around a selection. before: the text of the selection's first line before it;
// selected: the selected text (it can span lines); after: the text of its last line after it.
// Returns { cutBefore, cutAfter, text, select }: replace the cutBefore characters before the selection, the selection
// and the cutAfter characters after it with `text`, then select text.slice(select[0], select[1]).
// - the selection is inside \cmd{...} (also with other commands in between, as in \textbf{\textit{x}}): unwrap it
// - the selection is "\cmd{...}" itself: unwrap it
// - several paragraphs: wrap each one that is not wrapped yet, or unwrap them all when they all are
// - otherwise wrap it, keeping the same text selected (with nothing selected, the cursor goes between the braces)
export function toggleWrap(cmd, before, selected, after) {
  const open = `\\${cmd}{`;
  const around = balanced(selected) ? enclosing(open, before, after) : null;
  if (around) {
    const inner = before.slice(around.start + open.length);   // the groups between \cmd{ and the selection stay
    const text = inner + selected + after.slice(0, around.inner);
    return { cutBefore: before.length - around.start, cutAfter: around.inner + 1, text,
             select: [inner.length, inner.length + selected.length] };
  }
  const unwrapped = escaped(before, before.length) || trailingComment(before) < before.length
    ? null : unwrap(open, selected);
  if (unwrapped !== null) {
    const text = unwrapped;
    return { cutBefore: 0, cutAfter: 0, text, select: [0, text.length] };
  }
  const parts = selected.split(PARAGRAPH_BREAK);   // paragraphs at even indexes, the breaks between them at odd ones
  if (parts.length > 1) {
    const paragraphs = parts.filter((p, i) => i % 2 === 0 && p.trim());
    const remove = paragraphs.every(p => unwrap(open, p) !== null);
    const text = parts.map((p, i) => i % 2 || !p.trim() ? p : remove ? unwrap(open, p)
                                      : unwrap(open, p) !== null ? p : wrap(open, p)).join('');
    return { cutBefore: 0, cutAfter: 0, text, select: [0, text.length] };
  }
  return { cutBefore: 0, cutAfter: 0, text: wrap(open, selected),
           select: [open.length, open.length + trailingComment(selected)] };
}
