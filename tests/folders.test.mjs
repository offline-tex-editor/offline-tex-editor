// Tests for the current folder of the file list (offline_tex_editor/static/folders.js), the folder that Add files,
// New file and New folder all start in. Run with: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { currentFolder, followRename, stillListed } from '../offline_tex_editor/static/folders.js';

const file = path => ({ path, dir: false }), folder = path => ({ path, dir: true });

test('the folder clicked last, or the folder of the file clicked last', () => {
  assert.equal(currentFolder(folder('figures'), 'main.tex'), 'figures');
  assert.equal(currentFolder(file('old/note.tex'), 'main.tex'), 'old');
  assert.equal(currentFolder(file('notes.tex'), 'paper/main.tex'), '');
  assert.equal(currentFolder(folder(''), 'paper/main.tex'), '');   // a click below the rows
});

test('before any click, the open file\'s folder', () => {
  assert.equal(currentFolder(null, 'paper/main.tex'), 'paper');
  assert.equal(currentFolder(null, null), '');
});

test('renaming the folder of the clicked file moves the current folder along', () => {
  // click old/note.tex, then rename old/ to new/
  const clicked = followRename(file('old/note.tex'), 'old', 'new');
  assert.equal(currentFolder(clicked, 'main.tex'), 'new');
  assert.equal(currentFolder(stillListed(clicked, ['main.tex', 'new/note.tex'], ['new']), 'main.tex'), 'new');
  // moving it deeper, and renaming the file itself
  assert.equal(currentFolder(followRename(file('old/note.tex'), 'old', 'a/b/old'), null), 'a/b/old');
  assert.equal(currentFolder(followRename(file('old/note.tex'), 'old/note.tex', 'other/note.tex'), null), 'other');
  assert.equal(currentFolder(followRename(folder('old/sub'), 'old', 'new'), null), 'new/sub');
});

test('renaming something else leaves the current folder alone', () => {
  assert.deepEqual(followRename(file('old/note.tex'), 'ol', 'x'), file('old/note.tex'));
  assert.deepEqual(followRename(file('older/note.tex'), 'old', 'new'), file('older/note.tex'));
  assert.deepEqual(followRename(folder(''), 'old', 'new'), folder(''));
});

test('deleting the clicked file or its folder falls back to the open file\'s folder', () => {
  // click old/note.tex, then delete old/ (or the editor finds it gone after a rename elsewhere)
  const left = stillListed(file('old/note.tex'), ['paper/main.tex'], ['paper']);
  assert.equal(left, null);
  assert.equal(currentFolder(left, 'paper/main.tex'), 'paper');
  assert.equal(stillListed(folder('old'), ['paper/main.tex'], ['paper']), null);
  // still there: kept
  assert.deepEqual(stillListed(file('old/note.tex'), ['old/note.tex'], ['old']), file('old/note.tex'));
  assert.deepEqual(stillListed(folder(''), [], []), folder(''));
});

test('an external rename or delete cannot leave a missing destination through the open document', () => {
  const dirs = ['paper', 'renamed'];
  const clicked = stillListed(file('old/note.tex'), ['paper/main.tex', 'renamed/note.tex'], dirs);
  assert.equal(currentFolder(clicked, 'old/note.tex', dirs), '');
  assert.equal(currentFolder(null, 'paper/main.tex', dirs), 'paper');
  assert.equal(currentFolder(folder(''), 'old/note.tex', dirs), '');
  assert.equal(currentFolder(folder('old'), 'paper/main.tex', dirs), '');
});
