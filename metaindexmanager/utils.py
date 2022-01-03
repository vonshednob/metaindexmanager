import os
import curses
import stat
import logging
import shutil
import pathlib
import subprocess

import multidict

import metaindex.shared
import metaindex.ocr
import metaindex.indexer

from cursedspace import colors

from .shared import PROGRAMNAME


class MetaindexmanagerLogger:
    def __init__(self):
        self.logger = None
        self.formatter = logging.Formatter('[%(levelname)s] %(message)s')
        self.handler = None

    def setup(self, level=logging.WARNING, filename=None):
        if filename is None:
            self.handler = logging.NullHandler()
        else:
            self.handler = logging.FileHandler(filename, encoding='utf-8')

        self.logger = logging.getLogger(PROGRAMNAME)
        self.logger.propagate = False
        self.logger.setLevel(level)
        self.logger.addHandler(self.handler)
        self.handler.setFormatter(self.formatter)

    def __getattr__(self, name):
        if hasattr(self.logger, name):
            return getattr(self.logger, name)
        raise AttributeError(name)

    def fatal(self, *args, **kwargs):
        return self.logger.fatal(*args, **kwargs)

    def error(self, *args, **kwargs):
        return self.logger.error(*args, **kwargs)

    def warning(self, *args, **kwargs):
        return self.logger.warning(*args, **kwargs)

    def info(self, *args, **kwargs):
        return self.logger.info(*args, **kwargs)

    def debug(self, *args, **kwargs):
        return self.logger.debug(*args, **kwargs)


logger = MetaindexmanagerLogger()

LS_COLORS_FALLBACK = "no=0:di=1:ex=0;31"
LS_COLORS = {}
LS_ICONS_FALLBACK = ':'.join([
    "di=", "fi=", "ln=", "so=", "ex=",
    # documents
    "*.doc=", "*.docx=", "*.odt=", "*.gdoc=", "*.rtf=",
    "*.pdf=", "*.ps=", "*.djvu=",
    # books
    "*.epub=", "*.mobi=", "*.azw=", "*.azw3=", "*.ebook=",
    # plain text like
    "*.txt=", "*.eml=", "*.markdown=", "*.md=", "*.mkd=",
    "*.conf=", "*.cnf=", "*.cfg=", "*.ini=", "*.vim=",
    "*.json=", "*.yaml=", "*.yml=",
    # source code
    "*.c=", "*.h=", "*.cpp=", "*.cxx=", "*.hpp=", "*.hxx=", "*.cs=",
    "*.css=", "*.html=", "*.htm=", "*.xhtml=",
    "*.py=", "*.pyc=", "*.pyb=",
    "*.js=",
    "*.diff=", "*.patch=",
    # shell/script files
    "*.sh=", "*.bash=", "*.fish=", "*.zsh=", "*.ksh=",
    "*.awk=", "*.bat=", "*.cmd=", "*.ps1=",
    # archives,  or 
    "*.zip=", "*.rar=", "*.gz=", "*.xz=", "*.bz2=", "*.ace=",
    "*.bz=", "*.tar=", "*.lz=", "*.lzh=", "*.lzo=", "*.lzma=",
    "*.tgz=", "*.tbz=", "*.taz=", "*.tbz2=", "*.tz=", "*.tzo=",
    "*.deb=", "*.rpm=",
    # executables / binaries
    "*.apk=",
    "*.dll=", "*.exe=", "*.msi=",
    "*.so=",
    "*.db=", "*.sql=", "*.sqlite3=",
    "*.iso=",
    # spreadsheet
    "*.xls=", "*.ods=", "*.csv=", "*.gsheet=", "*.tsv=", "*.xlsx=",
    # presentation
    "*.ppt=", "*.pptx=", "*.gslides=", "*.odp=",
    # images  or 
    "*.jpg=", "*.jpeg=", "*.jpe=", "*.png=", "*.mng=", "*.bmp=",
    "*.tif=", "*.tiff=", "*.gif=", "*.ico=", "*.image=",
    "*.jif=", "*.jfif=", "*.jfi=", "*.svg=",
    "*.avif=", "*.webp=",
    "*.ai=", "*.psd=",
    # audio  or 
    "*.mp3=", "*.ogg=", "*.wav=", "*.aac=", "*.flac=", "*.m4a=",
    # video ,  or 
    "*.avi=", "*.mpg=", "*.mp4=", "*.ogv=", "*.webm=",
    # xml-like
    "*.xml=",
    "*.rss=",
    "*.gpx=",
    # PIM
    "*.vcf=", "*.ics=", # "*.fb=",
    # Fonts
    "*.ttf=", "*.otf=", "*.eot=", "*.font=", "*.woff=", "*.woff2=",
    # Apple stuff
    "*.ds_store=", "*.localized=",
    # temp, etc
    "*.lock=",
])
LS_ICONS = {}
DEFAULT_XDG_DIR_ICONS = [
    ('templates', ""),
    ('desktop', ""),
    ('download', ""),
    ('publicshare', ""),
    ('documents', ""),
    ('music', ""),
    ('pictures', ""),
    ('videos', ""),
]
XDG_DIR_NAMES = [name for name, _ in DEFAULT_XDG_DIR_ICONS]
USERDIR_ICONS_FALLBACK = ':'.join([f"{name}={icon}" for name, icon in DEFAULT_XDG_DIR_ICONS])
USERDIR_ICONS = {}
TERM_COLOR_MAP = {
    '31': curses.COLOR_RED,
    '32': curses.COLOR_GREEN,
    '33': curses.COLOR_YELLOW,
    '34': curses.COLOR_BLUE,
    '35': curses.COLOR_MAGENTA,
    '36': curses.COLOR_CYAN,
    '37': curses.COLOR_WHITE,
    '40': curses.COLOR_BLACK,
    '41': curses.COLOR_RED,
    '42': curses.COLOR_GREEN,
    '43': curses.COLOR_YELLOW,
    '44': curses.COLOR_BLUE,
    '45': curses.COLOR_MAGENTA,
    '46': curses.COLOR_CYAN,
    '47': -1,
}


def parse_key_sequence(text):
    sequence = []

    pos = 0
    while pos < len(text):
        token = text[pos]
        if token == '<':
            other = text.find('>', pos)
            if other < 0:
                return None
            sequence.append(text[pos:other+1])
            pos = other
        elif token == '^' and pos < len(text)-1:
            pos += 1
            if text[pos] == '^':
                sequence.append('^')
            else:
                sequence.append('^' + text[pos])
        else:
            sequence.append(token)

        pos += 1

    return tuple(sequence)


def parse_ls_colors():
    global LS_COLORS
    LS_COLORS = {}

    for pair in os.getenv('LS_COLORS', LS_COLORS_FALLBACK).split(':'):
        if '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        value = value.split(';')

        attr = curses.A_NORMAL
        fg = None
        bg = None

        if len(value) == 0:
            continue
        if len(value) > 0:
            if value[0] == '0':
                pass
            if value[0] == '1':
                attr = curses.A_BOLD
        if len(value) > 1:
            fg = TERM_COLOR_MAP.get(value[1], None)
        if len(value) > 2:
            bg = TERM_COLOR_MAP.get(value[2], -1)

        LS_COLORS[key] = (attr, fg, bg)


def parse_ls_icons():
    global LS_ICONS
    LS_ICONS = {}

    global USERDIR_ICONS
    USERDIR_ICONS = {}

    # get the user defined mapping of dir [type] -> icon from $USERDIR_ICONS
    dirname_icons = []
    xdguserdir = shutil.which('xdg-user-dir')
    home = pathlib.Path().home()
    for pair in os.getenv('USERDIR_ICONS', USERDIR_ICONS_FALLBACK).split(':'):
        if '=' not in pair:
            continue

        key, icon = pair.split('=', 1)
        if len(icon) != 1:
            continue
        path = None
        if key.lower() in XDG_DIR_NAMES and xdguserdir is not None:
            result = subprocess.run([xdguserdir, key.upper()], capture_output=True)
            if result is None:
                xdguserdir = None
            else:
                path = pathlib.Path(str(result.stdout, 'utf-8').strip())
                if path == home:
                    path = None

        if path is None:
            path = pathlib.Path(key).expanduser()
        USERDIR_ICONS[path] = icon

    for pair in os.getenv('LS_ICONS', LS_ICONS_FALLBACK).split(':'):
        if '=' not in pair:
            continue

        key, icon = pair.split('=', 1)
        if len(icon) != 1:
            continue

        LS_ICONS[key] = icon


def get_ls_colors(path, stats=None):
    """Get the term attributes and colors for node at path

    Returns a tuple (attribute, foreground color, background color) based on LS_COLORS

    Foreground and background color may be None if not specified, otherwise some color from cursedspace.colors.
    The attribute will be at the very least curses.A_NORMAL.

    You should call parse_ls_colors prior to calling this to see any results.
    """
    tests = []

    # LS_COLORS:
    # di: directory
    # ex: executable
    # fi: regular file
    # pi: named pipe
    # so: socket
    # bd: block device
    # cd: character device
    # ln: symlink
    # or: symlink without target
    if path.is_dir():
        tests += ['di']
    if path.is_symlink():
        tests += ['ln']
    if path.is_socket():
        tests += ['so']
    if path.is_block_device():
        tests += ['bd']
    if path.is_char_device():
        tests += ['cd']
    if path.is_fifo():
        tests += ['pi']
    if path.is_file():
        if stats is None:
            try:
                stats = path.stat()
            except:
                stats = None
        if hasattr(stats, "st_mode") and (stats.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)) != 0:
            tests += ['ex']
        else:
            tests += ['fi']
        if len(path.suffix) > 0:
            tests = ['*' + path.suffix] + tests
    tests.append('no')
    
    attr = curses.A_NORMAL
    fg = None
    bg = None
    for test in reversed(tests):
        if test not in LS_COLORS:
            continue
        attr, ifg, ibg = LS_COLORS[test]
        fg = fg if ifg is None else ifg
        bg = bg if ibg is None else ibg
    return (attr, fg, bg)


def get_ls_icon(path, stats=None):
    """Get the NerdFont/FontAwesome unicode icon for the node at path

    Returns the icon or a " " (space) character based on LS_ICONS.

    You should call parse_ls_icons prior to calling this to see any results.
    """
    global LS_ICONS

    if path.is_dir() and path in USERDIR_ICONS:
        return USERDIR_ICONS[path]

    tests = ['no']
    if path.is_symlink():
        tests += ['ln']
    if path.is_dir():
        tests += ['di']
    if path.is_file():
        if stats is None:
            try:
                stats = path.stat()
            except:
                stats = None
        if hasattr(stats, "st_mode") and (stats.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)) != 0:
            tests += ['ex']
        else:
            tests += ['fi']
        if len(path.suffix) > 0:
            tests += ['*' + path.suffix.lower()]

    for test in reversed(tests):
        if test not in LS_ICONS:
            continue
        return LS_ICONS[test]
    return " "


def collection_meta_as_writable(data, basepath):
    """Change the 'data', as read from stores.get_for_collection(), to be usable for stores.store

    basepath is the parent path of the metadata file.
    """
    # turn the collection_extra again into the editable plain form,
    # i.e. restore '*', '**', and filename entries
    for key in set(data.keys()):
        if key == basepath:
            nkey = '*'
            if data[key].popall(metaindex.shared.IS_RECURSIVE) == [True]:
                nkey = '**'
            data[nkey] = data.pop(key)
            key = nkey
        else:
            nkey = key.name
            if isinstance(data, multidict.MultiDict):
                specifics = data.popall(key, [])
                if len(specifics) > 1:
                    merged = multidict.MultiDict()
                    for specific in specifics:
                        merged.extend(specific)
                    specifics = merged
            else:
                assert isinstance(data, dict)
                specifics = data.pop(key)

            data[nkey] = specifics
            key = nkey
        data[key].popall(metaindex.shared.IS_RECURSIVE, [])
    return data


def first_line(text):
    """Return only the first line of a potential multi-line text"""
    return text.split("\n")[0].split("\r")[0]


def do_ocr(path, **kwargs):
    ocr = metaindex.ocr.TesseractOCR(True, **kwargs)
    results = metaindex.indexer.index_files([path], 1, ocr, True)

    if len(results) == 0:
        return False, None

    _, success, extra = results[0]
    fulltext = extra.get('ocr.fulltext', '')
    return success and len(fulltext) > 0, fulltext

