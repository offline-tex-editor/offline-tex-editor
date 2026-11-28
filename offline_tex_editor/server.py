"""Offline TeX Editor: a LaTeX editor that runs on your own machine. Edit in the browser, compile with latexmk,
preview the PDF with SyncTeX both ways, find and replace, use git, and sync with a WebDAV folder. Standard library
only; serves on 127.0.0.1 by default.

    offline-tex-editor [--root PROJECT_DIR] [--main FILE] [--engine auto] [--port N] [--open]
    offline-tex-editor --root PROJECT_DIR --webdav FOLDER_URL [--webdav-user NAME]

Compiles with latexmk into <root>/build/<jobname>.pdf with -synctex=1, and -f so a PDF is still produced when there
are errors.
"""
import argparse
import base64
import difflib
import getpass
import gzip
import io
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse, urlsplit

from . import __version__, gitapi, latexlog, project, webdav

HERE = Path(__file__).resolve().parent
STATIC = {'static': HERE / 'static', 'vendor': HERE / 'vendor'}
TYPES = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
         '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
         '.pdf': 'application/pdf', '.eps': 'application/postscript', '.tif': 'image/tiff', '.tiff': 'image/tiff',
         '.bmp': 'image/bmp'}
WILDCARD_HOSTS = {'0.0.0.0', '::', ''}
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024 * 1024
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
RAW_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox; frame-ancestors 'none'"
# Long log lines, so file names and messages are not wrapped at 79 characters (TeX Live reads these from the env).
TEX_ENV = dict(os.environ, max_print_line='1000', error_line='254', half_error_line='238')

ROOT = None
MAIN = 'main.tex'
JOB = 'main'
ENGINE = 'auto'
SHELL_ESCAPE = False
TIMEOUT = 600
ALLOWED_HOSTS = {'localhost', '127.0.0.1', '::1'}
ANY_HOST = False
settings = {'draft': False, 'only': None}
compile_lock = threading.Lock()
git_lock = threading.Lock()
webdav_lock = threading.Lock()
fs_lock = threading.Lock()
proc_state = {'proc': None, 'stop': False, 'force_next': False, 'last_sig': None}
last_compile = {}


class UserError(Exception):
    """A request the user can fix: answered with 400 and the message."""


class Conflict(Exception):
    """Answered with 409 and the payload."""

    def __init__(self, payload):
        super().__init__(payload.get('error', 'conflict'))
        self.payload = payload


def reset_compile_state():
    last_compile.clear()
    last_compile.update(success=None, started=None, finished=None, seconds=None, errors=[], warnings=[], log_tail='',
                        running=False, stopped=False, engine=None, engine_source=None)


reset_compile_state()


def configure(root, main=None, jobname=None, host='127.0.0.1', engine='auto', shell_escape=False, timeout=600):
    """Set the project and options. Called by main() and by the tests. Raises ValueError for a bad --root/--main."""
    global ROOT, MAIN, JOB, ENGINE, SHELL_ESCAPE, TIMEOUT, ALLOWED_HOSTS, ANY_HOST
    ROOT = Path(root).resolve()
    if not ROOT.is_dir():
        raise ValueError(f'{root} is not a directory')
    MAIN = project.resolve_main(ROOT, main)
    JOB = jobname or Path(MAIN).stem
    ENGINE, SHELL_ESCAPE, TIMEOUT = engine, shell_escape, timeout
    ALLOWED_HOSTS = {'localhost', '127.0.0.1', '::1', host.lower().strip('[]')}
    ANY_HOST = host in WILDCARD_HOSTS
    settings.update(draft=False, only=None)
    proc_state.update(proc=None, stop=False, force_next=False, last_sig=None)
    reset_compile_state()


# ---------- paths ----------

def rel_of(p):
    return p.relative_to(ROOT).as_posix()


def safe(rel):
    """Resolve a path inside ROOT; refuse anything outside it."""
    p = (ROOT / rel).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise PermissionError(f'{rel} is outside the project')
    return p


def editable(rel):
    """A path the editor may open or save: inside ROOT, an editable type, and not inside .git."""
    p = safe(rel)
    if not project.is_editable(p) or '.git' in p.relative_to(ROOT).parts:
        raise PermissionError(f'{rel} is not an editable file')
    return p


def asset(rel):
    p = safe(rel)
    if p.suffix.lower() not in project.ASSETS:
        raise PermissionError(f'{rel} is not an image or PDF')
    return p


def fs_target(rel):
    """A path file operations may create, rename or delete: inside ROOT, not ROOT, not in build/ or .git/."""
    p = safe(rel)
    if p == ROOT or project.skipped(p.relative_to(ROOT)):
        raise PermissionError(f'{rel}: not allowed here')
    return p


def hostname(netloc):
    try:
        return urlsplit('//' + netloc).hostname
    except ValueError:
        return None


def list_files():
    return project.list_files(ROOT)[0]


def main_dir():
    """The main file's folder. TeX runs there (latexmk -cd), so \\input, \\includegraphics, \\bibliography and
    \\documentclass find the files next to the main file, and relative names in TeX's output are relative to it."""
    return (ROOT / MAIN).parent


def tex_path(name):
    """A file name as TeX, BibTeX or SyncTeX write it (absolute, or relative to main_dir()), resolved inside ROOT."""
    return safe(main_dir() / name)


# ---------- compiling ----------

def effective_engine():
    """(engine or None to let the project's latexmkrc decide, where the choice comes from)."""
    if ENGINE != 'auto':
        return ENGINE, '--engine'
    try:
        magic = project.engine_from_magic(project.read_text(ROOT / MAIN, 65536))
    except OSError:
        magic = None
    if magic:
        return magic, '% !TEX program'
    if project.rc_sets_pdf_mode(ROOT):
        return None, 'latexmkrc'
    return 'pdflatex', 'default'


def latexmk_cmd(engine, force=False):
    cmd = ['latexmk']
    if force:
        cmd.append('-g')
    if engine:
        cmd.append({'pdflatex': '-pdf', 'xelatex': '-xelatex', 'lualatex': '-lualatex'}[engine])
    outdir = Path(os.path.relpath(ROOT / 'build', main_dir())).as_posix()   # build/, seen from the main file's folder
    cmd += ['-cd', '-f', '-interaction=nonstopmode', '-file-line-error', '-synctex=1', f'-outdir={outdir}',
            f'-jobname={JOB}']
    if SHELL_ESCAPE:
        cmd.append('-shell-escape')
    pretex = ''
    if settings['draft']:
        pretex += r'\PassOptionsToPackage{draft}{graphicx}'
    if settings['only']:
        pretex += r'\includeonly{%s}' % settings['only']
    if pretex:
        cmd.append('-usepretex=' + pretex)
    cmd.append(MAIN)
    return cmd


def kill_tree(proc):
    """Stop latexmk and the programs it started (it runs in its own process group)."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(3)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)


def mirror_dirs():
    """Create build/<dir> for each source folder below the main file's. TeX cannot create folders, so with an output
    directory, \\include{chapters/one} fails ("I can't write on file chapters/one.aux") unless build/chapters exists."""
    base = main_dir()
    for p, _ in project.walk(ROOT):
        if p.suffix == '.tex' and base in p.parent.parents:
            (ROOT / 'build' / p.parent.relative_to(base)).mkdir(parents=True, exist_ok=True)


def run_latexmk(cmd):
    """(exit code, output, why it ended early: None, 'timeout', 'stopped' or 'missing')."""
    group = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', env=TEX_ENV, **group)
    except FileNotFoundError:
        return -1, 'latexmk not found on PATH. Install a TeX distribution that includes it (TeX Live does).', 'missing'
    proc_state['proc'] = proc
    try:
        try:
            out, _ = proc.communicate(timeout=TIMEOUT)
            why = 'stopped' if proc_state['stop'] else None
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            out, _ = proc.communicate()
            out, why = out + f'\nlatexmk timed out after {TIMEOUT} s (see --timeout)', 'timeout'
    finally:
        proc_state['proc'] = None
    return proc.returncode, out, why


def stop_compile():
    proc = proc_state['proc']
    if proc is None:
        return {'stopped': False}
    proc_state['stop'] = True
    kill_tree(proc)
    return {'stopped': True}


def bib_index():
    return {e['key']: (e['file'], e['line']) for e in project.bib_entries(ROOT, list_files())}


def bib_file(name):
    """A .bib name from a BibTeX/biber log, as a project path (they may give a bare file name)."""
    if not name:
        return None
    try:
        p = tex_path(name)
        if p.is_file():
            return rel_of(p)
    except PermissionError:
        pass
    base = Path(name).name
    return next((f for f in list_files() if Path(f).name == base), name)


def read_logs():
    log_path, blg_path = ROOT / 'build' / f'{JOB}.log', ROOT / 'build' / f'{JOB}.blg'
    index = None

    def find_key(key):
        nonlocal index
        index = bib_index() if index is None else index
        return index.get(key)

    errors, warnings = latexlog.parse_log(project.read_text(log_path) if log_path.exists() else '', ROOT, find_key,
                                          main_dir())
    if blg_path.exists():
        berr, bwarn, _ = latexlog.parse_blg(project.read_text(blg_path))
        for item in berr + bwarn:
            item['file'] = bib_file(item['file'])
        errors += berr
        warnings += bwarn
    return errors, warnings


def run_compile():
    with compile_lock:
        last_compile.update(running=True, started=time.time(), stopped=False)
        proc_state['stop'] = False
        t0 = time.time()
        engine, source = effective_engine()
        sig = (MAIN, JOB, engine, settings['draft'], settings['only'], SHELL_ESCAPE)
        force = (proc_state['force_next'] or proc_state['last_sig'] not in (None, sig)
                 or not (ROOT / 'build' / f'{JOB}.synctex.gz').exists())
        cmd = latexmk_cmd(engine, force)
        try:
            errors, warnings = [], []
            mirror_dirs()
            code, out, why = run_latexmk(cmd)
            if why != 'missing':
                errors, warnings = read_logs()
                try:
                    rotate_snapshots()
                except Exception as e:  # the change view is a convenience; never fail the compile over it
                    print(f'snapshot failed: {e!r}', flush=True)
        except BaseException:
            last_compile['running'] = False  # never leave the UI showing "compiling…" forever
            raise
        proc_state.update(last_sig=sig, force_next=why in ('timeout', 'stopped'))
        last_compile.update(success=(code == 0 and not errors and why is None), finished=time.time(),
                            seconds=round(time.time() - t0, 1), errors=errors, warnings=warnings,
                            log_tail='\n'.join(out.splitlines()[-80:]), running=False, stopped=why == 'stopped',
                            engine=engine, engine_source=source, main=MAIN)
        return dict(last_compile)


def pdf_info():
    """(mtime, complete) of the PDF, or (None, False). A PDF still being written has no %%EOF at its end yet."""
    pdf = ROOT / 'build' / f'{JOB}.pdf'
    try:
        size, mtime = pdf.stat().st_size, pdf.stat().st_mtime
        with open(pdf, 'rb') as f:
            f.seek(max(0, size - 2048))
            return mtime, b'%%EOF' in f.read()
    except OSError:
        return None, False


def settings_view():
    engine, source = effective_engine()
    entries, includes = project.outline(ROOT, MAIN)
    return {'main': MAIN, 'job': JOB, 'draft': settings['draft'], 'only': settings['only'], 'engine': engine,
            'engine_source': source, 'shell_escape': SHELL_ESCAPE, 'timeout': TIMEOUT,
            'roots': project.find_roots(ROOT, list_files()), 'includes': includes,
            'tools': {t: shutil.which(t) is not None for t in ('latexmk', 'synctex', 'texcount', 'git', 'biber')}}


def set_main(rel):
    global MAIN, JOB
    p = editable(rel)
    if p.suffix != '.tex' or not project.is_root(project.read_text(p, 65536)):
        raise UserError(f'{rel} is not a LaTeX document (no \\documentclass)')
    MAIN, JOB = rel_of(p), p.stem
    settings['only'] = None
    reset_compile_state()


def update_settings(b):
    if 'main' in b and b['main'] != MAIN:
        set_main(b['main'])
    if 'draft' in b:
        settings['draft'] = bool(b['draft'])
    if 'only' in b:
        only = b['only'] or None
        if only is not None and only not in project.outline(ROOT, MAIN)[1]:
            raise UserError(f'{only} is not \\include\'d by {MAIN}')
        settings['only'] = only
    return settings_view()


# ---------- changes between compiles ----------
# After each compile the source files it read are snapshotted to build/.editor-snapshots/<job>-last.json. When the
# sources differ from the previous snapshot, that one becomes <job>-prev.json, so /api/changes always shows the most
# recent compile that changed something.

def snap_file(name):
    return ROOT / 'build' / '.editor-snapshots' / f'{JOB}-{name}.json'


def compile_inputs():
    """Project files the last compile read: INPUT lines of the .fls, plus the .bib databases named in the .blg."""
    rels = set()
    fls = ROOT / 'build' / f'{JOB}.fls'
    if fls.exists():
        for line in project.read_text(fls).splitlines():
            if line.startswith('INPUT '):
                rels.add(line[6:].strip())
    blg = ROOT / 'build' / f'{JOB}.blg'
    if blg.exists():
        rels.update(latexlog.parse_blg(project.read_text(blg))[2])
    out = set()
    for r in rels:
        try:
            p = tex_path(r)
        except PermissionError:
            continue
        if p.is_file() and project.is_editable(p) and not project.skipped(p.relative_to(ROOT)):
            out.add(rel_of(p))
    return sorted(out) or [f for f in list_files() if f.endswith(('.tex', '.bib'))]


def load_snapshot(name):
    p = snap_file(name)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def rotate_snapshots():
    cur = {'time': time.time(), 'files': {r: project.read_text(ROOT / r) for r in compile_inputs()}}
    last = load_snapshot('last')
    if last and last['files'] == cur['files']:
        return
    snap_file('last').parent.mkdir(parents=True, exist_ok=True)
    if last:
        snap_file('prev').write_text(json.dumps(last), encoding='utf-8')
    snap_file('last').write_text(json.dumps(cur), encoding='utf-8')


TOKEN = re.compile(r'\s+|\w+|[^\w\s]')


def word_diff(a, b):
    """Segments [kind, text] (kind eq/add/del) turning a into b, word by word; a near-total rewrite is shown whole."""
    ta, tb = TOKEN.findall(a), TOKEN.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    if sm.ratio() < 0.3:
        return [['del', a], ['add', b]]
    segs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        parts = [['eq', ''.join(ta[i1:i2])]] if tag == 'equal' else \
                [['del', ''.join(ta[i1:i2])], ['add', ''.join(tb[j1:j2])]]
        for kind, text in parts:
            if not text:
                continue
            if segs and segs[-1][0] == kind:
                segs[-1][1] += text
            else:
                segs.append([kind, text])
    return segs


def file_hunks(a, b, context=2):
    al, bl = a.splitlines(), b.splitlines()
    hunks = []
    for group in difflib.SequenceMatcher(None, al, bl, autojunk=False).get_grouped_opcodes(context):
        segs = []
        for tag, i1, i2, j1, j2 in group:
            old, new = '\n'.join(al[i1:i2]) + '\n', '\n'.join(bl[j1:j2]) + '\n'
            if tag == 'equal':
                segs.append(['eq', old])
            elif tag == 'delete':
                segs.append(['del', old])
            elif tag == 'insert':
                segs.append(['add', new])
            else:
                segs.extend(word_diff(old, new))
        hunks.append({'line': group[0][3] + 1, 'segs': segs})
    return hunks


def changes():
    prev, last = load_snapshot('prev'), load_snapshot('last')
    if not prev or not last:
        return {'baseline': False, 'files': []}
    files = []
    for rel in sorted(set(prev['files']) | set(last['files'])):
        a, b = prev['files'].get(rel), last['files'].get(rel)
        if a == b:
            continue
        status = 'added' if a is None else 'deleted' if b is None else 'modified'
        files.append({'path': rel, 'status': status, 'hunks': file_hunks(a or '', b or '')})
    return {'baseline': True, 'from': prev['time'], 'to': last['time'], 'files': files}


# ---------- SyncTeX ----------

_synctex_cache = {'key': None, 'names': {}}


def synctex_names():
    """Input file names exactly as the .synctex.gz records them, by resolved path. Forward search must use the
    recorded name, which may be relative, start with ./ or contain spaces."""
    f = ROOT / 'build' / f'{JOB}.synctex.gz'
    try:
        key = (f, f.stat().st_mtime)
    except OSError:
        return {}
    if _synctex_cache['key'] != key:
        names = {}
        with gzip.open(f, 'rt', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if line.startswith('Input:'):
                    name = line.split(':', 2)[2].rstrip('\n')
                    p = Path(name)
                    try:
                        names.setdefault((main_dir() / p).resolve(), name)
                    except OSError:
                        pass
        _synctex_cache.update(key=key, names=names)
    return _synctex_cache['names']


def synctex(args):
    proc = subprocess.run(['synctex', *args], cwd=ROOT / 'build', capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=20)
    return proc.stdout


def synctex_view(rel, line, column=0):
    """PDF position of a source line. Lines with no typeset material (blank, comments, \\begin) have no record, so
    nearby lines are tried, nearest first."""
    src = safe(rel)
    name = synctex_names().get(src, str(src))
    for delta in (0, 1, -1, 2, -2, 3, -3, 4, 5, 6, 8, 10):
        ln = line + delta
        if ln < 1:
            continue
        out = synctex(['view', '-i', f'{ln}:{column}:{name}', '-o', f'{JOB}.pdf'])
        pages = re.findall(r'^Page:(\d+)$', out, re.M)
        if pages:
            ys = re.findall(r'^y:([\d.]+)$', out, re.M)
            xs = re.findall(r'^x:([\d.]+)$', out, re.M)
            return {'page': int(pages[0]), 'x': float(xs[0]) if xs else 0, 'y': float(ys[0]) if ys else 0,
                    'line': ln}
    raise FileNotFoundError('no PDF location for that line (compile first?)')


def synctex_edit(page, x, y):
    out = synctex(['edit', '-o', f'{int(page)}:{float(x):.2f}:{float(y):.2f}:{JOB}.pdf'])
    f = re.search(r'^Input:(.*)$', out, re.M)
    ln = re.search(r'^Line:(-?\d+)$', out, re.M)
    if not f:
        raise FileNotFoundError('no source location for that spot')
    p = Path(f.group(1))
    p = (main_dir() / p).resolve()
    if ROOT not in p.parents:
        raise FileNotFoundError(f'that spot comes from {f.group(1)}, outside the project')
    return {'path': rel_of(p), 'line': max(1, int(ln.group(1))) if ln else 1}


# ---------- other tools ----------

WORDCOUNT_FIELDS = {'Words in text': 'text', 'Words in headers': 'headers',
                    'Words outside text (captions, etc.)': 'outside', 'Number of headers': 'n_headers',
                    'Number of floats/tables/figures': 'floats', 'Number of math inlines': 'math_inline',
                    'Number of math displayed': 'math_display'}


def word_count():
    if shutil.which('texcount') is None:
        raise UserError('texcount not found. It comes with TeX Live (on Debian/Ubuntu: texlive-extra-utils).')
    p = subprocess.run(['texcount', '-inc', '-total', '-utf8', '-q', Path(MAIN).name], cwd=main_dir(),
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    out = {}
    for line in p.stdout.splitlines():
        k, _, v = line.partition(':')
        if k.strip() in WORDCOUNT_FIELDS and v.strip().isdigit():
            out[WORDCOUNT_FIELDS[k.strip()]] = int(v)
    if 'text' not in out:
        raise UserError('texcount failed: ' + (p.stderr or p.stdout).strip()[:300])
    return out


# ---------- export ----------

def export_file(path):
    """A resolved, regular file inside the project, or None (including broken or cyclic links)."""
    try:
        real = path.resolve()
        return real if ROOT in real.parents and real.is_file() else None
    except (OSError, RuntimeError):
        return None


def export_zip():
    """The project's sources as a .zip, as they are saved: its files, without build/, .git/ or other hidden files and
    folders (.latexmkrc is kept), and with the bibliography made in the last compile (build/<job>.bbl) next to the
    main document, named after it, which is where arXiv for one looks for it. A .bbl of the project's own is kept."""
    buf, names = io.BytesIO(), set()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p, rel in project.walk(ROOT):
            hidden = any(part.startswith('.') for part in rel.split('/')) and rel not in project.EDITABLE_NAMES
            real = export_file(p)
            if hidden or real is None:
                continue
            z.write(real, rel)
            names.add(rel)
        bbl, name = export_file(ROOT / 'build' / f'{JOB}.bbl'), Path(MAIN).with_suffix('.bbl').as_posix()
        if bbl is not None and name not in names:
            z.write(bbl, name)
    return buf.getvalue()


def export_note():
    """What to tell about the .bbl in the .zip, or None: none was made yet, or it may be older than the sources."""
    if export_file(ROOT / Path(MAIN).with_suffix('.bbl')) is not None:
        return None   # the project's own .bbl goes in as it is
    files = list_files()
    sources = [p for f in files if f.endswith(('.tex', '.bib')) for p in [export_file(ROOT / f)] if p is not None]
    bibs = [p for f in files if f.endswith('.bib') for p in [export_file(ROOT / f)] if p is not None]
    bbl, aux = export_file(ROOT / 'build' / f'{JOB}.bbl'), export_file(ROOT / 'build' / f'{JOB}.aux')
    if bbl is None:
        return ('No bibliography from a compile is available inside the project, so the .zip has no .bbl. '
                'If the document uses BibTeX or biber, '
                'compile it, then download again.') if bibs else None
    newest = max((p.stat().st_mtime for p in sources), default=0)
    compiled = aux.stat().st_mtime if aux is not None else bbl.stat().st_mtime
    if newest > compiled or any(b.stat().st_mtime > bbl.stat().st_mtime for b in bibs):
        return 'Sources changed since the last compile, so the .bbl may be out of date. Recompile, then download again.'
    return None


# ---------- file operations ----------

def fs_new(b):
    p = fs_target(b['path'])
    with fs_lock:
        if p.exists():
            raise UserError(f"{b['path']} already exists")
        if b.get('kind') == 'folder':
            p.mkdir(parents=True)
        else:
            if not project.is_editable(p):
                raise UserError('a new file needs an editable extension such as .tex or .bib')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'')
    return {'path': rel_of(p)}


def fs_rename(b):
    global MAIN
    a, dst = fs_target(b['from']), fs_target(b['to'])
    with fs_lock:
        if not a.exists():
            raise FileNotFoundError(b['from'])
        if dst.exists():
            raise UserError(f"{b['to']} already exists")
        if a.is_file() and not (project.is_editable(dst) or dst.suffix.lower() in project.ASSETS):
            raise UserError('keep an editable or image extension')
        if a.is_dir() and a in dst.parents:
            raise UserError('cannot move a folder into itself')
        dst.parent.mkdir(parents=True, exist_ok=True)
        main = ROOT / MAIN
        a.rename(dst)
        if main == a or a in main.parents:  # keep compiling the same document
            MAIN = rel_of(dst / main.relative_to(a)) if main != a else rel_of(dst)
    return {'path': rel_of(dst), 'main': MAIN}


def fs_delete(b):
    p = fs_target(b['path'])
    with fs_lock:
        if not p.exists():
            raise FileNotFoundError(b['path'])
        main = ROOT / MAIN
        if p == main or p in main.parents:
            raise UserError('this is the main document (or its folder); choose another main document first')
        dest = project.trash(ROOT, p)  # not deleted, so a mistake can be undone
    return {'trash': rel_of(dest)}


def fs_upload(b):
    p = fs_target(b['path'])
    if not (project.is_editable(p) or p.suffix.lower() in project.ASSETS):
        raise UserError(f"{b['path']}: only images, PDFs and editable files can be added")
    try:
        data = base64.b64decode(b['data'], validate=True)
    except ValueError:
        raise UserError('bad file data')
    with fs_lock:
        if p.exists() and not b.get('replace'):
            raise Conflict({'error': f"{b['path']} already exists", 'exists': True})
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return {'path': rel_of(p), 'size': len(data)}


# ---------- search ----------

def query_rx(d):
    try:
        return project.compile_query(d['q'], str(d.get('regex')) in ('1', 'True', 'true'),
                                     str(d.get('case')) in ('1', 'True', 'true'),
                                     str(d.get('word')) in ('1', 'True', 'true'))
    except re.error as e:
        raise UserError(f'bad regular expression: {e}')


def h_search(q):
    if not q.get('q'):
        return {'matches': [], 'truncated': False}
    matches, truncated = project.search(ROOT, list_files(), query_rx(q))
    return {'matches': matches, 'truncated': truncated}


def h_replace(b):
    if not b.get('q'):
        raise UserError('nothing to replace')
    files = list_files()
    if b.get('paths'):
        files = [f for f in files if f in set(b['paths'])]
    regex = bool(b.get('regex'))
    try:
        counts = project.replace(ROOT, files, query_rx(b), b.get('replacement', ''), regex)
    except UnicodeEncodeError as e:
        raise UserError(f'cannot save: the replacement has characters the file\'s encoding cannot hold ({e.reason})')
    return {'files': counts, 'replaced': sum(counts.values())}


# ---------- HTTP ----------

def h_file(q):
    p = editable(q['path'])
    text, enc, eol = project.read_source(p)
    return {'path': q['path'], 'content': text, 'mtime': p.stat().st_mtime, 'encoding': enc, 'eol': eol}


def h_save(b):
    p = editable(b['path'])
    on_disk = p.stat().st_mtime if p.exists() else None
    if b.get('mtime') and on_disk and abs(on_disk - b['mtime']) > 1e-6 and not b.get('force'):
        raise Conflict({'error': 'changed on disk since you opened it', 'mtime': on_disk})
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        project.write_source(p, b['content'], b.get('encoding', 'utf-8'))
    except UnicodeEncodeError as e:
        raise UserError(f'cannot save as {b.get("encoding")}: {e.reason}. Remove the characters it cannot hold.')
    return {'mtime': p.stat().st_mtime}


def h_status(q):
    mtime, complete = pdf_info()
    return dict(last_compile, pdf_mtime=mtime, pdf_complete=complete, main=MAIN, job=JOB, draft=settings['draft'],
                only=settings['only'])


def h_compile(b):
    if compile_lock.locked():
        raise Conflict({'error': 'a compile is already running'})
    return run_compile()


def h_outline(q):
    entries, includes = project.outline(ROOT, MAIN)
    return {'main': MAIN, 'entries': entries, 'includes': includes}


def h_labels(q):
    files = list_files()
    return {'labels': project.labels(ROOT, files), 'bib': project.bib_entries(ROOT, files),
            'commands': project.commands(ROOT, files)}


GET_ROUTES = {
    '/api/files': lambda q: dict(zip(('files', 'assets'), project.list_files(ROOT)), dirs=project.list_dirs(ROOT),
                                 root=str(ROOT), main=MAIN),
    '/api/file': h_file,
    '/api/mtime': lambda q: {'mtime': (lambda p: p.stat().st_mtime if p.exists() else None)(editable(q['path']))},
    '/api/status': h_status,
    '/api/settings': lambda q: settings_view(),
    '/api/changes': lambda q: changes(),
    '/api/synctex/edit': lambda q: synctex_edit(q['page'], q['x'], q['y']),
    '/api/synctex/view': lambda q: synctex_view(q['path'], int(q['line']), int(q.get('column', 0))),
    '/api/search': h_search,
    '/api/outline': h_outline,
    '/api/labels': h_labels,
    '/api/wordcount': lambda q: word_count(),
    '/api/git/status': lambda q: gitapi.status(ROOT),
    '/api/git/diff': lambda q: gitapi.diff(ROOT, q['path'], q.get('staged') == '1'),
    '/api/git/log': lambda q: gitapi.log(ROOT),
    '/api/git/show': lambda q: gitapi.show(ROOT, q['rev']),
    '/api/webdav/status': lambda q: webdav.status(ROOT),
}
POST_ROUTES = {
    '/api/file': h_save,
    '/api/compile': h_compile,
    '/api/compile/stop': lambda b: stop_compile(),
    '/api/settings': update_settings,
    '/api/replace': h_replace,
    '/api/fs/new': fs_new,
    '/api/fs/rename': fs_rename,
    '/api/fs/delete': fs_delete,
    '/api/fs/upload': fs_upload,
}
GIT_OPS = {
    'stage': lambda b: gitapi.stage(ROOT, b.get('paths', []), bool(b.get('all'))),
    'unstage': lambda b: gitapi.unstage(ROOT, b.get('paths', [])),
    'commit': lambda b: gitapi.commit(ROOT, b.get('message', ''), bool(b.get('amend'))),
    'push': lambda b: gitapi.push(ROOT),
    'pull': lambda b: gitapi.pull(ROOT, b.get('mode', 'ff')),
    'fetch': lambda b: gitapi.fetch(ROOT),
    'abort': lambda b: gitapi.abort(ROOT),
    'continue': lambda b: gitapi.resume(ROOT),
    'sync': lambda b: gitapi.sync(ROOT, b.get('mode', 'ff')),
    'remote': lambda b: gitapi.set_remote(ROOT, b.get('url', '')),
    'init': lambda b: gitapi.init(ROOT),
}
def h_webdav_sync(b):
    """Sync, and keep compiling the same document when the sync renamed it (a rename that changed only the case)."""
    global MAIN
    r = webdav.sync(ROOT, MAIN, b.get('accept') or [])
    for old, new in r['result']['renamed_here']:
        if MAIN == old or MAIN.startswith(old + '/'):
            MAIN = new + MAIN[len(old):]
    return dict(r, main=MAIN)


# Each one asks the server (only POSTs may: another site's page can make the browser send a GET, but not a JSON POST).
WEBDAV_OPS = {
    'connect': lambda b: webdav.connect(ROOT, b.get('url', ''), b.get('user', ''), b.get('password', '')),
    'disconnect': lambda b: webdav.disconnect(ROOT),
    'check': lambda b: webdav.check(ROOT, MAIN),
    'sync': lambda b: h_webdav_sync(b),
    'peek': lambda b: webdav.peek(ROOT, b.get('path')),
}


class Handler(BaseHTTPRequestHandler):
    server_version = f'OfflineTeXEditor/{__version__}'

    def log_message(self, fmt, *a):
        pass

    def send(self, code, body, ctype='application/json', csp="frame-ancestors 'none'", headers=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == 'application/json' else body).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')  # no clickjacking the Push button from another site
        self.send_header('Content-Security-Policy', csp)
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get('Content-Length', 0))
        if n > MAX_BODY:
            raise UserError(f'request too large (over {MAX_BODY // 2**20} MB)')
        return json.loads(self.rfile.read(n) or b'{}')

    def refused(self, post):
        """Why this request must be refused, or None.

        The server has no login, so it must only answer the editor page itself. A Host header naming another site
        means DNS rebinding; an Origin from another site, or a POST that is not JSON (which a cross-site page can send
        without a CORS preflight), means cross-site request forgery.
        """
        host = self.headers.get('Host', '')
        if not ANY_HOST and hostname(host) not in ALLOWED_HOSTS:
            return f'unexpected Host header {host!r}'
        if post:
            origin = self.headers.get('Origin')
            if origin is not None and urlsplit(origin).netloc != host:
                return f'cross-origin request from {origin!r} refused'
            if self.headers.get_content_type() != 'application/json':
                return 'Content-Type must be application/json'
        return None

    def fail(self, e):
        if isinstance(e, PermissionError):
            return self.send(403, {'error': str(e)})
        if isinstance(e, Conflict):
            return self.send(409, e.payload)
        if isinstance(e, KeyError):
            return self.send(400, {'error': f'missing parameter {e}'})
        if isinstance(e, webdav.NeedPassword):
            return self.send(400, {'error': str(e), 'needs_password': True})
        if isinstance(e, (UserError, gitapi.GitError, webdav.DavError, ValueError)):
            return self.send(400, {'error': str(e)})
        if isinstance(e, FileNotFoundError):
            return self.send(404, {'error': str(e)})
        if isinstance(e, subprocess.TimeoutExpired):
            return self.send(504, {'error': f'{e.cmd[0]} timed out'})
        return self.send(500, {'error': repr(e)})

    def do_GET(self):
        why = self.refused(post=False)
        if why:
            return self.send(403, {'error': why})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ('/', '/index.html'):
                return self.send(200, (HERE / 'index.html').read_bytes(), 'text/html; charset=utf-8', PAGE_CSP)
            if u.path == '/pdf':
                mtime, complete = pdf_info()
                if mtime is None:
                    return self.send(404, {'error': 'no PDF yet; compile first'})
                if not complete:
                    return self.send(409, {'error': 'the PDF is still being written'})
                return self.send(200, (ROOT / 'build' / f'{JOB}.pdf').read_bytes(), 'application/pdf')
            if u.path == '/api/export':
                note = export_note()
                return self.send(200, export_zip(), 'application/zip',
                                 headers={'X-Export-Note': quote(note)} if note else None)
            if u.path == '/api/raw':
                p = asset(q['path'])
                return self.send(200, p.read_bytes(), TYPES.get(p.suffix.lower(), 'application/octet-stream'),
                                 RAW_CSP)
            route = GET_ROUTES.get(u.path)
            if route:
                return self.send(200, route(q))
            top, _, rest = u.path.lstrip('/').partition('/')
            if top in STATIC and rest:
                p = (STATIC[top] / rest).resolve()
                if STATIC[top] in p.parents and p.is_file():
                    ctype = TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
                    return self.send(200, p.read_bytes(), ctype)
            return self.send(404, {'error': 'not found'})
        except Exception as e:  # report, don't crash the server
            return self.fail(e)

    def do_POST(self):
        why = self.refused(post=True)
        if why:
            return self.send(403, {'error': why})
        u = urlparse(self.path)
        try:
            b = self.body()
            route = POST_ROUTES.get(u.path)
            if route:
                return self.send(200, route(b))
            if u.path.startswith('/api/git/'):
                op = GIT_OPS.get(u.path.rsplit('/', 1)[1])
                if op is None:
                    return self.send(404, {'error': 'unknown git operation'})
                with git_lock:
                    return self.send(200, op(b))
            if u.path.startswith('/api/webdav/'):
                op = WEBDAV_OPS.get(u.path.rsplit('/', 1)[1])
                if op is None:
                    return self.send(404, {'error': 'unknown WebDAV operation'})
                if not webdav_lock.acquire(blocking=False):
                    raise Conflict({'error': 'a WebDAV sync is already running'})
                try:
                    return self.send(200, op(b))
                finally:
                    webdav_lock.release()
            return self.send(404, {'error': 'not found'})
        except Exception as e:
            return self.fail(e)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two servers share a port, which would hide that the port is busy.
    allow_reuse_address = os.name != 'nt'


def make_server(host, port):
    """Listen on host:port, or on the first free port from 8765 when port is None."""
    cls = Server
    if ':' in host:
        cls = type('Server6', (Server,), {'address_family': socket.AF_INET6})
    ports = [port] if port else list(range(DEFAULT_PORT, DEFAULT_PORT + 20))
    err = None
    for p in ports:
        try:
            return cls((host, p), Handler)
        except OSError as e:
            err = e
    if port:
        raise SystemExit(f'cannot listen on {host}:{port}: {err.strerror or err}')
    raise SystemExit(f'no free port between {ports[0]} and {ports[-1]} on {host}; pass --port')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='offline-tex-editor', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, default=Path.cwd(), help='LaTeX project directory (default: current directory)')
    ap.add_argument('--main', help='main .tex file, relative to --root (default: main.tex, or the document found)')
    ap.add_argument('--jobname', help='latexmk job name, i.e. the PDF name in build/ (default: stem of --main)')
    ap.add_argument('--engine', choices=['auto', *project.ENGINES], default='auto',
                    help='TeX engine (default auto: "%% !TEX program" in the main file, else the project '
                         'latexmkrc, else pdflatex)')
    ap.add_argument('--shell-escape', action='store_true',
                    help='let the document run external programs (needed by some packages, e.g. svg); only for '
                         'projects you trust')
    ap.add_argument('--timeout', type=int, default=600, help='stop a compile after this many seconds (default 600)')
    ap.add_argument('--host', default='127.0.0.1', help='bind address (default: 127.0.0.1, local only)')
    ap.add_argument('--port', type=int, help=f'port (default: the first free one from {DEFAULT_PORT})')
    ap.add_argument('--open', action='store_true', help='open the editor in the default browser')
    ap.add_argument('--no-initial-compile', action='store_true')
    ap.add_argument('--webdav', metavar='URL',
                    help='first get the project from this WebDAV folder (or send it there), and keep the two connected; '
                         '--root is created if needed')
    ap.add_argument('--webdav-user', metavar='NAME', default='',
                    help='user name for --webdav; the password is asked for, unless it is in ~/.netrc')
    ap.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    a = ap.parse_args(argv)
    if a.webdav:
        try:
            print(webdav.clone(a.root.resolve(), a.webdav, a.webdav_user, getpass.getpass), flush=True)
        except (webdav.DavError, OSError) as e:
            raise SystemExit(f'WebDAV: {e}')
    try:
        configure(a.root, a.main, a.jobname, a.host, a.engine, a.shell_escape, a.timeout)
    except ValueError as e:
        raise SystemExit(str(e))
    missing = [t for t in ('latexmk', 'synctex') if shutil.which(t) is None]
    if missing:
        print(f'warning: {" and ".join(missing)} not found on PATH; install a TeX distribution such as TeX Live',
              flush=True)
    if ANY_HOST:
        print('warning: listening on all interfaces with no authentication; anyone who can reach this port can '
              'edit files, push with your git credentials and sync with your WebDAV password', flush=True)
    if SHELL_ESCAPE:
        print('warning: --shell-escape lets this project run programs on your computer when it compiles', flush=True)
    srv = make_server(a.host, a.port)
    port = srv.server_address[1]
    shown = 'localhost' if a.host in WILDCARD_HOSTS else (f'[{a.host}]' if ':' in a.host else a.host)
    url = f'http://{shown}:{port}/'
    if not a.no_initial_compile:
        threading.Thread(target=run_compile, daemon=True).start()
    engine, source = effective_engine()
    print(f'Editing {ROOT / MAIN} -> build/{JOB}.pdf ({engine or "engine from latexmkrc"}, {source})\n'
          f'Open {url}  (Ctrl+C to stop)', flush=True)
    if a.open:
        threading.Timer(0.3, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        proc = proc_state['proc']
        if proc is not None:
            kill_tree(proc)


if __name__ == '__main__':
    main()
