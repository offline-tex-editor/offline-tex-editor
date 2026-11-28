// Completing an argument: where a cross-reference command wants a label, and the edit that accepting a completion
// makes. Pure functions, tested with `node --test tests/`.

// \ref, \eqref, \pageref, \autoref, \nameref, \cref, \Cref, \vref, \labelcref, ... (any command ending in "ref"),
// but not \href{URL} or \hyperref{URL}{...}, whose braces hold a web address.
const REF = /\\(?!h(?:yper)?ref\b)[a-zA-Z]*ref\*?\{([^{}]*)$/;
// \hyperref[label]{text}: the label is in square brackets
const HYPERREF = /\\hyperref\[([^\]]*)$/;

// For the text of a line up to the cursor: { typed, close } when the cursor is in a label argument (typed: what is
// already there, close: the character that ends the argument), or null.
export function refArgument(before) {
  let m;
  if ((m = before.match(REF))) return { typed: m[1], close: '}' };
  if ((m = before.match(HYPERREF))) return { typed: m[1], close: ']' };
  return null;
}

// Accepting `text` in an argument (a label, a citation key or a file name) that starts at `from` in `line`, with the
// cursor at `cursor`: { from, to, insert } replaces line.slice(from, to). What was typed runs on to the next space,
// comma or brace; in a square-bracket argument (close "]") also to the next "]", which in braces belongs to the name
// (\includegraphics{plot]final.png}). The argument is closed, unless it is already or a comma follows (a key list).
export function argumentEdit(line, from, cursor, text, close = '}') {
  const word = close === ']' ? /[^\s,{}\]]/ : /[^\s,{}]/;
  let to = cursor;
  while (to < line.length && word.test(line[to])) to++;
  const closed = line[to] === close || (close === '}' && line[to] === ',');
  return { from, to, insert: text + (closed ? '' : close) };
}
