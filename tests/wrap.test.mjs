// Tests for wrapping the selection in \textbf{...} and the like (offline_tex_editor/static/wrap.js). Run with:
// node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { toggleWrap } from '../offline_tex_editor/static/wrap.js';

// Apply the edit to before + selected + after; returns the new text with [ and ] around the new selection.
function apply(before, selected, after, cmd = 'textbf') {
  const e = toggleWrap(cmd, before, selected, after);
  const head = before.slice(0, before.length - e.cutBefore), tail = after.slice(e.cutAfter);
  return head + e.text.slice(0, e.select[0]) + '[' + e.text.slice(e.select[0], e.select[1]) + ']' +
    e.text.slice(e.select[1]) + tail;
}

test('wraps the selection and keeps it selected', () => {
  assert.equal(apply('a ', 'word', ' b'), 'a \\textbf{[word]} b');
  assert.equal(apply('', 'two words', '', 'textit'), '\\textit{[two words]}');
});

test('with nothing selected, the cursor goes between the braces', () => {
  assert.equal(apply('a ', '', ' b'), 'a \\textbf{[]} b');
});

test('unwraps a selection inside the command', () => {
  assert.equal(apply('a \\textbf{', 'word', '} b'), 'a [word] b');
  assert.equal(apply('\\textbf{', '', '}'), '[]');   // pressed twice with nothing selected
});

test('unwraps a selection that is the whole command', () => {
  assert.equal(apply('a ', '\\textbf{word}', ' b'), 'a [word] b');
  assert.equal(apply('', '\\textbf{x \\emph{y}}', ''), '[x \\emph{y}]');
});

test('only unwraps the same command', () => {
  assert.equal(apply('\\textit{', 'word', '}'), '\\textit{\\textbf{[word]}}');
  assert.equal(apply('', '\\textit{word}', '', 'textbf'), '\\textbf{[\\textit{word}]}');
});

test('does not unwrap braces that belong to something else', () => {
  // the selection starts and ends like \textbf{...}, but those are two separate groups
  assert.equal(apply('', '\\textbf{a} and \\textbf{b}', ''), '\\textbf{[\\textbf{a} and \\textbf{b}]}');
  // "\textbf{" before and "}" after, but the selection closes the group itself
  assert.equal(apply('\\textbf{', 'a} b \\emph{c', '}'), '\\textbf{\\textbf{[a} b \\emph{c]}}');
  // escaped braces are text: here the group is never closed
  assert.equal(apply('', '\\textbf{50\\}', ''), '\\textbf{[\\textbf{50\\}]}');
  assert.equal(apply('', '\\textbf{50\\%}', ''), '[50\\%]');
});

test('nested commands: the command is found through the ones inside it', () => {
  // x selected in \textbf{\textit{x}}: Ctrl+B takes the bold off, Ctrl+I the italics
  assert.equal(apply('a \\textbf{\\textit{', 'x', '}} b'), 'a \\textit{[x]} b');
  assert.equal(apply('a \\textbf{\\textit{', 'x', '}} b', 'textit'), 'a \\textbf{[x]} b');
  assert.equal(apply('\\textbf{\\emph{\\textsc{', 'x', '}}}'), '\\emph{\\textsc{[x]}}');
  // not when the selection is only part of the inner group
  assert.equal(apply('\\textbf{\\textit{a ', 'x', '}}'), '\\textbf{\\textit{a \\textbf{[x]}}}');
  // wrapping inside another command
  assert.equal(apply('\\emph{', 'x', '}'), '\\emph{\\textbf{[x]}}');
});

test('multiline selections', () => {
  assert.equal(apply('a ', 'one\ntwo', ' b'), 'a \\textbf{[one\ntwo]} b');
  assert.equal(apply('a \\textbf{', 'one\ntwo', '} b'), 'a [one\ntwo] b');
  assert.equal(apply('', '\\textbf{one\ntwo}', ''), '[one\ntwo]');
});

test('several paragraphs are wrapped one by one, since \\textbf cannot span a blank line', () => {
  assert.equal(apply('', 'first\n\nsecond', ''), '[\\textbf{first}\n\n\\textbf{second}]');
  assert.equal(apply('', '\\textbf{first}\n\n\\textbf{second}', ''), '[first\n\nsecond]');
  // a paragraph that is bold already stays as it is; the others are made bold too
  assert.equal(apply('', '\\textbf{first}\n  \nsecond\n\n\nthird', ''), '[\\textbf{first}\n  \n\\textbf{second}\n\n\n\\textbf{third}]');
  // a blank line at the end of the selection is left out
  assert.equal(apply('', 'first\n\n', ''), '[\\textbf{first}\n\n]');
});
