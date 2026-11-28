// Wrapping the selection in a command such as \textbf{...}, or unwrapping it. Pure functions, tested with
// `node --test tests/`.

// Whether the braces in `s` pair up (escaped \{ and \} do not count).
function balanced(s) {
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\') i++;
    else if (s[i] === '{') depth++;
    else if (s[i] === '}' && --depth < 0) return false;
  }
  return depth === 0;
}

// Whether `s` is one \cmd{...} group (`open` is "\cmd{") and nothing else.
const isWrapped = (open, s) => s.startsWith(open) && s.endsWith('}') && balanced(s) && balanced(s.slice(open.length, -1));

// The selection fills a chain of groups, \cmd{ is one of them: where in `before` it starts, and how many groups are
// inside it. With "x" selected in \textbf{\textit{x}}, \textbf{ is found one group out. Null when it is not there.
function enclosing(open, before, after) {
  let rest = before;
  for (let inner = 0; after[inner] === '}'; inner++) {
    const m = rest.match(/\\[a-zA-Z]+\{$/);
    if (!m) return null;
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
  if (isWrapped(open, selected)) {
    const text = selected.slice(open.length, -1);
    return { cutBefore: 0, cutAfter: 0, text, select: [0, text.length] };
  }
  const parts = selected.split(PARAGRAPH_BREAK);   // paragraphs at even indexes, the breaks between them at odd ones
  if (parts.length > 1) {
    const paragraphs = parts.filter((p, i) => i % 2 === 0 && p.trim());
    const unwrap = paragraphs.every(p => isWrapped(open, p));
    const text = parts.map((p, i) => i % 2 || !p.trim() ? p : unwrap ? p.slice(open.length, -1)
                                      : isWrapped(open, p) ? p : open + p + '}').join('');
    return { cutBefore: 0, cutAfter: 0, text, select: [0, text.length] };
  }
  return { cutBefore: 0, cutAfter: 0, text: open + selected + '}', select: [open.length, open.length + selected.length] };
}
