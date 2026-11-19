"""Reading LaTeX, BibTeX and biber logs: errors and warnings with file and line, plus a plain-language hint for the
common ones. Pure functions over log text, so they are easy to test.
"""
import re
from pathlib import Path, PureWindowsPath

# "file:line: message", as written with -file-line-error. The path may start with a Windows drive letter.
ERR = re.compile(r'^((?:[A-Za-z]:)?[^:\n]*?\.[A-Za-z0-9]{1,8}):(\d+): (.*)$')
WARN = re.compile(r'(?:LaTeX|Package [\w-]+|Class [\w-]+) Warning: (.*?)(?: on input line (\d+))?\.?$')
WARN_KEYWORDS = ('undefined', 'Citation', 'Reference', 'multiply', 'could not be found', 'Rerun to get')

# (pattern on the message, hint). {0}, {1} are the pattern's groups; the hint is a str.format() template, so a
# literal brace is written {{ or }}.
HINTS = [
    (r'Undefined control sequence',
     'A command is misspelled, or the package that defines it is not loaded. The unknown command is the last one '
     'shown on the l.N line of the context.'),
    (r'Missing \$ inserted',
     'Something that only works in math mode (such as _, ^ or \\alpha) is outside it, or a math environment is not '
     'closed. Write a literal underscore as \\_.'),
    (r"File `([^']+\.(?:sty|cls))' not found",
     '{0} is not installed. With TeX Live, install it with "tlmgr install <package>"; on Debian or Ubuntu, '
     'install the texlive-* package that contains it.'),
    (r"File `([^']+)' not found",
     'LaTeX cannot find {0}. Paths are relative to the main file\'s folder, use forward slashes and are '
     'case-sensitive.'),
    (r'Runaway argument|Paragraph ended before .* was complete|File ended while scanning',
     'A closing brace }} is missing, often on this line or the one before.'),
    (r"Missing \} inserted|Extra \}, or forgotten|Too many \}'s|Missing \{ inserted",
     'Braces {{ }} (or $ signs) do not pair up near this line.'),
    (r'\\begin\{([^}]*)\} on input line \d+ ended by \\end\{([^}]*)\}',
     '\\begin{{{0}}} is closed by \\end{{{1}}}: an environment is left open or closed in the wrong order.'),
    (r'Missing \\begin\{document\}',
     'Something is typeset before \\begin{{document}}: look for stray text in the preamble.'),
    (r'Misplaced alignment tab character &',
     'An & outside a table or an align environment. Write a literal ampersand as \\&.'),
    (r"There's no line here to end",
     '\\\\ is used where there is no line to end, for example right after a heading or at the start of a '
     'paragraph. Use a blank line or \\vspace instead.'),
    (r'requires either XeTeX or LuaTeX',
     'This document needs XeLaTeX or LuaLaTeX. Put "% !TEX program = xelatex" (or lualatex) on the first line of '
     'the main file, or start the editor with --engine xelatex.'),
    (r'shell.escape|write18',
     'A package (such as minted or svg) runs external programs. Restart the editor with --shell-escape if you '
     'trust this project.'),
    (r'Option clash for package (\S+)',
     'The package {0} is loaded twice with different options. Load it once, or give the options with '
     '\\PassOptionsToPackage before \\documentclass.'),
    (r'Can be used only in preamble', 'This command must come before \\begin{{document}}.'),
    (r'Not in outer par mode', 'A figure, table or \\marginpar is inside a box, a minipage or another float.'),
    (r'Dimension too large', 'A length is far too big: often an image scaled by a huge factor, or a TikZ '
                             'coordinate far off.'),
    (r'Illegal unit of measure', 'A length is missing its unit (such as pt, cm or \\linewidth).'),
    (r'Unknown graphics extension|Cannot determine size of graphic',
     'This engine cannot include that image format. pdflatex takes .pdf, .png and .jpg; convert .eps or .svg '
     'first (or use the svg package with --shell-escape).'),
    (r'Unicode character|Invalid UTF-8|inputenc Error',
     'A character pdflatex cannot typeset, often from pasted text. Replace it, or compile with XeLaTeX or '
     'LuaLaTeX ("% !TEX program = xelatex" on the first line).'),
    (r'Environment (\S+) undefined',
     'The environment {0} is not defined: load the package that provides it (for example amsmath for align) or '
     'check the spelling.'),
    (r'Lonely \\item', '\\item is outside a list: put it inside itemize, enumerate or description.'),
    (r"Something's wrong--perhaps a missing \\item",
     'A list has text before its first \\item, or \\\\ starts a paragraph.'),
    (r'Emergency stop|job aborted',
     'LaTeX stopped early. Fix the first error in the list; the later ones often follow from it.'),
    # warnings
    (r'Citation .* undefined|could not be found',
     'The key is not in any .bib file this document uses, or the bibliography has errors (see the BibTeX/biber '
     'messages).'),
    (r'Reference .* undefined',
     'No \\label with this name, or it is in a part that is not compiled (\\includeonly).'),
    (r'multiply defined', 'Two \\label commands use the same name.'),
    (r'Rerun to get', 'Cross-references did not settle. Recompile; if this keeps happening, delete the build '
                      'folder.'),
    # bibliography tools
    (r"didn't find a database entry", 'This key is cited but is not in any .bib file the document uses.'),
    (r"couldn't open (?:database|style) file (\S+)", 'BibTeX cannot find {0}: check the name in \\bibliography or '
                                                      '\\bibliographystyle.'),
    (r'I was expecting|syntax error|Repeated entry',
     'This .bib entry is malformed: check for a missing comma, an unbalanced brace or a duplicate key.'),
]
_HINTS = [(re.compile(p), h) for p, h in HINTS]


def hint(message):
    for rx, text in _HINTS:
        m = rx.search(message)
        if m:
            return text.format(*m.groups())
    return None


def relpath(name, root):
    """A log's file name as a project-relative POSIX path, or (name, True) when it is outside the project."""
    name = name[2:] if name.startswith('./') else name
    if root is None:
        return name, False
    p = Path(name)
    if PureWindowsPath(name).anchor and not p.is_absolute():   # C:/... read on a non-Windows system
        return name, True
    p = (p if p.is_absolute() else root / p).resolve()
    if p == root or root in p.parents:
        return p.relative_to(root).as_posix(), False
    return name, True


BIBITEM = re.compile(r'\\bibitem\s*(?:\[.*\])?\s*\{([^}]+)\}|\\entry\{([^}]+)\}')


def bbl_key(bbl, line):
    """The citation key of the entry at `line` of a .bbl file (BibTeX \\bibitem or biblatex \\entry)."""
    try:
        lines = bbl.read_text(encoding='utf-8', errors='replace').splitlines()[:line]
    except OSError:
        return None
    for text in reversed(lines):
        m = BIBITEM.search(text)
        if m:
            return m.group(1) or m.group(2)
    return None


def parse_log(text, root=None, find_key=None):
    """Errors and warnings from a LaTeX .log. root: the project directory, to make paths relative. find_key(key):
    where a bibliography key is defined, as (file, line), to point errors inside the .bbl at the .bib entry."""
    errors, warnings = [], []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = ERR.match(line)
        if m:
            name, ln, msg = m.group(1), int(m.group(2)), m.group(3)
            if msg.lstrip().startswith('==> Fatal error occurred'):
                continue   # TeX's summary of the error above
            # Package errors continue on lines that start with "(package)".
            j = i + 1
            while j < len(lines) and re.match(r'\([\w@-]+\)\s', lines[j]):
                msg += ' ' + lines[j].split(')', 1)[1].strip()
                j += 1
            ctx = ' '.join(l.strip() for l in lines[j:j + 2] if l.strip())[:300]
            path, external = relpath(name, root)
            e = {'file': path, 'line': ln, 'message': msg, 'context': ctx, 'hint': hint(msg), 'external': external}
            if path.endswith('.bbl') and root is not None:
                key = bbl_key((root / path) if not external else Path(name), ln)
                where = find_key(key) if key and find_key else None
                e['message'] = f'{msg} (in the bibliography entry {key})' if key else msg
                e['hint'] = e['hint'] or 'The problem is in a bibliography entry: check its fields in the .bib file.'
                if where:
                    e.update(file=where[0], line=where[1], external=False)
            errors.append(e)
            continue
        # Some errors are printed as "! message" even with -file-line-error, notably "! LaTeX Error: File `x.sty'
        # not found." when a package is missing. Without this, only the "Emergency stop" after it would show.
        if line.startswith('! ') and not any(e['message'] == line[2:].strip() for e in errors):
            msg = line[2:].strip()
            at = next((l for l in lines[i + 1:i + 8] if re.match(r'l\.\d+ ', l)), '')
            errors.append({'file': None, 'line': None, 'message': msg, 'context': at.strip()[:300], 'hint': hint(msg),
                           'external': True})
            continue
        m = WARN.search(line)
        if m and any(k in line for k in WARN_KEYWORDS):
            msg = m.group(1)[:200]
            warnings.append({'message': msg, 'line': int(m.group(2)) if m.group(2) else None, 'hint': hint(msg)})
    seen, uniq = set(), []
    for w in warnings:
        if w['message'] not in seen:
            seen.add(w['message'])
            uniq.append(w)
    return errors, uniq


def parse_blg(text):
    """Errors, warnings and database (.bib) names from a BibTeX or biber .blg log."""
    errors, warnings, databases = [], [], []
    lines = text.splitlines()

    def add(kind, tool, msg, file=None, line=None, context=''):
        item = {'file': file, 'line': line, 'message': f'{tool}: {msg.strip()}', 'context': context,
                'hint': hint(msg), 'external': False}
        (errors if kind == 'error' else warnings).append(item)

    for i, line in enumerate(lines):
        # BibTeX
        m = re.match(r'Database file #\d+: (.+)$', line)
        if m:
            databases.append(m.group(1).strip())
            continue
        m = re.search(r'---line (\d+) of file (.+)$', line)
        if m:
            msg = line[:m.start()].strip() or (lines[i - 1].strip() if i else '')
            ctx = ' '.join(l.strip(' :') for l in lines[i + 1:i + 3] if l.strip(' :'))
            add('error', 'BibTeX', msg, m.group(2).strip(), int(m.group(1)), ctx)
            continue
        m = re.match(r'Warning--(.*)$', line)
        if m:
            n = re.match(r'--line (\d+) of file (.+)$', lines[i + 1]) if i + 1 < len(lines) else None
            add('warning', 'BibTeX', m.group(1), n.group(2).strip() if n else None, int(n.group(1)) if n else None)
            continue
        if re.match(r"I couldn't open (?:database|style|auxiliary) file", line) or line.startswith('I found no '):
            add('error', 'BibTeX', line)
            continue
        # biber
        m = re.search(r"Found BibTeX data source '(.+?)'|Looking for bibtex (?:format )?file '(.+?)'", line)
        if m:
            databases.append(m.group(1) or m.group(2))
            continue
        m = re.search(r'\b(ERROR|WARN) - (.*)$', line)
        if m:
            msg = m.group(2)
            f = re.search(r'([^/\\\s]+\.bib)(?:_\d+\.utf8)?, line (\d+)', msg)
            add('error' if m.group(1) == 'ERROR' else 'warning', 'Biber', msg,
                f.group(1) if f else None, int(f.group(2)) if f else None)
    return errors, warnings, list(dict.fromkeys(databases))
