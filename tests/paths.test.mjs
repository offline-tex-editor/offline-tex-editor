// Tests for file names as the main document sees them (offline_tex_editor/static/paths.js). Run with:
// node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fromMain, figureFolder, pastedName, texSafeName, includeGraphics } from '../offline_tex_editor/static/paths.js';

test('a main document at the top sees project paths as they are', () => {
  assert.equal(fromMain('figures/plot.png', 'main.tex'), 'figures/plot.png');
  assert.equal(fromMain('refs.bib', 'main.tex'), 'refs.bib');
});

test('files below the main document\'s folder are relative to it', () => {
  assert.equal(fromMain('paper/figures/plot.png', 'paper/main.tex'), 'figures/plot.png');
  assert.equal(fromMain('paper/refs.bib', 'paper/main.tex'), 'refs.bib');
  assert.equal(fromMain('a/b/sections/intro.tex', 'a/b/main.tex'), 'sections/intro.tex');
});

test('files elsewhere in the project get ../', () => {
  assert.equal(fromMain('notes.tex', 'paper/main.tex'), '../notes.tex');
  assert.equal(fromMain('shared/refs.bib', 'paper/main.tex'), '../shared/refs.bib');
  assert.equal(fromMain('a/c/x.tex', 'a/b/main.tex'), '../c/x.tex');
  assert.equal(fromMain('x.tex', 'a/b/main.tex'), '../../x.tex');
});

test('a file named like the main document\'s folder is not taken for that folder', () => {
  assert.equal(fromMain('paper', 'paper/main.tex'), '../paper');
  assert.equal(fromMain('paperx/a.tex', 'paper/main.tex'), '../paperx/a.tex');
});

test('pasted images go to a figures folder next to the main document', () => {
  assert.equal(figureFolder(['sections', 'figures'], 'main.tex'), 'figures');
  assert.equal(figureFolder(['Figures', 'img'], 'main.tex'), 'Figures');
  assert.equal(figureFolder(['images', 'img'], 'main.tex'), 'images');
  assert.equal(figureFolder(['paper', 'paper/figs', 'figures'], 'paper/main.tex'), 'paper/figs');
});

test('without a figures folder, pasted images go to the main document\'s folder', () => {
  assert.equal(figureFolder(['sections'], 'main.tex'), '');
  assert.equal(figureFolder(['paper', 'figures', 'paper/sections/figures'], 'paper/main.tex'), 'paper');
});

test('a pasted image is named after when it was pasted', () => {
  const at = new Date(2026, 10, 7, 9, 5, 3);
  assert.equal(pastedName(at, 'png'), 'pasted-20261107-090503.png');
  assert.equal(pastedName(at, 'jpg', 2), 'pasted-20261107-090503-2.jpg');
});

test('file names that \\includegraphics cannot read are made safe', () => {
  // checked with pdflatex: these stop it, or (several spaces) make it look for another name
  assert.equal(texSafeName('a#b.png'), 'a-b.png');
  assert.equal(texSafeName('50%.png'), '50-.png');
  assert.equal(texSafeName('say "hi".png'), 'say -hi-.png');
  assert.equal(texSafeName('a\\b.png'), 'a-b.png');
  assert.equal(texSafeName('a{b.png'), 'a-b.png');
  assert.equal(texSafeName('two  spaces\t.png'), 'two spaces .png');
  // these work as they are
  for (const ok of ['my plot.png', 'a_b.png', 'a&b~c$d^e.png', 'ä b.png', "it's.png", 'a[b],c=d!.png', 'a.b.c.png'])
    assert.equal(texSafeName(ok), ok);
});

test('the \\includegraphics path is relative to the main document, also in a subfolder', () => {
  assert.equal(includeGraphics('figures/my plot.png', 'main.tex'), '\\includegraphics[width=\\linewidth]{figures/my plot.png}');
  assert.equal(includeGraphics('paper/figures/a_b.png', 'paper/main.tex'), '\\includegraphics[width=\\linewidth]{figures/a_b.png}');
  assert.equal(includeGraphics('paper/x.png', 'paper/main.tex'), '\\includegraphics[width=\\linewidth]{x.png}');
  assert.equal(includeGraphics('a/b/figs/x.png', 'a/b/main.tex'), '\\includegraphics[width=\\linewidth]{figs/x.png}');
});
