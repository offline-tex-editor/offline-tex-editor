// Check that generated edits are valid input to TeX, not just the expected JavaScript strings.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, copyFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { toggleWrap } from '../offline_tex_editor/static/wrap.js';
import { texSafeName, includeGraphics } from '../offline_tex_editor/static/paths.js';

const haveTex = spawnSync('pdflatex', ['--version']).status === 0;
function compile(dir, name, body) {
  writeFileSync(join(dir, name + '.tex'), '\\documentclass{article}\n\\usepackage{graphicx}\n' +
    '\\begin{document}\n' + body + '\n\\end{document}\n');
  const r = spawnSync('pdflatex', ['-interaction=nonstopmode', '-halt-on-error', name + '.tex'],
    { cwd: dir, encoding: 'utf8', timeout: 30000 });
  assert.equal(r.status, 0, r.error?.message || r.stdout + r.stderr);
}

test('formatting comments and escaped command prefixes still compiles', { skip: !haveTex }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'ote-wrap-'));
  try {
    const cases = [['', 'hello % comment', ''], ['', 'one % } ignored\ntwo', ''],
      ['', 'one % comment\n\ntwo % end', ''], ['first\\\\textbf{', 'word', '}'],
      ['', '50\\% off', '']];
    const body = [];
    for (const cmd of ['textbf', 'textit']) {
      for (const [before, selected, after] of cases) {
        const e = toggleWrap(cmd, before, selected, after);
        body.push(before.slice(0, before.length - e.cutBefore) + e.text + after.slice(e.cutAfter));
      }
    }
    compile(dir, 'wrapped', body.join('\n\n'));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('an uploaded PDF name with TeX caret conversion can be included', { skip: !haveTex }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'ote-graphics-'));
  try {
    compile(dir, 'figure', 'A figure');
    const name = texSafeName('a^^41.pdf');
    copyFileSync(join(dir, 'figure.pdf'), join(dir, name));
    compile(dir, 'main', includeGraphics(name, 'main.tex'));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
