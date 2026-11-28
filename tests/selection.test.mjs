// Tests for selecting several files in the file list (offline_tex_editor/static/selection.js). Run with:
// node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rangeBetween, topmost, forDeleting, deletionReport, renameSelection, stillSelected } from '../offline_tex_editor/static/selection.js';

const order = ['main.tex', 'refs.bib', 'figures', 'figures/a.png', 'figures/b.png', 'sections', 'sections/intro.tex'];

test('Shift+click selects everything shown between the two rows, in either direction', () => {
  assert.deepEqual(rangeBetween(order, 'refs.bib', 'figures/a.png'), ['refs.bib', 'figures', 'figures/a.png']);
  assert.deepEqual(rangeBetween(order, 'figures/b.png', 'main.tex'),
                   ['main.tex', 'refs.bib', 'figures', 'figures/a.png', 'figures/b.png']);
  assert.deepEqual(rangeBetween(order, 'sections', 'sections'), ['sections']);
});

test('without a row to start from, Shift+click selects the clicked row', () => {
  assert.deepEqual(rangeBetween(order, null, 'refs.bib'), ['refs.bib']);
  assert.deepEqual(rangeBetween(order, 'gone.tex', 'refs.bib'), ['refs.bib']);
  assert.deepEqual(rangeBetween(order, 'main.tex', 'gone.tex'), []);
});

test('files in a selected folder go with the folder', () => {
  assert.deepEqual(topmost(['figures', 'figures/a.png', 'refs.bib', 'figures/sub/x.png']), ['figures', 'refs.bib']);
  assert.deepEqual(topmost(['figures/a.png', 'figures/b.png']), ['figures/a.png', 'figures/b.png']);
  // a name that only starts like the folder is not inside it
  assert.deepEqual(topmost(['fig', 'figures/a.png']), ['fig', 'figures/a.png']);
});

test('deleting keeps the main document and its folders, but not what is selected in them', () => {
  assert.deepEqual(forDeleting(['paper', 'paper/sec/s.tex', 'notes.tex'], 'paper/main.tex'),
                   { remove: ['paper/sec/s.tex', 'notes.tex'], keep: ['paper'], skip: [] });
  assert.deepEqual(forDeleting(['a', 'a/b', 'a/b/main.tex', 'a/b/c', 'a/b/c/x.tex', 'a/y.tex'], 'a/b/main.tex'),
                   { remove: ['a/b/c', 'a/y.tex'], keep: ['a', 'a/b', 'a/b/main.tex'], skip: [] });
  assert.deepEqual(forDeleting(['paperx', 'pap'], 'paper/main.tex'), { remove: ['paperx', 'pap'], keep: [], skip: [] });
});

test('overlapping folder and file selections: each file once', () => {
  assert.deepEqual(topmost(['a', 'a/b', 'a/b/c.tex', 'a/x.tex', 'z.tex']), ['a', 'z.tex']);
  assert.deepEqual(forDeleting(['a/b/c.tex', 'a/b', 'a'], 'main.tex').remove, ['a']);
});

test('filtering and folding: ranges cover the rows shown, hidden rows stay selected', () => {
  // figures/ folded (or filtered out): its files are not shown, so Shift+click does not pick them up
  const shown = ['main.tex', 'refs.bib', 'figures', 'sections', 'sections/intro.tex'];
  assert.deepEqual(rangeBetween(shown, 'refs.bib', 'sections'), ['refs.bib', 'figures', 'sections']);
  // a selected file that is only hidden is still in the project, so it stays selected
  const listed = new Set(['main.tex', 'figures', 'figures/a.png', 'sections']);
  assert.deepEqual(stillSelected(['figures/a.png', 'main.tex'], listed), ['figures/a.png', 'main.tex']);
});

test('renames and deletes refresh the selection', () => {
  assert.deepEqual(renameSelection(['old/a.tex', 'old', 'older/b.tex', 'x.tex'], 'old', 'new'),
                   ['new/a.tex', 'new', 'older/b.tex', 'x.tex']);
  assert.deepEqual(renameSelection(['x.tex'], 'x.tex', 'sub/y.tex'), ['sub/y.tex']);
  // after a delete (here or outside the editor) what is gone drops out
  assert.deepEqual(stillSelected(['old/a.tex', 'x.tex', 'old'], new Set(['x.tex'])), ['x.tex']);
});

test('unsaved open files are not deleted, nor folders that hold one', () => {
  const plan = forDeleting(['notes.tex', 'a', 'a/x.tex', 'b'], 'main.tex', ['notes.tex', 'a/y.tex']);
  assert.deepEqual(plan, { remove: ['a/x.tex', 'b'], keep: [], skip: ['notes.tex', 'a'] });
  // main document protection comes first
  assert.deepEqual(forDeleting(['paper'], 'paper/main.tex', ['paper/main.tex']), { remove: [], keep: ['paper'], skip: [] });
});

test('the report names what was deleted, kept, skipped and failed', () => {
  assert.equal(deletionReport({ deleted: ['a', 'b.tex'], keep: [], skip: [], failed: [] }, 'main.tex'),
               'Deleted 2 (moved to build/.editor-trash): a, b.tex');
  assert.equal(deletionReport({ deleted: ['b.tex'], keep: ['paper'], skip: ['notes.tex'],
                                failed: [{ path: 'c.tex', error: 'permission denied' }] }, 'paper/main.tex'),
               'Deleted 1 (moved to build/.editor-trash): b.tex; kept paper (the main document and its folders); '
               + 'skipped notes.tex (unsaved changes: save or undo them first); could not delete c.tex (permission denied)');
  assert.equal(deletionReport({ deleted: [], keep: ['main.tex'], skip: [], failed: [] }, 'main.tex'),
               'Deleted 0 (moved to build/.editor-trash); kept main.tex (the main document)');
});
