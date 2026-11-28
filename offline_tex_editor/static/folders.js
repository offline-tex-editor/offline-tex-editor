// The current folder of the file list: where Add files, New file and New folder work. Pure functions, tested with
// `node --test tests/`.
//
// `clicked` is the row clicked last, { path, dir } (dir: whether it is a folder; the empty path is the project
// folder, after a click below the rows), or null before any click.

const dirOf = p => p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';

// The current folder: the folder clicked last, or the folder of the file clicked last; before any click, the folder
// of the open file (`current`), or the project folder ('').
export function currentFolder(clicked, current, dirs) {
  const dir = clicked ? (clicked.dir ? clicked.path : dirOf(clicked.path)) : current ? dirOf(current) : '';
  // An open document can outlive a folder renamed or deleted outside the editor.
  return !dirs || dirs.includes(dir) ? dir : '';
}

// Where `path` is after `from` (a file or a folder) was renamed or moved to `to`: moved along when it is `from` or
// inside it, else where it was.
export function renamedPath(path, from, to) {
  if (path === from) return to;
  return path.startsWith(from + '/') ? to + path.slice(from.length) : path;
}

// After `from` was renamed or moved to `to`: the clicked row moves along when it is `from` or inside it.
export function followRename(clicked, from, to) {
  return !clicked || !clicked.path ? clicked : { ...clicked, path: renamedPath(clicked.path, from, to) };
}

// After the file list was read again: the clicked row, or null when it is no longer there (deleted, or renamed
// outside the editor), so that files are never added to a folder that is gone. files: every file in the list.
export function stillListed(clicked, files, dirs) {
  if (!clicked || !clicked.path) return clicked;
  return (clicked.dir ? dirs : files).includes(clicked.path) ? clicked : null;
}
