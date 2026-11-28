"""Tests for the editor's server side. Standard library only:

    python3 -m unittest discover -s tests -v

Tests that need git, latexmk, synctex, xelatex, biber or texcount are skipped when the tool is not on PATH.
"""
import base64
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from offline_tex_editor import gitapi, latexlog, project, server  # noqa: E402

HAVE = {t: shutil.which(t) is not None for t in ('git', 'latexmk', 'synctex', 'xelatex', 'biber', 'texcount')}
HAVE_TEX = HAVE['latexmk'] and HAVE['synctex']


def write(root, files):
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode())


# ---------- pure functions ----------

class ParseLog(unittest.TestCase):
    def test_errors_and_warnings(self):
        log = '\n'.join([
            './sections/intro.tex:12: Undefined control sequence.',
            'l.12 \\foo',
            '          bar',
            "LaTeX Warning: Citation `knuth' on page 1 undefined on input line 7.",
            "LaTeX Warning: Citation `knuth' on page 1 undefined on input line 7.",
            'LaTeX Font Warning: Font shape not available.',
        ])
        errors, warnings = latexlog.parse_log(log)
        self.assertEqual(len(errors), 1)
        e = errors[0]
        self.assertEqual((e['file'], e['line'], e['message'], e['context']),
                         ('sections/intro.tex', 12, 'Undefined control sequence.', 'l.12 \\foo bar'))
        self.assertIn('misspelled', e['hint'])
        self.assertEqual([(w['message'], w['line']) for w in warnings], [("Citation `knuth' on page 1 undefined", 7)])
        self.assertIn('.bib', warnings[0]['hint'])

    def test_paths_outside_the_project_and_windows_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = (Path(d) / 'project').resolve()
            outside = (Path(d).resolve() / 'texmf' / 'x.sty').as_posix()   # absolute on every platform
            log = f'{root.as_posix()}/a.tex:3: Missing $ inserted.\n{outside}:9: Oops\n' \
                  'C:/texlive/2024/texmf-dist/tex/latex/y/y.sty:4: Something\n'
            errors, _ = latexlog.parse_log(log, root)
            self.assertEqual([(e['file'], e['external']) for e in errors],
                             [('a.tex', False), (outside, True), ('C:/texlive/2024/texmf-dist/tex/latex/y/y.sty', True)])

    def test_lua_error_and_its_stack_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            log = '\n'.join([
                "...share/texlive/texmf-dist/tex/latex/fontspec/fontspec.lua:49: attempt to index a nil value "
                "(global 'luaotfload')",
                'stack traceback:',
                "\t...share/texlive/texmf-dist/tex/latex/fontspec/fontspec.lua:49: in field 'check_ot_script'",
                '\t[\\directlua]:1: in main chunk.',
                '\\lua_now:e #1->\\__lua_now:n {#1}',
                '',
                'l.24 \\babelprovide',
            ])
            errors, _ = latexlog.parse_log(log, Path(d).resolve())
            # one error, not one per traceback line, and the shortened path is not taken for a project file
            self.assertEqual([(e['file'], e['line'], e['external']) for e in errors],
                             [('...share/texlive/texmf-dist/tex/latex/fontspec/fontspec.lua', 49, True)])

    def test_missing_package_printed_with_an_exclamation_mark(self):
        log = '\n'.join([
            "! LaTeX Error: File `etoolbox.sty' not found.",
            '',
            'Type X to quit or <RETURN> to proceed,',
            'or enter new name. (Default extension: sty)',
            '',
            'Enter file name: ',
            '/usr/share/texlive/texmf-dist/tex/latex/hyperref/hyperref.sty:117: Emergency stop.',
            '<read *> ',
        ])
        errors, _ = latexlog.parse_log(log)
        self.assertEqual([e['message'] for e in errors],
                         ["LaTeX Error: File `etoolbox.sty' not found.", 'Emergency stop.'])
        self.assertIn('etoolbox.sty is not installed', errors[0]['hint'])
        self.assertIsNone(errors[0]['file'])
        # an error already reported in file:line form is not repeated
        errors, _ = latexlog.parse_log('./a.tex:3: Undefined control sequence.\n! Undefined control sequence.\n')
        self.assertEqual(len(errors), 1)

    def test_engine_error_without_a_space_after_the_exclamation_mark(self):
        # pdfTeX's own fatal errors, often the only error in the log of a compile that produced no PDF
        log = '\n'.join([
            '(/usr/share/texlive/texmf-dist/tex/latex/latexconfig/epstopdf-sys.cfg))',
            '!pdfTeX error: pdflatex (file ./one.pdf): PDF inclusion: required page does not exist <5>',
            ' ==> Fatal error occurred, no output PDF file produced!',
            '!pdfTeX error: pdflatex (file t1-zi4r-0): Font t1-zi4r-0 at 600 not found',
        ])
        errors, _ = latexlog.parse_log(log)
        self.assertEqual([e['message'] for e in errors],
                         ['pdfTeX error: pdflatex (file ./one.pdf): PDF inclusion: required page does not exist <5>',
                          'pdfTeX error: pdflatex (file t1-zi4r-0): Font t1-zi4r-0 at 600 not found'])
        self.assertEqual(latexlog.parse_log('!Not an error line\n')[0], [])

    def test_hints(self):
        cases = {
            "! LaTeX Error: File `tikz-cd.sty' not found.": 'tikz-cd.sty is not installed',
            'Package fontspec Error: The fontspec package requires either XeTeX or LuaTeX.': 'xelatex',
            'Package minted Error: You must invoke LaTeX with the -shell-escape flag.': '--shell-escape',
            '\\begin{itemize} on input line 3 ended by \\end{enumerate}.': '\\begin{itemize} is closed by',
            'Misplaced alignment tab character &.': '\\&',
            'Paragraph ended before \\textbf was complete.': 'A closing brace } is missing',
            'Missing } inserted.': 'Braces { } (or $ signs)',
            'LaTeX Error: Missing \\begin{document}.': 'before \\begin{document}',
            'LaTeX Error: Can be used only in preamble.': 'before \\begin{document}',
            'Some message nobody has seen before': None,
        }
        for msg, want in cases.items():
            with self.subTest(msg=msg):
                got = latexlog.hint(msg)
                if want is None:
                    self.assertIsNone(got)
                else:
                    self.assertIn(want, got)

    def test_every_hint_formats(self):
        # hints are str.format() templates: a literal brace must be doubled, or hint() raises
        for pattern, text in latexlog.HINTS:
            with self.subTest(pattern=pattern):
                text.format(*['x'] * re.compile(pattern).groups)

    def test_error_in_bbl_points_at_the_bib_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            write(root, {'build/main.bbl': '\\begin{thebibliography}{1}\n\n\\bibitem{good}\nA.\n\n'
                                           '\\bibitem{bad}\nB \\oops.\n\\end{thebibliography}\n'})
            log = './build/main.bbl:7: Undefined control sequence.\nl.7 B \\oops\n'
            errors, _ = latexlog.parse_log(log, root, lambda key: {'bad': ('refs.bib', 12)}.get(key))
            self.assertEqual((errors[0]['file'], errors[0]['line']), ('refs.bib', 12))
            self.assertIn('bad', errors[0]['message'])


class ParseBlg(unittest.TestCase):
    def test_bibtex(self):
        blg = '\n'.join([
            'Database file #1: refs.bib',
            "I was expecting a `,' or a `}'---line 5 of file refs.bib",
            ' :   title = {Broken',
            " :                   ",
            "I'm skipping whatever remains of this entry",
            'Warning--I didn\'t find a database entry for "nokey"',
            'Warning--empty journal in knuth1984',
            '--line 9 of file refs.bib',
            '(There was 1 error message)',
        ])
        errors, warnings, dbs = latexlog.parse_blg(blg)
        self.assertEqual(dbs, ['refs.bib'])
        self.assertEqual([(e['file'], e['line']) for e in errors], [('refs.bib', 5)])
        self.assertIn("expecting a `,'", errors[0]['message'])
        self.assertEqual([(w['file'], w['line']) for w in warnings], [(None, None), ('refs.bib', 9)])
        self.assertIn('not in any .bib', warnings[0]['hint'])

    def test_bibtex_missing_style_is_listed_once(self):
        blg = '\n'.join([
            'The top-level auxiliary file: sn-article.aux',
            "I couldn't open style file sn-mathphys-num.bst",
            '---line 2 of file sn-article.aux',
            ' : \\bibstyle{sn-mathphys-num',
            ' :                          }',
            "I'm skipping whatever remains of this command",
            'I found no style file---while reading file sn-article.aux',
        ])
        errors, _, _ = latexlog.parse_blg(blg)
        self.assertEqual([(e['message'], e['file']) for e in errors],
                         [("BibTeX: I couldn't open style file sn-mathphys-num.bst", None),
                          ('BibTeX: I found no style file---while reading file sn-article.aux', None)])
        self.assertEqual(errors[0]['context'], '\\bibstyle{sn-mathphys-num }')
        self.assertIn('sn-mathphys-num.bst', errors[0]['hint'])

    def test_biber(self):
        blg = '\n'.join([
            "[52] Biber.pm:418> INFO - Looking for bibtex file 'refs.bib' for section 0",
            "[60] bibtex.pm:1688> INFO - LaTeX decoding ...",
            "[61] Biber.pm:1311> INFO - Found BibTeX data source 'refs.bib'",
            '[70] Utils.pm:411> ERROR - BibTeX subsystem: /tmp/biber_tmp_x/refs.bib_123.utf8, line 4, syntax error',
            "[80] Biber.pm:131> WARN - I didn't find a database entry for 'nokey' (section 0)",
        ])
        errors, warnings, dbs = latexlog.parse_blg(blg)
        self.assertEqual(dbs, ['refs.bib'])
        self.assertEqual([(e['file'], e['line']) for e in errors], [('refs.bib', 4)])
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0]['message'].startswith('Biber: '))


class Structure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_magic_comments_and_engine(self):
        text = '% !TEX program = XeLaTeX\n% !TeX root = ../thesis.tex\n\\documentclass{article}\n'
        self.assertEqual(project.magic_comments(text), {'program': 'XeLaTeX', 'root': '../thesis.tex'})
        self.assertEqual(project.engine_from_magic(text), 'xelatex')
        self.assertEqual(project.engine_from_magic('% !TEX TS-program = lualatexmk\n'), 'lualatex')
        self.assertIsNone(project.engine_from_magic('% !TEX program = context\n'))

    def test_root_documents(self):
        self.assertEqual(project.doc_class('% \\documentclass{book}\n\\documentclass[11pt]{article}'), 'article')
        self.assertFalse(project.is_root('\\documentclass[../main.tex]{subfiles}'))
        write(self.root, {'notes.tex': '\\documentclass{article}', 'paper.tex': '\\documentclass{article}',
                          'fig.tex': '\\documentclass{standalone}', 'ch/one.tex': '\\documentclass[../paper]{subfiles}',
                          'deep/x.tex': '\\documentclass{article}', 'macros.tex': '\\newcommand\\R{}'})
        self.assertEqual(project.find_roots(self.root, project.list_files(self.root)[0]),
                         ['paper.tex', 'notes.tex', 'fig.tex', 'deep/x.tex'])
        self.assertEqual(project.resolve_main(self.root), 'paper.tex')

    def test_resolve_main_follows_tex_root(self):
        write(self.root, {'main.tex': '% !TEX root = book/thesis.tex\n',
                          'book/thesis.tex': '\\documentclass{book}', 'book/ch1.tex': '% !TEX root = thesis.tex\n'})
        self.assertEqual(project.resolve_main(self.root), 'book/thesis.tex')
        self.assertEqual(project.resolve_main(self.root, 'book/ch1.tex'), 'book/thesis.tex')
        with self.assertRaises(ValueError):
            project.resolve_main(self.root, 'missing.tex')
        write(self.root, {'esc.tex': '% !TEX root = ../../etc/x.tex\n'})
        with self.assertRaises(ValueError):
            project.resolve_main(self.root, 'esc.tex')

    def test_outline_follows_inputs(self):
        write(self.root, {
            'main.tex': '\\documentclass{book}\n\\begin{document}\n\\chapter{Intro}\\label{ch:intro}\n'
                        '% \\section{Commented out}\n\\input{parts/a}\n\\include{parts/b}\n'
                        '\\subfile{parts/c.tex}\n\\import{parts/}{d}\n\\end{document}\n\\section{After the end}\n',
            'parts/a.tex': '\\section[Short]{A {\\em nested} title}\n',
            'parts/b.tex': '\\section*{B}\n\\subsection{B.1}\n',
            'parts/c.tex': '\\documentclass[../main]{subfiles}\n\\begin{document}\n\\section{C}\n\\end{document}\n',
            'parts/d.tex': '\\paragraph{D}\n',
        })
        entries, includes = project.outline(self.root, 'main.tex')
        self.assertEqual([(e['level'], e['title'], e['file'], e['line']) for e in entries], [
            (1, 'Intro', 'main.tex', 3), (2, 'A {\\em nested} title', 'parts/a.tex', 1), (2, 'B', 'parts/b.tex', 1),
            (3, 'B.1', 'parts/b.tex', 2), (2, 'C', 'parts/c.tex', 3), (5, 'D', 'parts/d.tex', 1)])
        self.assertEqual(includes, ['parts/b'])

    def test_labels_bib_and_commands(self):
        write(self.root, {
            'main.tex': '\\section{Results}\\label{sec:res}\n\\begin{equation}\n\\label{eq:1}\n% \\label{gone}\n',
            'refs.bib': '@string{acm = "ACM"}\n@Article{knuth84,\n  author = {Donald E. Knuth},\n'
                        '  title = {Literate {P}rogramming},\n  year = 1984,\n}\n'
                        '@book{lamport, title = "LaTeX", author = "Leslie Lamport", year = {1994}}\n',
            'macros.sty': '\\newcommand{\\R}{\\mathbb{R}}\n\\newcommand*\\norm[1]{\\lVert#1\\rVert}\n'
                          '\\DeclareMathOperator{\\argmax}{arg\\,max}\n\\newenvironment{proofsketch}{}{}\n',
        })
        files = project.list_files(self.root)[0]
        self.assertEqual([(l['key'], l['line'], l['context']) for l in project.labels(self.root, files)],
                         [('sec:res', 1, '\\section{Results}'), ('eq:1', 3, '\\begin{equation}')])
        bib = project.bib_entries(self.root, files)
        self.assertEqual([(b['key'], b['type'], b['title'], b['author'], b['year'], b['line']) for b in bib], [
            ('knuth84', 'article', 'Literate Programming', 'Donald E. Knuth', '1984', 2),
            ('lamport', 'book', 'LaTeX', 'Leslie Lamport', '1994', 7)])
        cmds = {c['name']: c['args'] for c in project.commands(self.root, files)}
        self.assertEqual(cmds, {'R': 0, 'norm': 1, 'argmax': 0, 'proofsketch': 0})

    def test_commands_from_xparse_robust_and_theorems(self):
        write(self.root, {'defs.tex': '\\NewDocumentCommand{\\pair}{m m}{(#1, #2)}\n'
                                      '\\NewDocumentCommand\\abs{s O{\\big{m}} m}{|#3|}\n'
                                      '\\ProvideDocumentCommand{\\later}{}{}\n'
                                      '\\DeclareRobustCommand{\\robust}[2]{#1#2}\n'
                                      '\\NewDocumentEnvironment{boxed}{m}{}{}\n'
                                      '\\newtheorem{thm}{Theorem}\n\\newtheorem{conj}[thm]{Conjecture}\n'
                                      '\\newtheorem*{remark*}{Remark}\n\\newtheoremstyle{note}{}{}{}{}{}{}{}{}\n'
                                      '\\declaretheorem[style=definition]{defn}\n'})
        found = {(c['name'], c['env']): c['args'] for c in project.commands(self.root, ['defs.tex'])}
        self.assertEqual(found, {('pair', False): 2, ('abs', False): 1, ('later', False): 0, ('robust', False): 2,
                                 ('boxed', True): 0, ('thm', True): 0, ('conj', True): 0, ('remark*', True): 0,
                                 ('defn', True): 0})

    def test_mandatory_args_skip_what_other_argument_types_take(self):
        # the m after t is the token t looks for, not an argument
        self.assertEqual(project.mandatory_args('t m m'), 1)
        cases = {'m': 1, '+m': 1, 's o m m': 2, '!o m': 1, 't+ m': 1, 't\\foo m': 1, 'tm': 0,
                 'r() m': 1, 'rmm m': 1, 'R(){m} m': 1, 'd<> m': 1, 'dmm m': 1, 'D<>{m} m': 1,
                 'O{m} m': 1, 'O{\\big{m}} m': 1, 'e{_^} m': 1, 'E{_^}{{m}{m}} m': 1,
                 '>{\\SplitList{m}} m': 1, 'v m': 1, '': 0}
        for spec, n in cases.items():
            with self.subTest(spec=spec):
                self.assertEqual(project.mandatory_args(spec), n)
        write(self.root, {'defs.tex': '\\NewDocumentCommand{\\example}{t m m}{#2}\n'})
        self.assertEqual([c['args'] for c in project.commands(self.root, ['defs.tex'])], [1])

    def test_search_and_replace_keep_encoding_and_line_endings(self):
        write(self.root, {'a.tex': b'alpha beta\r\nAlphabet\r\n', 'b.tex': 'caf\xe9 alpha\n'.encode('latin-1')})
        files = ['a.tex', 'b.tex']
        found, _ = project.search(self.root, files, project.compile_query('alpha'))
        self.assertEqual([(m['path'], m['line'], m['col']) for m in found], [('a.tex', 1, 0), ('a.tex', 2, 0),
                                                                             ('b.tex', 1, 5)])
        found, _ = project.search(self.root, files, project.compile_query('alpha', word=True, case=True))
        self.assertEqual([(m['path'], m['line']) for m in found], [('a.tex', 1), ('b.tex', 1)])
        counts = project.replace(self.root, files, project.compile_query(r'(\w+) beta', regex=True), '$1 gamma',
                                 regex=True)
        self.assertEqual(counts, {'a.tex': 1})
        self.assertEqual((self.root / 'a.tex').read_bytes(), b'alpha gamma\r\nAlphabet\r\n')
        counts = project.replace(self.root, files, project.compile_query('alpha', word=True), 'omega')
        self.assertEqual(counts, {'a.tex': 1, 'b.tex': 1})   # whole word: "Alphabet" is left alone
        self.assertEqual((self.root / 'a.tex').read_bytes(), b'omega gamma\r\nAlphabet\r\n')
        self.assertEqual((self.root / 'b.tex').read_bytes(), 'caf\xe9 omega\n'.encode('latin-1'))
        with self.assertRaises(UnicodeEncodeError):   # nothing is written when one file cannot take the text
            project.replace(self.root, files, project.compile_query('omega'), '\u03c9')
        self.assertEqual((self.root / 'a.tex').read_bytes(), b'omega gamma\r\nAlphabet\r\n')

    def test_replacement_rules(self):
        m = re.search(r'(\w+) (?P<last>\w+)', 'Donald Knuth')
        cases = {r'\textbf{$1}': r'\textbf{Donald}',      # backslashes are literal (no \t tab, as with re.sub)
                 '$2, $1': 'Knuth, Donald', '[$&]': '[Donald Knuth]', '$<last>': 'Knuth', '$$1': '$1',
                 '$10': 'Donald0', '$3': '$3', '$<nope>': '$<nope>', 'no groups': 'no groups'}
        for template, want in cases.items():
            with self.subTest(template=template):
                self.assertEqual(project.expand_replacement(template, m), want)

    def test_read_source(self):
        write(self.root, {'u.tex': 'é\n'.encode(), 'l.tex': 'é\r\n'.encode('latin-1')})
        self.assertEqual(project.read_source(self.root / 'u.tex'), ('é\n', 'utf-8', '\n'))
        self.assertEqual(project.read_source(self.root / 'l.tex'), ('é\r\n', 'latin-1', '\r\n'))


class Diffs(unittest.TestCase):
    def test_word_diff(self):
        segs = server.word_diff('the quick brown fox\n', 'the slow brown fox\n')
        self.assertEqual(segs, [['eq', 'the '], ['del', 'quick'], ['add', 'slow'], ['eq', ' brown fox\n']])

    def test_rewrite_is_shown_whole(self):
        self.assertEqual(server.word_diff('alpha', 'omega, beta'), [['del', 'alpha'], ['add', 'omega, beta']])

    def test_file_hunks(self):
        a = ''.join(f'line {i}\n' for i in range(20))
        b = a.replace('line 10\n', 'line ten\n')
        hunks = server.file_hunks(a, b)
        self.assertEqual(len(hunks), 1)
        self.assertEqual(hunks[0]['line'], 9)  # two lines of context before line 11
        self.assertIn(['add', 'ten'], hunks[0]['segs'])


class GitParsing(unittest.TestCase):
    def test_parse_status(self):
        raw = '## main...origin/main [ahead 2, behind 1]\0M  a.tex\0 M b.tex\0R  new.tex\0old.tex\0?? c.tex\0UU d.tex\0'
        branch, files = gitapi.parse_status(raw)
        self.assertEqual(gitapi.parse_branch(branch),
                         {'branch': 'main', 'upstream': 'origin/main', 'ahead': 2, 'behind': 1})
        by_path = {f['path']: f for f in files}
        self.assertTrue(by_path['a.tex']['staged'] and not by_path['a.tex']['unstaged'])
        self.assertTrue(by_path['b.tex']['unstaged'] and not by_path['b.tex']['staged'])
        self.assertEqual(by_path['new.tex']['orig'], 'old.tex')
        self.assertTrue(by_path['c.tex']['untracked'])
        d = by_path['d.tex']
        self.assertTrue(d['conflict'] and not d['staged'] and not d['unstaged'])

    def test_credential_errors_say_what_to_do(self):
        msg = gitapi.explain("fatal: could not read Username for 'https://github.com': terminal prompts disabled")
        self.assertIn('gh auth login', msg)
        self.assertEqual(gitapi.explain('fatal: something else'), 'fatal: something else')

    def test_parse_branch_without_commits(self):
        self.assertEqual(gitapi.parse_branch('No commits yet on main')['branch'], 'main')


class Commands(unittest.TestCase):
    def test_latexmk_command(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, {'main.tex': '\\documentclass{article}'})
            server.configure(d, 'main.tex')
            self.assertEqual(server.latexmk_cmd('pdflatex'), [
                'latexmk', '-pdf', '-cd', '-f', '-interaction=nonstopmode', '-file-line-error', '-synctex=1',
                '-outdir=build', '-jobname=main', 'main.tex'])
            server.settings.update(draft=True, only='chapters/one')
            cmd = server.latexmk_cmd(None, force=True)
            self.assertEqual(cmd[:2], ['latexmk', '-g'])
            self.assertNotIn('-pdf', cmd)   # the project's latexmkrc picks the engine
            self.assertIn('-usepretex=\\PassOptionsToPackage{draft}{graphicx}\\includeonly{chapters/one}', cmd)
            self.assertIn('-xelatex', server.latexmk_cmd('xelatex'))
        with tempfile.TemporaryDirectory() as d:   # TeX runs in the main file's folder; the PDF still goes to build/
            write(d, {'paper/tex/main.tex': '\\documentclass{article}'})
            server.configure(d, 'paper/tex/main.tex')
            cmd = server.latexmk_cmd('pdflatex')
            self.assertIn('-outdir=../../build', cmd)
            self.assertEqual(cmd[-1], 'paper/tex/main.tex')

    def test_effective_engine(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, {'main.tex': '\\documentclass{article}'})
            server.configure(d, 'main.tex')
            self.assertEqual(server.effective_engine(), ('pdflatex', 'default'))
            write(d, {'.latexmkrc': '# $pdf_mode = 1;\n'})
            self.assertEqual(server.effective_engine(), ('pdflatex', 'default'))   # commented out
            write(d, {'.latexmkrc': '$pdf_mode = 5;\n'})
            self.assertEqual(server.effective_engine(), (None, 'latexmkrc'))
            write(d, {'main.tex': '% !TEX program = lualatex\n\\documentclass{article}'})
            self.assertEqual(server.effective_engine(), ('lualatex', '% !TEX program'))
            server.configure(d, 'main.tex', engine='xelatex')
            self.assertEqual(server.effective_engine(), ('xelatex', '--engine'))


# ---------- the HTTP server ----------

class ServerCase(unittest.TestCase):
    """Runs the real HTTP server on a free port against a copy of example/ (or `files`, if set)."""
    files = None
    main = 'main.tex'
    options = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'project'
        if self.files is None:
            shutil.copytree(REPO / 'example', self.root)
        else:
            write(self.root, self.files)
        server.configure(self.root, self.main, **self.options)
        self.srv = server.make_server('127.0.0.1', 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=120)
        hdrs = dict(headers or {})
        if body is not None and not isinstance(body, (bytes, str)):
            body = json.dumps(body)
            hdrs.setdefault('Content-Type', 'application/json')
        conn.request(method, path, body=body, headers=hdrs)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        try:
            data = json.loads(data)
        except ValueError:
            pass
        return r.status, data, r

    def get(self, path, **kw):
        return self.request('GET', path, **kw)

    def post(self, path, body=None, **kw):
        return self.request('POST', path, body={} if body is None else body, **kw)

    def compile(self):
        code, r, _ = self.post('/api/compile')
        self.assertEqual(code, 200, r)
        return r


class FileApi(ServerCase):
    def test_list_files(self):
        write(self.root, {'figures/plot.png': b'\x89PNG', '.latexmkrc': '$pdf_mode = 1;\n'})
        code, data, _ = self.get('/api/files')
        self.assertEqual(code, 200)
        self.assertEqual(data['main'], 'main.tex')
        self.assertEqual(sorted(data['files']), ['.latexmkrc', 'main.tex', 'refs.bib', 'sections/introduction.tex'])
        self.assertEqual(data['assets'], ['figures/plot.png'])

    def test_read_save_and_conflict(self):
        code, f, _ = self.get('/api/file?path=main.tex')
        self.assertEqual(code, 200)
        self.assertEqual((f['encoding'], f['eol']), ('utf-8', '\n'))
        code, saved, _ = self.post('/api/file', {'path': 'main.tex', 'content': 'v2', 'mtime': f['mtime']})
        self.assertEqual(code, 200)
        self.assertEqual((self.root / 'main.tex').read_text(), 'v2')
        # Saving again with the stale mtime means someone else's edit would be lost: refused unless forced.
        code, _, _ = self.post('/api/file', {'path': 'main.tex', 'content': 'v3', 'mtime': f['mtime'] - 10})
        self.assertEqual(code, 409)
        code, _, _ = self.post('/api/file', {'path': 'main.tex', 'content': 'v3', 'mtime': f['mtime'] - 10,
                                             'force': True})
        self.assertEqual(code, 200)
        self.assertEqual((self.root / 'main.tex').read_text(), 'v3')

    def test_line_endings_and_encoding_survive_a_save(self):
        write(self.root, {'win.tex': b'a\r\nb\r\n', 'old.tex': 'caf\xe9\n'.encode('latin-1')})
        f = self.get('/api/file?path=win.tex')[1]
        self.assertEqual((f['content'], f['eol']), ('a\r\nb\r\n', '\r\n'))
        self.post('/api/file', {'path': 'win.tex', 'content': 'a\r\nc\r\n'})
        self.assertEqual((self.root / 'win.tex').read_bytes(), b'a\r\nc\r\n')
        f = self.get('/api/file?path=old.tex')[1]
        self.assertEqual((f['content'], f['encoding']), ('caf\xe9\n', 'latin-1'))
        self.assertEqual(self.post('/api/file', {'path': 'old.tex', 'content': 'th\xe9', 'encoding': 'latin-1'})[0],
                         200)
        self.assertEqual((self.root / 'old.tex').read_bytes(), 'th\xe9'.encode('latin-1'))
        code, err, _ = self.post('/api/file', {'path': 'old.tex', 'content': '\u03c9', 'encoding': 'latin-1'})
        self.assertEqual(code, 400)
        self.assertIn('latin-1', err['error'])

    def test_paths_are_confined(self):
        (self.root / '.git').mkdir()
        (self.root / '.git' / 'notes.txt').write_text('x')
        (self.root / 'secret.key').write_text('x')
        for path in ('../outside.tex', '/etc/passwd', 'secret.key', '.git/notes.txt'):
            with self.subTest(path=path):
                self.assertEqual(self.get(f'/api/file?path={path}')[0], 403)
                self.assertEqual(self.post('/api/file', {'path': path, 'content': 'x'})[0], 403)
        self.assertFalse((self.root.parent / 'outside.tex').exists())

    def test_static_files(self):
        self.assertEqual(self.get('/vendor/codemirror/codemirror.min.js')[0], 200)
        code, _, r = self.get('/vendor/pdfjs/pdf.min.mjs')
        self.assertEqual((code, r.getheader('Content-Type')), (200, 'text/javascript'))
        self.assertEqual(self.get('/static/app.js')[0], 200)
        for path in ('/server.py', '/offline_tex_editor/server.py', '/.git/config', '/vendor/../server.py',
                     '/static/../server.py'):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    def test_raw_assets_are_sandboxed(self):
        write(self.root, {'fig/a.svg': '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'})
        code, _, r = self.get('/api/raw?path=fig/a.svg')
        self.assertEqual((code, r.getheader('Content-Type')), (200, 'image/svg+xml'))
        self.assertIn('sandbox', r.getheader('Content-Security-Policy'))
        self.assertEqual(self.get('/api/raw?path=main.tex')[0], 403)
        self.assertEqual(self.get('/api/raw?path=../x.png')[0], 403)


class FileOperations(ServerCase):
    def test_new_rename_delete(self):
        self.assertEqual(self.post('/api/fs/new', {'path': 'chapters/one.tex'})[0], 200)
        self.assertTrue((self.root / 'chapters' / 'one.tex').is_file())
        self.assertEqual(self.post('/api/fs/new', {'path': 'figures', 'kind': 'folder'})[0], 200)
        self.assertEqual(self.post('/api/fs/new', {'path': 'chapters/one.tex'})[0], 400)        # exists
        self.assertEqual(self.post('/api/fs/new', {'path': 'run.exe'})[0], 400)                 # not editable
        for bad in ('../x.tex', 'build/x.tex', '.git/x.tex', ''):
            with self.subTest(path=bad):
                self.assertEqual(self.post('/api/fs/new', {'path': bad})[0], 403)
        code, r, _ = self.post('/api/fs/rename', {'from': 'chapters', 'to': 'parts'})
        self.assertEqual(code, 200, r)
        self.assertTrue((self.root / 'parts' / 'one.tex').is_file())
        self.assertEqual(self.post('/api/fs/rename', {'from': 'parts', 'to': 'parts/inner'})[0], 400)
        code, r, _ = self.post('/api/fs/delete', {'path': 'parts/one.tex'})
        self.assertEqual(code, 200, r)
        self.assertFalse((self.root / 'parts' / 'one.tex').exists())
        self.assertTrue((self.root / r['trash']).is_file())     # recoverable
        self.assertEqual(self.get('/api/files')[1]['files'].count('parts/one.tex'), 0)

    def test_main_document_is_protected_and_followed(self):
        self.assertEqual(self.post('/api/fs/delete', {'path': 'main.tex'})[0], 400)
        code, r, _ = self.post('/api/fs/rename', {'from': 'main.tex', 'to': 'paper.tex'})
        self.assertEqual((code, r['main']), (200, 'paper.tex'))
        self.assertEqual(self.get('/api/settings')[1]['main'], 'paper.tex')

    def test_upload(self):
        data = base64.b64encode(b'\x89PNG\r\n\x1a\n...').decode()
        self.assertEqual(self.post('/api/fs/upload', {'path': 'figures/p.png', 'data': data})[0], 200)
        self.assertEqual((self.root / 'figures' / 'p.png').read_bytes(), b'\x89PNG\r\n\x1a\n...')
        code, r, _ = self.post('/api/fs/upload', {'path': 'figures/p.png', 'data': data})
        self.assertEqual((code, r.get('exists')), (409, True))
        self.assertEqual(self.post('/api/fs/upload', {'path': 'figures/p.png', 'data': data, 'replace': True})[0], 200)
        self.assertEqual(self.post('/api/fs/upload', {'path': 'evil.html', 'data': data})[0], 400)
        self.assertEqual(self.post('/api/fs/upload', {'path': 'x.png', 'data': '!!notbase64'})[0], 400)


class ExportZip(ServerCase):
    """Downloading the project's sources as a .zip (/api/export), on a copy of example/ (main.tex, refs.bib)."""

    def export(self):
        code, data, r = self.get('/api/export')
        self.assertEqual((code, r.getheader('Content-Type')), (200, 'application/zip'), data)
        note = r.getheader('X-Export-Note')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return {n: z.read(n) for n in z.namelist()}, note and urllib.parse.unquote(note)

    def age(self, rel, seconds):
        t = time.time() - seconds
        os.utime(self.root / rel, (t, t))

    def test_files_without_build_hidden_files_and_outside_links(self):
        write(self.root, {'figures/p.png': b'\x89PNG', '.latexmkrc': '$pdf_mode = 1;\n', '.env': 'KEY=1\n',
                          '.vscode/settings.json': '{}', 'build/main.bbl': '\\begin{thebibliography}{1}\n',
                          'build/main.aux': '', 'build/main.pdf': b'%PDF'})
        outside = Path(self.tmp.name) / 'secret.txt'
        outside.write_text('not part of the project')
        try:
            (self.root / 'link.txt').symlink_to(outside)
        except OSError:  # Windows without the right to make links
            pass
        files, note = self.export()
        # no build/, no hidden files but .latexmkrc, nothing from outside; the .bbl next to the main document
        self.assertEqual(sorted(files), ['.latexmkrc', 'figures/p.png', 'main.bbl', 'main.tex', 'refs.bib',
                                         'sections/introduction.tex'])
        self.assertEqual(files['main.bbl'], b'\\begin{thebibliography}{1}\n')
        self.assertEqual(files['figures/p.png'], b'\x89PNG')
        self.assertIsNone(note)

    def test_nested_main_document_and_custom_job_name(self):
        write(self.root, {'paper/main.tex': '\\documentclass{article}\n', 'build/thesis.bbl': 'thesis bbl',
                          'build/main.bbl': 'an older job'})
        server.configure(self.root, 'paper/main.tex', jobname='thesis')
        files, _ = self.export()
        # LaTeX looks for the .bbl next to the main document, under its name, whatever the job was called
        self.assertEqual(files['paper/main.bbl'], b'thesis bbl')
        self.assertNotIn('main.bbl', files)

    def test_a_bbl_of_the_project_is_kept(self):
        write(self.root, {'main.bbl': 'written by hand', 'build/main.bbl': 'from the compile', 'build/main.aux': ''})
        files, note = self.export()
        self.assertEqual(files['main.bbl'], b'written by hand')
        self.assertIsNone(note)

    def test_missing_build_output(self):
        files, note = self.export()
        self.assertNotIn('main.bbl', files)
        self.assertIn('No bibliography from a compile yet', note)
        (self.root / 'refs.bib').unlink()   # no bibliography at all: nothing to say
        self.assertIsNone(self.export()[1])

    def test_stale_build_output(self):
        write(self.root, {'build/main.bbl': 'old', 'build/main.aux': ''})
        for rel, seconds in (('main.tex', 1200), ('refs.bib', 1200), ('sections/introduction.tex', 1200),
                             ('build/main.bbl', 600), ('build/main.aux', 600)):
            self.age(rel, seconds)
        self.assertIsNone(self.export()[1])   # compiled after the last save
        self.age('sections/introduction.tex', 0)
        files, note = self.export()   # a source saved after the last compile
        self.assertEqual(files['main.bbl'], b'old')
        self.assertIn('may be out of date', note)
        self.age('sections/introduction.tex', 1200)
        self.age('refs.bib', 300)   # a .bib newer than the .bbl, even if LaTeX ran since
        self.age('build/main.aux', 0)
        self.assertIn('may be out of date', self.export()[1])

    def test_unicode_file_names(self):
        write(self.root, {'figures/ä b.png': b'png', 'kapitel/Über.tex': 'Ü'})
        code, data, _ = self.get('/api/export')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(z.read('figures/ä b.png'), b'png')
            self.assertEqual(z.read('kapitel/Über.tex'), 'Ü'.encode())
            self.assertTrue(z.getinfo('kapitel/Über.tex').flag_bits & 0x800)   # names marked as UTF-8


class SearchApi(ServerCase):
    def test_search_and_replace(self):
        code, r, _ = self.get('/api/search?q=EDITOR&case=0')
        self.assertEqual(code, 200)
        self.assertEqual({m['path'] for m in r['matches']}, {'main.tex', 'sections/introduction.tex'})
        self.assertEqual(self.get('/api/search?q=EDITOR&case=1')[1]['matches'], [])
        self.assertEqual(self.get('/api/search?q=(&regex=1')[0], 400)
        code, r, _ = self.post('/api/replace', {'q': r'Section~\\ref\{(\w+):', 'regex': True,
                                                'replacement': r'\Cref{$1:'})
        self.assertEqual((code, r['replaced']), (200, 1), r)
        self.assertIn(r'\Cref{sec:intro}', (self.root / 'main.tex').read_text())   # backslash kept as typed
        self.assertEqual(self.post('/api/replace', {'q': '(x', 'regex': True, 'replacement': 'y'})[0], 400)


class Structure_(ServerCase):
    def test_outline_labels_settings(self):
        r = self.get('/api/outline')[1]
        self.assertEqual([e['title'] for e in r['entries']], ['Introduction', 'Some mathematics'])
        r = self.get('/api/labels')[1]
        self.assertEqual({l['key'] for l in r['labels']}, {'sec:intro', 'sec:math', 'eq:gauss'})
        self.assertEqual([b['key'] for b in r['bib']], ['knuth1984'])
        s = self.get('/api/settings')[1]
        self.assertEqual((s['main'], s['engine'], s['roots']), ('main.tex', 'pdflatex', ['main.tex']))

    def test_switch_main_document(self):
        write(self.root, {'slides.tex': '\\documentclass{beamer}\n'})
        self.assertEqual(self.post('/api/settings', {'main': 'sections/introduction.tex'})[0], 400)
        code, s, _ = self.post('/api/settings', {'main': 'slides.tex'})
        self.assertEqual((code, s['main'], s['job']), (200, 'slides.tex', 'slides'))
        self.assertEqual(self.post('/api/settings', {'only': 'nope'})[0], 400)
        self.assertEqual(self.post('/api/settings', {'draft': True})[1]['draft'], True)

    def test_incomplete_pdf_is_not_served(self):
        write(self.root, {'build/main.pdf': b'%PDF-1.5\n1 0 obj\n'})
        s = self.get('/api/status')[1]
        self.assertFalse(s['pdf_complete'])
        self.assertEqual(self.get('/pdf')[0], 409)
        write(self.root, {'build/main.pdf': b'%PDF-1.5\n1 0 obj\ntrailer\n%%EOF\n'})
        self.assertTrue(self.get('/api/status')[1]['pdf_complete'])
        self.assertEqual(self.get('/pdf')[0], 200)


class RequestChecks(ServerCase):
    """The server has no login, so it must refuse requests another web site could make on the user's behalf."""

    def test_page_headers(self):
        code, _, r = self.get('/')
        self.assertEqual(code, 200)
        self.assertEqual(r.getheader('X-Frame-Options'), 'DENY')
        csp = r.getheader('Content-Security-Policy')
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("script-src 'self';", csp)   # no inline or eval'd script

    def test_loopback_host_names_are_accepted(self):
        for host in (f'127.0.0.1:{self.port}', f'localhost:{self.port}', f'[::1]:{self.port}'):
            with self.subTest(host=host):
                self.assertEqual(self.get('/api/files', headers={'Host': host})[0], 200)

    def test_dns_rebinding_is_refused(self):
        code, data, _ = self.get('/api/file?path=main.tex', headers={'Host': f'attacker.example:{self.port}'})
        self.assertEqual(code, 403)
        self.assertNotIn('content', data)

    def test_cross_origin_post_is_refused(self):
        code, _, _ = self.post('/api/file', {'path': 'pwned.sh', 'content': 'x'},
                               headers={'Origin': 'https://attacker.example'})
        self.assertEqual(code, 403)
        self.assertFalse((self.root / 'pwned.sh').exists())

    def test_same_origin_post_is_accepted(self):
        code, _, _ = self.post('/api/file', {'path': 'notes.md', 'content': 'x'},
                               headers={'Origin': f'http://127.0.0.1:{self.port}'})
        self.assertEqual(code, 200)

    def test_non_json_post_is_refused(self):
        # A cross-site page can send text/plain without a CORS preflight (and some browsers omit Origin).
        for ctype in ('text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data; boundary=x'):
            with self.subTest(ctype=ctype):
                code, _, _ = self.request('POST', '/api/file', body='{"path": "pwned.sh", "content": "x"}',
                                          headers={'Content-Type': ctype})
                self.assertEqual(code, 403)
        self.assertFalse((self.root / 'pwned.sh').exists())

    def test_wildcard_bind_accepts_any_host(self):
        server.configure(self.root, 'main.tex', host='0.0.0.0')
        self.assertEqual(self.get('/api/files', headers={'Host': f'my-laptop.lan:{self.port}'})[0], 200)


class Ports(unittest.TestCase):
    def test_next_free_port_is_used(self):
        a = server.make_server('127.0.0.1', None)
        try:
            b = server.make_server('127.0.0.1', None)
            try:
                self.assertNotEqual(a.server_address[1], b.server_address[1])
            finally:
                b.server_close()
            with self.assertRaises(SystemExit):
                server.make_server('127.0.0.1', a.server_address[1])
        finally:
            a.server_close()


@unittest.skipUnless(HAVE['git'], 'git not installed')
class GitApi(ServerCase):
    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.root, check=True, capture_output=True,
                              text=True).stdout

    def identity(self, cwd):
        for k, v in (('user.name', 'Test'), ('user.email', 'test@example.invalid'), ('commit.gpgsign', 'false')):
            self.git('config', k, v, cwd=cwd)

    def test_not_a_repository(self):
        code, data, _ = self.get('/api/git/status')
        self.assertEqual(code, 200)
        if data['repo']:
            self.skipTest('the temporary directory is inside a git repository')
        self.assertEqual(self.get('/api/git/log')[0], 400)

    def test_stage_commit_log(self):
        self.git('init', '-q', '-b', 'main')
        self.identity(self.root)
        code, st, _ = self.get('/api/git/status')
        self.assertEqual(code, 200)
        self.assertTrue(st['repo'])
        self.assertTrue(all(f['untracked'] for f in st['files']))
        code, st, _ = self.post('/api/git/stage', {'paths': [f['path'] for f in st['files']]})
        self.assertTrue(all(f['staged'] for f in st['files']))
        code, out, _ = self.post('/api/git/commit', {'message': 'first'})
        self.assertEqual(code, 200, out)
        self.assertEqual(out['files'], [])
        self.assertEqual(self.get('/api/git/log')[1]['commits'][0]['subject'], 'first')
        self.assertEqual(self.post('/api/git/commit', {'message': 'empty'})[0], 400)  # nothing staged
        self.assertEqual(self.get('/api/git/show?rev=HEAD~1;rm')[0], 400)  # revisions are alphanumeric only
        self.assertEqual(self.post('/api/git/stage', {'paths': ['../x']})[0], 403)
        (self.root / 'notes.md').write_text('saved a moment ago')   # "Stage all" stages it whatever the panel showed
        self.assertEqual([f['path'] for f in self.post('/api/git/stage', {'all': True})[1]['files'] if f['staged']],
                         ['notes.md'])

    def remote_and_clone(self):
        """A bare remote (standing in for GitHub) with one commit; self.root is a clone of it, and `seed` another."""
        base = self.root.parent
        remote = base / 'remote.git'
        self.git('init', '-q', '--bare', '-b', 'main', str(remote), cwd=base)
        seed = base / 'seed'
        shutil.copytree(self.root, seed)
        self.git('init', '-q', '-b', 'main', cwd=seed)
        self.identity(seed)
        self.git('add', '-A', cwd=seed)
        self.git('commit', '-qm', 'base', cwd=seed)
        self.git('remote', 'add', 'origin', str(remote), cwd=seed)
        self.git('push', '-q', '-u', 'origin', 'main', cwd=seed)
        shutil.rmtree(self.root)
        self.git('clone', '-q', str(remote), str(self.root), cwd=base)
        self.identity(self.root)
        return seed, remote

    def commit_line(self, repo, rel, text, message):
        p = repo / rel
        p.write_text(p.read_text() + f'\n% {text}\n')
        self.git('commit', '-qam', message, cwd=repo)

    def diverge(self):
        """Two clones that change the same line: self.root is one, `seed` pushed first."""
        seed, _ = self.remote_and_clone()
        for repo, word in ((seed, 'theirs'), (self.root, 'mine')):
            p = repo / 'main.tex'
            p.write_text(p.read_text().replace('Your Name', word))
            self.git('commit', '-qam', word, cwd=repo)
        self.git('push', '-q', cwd=seed)
        self.git('fetch', '-q')

    def test_sync_pulls_then_pushes(self):
        seed, remote = self.remote_and_clone()
        self.commit_line(seed, 'refs.bib', 'theirs', 'theirs')
        self.git('push', '-q', cwd=seed)
        code, r, _ = self.post('/api/git/sync')                     # behind: pulls
        self.assertEqual((code, r['ahead'], r['behind']), (200, 0, 0), r)
        self.assertIn('% theirs', (self.root / 'refs.bib').read_text())
        self.commit_line(self.root, 'main.tex', 'mine', 'mine')
        code, r, _ = self.post('/api/git/sync')                     # ahead: pushes
        self.assertEqual((code, r['ahead'], r['behind']), (200, 0, 0), r)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'main', cwd=remote))
        self.assertEqual(self.post('/api/git/sync')[1]['output'], 'Already in sync.')

    def test_sync_diverged_then_rebase(self):
        seed, remote = self.remote_and_clone()
        self.commit_line(seed, 'refs.bib', 'theirs', 'theirs')
        self.git('push', '-q', cwd=seed)
        self.commit_line(self.root, 'main.tex', 'mine', 'mine')
        code, r, _ = self.post('/api/git/sync')
        self.assertEqual((code, r.get('diverged')), (200, True), r)   # asks how to combine them
        code, r, _ = self.post('/api/git/sync', {'mode': 'rebase'})
        self.assertEqual((code, r['state'], r['ahead'], r['behind']), (200, None, 0, 0), r)
        self.assertEqual([c['subject'] for c in self.get('/api/git/log')[1]['commits']][:3], ['mine', 'theirs', 'base'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'main', cwd=remote))

    def test_first_sync_creates_the_remote_branch(self):
        self.git('init', '-q', '-b', 'main')
        self.identity(self.root)
        code, r, _ = self.post('/api/git/sync')
        self.assertEqual(code, 400)
        self.assertIn('no remote', r['error'])
        remote = self.root.parent / 'empty.git'
        self.git('init', '-q', '--bare', str(remote), cwd=self.root.parent)
        self.git('remote', 'add', 'origin', str(remote))
        code, r, _ = self.post('/api/git/sync')
        self.assertEqual(code, 400)
        self.assertIn('first commit', r['error'])
        self.git('add', '-A')
        self.git('commit', '-qm', 'first')
        code, r, _ = self.post('/api/git/sync')
        self.assertEqual((code, r.get('pushed'), r['upstream']), (200, True, 'origin/main'), r)

    def test_connect_remote(self):
        self.git('init', '-q', '-b', 'main')
        for bad in ('ext::sh -c touch% /tmp/pwned', '--upload-pack=touch /tmp/pwned', 'file:///tmp/x', '/tmp/x', ''):
            with self.subTest(url=bad):
                self.assertEqual(self.post('/api/git/remote', {'url': bad})[0], 400)
        code, st, _ = self.post('/api/git/remote', {'url': 'https://github.com/someone/paper.git'})
        self.assertEqual((code, st['remotes']), (200, ['origin']))
        self.post('/api/git/remote', {'url': 'git@github.com:someone/paper.git'})   # changing the address
        self.assertEqual(self.git('remote', 'get-url', 'origin').strip(), 'git@github.com:someone/paper.git')

    def test_start_repository(self):
        if self.get('/api/git/status')[1]['repo']:
            self.skipTest('the temporary directory is inside a git repository')
        code, st, _ = self.post('/api/git/init')
        self.assertEqual((code, st['repo'], st['branch']), (200, True, 'main'))
        self.assertTrue(all(f['untracked'] for f in st['files']))
        self.assertEqual(self.post('/api/git/init')[0], 400)

    def test_diverged_pull_rebase_with_conflict(self):
        self.diverge()
        code, r, _ = self.post('/api/git/pull', {'mode': 'ff'})
        self.assertEqual((code, r.get('diverged')), (200, True), r)
        code, r, _ = self.post('/api/git/pull', {'mode': 'rebase'})
        self.assertEqual((code, r.get('conflict'), r['state']), (200, True, 'rebasing'), r)
        self.assertEqual([f['path'] for f in r['files'] if f['conflict']], ['main.tex'])
        self.assertEqual(self.post('/api/git/continue')[0], 400)             # still conflicted
        text = (self.root / 'main.tex').read_text()
        self.assertIn('<<<<<<<', text)
        (self.root / 'main.tex').write_text(text.split('<<<<<<<')[0] + '\\author{both}\n' +
                                            text.split('>>>>>>>')[1].split('\n', 1)[1])
        self.post('/api/git/stage', {'paths': ['main.tex']})
        code, r, _ = self.post('/api/git/continue')
        self.assertEqual((code, r['state']), (200, None), r)
        self.assertEqual([c['subject'] for c in self.get('/api/git/log')[1]['commits']][:3], ['mine', 'theirs', 'base'])

    def test_diverged_pull_merge_then_abort(self):
        self.diverge()
        code, r, _ = self.post('/api/git/pull', {'mode': 'merge'})
        self.assertEqual((code, r.get('conflict'), r['state']), (200, True, 'merging'), r)
        code, r, _ = self.post('/api/git/abort')
        self.assertEqual((code, r['state']), (200, None), r)
        self.assertIn('mine', (self.root / 'main.tex').read_text())
        self.assertEqual(self.post('/api/git/abort')[0], 400)                # nothing to abort


@unittest.skipUnless(HAVE_TEX, 'latexmk/synctex not installed')
class Compile(ServerCase):
    def test_compile_synctex_and_changes(self):
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        self.assertEqual((r['errors'], r['engine']), ([], 'pdflatex'))
        self.assertTrue((self.root / 'build' / 'main.pdf').exists())
        self.assertEqual(self.get('/pdf')[2].getheader('Content-Type'), 'application/pdf')

        code, loc, _ = self.get('/api/synctex/view?path=sections/introduction.tex&line=3')
        self.assertEqual(code, 200, loc)
        self.assertEqual(loc['page'], 1)
        code, src, _ = self.get(f"/api/synctex/edit?page=1&x={loc['x']}&y={loc['y']}")
        self.assertEqual(code, 200, src)
        self.assertEqual(src['path'], 'sections/introduction.tex')
        # when a line has no record, the nearest line that has one is used
        real, calls = server.synctex, []

        def sparse(args):
            calls.append(args[2])
            return real(args) if len(calls) > 2 else ''
        server.synctex = sparse
        try:
            code, loc, _ = self.get('/api/synctex/view?path=sections/introduction.tex&line=3')
        finally:
            server.synctex = real
        self.assertEqual((code, loc['line']), (200, 2), loc)   # tried 3, then 4, then 2

        self.assertFalse(self.get('/api/changes')[1]['baseline'])  # only one compile so far
        intro = self.root / 'sections' / 'introduction.tex'
        intro.write_text(intro.read_text().replace('small project', 'tiny project'))
        self.assertTrue(self.compile()['success'])
        ch = self.get('/api/changes')[1]
        self.assertTrue(ch['baseline'])
        self.assertEqual([f['path'] for f in ch['files']], ['sections/introduction.tex'])

    def test_errors_are_reported_with_file_line_and_hint(self):
        intro = self.root / 'sections' / 'introduction.tex'
        intro.write_text(intro.read_text() + '\n\\undefinedcommand\n')
        r = self.compile()
        self.assertFalse(r['success'])
        e = r['errors'][0]
        self.assertEqual(e['file'], 'sections/introduction.tex')
        self.assertIn('Undefined control sequence', e['message'])
        self.assertTrue(e['hint'])

    def test_unbalanced_brace_is_reported(self):
        intro = self.root / 'sections' / 'introduction.tex'
        intro.write_text(intro.read_text() + '\n\\textbf{never closed\n\nNext paragraph.\n')
        r = self.compile()                   # used to answer 400: the hint's braces broke str.format()
        self.assertFalse(r['success'])
        self.assertIn('closing brace', r['errors'][0]['hint'])

    def test_bibliography_errors(self):
        bib = self.root / 'refs.bib'
        bib.write_text(bib.read_text() + '\n@article{broken,\n  title = {No closing brace,\n  year = 2020\n')
        r = self.compile()
        bib_errors = [e for e in r['errors'] if e['message'].startswith('BibTeX')]
        self.assertTrue(bib_errors, r['errors'])
        self.assertEqual(bib_errors[0]['file'], 'refs.bib')

    def test_error_in_a_bib_entry_points_at_the_bib_file(self):
        bib = self.root / 'refs.bib'
        bib.write_text(bib.read_text().replace('Addison-Wesley', 'Addison \\nosuchmacro Wesley'))
        e = [e for e in self.compile()['errors'] if 'nosuchmacro' in e['context'] or 'knuth1984' in e['message']]
        self.assertTrue(e)
        self.assertEqual((e[0]['file'], e[0]['line']), ('refs.bib', 1))

    def test_draft_mode_compiles(self):
        self.post('/api/settings', {'draft': True})
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        self.assertIn('PassOptionsToPackage{draft}{graphicx}', r['log_tail'])

    @unittest.skipUnless(HAVE['xelatex'], 'xelatex not installed')
    def test_engine_from_magic_comment_and_latexmkrc(self):
        main = self.root / 'main.tex'
        main.write_text(main.read_text().replace('\\usepackage{amsmath}', '\\usepackage{amsmath}\n\\usepackage{fontspec}'))
        r = self.compile()                   # pdflatex cannot load fontspec: the hint says what to do
        self.assertFalse(r['success'])
        self.assertTrue(any('xelatex' in (e['hint'] or '') for e in r['errors']), r['errors'])
        main.write_text('% !TEX program = xelatex\n' + main.read_text())
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        self.assertEqual((r['engine'], r['engine_source']), ('xelatex', '% !TEX program'))
        main.write_text(main.read_text().split('\n', 1)[1])
        (self.root / '.latexmkrc').write_text('$pdf_mode = 5;\n')
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        self.assertEqual(r['engine_source'], 'latexmkrc')
        self.assertIn("Running 'xelatex", r['log_tail'])

    @unittest.skipUnless(HAVE['texcount'], 'texcount not installed')
    def test_word_count(self):
        code, r, _ = self.get('/api/wordcount')
        self.assertEqual(code, 200, r)
        self.assertGreater(r['text'], 40)
        self.assertEqual(r['math_display'], 1)


@unittest.skipUnless(HAVE_TEX, 'latexmk/synctex not installed')
class MainInSubfolder(ServerCase):
    """A project whose main file is not at the top, such as a repository with the paper in paper/: LaTeX finds
    the files next to the main file, as it does when compiled by hand in that folder."""
    main = 'paper/main.tex'
    files = {
        'README.md': 'The paper is in paper/.\n',
        'paper/main.tex': '\\documentclass{article}\n\\usepackage{paperdefs}\n\\begin{document}\n'
                          '\\input{sections/intro}\n\\include{chapters/one}\n'
                          '\\bibliographystyle{plain}\n\\bibliography{refs}\n\\end{document}\n',
        'paper/paperdefs.sty': '\\newcommand{\\projectname}{Subfolder}\n',
        'paper/sections/intro.tex': '\\section{Introduction}\nThis is \\projectname, after~\\cite{knuth1984}.\n',
        'paper/chapters/one.tex': '\\section{One}\nA chapter.\n',
        'paper/refs.bib': '@book{knuth1984, author = {Donald E. Knuth}, title = {The {\\TeX}book},\n'
                          '  publisher = {Addison-Wesley}, year = 1984}\n',
    }

    def test_compile_outline_and_synctex(self):
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        self.assertEqual((r['errors'], r['warnings']), ([], []))
        self.assertTrue((self.root / 'build' / 'main.pdf').exists())
        self.assertFalse((self.root / 'paper' / 'build').exists())
        outline = self.get('/api/outline')[1]['entries']
        self.assertEqual([e['file'] for e in outline], ['paper/sections/intro.tex', 'paper/chapters/one.tex'])

        code, loc, _ = self.get('/api/synctex/view?path=paper/sections/intro.tex&line=2')
        self.assertEqual(code, 200, loc)
        code, src, _ = self.get(f"/api/synctex/edit?page=1&x={loc['x']}&y={loc['y']}")
        self.assertEqual((code, src['path']), (200, 'paper/sections/intro.tex'), src)

        intro = self.root / 'paper' / 'sections' / 'intro.tex'
        intro.write_text(intro.read_text().replace('after', 'following'))
        self.assertTrue(self.compile()['success'])
        self.assertEqual([f['path'] for f in self.get('/api/changes')[1]['files']], ['paper/sections/intro.tex'])

    def test_error_points_at_the_project_file(self):
        intro = self.root / 'paper' / 'sections' / 'intro.tex'
        intro.write_text(intro.read_text() + '\\undefinedcommand\n')
        e = self.compile()['errors'][0]
        self.assertEqual((e['file'], e['line'], e['external']), ('paper/sections/intro.tex', 3, False))

    @unittest.skipUnless(HAVE['texcount'], 'texcount not installed')
    def test_word_count(self):
        code, r, _ = self.get('/api/wordcount')
        self.assertEqual(code, 200, r)
        self.assertGreaterEqual(r['text'], 4)   # was 0: texcount could not find the \\input and \\include files


@unittest.skipUnless(HAVE_TEX, 'latexmk/synctex not installed')
class StopAndTimeout(ServerCase):
    files = {'main.tex': '\\documentclass{article}\n\\begin{document}\nHi.\n\\def\\spin{\\spin}\\spin\n'
                         '\\end{document}\n'}

    def test_stop(self):
        result = {}
        t = threading.Thread(target=lambda: result.update(r=self.compile()))
        t.start()
        for _ in range(100):
            if server.proc_state['proc'] is not None:
                break
            time.sleep(0.05)
        time.sleep(1)
        t0 = time.time()
        self.assertEqual(self.post('/api/compile/stop')[1], {'stopped': True})
        t.join(20)
        self.assertLess(time.time() - t0, 10)
        self.assertTrue(result['r']['stopped'])
        self.assertFalse(result['r']['success'])
        self.assertFalse(self.get('/api/status')[1]['running'])
        self.assertEqual(self.post('/api/compile/stop')[1], {'stopped': False})

    def test_timeout(self):
        server.TIMEOUT = 2
        t0 = time.time()
        r = self.compile()
        self.assertLess(time.time() - t0, 15)
        self.assertIn('timed out', r['log_tail'])
        self.assertFalse(r['success'])


@unittest.skipUnless(HAVE_TEX, 'latexmk/synctex not installed')
class IncludeOnly(ServerCase):
    files = {'main.tex': '\\documentclass{book}\n\\begin{document}\n\\include{chapters/one}\n'
                         '\\include{chapters/two}\n\\end{document}\n',
             'chapters/one.tex': '\\chapter{One}\nFirst.\n', 'chapters/two.tex': '\\chapter{Two}\nSecond.\n'}

    def test_compile_one_chapter(self):
        s = self.get('/api/settings')[1]
        self.assertEqual(s['includes'], ['chapters/one', 'chapters/two'])
        self.assertTrue(self.compile()['success'])
        self.post('/api/settings', {'only': 'chapters/two'})
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        # A compiled chapter rewrites its .aux; an excluded one keeps the old one (its page numbers and labels).
        fls = (self.root / 'build' / 'main.fls').read_text()
        self.assertIn('OUTPUT build/chapters/two.aux', fls)
        self.assertNotIn('OUTPUT build/chapters/one.aux', fls)


@unittest.skipUnless(HAVE_TEX, 'latexmk/synctex not installed')
class SyncTeXPaths(ServerCase):
    files = {'main.tex': '\\documentclass{article}\n\\begin{document}\n\\input{./my chapters/chapter one}\n'
                         '\\end{document}\n',
             'my chapters/chapter one.tex': 'Text in a file whose path has spaces.\n\nAnother paragraph here.\n'}

    def test_spaces_and_dot_slash(self):
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        code, loc, _ = self.get('/api/synctex/view?path=my%20chapters/chapter%20one.tex&line=3')
        self.assertEqual(code, 200, loc)
        code, src, _ = self.get(f"/api/synctex/edit?page=1&x={loc['x']}&y={loc['y']}")
        self.assertEqual((code, src.get('path')), (200, 'my chapters/chapter one.tex'), src)


@unittest.skipUnless(HAVE_TEX and HAVE['biber'], 'latexmk/synctex/biber not installed')
class Biber(ServerCase):
    files = {'main.tex': '\\documentclass{article}\n\\usepackage[backend=biber]{biblatex}\n'
                         '\\addbibresource{refs.bib}\n\\begin{document}\nSee \\cite{knuth}.\n\\printbibliography\n'
                         '\\end{document}\n',
             'refs.bib': '@book{knuth, author = {Donald Knuth}, title = {The TeXbook}, year = 1984}\n'}

    def test_biblatex(self):
        r = self.compile()
        self.assertTrue(r['success'], r['log_tail'])
        self.assertIn('refs.bib', server.compile_inputs())
        (self.root / 'main.tex').write_text((self.root / 'main.tex').read_text().replace('{knuth}', '{nokey}'))
        r = self.compile()
        self.assertTrue(any('nokey' in w['message'] for w in r['warnings']), r['warnings'])


class MissingLatexmk(ServerCase):
    def test_reports_instead_of_hanging(self):
        real = server.subprocess.Popen

        def no_latexmk(cmd, *a, **kw):
            if cmd[0] == 'latexmk':
                raise FileNotFoundError(2, 'No such file or directory', 'latexmk')
            return real(cmd, *a, **kw)

        server.subprocess.Popen = no_latexmk
        try:
            r = self.post('/api/compile')[1]
        finally:
            server.subprocess.Popen = real
        self.assertFalse(r['success'])
        self.assertFalse(r['running'])
        self.assertIn('latexmk not found', r['log_tail'])
        self.assertFalse(self.get('/api/status')[1]['running'])


if __name__ == '__main__':
    unittest.main()
