# Offline TeX Editor

A LaTeX editor that runs on your own machine and opens in your browser: edit, recompile with `latexmk`, and
preview the PDF side by side with SyncTeX in both directions.

Fully offline: no accounts, no cloud, no internet connection needed. It runs as a small server on your computer,
and goes online only when you sync with GitHub or share the project with your team through a WebDAV folder.

![The editor with LaTeX source on the left and the compiled PDF on the right](https://offline-tex-editor.github.io/assets/editor.jpg)

## Install

You need Python 3.9 or newer and a TeX distribution (see [Requirements](#requirements)). Install the editor with
pip, or run it straight from its source code.

### With pip

```bash
pip install offline-tex-editor
```

Or install it with [pipx](https://pipx.pypa.io), which keeps it apart from your other Python packages:

```bash
pipx install offline-tex-editor
```

To update later, run `pip install --upgrade offline-tex-editor` (or `pipx upgrade offline-tex-editor`).

### From the source code

Clone the repository and start the editor from the clone. Nothing else needs to be installed:

```bash
git clone https://github.com/offline-tex-editor/offline-tex-editor.git
cd offline-tex-editor
./start.sh --root path/to/your/project --open
```

On Windows, run `.\start.cmd` instead of `./start.sh`. Both take the same [options](#options) as the
`offline-tex-editor` command. To update later, run `git pull` in the clone. To get the `offline-tex-editor`
command from the clone instead, run `pip install .` in it.

## Run

Start it on your LaTeX project's folder:

```bash
offline-tex-editor --root path/to/your/project --open
```

(From a clone of the source code, run `./start.sh`, or `.\start.cmd` on Windows, with the same options.)

`--open` opens the editor in your browser. Without it, open the address it prints, usually
http://127.0.0.1:8765/. Stop the editor with Ctrl+C in the terminal.

Started without `--root`, it uses the current folder. If the shell says the `offline-tex-editor` command is not
found, pip put it in a folder that is not on your PATH (pip prints a warning naming that folder). Run
`python -m offline_tex_editor` instead, or install with pipx.

## Requirements

- Python 3.9 or newer
- A TeX distribution with `latexmk` and `synctex`. TeX Live includes both (Debian/Ubuntu:
  `sudo apt install latexmk texlive-latex-recommended`; macOS: MacTeX). With MiKTeX on Windows, `latexmk` also
  needs Perl.
- Optional: `git` for the Git panel (and for merging teammates' changes over WebDAV), `biber` for biblatex,
  `texcount` for the word count
- A browser from 2024 or later

Developed and tested on Linux. It is expected to work on macOS; on Windows it has not yet been tried with a real
TeX installation, so reports are welcome.

## Features

**Writing**
- LaTeX editor with tabs for open files, syntax highlighting, bracket matching, go to line, and comment toggling
  (Ctrl/Cmd+/)
- Find and replace in the file (Ctrl/Cmd+F; Ctrl+H, or Cmd+Option+F on a Mac, for replace): every match is
  highlighted and counted, with options for case, whole words and regular expressions; replace one match at a
  time or all at once (one undo step)
- Autocompletion for `\ref`/`\cref` labels, `\cite` keys (matching author and title too), environments (`\begin`
  adds the `\end`), file names in `\input` and `\includegraphics`, and commands, including your own `\newcommand`s
- Spell check with your browser's dictionary, which skips LaTeX commands (turn it on in ⚙)
- Files changed by other programs reload automatically; saving over a newer version on disk asks first. Encodings
  (UTF-8 or Latin-1) and line endings (LF or CRLF) are kept as they are

**The project**
- File tree with images and PDFs; create, rename, move and delete files and folders (deleted files go to
  `build/.editor-trash/`, so mistakes can be undone); add files with a button (into the folder you clicked last)
  or by dropping them on a folder; preview images and PDF figures
- Search and replace in all files, with the same options (Ctrl/Cmd+Shift+F). With regular expressions, `$1`
  in the replacement inserts the first group (`$&` the whole match); backslashes are kept as typed, so
  `\textbf{$1}` works
- Document outline that follows `\input`, `\include`, `\subfile` and `\import`, and highlights the current section
- Word count (with `texcount`, which comes with TeX Live)
- Download the project's sources as a .zip (in ⚙): open files are saved first, and the .zip has the source files
  and figures, without `build/` and hidden files, plus the bibliography from the last compile (the `.bbl`, which arXiv
  for one needs) next to the main document. It is a copy of the sources, not a check against a venue's rules

**Compiling**
- Recompiles on save (can be switched off) or with Ctrl/Cmd+Enter; a Stop button and a time limit for runaway
  documents; a save made during a compile is compiled next
- pdfLaTeX, XeLaTeX or LuaLaTeX: see [Main document and engine](#main-document-and-engine)
- Errors and warnings with file and line (click to open), the TeX context, and a plain-language hint for common
  errors. BibTeX and biber messages are shown too, and an error inside the generated bibliography points at the
  `.bib` entry that caused it
- For long documents: a fast draft mode that draws images as boxes, and "compile only" one `\include`d chapter
- "Changes": a word-level diff of the sources between the last two compiles that changed something

**The PDF**
- Preview that keeps its scroll position across recompiles; zoom and page navigation
- Find in the PDF (Ctrl/Cmd+F when the editor is not focused): finds words split by ligatures, line breaks and
  hyphenation. PDF text can be selected and copied
- SyncTeX: double-click the PDF to jump to the source, or press Ctrl/Cmd+J to find the cursor in the PDF

**Git and GitHub**
- **Sync** in one click: pull, then push. When your branch and GitHub both have new commits, choose to rebase or
  merge. Separate Pull, Push and Fetch buttons are there too, and the panel fetches in the background, so it shows
  when GitHub has commits you don't have yet
- Start a git repository for a project, and connect it to a GitHub repository by pasting the repository's address
  (create an empty repository on GitHub first); the first Sync then sends your commits there
- Changed files with diffs, stage/unstage, commit, history. Conflicts are listed and highlighted in the editor;
  mark them resolved, then finish (or abort) the merge or rebase
- Uses your own git and its credentials; the editor stores nothing. To push to GitHub over https, sign in once
  with the GitHub CLI (`gh auth login`, then `gh auth setup-git`) or set up another credential helper

**Teams: WebDAV (Nextcloud, ownCloud)**
- Share a project through a folder on a WebDAV server, such as Nextcloud, ownCloud or a NAS. Everyone edits their
  own copy, offline, and presses **Sync**: what changed here is uploaded, and what teammates changed is downloaded.
  It is not live co-editing: changes travel when someone syncs. See
  [Sharing a project over WebDAV](#sharing-a-project-over-webdav)
- When two people changed the same file, their edits are merged (with git, when it is installed). Edits to the same
  lines get conflict markers, which the editor highlights, and the file is uploaded once they are resolved. Without
  git, and for images, the server's version is saved next to yours as "name (server copy).ext"
- Nothing on the server is overwritten by accident: an upload is refused when a teammate uploaded a newer version
  in the meantime, and the next sync merges the two. Files deleted on the server go to `build/.editor-trash/` here
- The panel checks the server every few minutes, so it shows when teammates changed something. A new or changed
  `.latexmkrc` from the server (it runs as a program when you compile) is downloaded only after you review and
  accept it
- Syncs the sources, images and PDFs, and folders (empty ones too), never `build/` or `.git/`. A folder is deleted
  on the other side only once it is empty, so files that are not synced (a teammate's notes, say) are never deleted
  with it. It works alongside git: WebDAV shares the files, git keeps the history
- Works on Windows and macOS, where `Fig.png` and `fig.png` are the same file: a rename that changes only the case is
  followed on both sides, and two files on the server whose names differ only in case are left out, with a message
  asking to rename one (on Linux they are synced, with a warning for teammates on the other systems)

## What's new

### 0.3.2 (2026-11-23)

- A missing or extra brace, a missing `\begin{document}` or a command that belongs in the preamble is shown in
  the error list with its hint, instead of the compile failing with no errors listed

### 0.3.1 (2026-11-22)

- **A new side bar**: one icon each for Files, Outline, Search, Git and WebDAV, instead of tab buttons cut short. The
  number of changed files shows on the Git icon, and a dot on the WebDAV icon when there is something to sync
- Files and folders in the list have icons; the buttons for a new file or folder, adding files, renaming and deleting
  are icons too. Folder names keep their case
- In the Search panel, match case, whole words and regular expressions are toggle buttons
- In the dark theme, scroll bars and other browser controls are dark too

### 0.3.0 (2026-11-22)

- **Share a project with your team over WebDAV** (Nextcloud, ownCloud, a NAS). Everyone edits their own copy and
  presses **Sync** in the new WebDAV tab. Edits to the same file are merged, and nothing on the server is
  overwritten by accident. A `.latexmkrc` from the server is downloaded only after you accept it. Teammates get the
  project with `--webdav URL`. See [Sharing a project over WebDAV](#sharing-a-project-over-webdav)
- WebDAV sign-in with Basic or Digest authentication; empty folders are synced too; renames that change only the case
  are followed on Windows and macOS
- The source code is on GitHub, and the editor runs straight from a clone with `./start.sh` or `.\start.cmd`

### 0.2.3 (2026-11-19)

- The PyPI page acknowledges the TeX trademark

### 0.2.2 (2026-11-19)

- **Sync** with GitHub in one click in the Git panel: pull, then push, with a choice of rebase or merge when both
  sides have new commits. The panel fetches in the background and shows how far ahead or behind you are
- Connect a project to a GitHub repository by pasting its address, or start a git repository for a project that has
  none

### 0.2.1 (2026-11-19)

- Find and replace in the open file (Ctrl/Cmd+F; Ctrl+H or Cmd+Option+F), with case, whole-word and
  regular-expression options, and Replace all as one undo step
- Replacing in all files keeps backslashes as typed, so `\textbf{$1}` works
- Errors that LaTeX prints without a line, such as a missing package, are listed with a hint

### 0.2.0 (2026-11-19)

- First release on PyPI: `pip install offline-tex-editor`. See [Features](#features) for what it does

## Options

| Option | Default | Meaning |
|---|---|---|
| `--root DIR` | current folder | LaTeX project folder |
| `--main FILE` | see below | main `.tex` file, relative to `--root` |
| `--engine NAME` | `auto` | `pdflatex`, `xelatex` or `lualatex`; see below |
| `--jobname NAME` | name of the main file | PDF name in `build/` |
| `--shell-escape` | off | let the document run programs (minted before v3, svg, gnuplottex); only for projects you trust |
| `--timeout N` | `600` | stop a compile after N seconds |
| `--port N` | first free from 8765 | port; several projects can be open at once |
| `--host ADDR` | `127.0.0.1` | bind address; the default is reachable only from your machine |
| `--open` | off | open the editor in your browser |
| `--no-initial-compile` | off | skip the compile at start-up |
| `--webdav URL` | | get the project from this WebDAV folder first (or send it there), and stay connected to it |
| `--webdav-user NAME` | | user name for `--webdav`; the password is asked for, unless it is in `~/.netrc` |
| `--version` | | print the version |

The PDF and auxiliary files go to `build/` in the project folder.

## Main document and engine

**Main document.** `--main` if given; otherwise `main.tex`; otherwise the `.tex` file with `\documentclass` that
looks most like a main file. A `% !TEX root = ../thesis.tex` comment in the chosen file is followed. To work on
another document of the same project (slides, a cover letter), pick it in ⚙. LaTeX runs in the main document's
folder, so a main document in a subfolder (such as `paper/main.tex`) finds the files next to it; the PDF still goes
to `build/` in the project folder.

**Engine.** In this order:
1. `--engine` on the command line;
2. a `% !TEX program = xelatex` (or `lualatex`, `pdflatex`) comment at the top of the main file, as used by
   TeXShop, TeXstudio and VS Code;
3. `$pdf_mode` in the project's `.latexmkrc` or `latexmkrc`;
4. otherwise pdfLaTeX.

⚙ shows which one is in effect and why.

## Sharing a project over WebDAV

One person connects the project: in the **WebDAV** panel (the cloud icon on the left), enter the address of an empty
folder on the server, your user name and your password, and press **Sync** to upload the project. Then share that
folder with the team on the server.
The address must start with `https://`. Nextcloud and ownCloud show the WebDAV address of your files in the Files
app's settings (bottom left); it looks like `https://cloud.example.org/remote.php/dav/files/USER/`, and the
folder's name goes at the end.

Each teammate then gets the project with the address of the shared folder in their own account:

```bash
offline-tex-editor --root thesis --webdav https://cloud.example.org/remote.php/dav/files/USER/Thesis/ --webdav-user USER --open
```

This creates the `thesis` folder, downloads the project into it, and opens the editor, connected to the server.
After that, `offline-tex-editor --root thesis` is enough: the connection is remembered (in `build/.editor-webdav/`).
Someone who already has a copy of the project can connect it in the WebDAV panel instead; the first sync compares the
two, and keeps the server's version of any file that differs as a "(server copy)" next to theirs.

- **Passwords** are kept only while the editor runs, and asked for again after a restart. To have yours remembered,
  put it in `~/.netrc` (a line `machine cloud.example.org login USER password …`, as curl uses). If your account
  uses two-factor sign-in, create an app password (Nextcloud: Settings, Security) and use that. Servers that ask for
  Digest authentication instead of Basic work too.
- **Conflicts.** Edits to different parts of a file are merged. When two people changed the same lines, the file
  gets blocks like `<<<<<<< this computer` … `=======` … `>>>>>>> server`: keep the right text, delete the marker
  lines, save, and sync again. A file that cannot be merged (or any file, without git) is listed under "Resolve
  first" with its "(server copy)": keep what you need in your file, delete the copy, and sync again.
- **Sync often**, at least before and after a working session: the sooner changes travel, the fewer conflicts.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl/Cmd+S | Save (and recompile, if auto-compile is on) |
| Ctrl/Cmd+Enter | Recompile |
| Ctrl/Cmd+J | Show the cursor position in the PDF |
| Double-click the PDF | Jump to the source |
| Ctrl+Space | Complete a command, label or citation key |
| Ctrl/Cmd+/ | Comment or uncomment lines |
| Ctrl/Cmd+B, Ctrl/Cmd+I | Put the selection in `\textbf{}` or `\textit{}`, or take it out again |
| Ctrl/Cmd+F | Find in the file (in the editor) or in the PDF (elsewhere) |
| Ctrl+H, Cmd+Option+F | Find and replace in the file |
| Enter, Shift+Enter | Next and previous match (also F3 and Ctrl/Cmd+G) |
| Ctrl/Cmd+Shift+F | Search and replace in all files |

## Security

The editor is meant for one person on their own machine. It has no login, so:

- **Keep the default `--host 127.0.0.1`.** The Git panel can push with your credentials and the WebDAV panel can
  sync with your password, and anyone who can reach the port can use them. Binding to another address prints a warning; put something with authentication in front of
  it if you need remote access.
- File operations stay inside the project folder, never touch `.git/` or `build/`, and only open or create
  editable source types (`.tex .bib .sty .cls .bst .md .txt .csv .py .sh` and a few more). Uploads are limited to
  those and to images and PDFs. Deleted files are moved to `build/.editor-trash/`, not erased.
- It refuses requests that a web page from another site could make while the editor is open: requests whose `Host`
  header is not this machine (DNS rebinding), and POSTs that are cross-origin or are not JSON (cross-site request
  forgery). The page cannot be framed by other sites, and its Content-Security-Policy allows no inline or
  evaluated scripts. Images are served with a sandboxing policy, so an SVG cannot run scripts.
- Git commands never prompt: a push that needs credentials you have not set up fails with git's message instead
  of hanging.
- WebDAV passwords stay in memory (or in your `~/.netrc`): the editor never writes them to disk, sends them only over
  https and only to the address you entered (it does not follow redirects). Files from the server get the same
  checks as everything else: they stay inside the project folder, never go into `.git/` or `build/`, and are limited
  to editable types, images and PDFs. A `.latexmkrc` from the server is downloaded only when you accept it. Still,
  syncing a folder means trusting the people who can write to it, as with a shared git repository.
- Compiling runs `latexmk`, which reads the project's `.latexmkrc` (Perl code); `--shell-escape` lets the document
  run programs. Only compile projects you trust, as with any LaTeX toolchain.

To report a security problem privately, see
[Contact](https://offline-tex-editor.github.io/#contact).

## Help and suggestions

Ideas, bug reports and questions are welcome: use the
[suggestion box](https://offline-tex-editor.github.io/#suggest) on the website or the
[issue tracker](https://github.com/offline-tex-editor/offline-tex-editor/issues).

## Contributing

The source code is on [GitHub](https://github.com/offline-tex-editor/offline-tex-editor). Bug fixes and
improvements are welcome as pull requests; for a larger change, please open an issue first so that we can agree on
the approach. [CONTRIBUTING.md](https://github.com/offline-tex-editor/offline-tex-editor/blob/main/CONTRIBUTING.md)
explains how to run the editor from a clone, run the tests, and the few rules the code follows.

## License

MIT License; see [LICENSE](https://github.com/offline-tex-editor/offline-tex-editor/blob/main/LICENSE) (the
full text also comes with the package). Offline TeX Editor includes CodeMirror 5 (MIT) and pdf.js
(Apache-2.0), which keep their own licenses.

TeX is a trademark of the American Mathematical Society.
