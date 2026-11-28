// Tests for finding the label argument of a cross-reference (offline_tex_editor/static/refs.js). Run with:
// node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { refArgument, argumentEdit } from '../offline_tex_editor/static/refs.js';

test('reference commands want a label in braces', () => {
  for (const cmd of ['ref', 'eqref', 'pageref', 'autoref', 'nameref', 'cref', 'Cref', 'vref', 'labelcref', 'cpageref'])
    assert.deepEqual(refArgument(`see \\${cmd}{sec:`), { typed: 'sec:', close: '}' }, cmd);
  assert.deepEqual(refArgument('\\cref*{'), { typed: '', close: '}' });
  assert.deepEqual(refArgument('\\cref{a,b'), { typed: 'a,b', close: '}' });
});

test('\\href and \\hyperref{URL} take a web address, not a label', () => {
  assert.equal(refArgument('\\href{'), null);
  assert.equal(refArgument('\\href{https://example.org'), null);
  assert.equal(refArgument('\\hyperref{'), null);
});

test('\\hyperref[label] wants a label in square brackets', () => {
  assert.deepEqual(refArgument('\\hyperref[fig:'), { typed: 'fig:', close: ']' });
  assert.equal(refArgument('\\hyperref[fig:plot]{the '), null);
});

test('no label wanted outside the argument', () => {
  assert.equal(refArgument('\\ref{sec:a} and '), null);
  assert.equal(refArgument('\\label{'), null);
  assert.equal(refArgument('plain text'), null);
});

// Accept `text` with the cursor at "|" in `line`, the argument starting at `from` (the first character after { or [).
function accept(line, text, close) {
  const cursor = line.indexOf('|'), plain = line.replace('|', '');
  const from = Math.max(plain.lastIndexOf('{', cursor - 1), plain.lastIndexOf('[', cursor - 1)) + 1;
  const e = argumentEdit(plain, from, cursor, text, close);
  return plain.slice(0, e.from) + e.insert + plain.slice(e.to);
}

test('accepting a label closes the argument once', () => {
  assert.equal(accept('see \\ref{sec|', 'sec:intro'), 'see \\ref{sec:intro}');
  assert.equal(accept('see \\ref{se|c} now', 'sec:intro'), 'see \\ref{sec:intro} now');
  assert.equal(accept('\\cite{knu|,lamport}', 'knuth84'), '\\cite{knuth84,lamport}');
});

test('accepting a label in \\hyperref[...] closes the bracket once', () => {
  assert.equal(accept('\\hyperref[fig|', 'fig:plot', ']'), '\\hyperref[fig:plot]');
  assert.equal(accept('\\hyperref[|]{the plot}', 'fig:plot', ']'), '\\hyperref[fig:plot]{the plot}');
  assert.equal(accept('\\hyperref[fi|g:old]{the plot}', 'fig:plot', ']'), '\\hyperref[fig:plot]{the plot}');
});

test('a "]" inside braces is part of the name', () => {
  assert.equal(accept('\\includegraphics{plot|]final.png}', 'plot]final.png'), '\\includegraphics{plot]final.png}');
  assert.equal(accept('\\includegraphics{plot|', 'plot]final.png'), '\\includegraphics{plot]final.png}');
  assert.equal(accept('\\input{a]b|}', 'a]b.tex'), '\\input{a]b.tex}');
});
