// The current folder of the file list: where Add files, New file and New folder work. Pure functions, tested with
// `node --test tests/`.
//
// `clicked` is the row clicked last, { path, dir } (dir: whether it is a folder; the empty path is the project
// folder, after a click below the rows), or null before any click.

const dirOf = p => p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';

// The current folder: the folder clicked last, or the folder of the file clicked last; before any click, the folder
// of the open file (`current`), or the project folder ('').
export function currentFolder(clicked, current) {
  if (clicked) return clicked.dir ? clicked.path : dirOf(clicked.path);
  return current ? dirOf(current) : '';
}

// After `from` (a file or a folder) was renamed or moved to `to`: the clicked row moves along when it is `from` or
// inside it.
export function followRename(clicked, from, to) {
  if (!clicked || !clicked.path) return clicked;
  if (clicked.path === from) return { ...clicked, path: to };
  if (clicked.path.startsWith(from + '/')) return { ...clicked, path: to + clicked.path.slice(from.length) };
  return clicked;
}

// After the file list was read again: the clicked row, or null when it is no longer there (deleted, or renamed
// outside the editor), so that files are never added to a folder that is gone. files: every file in the list.
export function stillListed(clicked, files, dirs) {
  if (!clicked || !clicked.path) return clicked;
  return (clicked.dir ? dirs : files).includes(clicked.path) ? clicked : null;
}
