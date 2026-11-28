// File names as the main document sees them. Pure functions, tested with `node --test tests/`.
//
// LaTeX runs in the main document's folder, so \input, \includegraphics and \bibliography name project files
// relative to it: with paper/main.tex, paper/figures/x.png is written figures/x.png, and notes.tex at the top of the
// project ../notes.tex.

// `path` (relative to the project folder) as seen from the folder of `main` (also relative to the project folder).
export function fromMain(path, main) {
  const base = main.split('/').slice(0, -1), parts = path.split('/');
  let same = 0;   // folders shared by both; the last part of `path` is its file name, never a folder
  while (same < base.length && same < parts.length - 1 && base[same] === parts[same]) same++;
  return [...Array(base.length - same).fill('..'), ...parts.slice(same)].join('/');
}

// Folders that usually hold a document's figures, best first.
const FIGURE_DIRS = ['figures', 'figs', 'images', 'img', 'graphics'];

// Where an image pasted or dropped into the editor is saved, relative to the project folder: a figures folder next to
// the main document if there is one (of any case), else the main document's folder. dirs: the project's folders.
export function figureFolder(dirs, main) {
  const base = main.split('/').slice(0, -1).join('/'), prefix = base ? base + '/' : '';
  for (const name of FIGURE_DIRS) {
    const found = dirs.find(d => d.startsWith(prefix) && d.slice(prefix.length).toLowerCase() === name);
    if (found) return found;
  }
  return base;
}

// A file name that \includegraphics can read: LaTeX stops at #, %, ", \ and unbalanced braces in it, and reads several
// spaces as one, so those become "-" and a single space.
export function texSafeName(name) {
  return name.replace(/[#%"\\{}]/g, '-').replace(/\s+/g, ' ').trim();
}

// The \includegraphics line for an image at `path` (relative to the project folder), as the main document sees it.
export const includeGraphics = (path, main) => `\\includegraphics[width=\\linewidth]{${fromMain(path, main)}}`;

// A file name for a pasted image, which has none of its own: pasted-20261127-104305.png, or with n,
// pasted-20261127-104305-2.png.
export function pastedName(date, ext, n) {
  const two = x => String(x).padStart(2, '0');
  const day = `${date.getFullYear()}${two(date.getMonth() + 1)}${two(date.getDate())}`;
  const time = `${two(date.getHours())}${two(date.getMinutes())}${two(date.getSeconds())}`;
  return `pasted-${day}-${time}${n ? '-' + n : ''}.${ext}`;
}
