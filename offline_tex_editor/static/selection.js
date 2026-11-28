// Selecting several files and folders in the file list. Pure functions, tested with `node --test tests/`.
import { renamedPath } from './folders.js';

// Shift+click: the paths from `a` to `b` (both included) in the order the list shows them. Without `a` (or when it
// is no longer shown), just `b`.
export function rangeBetween(order, a, b) {
  const i = order.indexOf(a), j = order.indexOf(b);
  if (j < 0) return [];
  if (i < 0) return [b];
  return order.slice(Math.min(i, j), Math.max(i, j) + 1);
}

// What deleting the selected paths does: { remove, keep, skip }.
// - keep: the main document and the folders it is in, which cannot be deleted
// - skip: open files with unsaved changes (`unsaved`), and folders with one inside, so that no edit is lost
// - remove: the rest, without paths inside a folder that is removed
// The selected files in a kept or skipped folder are removed one by one, so selecting paper/ and paper/notes.tex
// still deletes paper/notes.tex.
export function forDeleting(paths, main, unsaved = []) {
  const holds = (p, file) => file === p || file.startsWith(p + '/');
  const keep = paths.filter(p => holds(p, main));
  const skip = paths.filter(p => !keep.includes(p) && unsaved.some(u => holds(p, u)));
  return { remove: topmost(paths.filter(p => !keep.includes(p) && !skip.includes(p))), keep, skip };
}

// The status line after deleting: what was deleted, kept, skipped and could not be deleted ({ path, error } list).
export function deletionReport({ deleted, keep, skip, failed }, main) {
  const list = ps => ps.join(', ');
  const out = [`Deleted ${deleted.length} (moved to build/.editor-trash)` + (deleted.length ? `: ${list(deleted)}` : '')];
  if (keep.length) out.push(`kept ${list(keep)} (${keep.length === 1 && keep[0] === main ? 'the main document' : 'the main document and its folders'})`);
  if (skip.length) out.push(`skipped ${list(skip)} (unsaved changes: save or undo them first)`);
  if (failed.length) out.push(`could not delete ${failed.map(f => `${f.path} (${f.error})`).join(', ')}`);
  return out.join('; ');
}

// The selection after `from` was renamed or moved to `to`, or after the file list was read again (`listed`: every
// file and folder there is now; hidden rows, folded or filtered out, stay selected).
export const renameSelection = (paths, from, to) => paths.map(p => renamedPath(p, from, to));
export const stillSelected = (paths, listed) => paths.filter(p => listed.has(p));

// The selected paths without those inside a selected folder, which go with their folder (deleting the folder and then
// a file in it would fail, and a .zip would hold the file twice).
export function topmost(paths) {
  const all = new Set(paths);
  return paths.filter(p => !p.split('/').slice(0, -1).some((_, i, parts) => all.has(parts.slice(0, i + 1).join('/'))));
}
