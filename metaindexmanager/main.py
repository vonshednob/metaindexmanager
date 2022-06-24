import curses
import datetime
import sys
import os
import shlex
import logging
import shutil
import argparse
import subprocess
import pathlib
import traceback
import importlib
import queue
import threading
import configparser
import urllib.request

import metaindex.configuration
import metaindex.logger
from metaindex import stores as _
from metaindex.cache import MemoryCache

import cursedspace
from cursedspace import colors
from cursedspace import Panel
from cursedspace import Key
from cursedspace import InputLine
from cursedspace import ShellContext

import metaindexmanager.commands as _
import metaindexmanager.command as _
from . import layouts
from . import utils
from . import version
from . import shared
from .utils import logger
from .panel import LIST_SCROLL_COMMANDS, find_panel_type
from .command import resolve_command, Command
from .docpanel import DocPanel
from .filepanel import FilePanel
from .detailpanel import DetailPanel as _
from .commandinput import CommandInput, expand_part
from .keyhelppanel import KeyHelpPanel
from .editorpanel import EditorPanel
from .helppanel import HelpPanel
from .clipboard import Clipboard


CONFIGPATH = metaindex.configuration.HOME / ".config" / shared.PROGRAMNAME
DATAPATH = metaindex.configuration.HOME / ".local" / "share" / shared.PROGRAMNAME

try:
    from xdg import BaseDirectory
    DATAPATH = pathlib.Path(BaseDirectory.save_data_path(shared.PROGRAMNAME) or DATAPATH)
    CONFIGPATH = pathlib.Path(BaseDirectory.save_config_path(shared.PROGRAMNAME) or CONFIGPATH)
except ImportError:
    BaseDirectory = None

ADDONSPATH = DATAPATH / "addons"
LOGFILE = DATAPATH / "ui.log"
HISTORYFILE = DATAPATH / "history.txt"
BOOKMARKFILE = DATAPATH / "bookmarks.txt"
CONFIGFILE = CONFIGPATH / "config.rc"

PREF_OPENER = 'opener'
DEFAULT_OPENER = 'xdg-open'
PREF_EXT_EDITOR = 'editor'
PREF_HIST_SIZE = 'history-size'
DEFAULT_HIST_SIZE = '1000'
PREF_INFO_TIMEOUT = 'info-timeout'
DEFAULT_INFO_TIMEOUT = '10s'


class Context:
    def __init__(self, **kwargs):
        self.panel = kwargs.get('panel', None)
        self.application = kwargs.get('application', None)


class YesNoConfirmation(InputLine):
    def __init__(self, callback, default, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callback = callback
        self.default = default.lower()[:1]

    def handle_key(self, key):
        if key == Key.RETURN:
            text = self.text.strip().lower()
            if len(text) == 0:
                text = self.default
            if len(text) > 0 and text.startswith('y'):
                self.callback()
            try:
                self.win.addstr(0, 0, " "*self.dim[1])
            except curses.error:
                pass
            self.win.noutrefresh()
            self.destroy()

            self.app.current_panel = self.app.previous_focus
            self.app.paint()
        else:
            super().handle_key(key)


class MetaIndexManagerConfiguration(metaindex.configuration.BaseConfiguration):
    @property
    def find_is_case_sensitive(self):
        return self.bool(shared.ALL_SCOPE,
                         shared.PREF_FIND_CASE_SENSITIVE,
                         shared.DEFAULT_FIND_CASE_SENSITIVE)


class Application(cursedspace.Application):
    def __init__(self, args):
        super().__init__()
        # key definition is quirky:
        # the mapping is 'sequence of keys' to 'command'
        # command can be either of these:
        # - 'command', name of a command (to be resolved and executed as is)
        # - '::command param1 param2', command with parameters to be executed
        #    as such
        # - ':command param1', command to be filled into the command line and
        #    the user has to complete it
        self.keys = [
            (shared.ANY_SCOPE, ('q', ), ('close',)),
            (shared.ANY_SCOPE, ('X', ), ('quit',)),
            (shared.ANY_SCOPE, ('?', ), ('help',)),
            (shared.ANY_SCOPE, ('<F1>', ), ('help',)),
            (FilePanel.SCOPE, (Key.RIGHT,), ('open',)),
            (FilePanel.SCOPE, ('O',), (':open-with',)),
            (DocPanel.SCOPE, (Key.RIGHT,), ('open',)),
            (FilePanel.SCOPE, ('O',), (':open-with',)),
            (EditorPanel.SCOPE, (Key.RIGHT,), ('open',)),
            (FilePanel.SCOPE, ('O',), (':open-with',)),
            (FilePanel.SCOPE, (Key.LEFT,), ('go-to-parent',)),
            (shared.ANY_SCOPE, (Key.TAB, ), ('next-panel',)),
            (shared.ANY_SCOPE, ('g', 'n', 'f'), ('new-file-panel',)),
            (shared.ANY_SCOPE, ('g', 'n', 'd'), ('new-documents-panel',)),
            (shared.ANY_SCOPE, ('g', 'p'), ('::focus',)),
            (shared.ANY_SCOPE, ('g', 't'), ('next-panel',)),
            (shared.ANY_SCOPE, ('g', 'T'), ('previous-panel',)),
            (shared.ANY_SCOPE, ('g', 'l'), ('go-to-location',)),
            (DocPanel.SCOPE, ('g', 's'), (':search',)),
            (DocPanel.SCOPE, (Key.F3, ), (':search',)),
            (FilePanel.SCOPE, ('g', 'h'), ('::cd ~', "Go home")),
            (FilePanel.SCOPE, ('g', 'd'), ('details',)),
            (DocPanel.SCOPE, ('g', 'd'), ('details',)),
            (FilePanel.SCOPE, ('c', 'd'), (':cd',)),
            (FilePanel.SCOPE, ('d', 'D'), ('rm',)),
            (FilePanel.SCOPE, ('a',), (':rename %n',)),
            (FilePanel.SCOPE, ('y', 'y'), ('copy',)),
            (FilePanel.SCOPE, ('d', 'd'), ('cut',)),
            (FilePanel.SCOPE, ('y', 'a'), ('append',)),
            (FilePanel.SCOPE, ('d', 'a'), ('cut-append',)),
            (FilePanel.SCOPE, ('p', 'p'), ('paste',)),
            (FilePanel.SCOPE, ('p', 'o'), ('paste-overwrite',)),
            (FilePanel.SCOPE, ('p', 'a'), ('paste-append',)),
            (FilePanel.SCOPE, ('!', ), (':shell',)),
            (DocPanel.SCOPE, ('y', 'y'), ('copy',)),
            (DocPanel.SCOPE, ('y', 'a'), ('append',)),
            (EditorPanel.SCOPE, ('y', 'y'), ('copy',)),
            (EditorPanel.SCOPE, ('y', 'a'), ('append',)),
            (EditorPanel.SCOPE, ('p', 'p'), ('paste',)),
            (shared.ANY_SCOPE, ('y', '0'), ('clear-clipboard',)),
            (FilePanel.SCOPE, ('z', 'h'), ('toggle-hidden',)),
            (FilePanel.SCOPE, ('z', 'm'), ('toggle-sidecar',)),
            (shared.ANY_SCOPE, ('z', 's'), ('::layout horizontal', 'Split layout')),
            (shared.ANY_SCOPE, ('z', 't'), ('::layout tabbed', 'Tabbed layout')),
            (shared.ANY_SCOPE, (':', ), ('enter-command',)),
            (shared.ANY_SCOPE, ('^L', ), ('repaint',)),
            (DocPanel.SCOPE, ('e', ), ('edit-metadata',)),
            (DocPanel.SCOPE, ('E', ), ('edit-metadata-external',)),
            (FilePanel.SCOPE, ('e', ), ('edit-metadata',)),
            (FilePanel.SCOPE, ('E', ), ('edit-metadata-external',)),
            (EditorPanel.SCOPE, ('E', ), ('edit-metadata-external',)),
            (shared.ANY_SCOPE, ('^R', ), ('refresh',)),
            (FilePanel.SCOPE, ('m', ), ('::mark',)),
            (DocPanel.SCOPE, ('m', ), ('::mark',)),
            (FilePanel.SCOPE, (Key.SPACE,), ('select',)),
            (FilePanel.SCOPE, ('u', 'v'), ('clear-selection',)),
            (FilePanel.SCOPE, ('v', ), ('invert-selection',)),
            (shared.ANY_SCOPE, ("'", ), ('::jump-to-mark',)),
            (shared.ANY_SCOPE, (Key.DOWN,), ('next-item',)),
            (shared.ANY_SCOPE, ('j',), ('next-item',)),
            (shared.ANY_SCOPE, (Key.UP,), ('previous-item',)),
            (shared.ANY_SCOPE, ('k',), ('previous-item',)),
            (shared.ANY_SCOPE, (Key.PGUP,), ('previous-page',)),
            (shared.ANY_SCOPE, (Key.PGDN,), ('next-page',)),
            (shared.ANY_SCOPE, (Key.HOME,), ('go-to-start',)),
            (shared.ANY_SCOPE, (Key.END,), ('go-to-end',)),
            (shared.ANY_SCOPE, ('g', 'g'), ('go-to-start',)),
            (shared.ANY_SCOPE, ('G',), ('go-to-end',)),
            (shared.ANY_SCOPE, ('/',), (':find',)),
            (shared.ANY_SCOPE, ('n',), ('find-next',)),
            (shared.ANY_SCOPE, ('N',), ('find-prev',)),
            (EditorPanel.SCOPE, (Key.RETURN,), ('edit-mode',)),
            (EditorPanel.SCOPE, ('i',), ('edit-mode',)),
            (EditorPanel.SCOPE, ('o',), ('add-value',)),
            (EditorPanel.SCOPE, ('c',), ('replace-value',)),
            (EditorPanel.SCOPE, ('a',), (':add-tag', 'Add a new tag')),
            (EditorPanel.SCOPE, ('d', 'd'), ('del-tag',)),
            (EditorPanel.SCOPE, ('u',), ('undo-change',)),
            (EditorPanel.SCOPE, ('U',), ('undo-all-changes',)),
            (EditorPanel.SCOPE, ('^R',), ('redo-change',)),
            (EditorPanel.SCOPE, ('r',), ('redo-change',)),
            ]
        self.cancel_input = [Key.ESCAPE]
        self.key_sequence = []
        self.current_panel = None
        self.previous_focus = None
        self.panels = []
        self.key_help_panel = None
        self.command_input = None
        self.blocking_task = None
        self.info_text_timestamp = None
        self.info_text_timeout = datetime.timedelta(seconds=10)

        conf = configparser.ConfigParser(interpolation=None)
        conf.read_dict({shared.ALL_SCOPE: {PREF_OPENER: DEFAULT_OPENER,
                                           PREF_INFO_TIMEOUT: DEFAULT_INFO_TIMEOUT,
                                           shared.PREF_BORDER: shared.DEFAULT_BORDER},
                        EditorPanel.SCOPE: {
                            EditorPanel.CONFIG_NO_COMPLETION: 'title',
                            EditorPanel.CONFIG_TAGS: EditorPanel.CONFIG_TAGS_DEFAULT,
                            },
                        })
        self.configuration = MetaIndexManagerConfiguration(conf)
        utils.parse_ls_colors()
        utils.parse_ls_icons()

        self.layout = layouts.get_layout('horizontal')
        assert self.layout is not None
        self.layout = self.layout(self)

        self.named_clipboard = {}
        # bookmarks are tuples (panel type, base path, selected item)
        self.bookmarks = {}
        try:
            self.restore_bookmarks()
        except Exception as exc:
            logger.debug("Failed to restore bookmarks: %s", exc)

        # during command execution paints are not executed, but enqueued
        self.prevent_paint = False
        self.queued_paint = None
        self.queued_config_change = None
        # tuples (panel, function: bool) to call upon next start of the main loop
        self.callbacks = queue.Queue()

        self.key_timeout = 100

        self.loading_config = False
        self.load_config_stack = []

        self.select_file_mode = False
        self.select_file_output = None
        self.selected_file = None
        if args.select_file_mode:
            self.select_file_mode = True
            self.select_file_output = args.select_file_output
            self.keys += [
                (DocPanel.SCOPE, (Key.RETURN,), ('select-and-exit',)),
                (FilePanel.SCOPE, (Key.RETURN,), ('select-and-exit',)),
            ]
        self.start_locations = args.location

        self.clipboard = Clipboard(self)

        self.command_history = []
        if HISTORYFILE.is_file():
            self.command_history = [line for line in HISTORYFILE.read_text().split("\n")
                                         if len(line.strip()) > 0]

        self.metaindexconf = metaindex.configuration.load(args.metaindex_config)
        self.cache = MemoryCache(self.metaindexconf)
        self.cache.start()

        self.known_programs = []
        self.refresh_known_programs()

        configpath = pathlib.Path(args.config).expanduser()
        if configpath.parent.exists():
            here = os.getcwd()
            os.chdir(configpath.parent)
            self.load_config_file(configpath)
            os.chdir(here)

    def main(self):
        self.command_input = None
        if len(self.start_locations) > 0:
            for location in self.start_locations:
                path = pathlib.Path(location).expanduser().resolve()
                if path.is_dir() and len(location) > 0:
                    self.panels.append(FilePanel(self, path=path))
                else:
                    self.panels.append(DocPanel(self, searchterm=location))
            self.current_panel = self.panels[-1]
        else:
            default_view = self.configuration.get(shared.ALL_SCOPE,
                                                  shared.PREF_DEFAULT_PANEL,
                                                  shared.DEFAULT_DEFAULT_PANEL)
            logger.debug("default view configured to %s", default_view)
            paneltype = find_panel_type(default_view)
            if paneltype is None:
                paneltype = DocPanel
            self.current_panel = paneltype(self)
            self.panels.append(self.current_panel)
        self.resize_panels()
        self.paint()
        self.set_term_title(shared.PROGRAMNAME)

        timed_out = False
        redraw = False
        self.screen.timeout(self.key_timeout)
        self.info(f"Welcome to {shared.PROGRAMNAME}")

        # quit when there are no panels (left) to display
        while len(self.panels) > 0:
            while not self.callbacks.empty():
                panel, fnc = self.callbacks.get()

                if panel is self.blocking_task:
                    redraw = fnc()

                elif panel in self.panels and fnc() and self.layout.is_visible(panel):
                    try:
                        panel.paint(True)
                    except curses.error:
                        pass
                    redraw = True

                    if redraw and self.blocking_task is not None:
                        self.blocking_task.paint()

            if not timed_out or redraw:
                if self.key_help_panel is not None:
                    self.key_help_panel.paint()

                if self.blocking_task is not None:
                    self.blocking_task.focus()
                elif self.key_help_panel is not None:
                    self.key_help_panel.focus()
                elif self.current_panel is not None:
                    self.current_panel.focus()
                curses.doupdate()

            timed_out = False
            redraw = False

            key = self.read_key()

            if key == Key.TIMEOUT:
                timed_out = True

            elif key == Key.RESIZE:
                self.resize_panels()
                self.paint()

            elif self.blocking_task is not None:
                self.blocking_task.handle_key(key)

            elif isinstance(self.current_panel, InputLine):
                self.current_panel.handle_key(key)

            elif key in self.cancel_input and len(self.key_sequence) > 0:
                self.key_sequence = []
                self.hide_key_help()

            else:
                self.key_sequence.append(str(key))
                seq = tuple(self.key_sequence)
                resolved = self.resolve_key_sequence()
                if resolved is not None:
                    self.key_sequence = []
                    if len(resolved) == 2:
                        commandname, _ = resolved
                    elif len(resolved) == 1:
                        commandname = resolved[0]
                    else:
                        logger.error(f"Command sequence {seq} has an invalid command tuple {resolved}")
                        continue

                    self.hide_key_help()

                    if commandname in LIST_SCROLL_COMMANDS:
                        if self.current_panel is not None:
                            self.current_panel.handle_key(seq)
                    elif commandname.startswith(':') and not commandname.startswith('::'):
                        rawprefill = shlex.split(commandname[1:])
                        prefill = shlex.join([rawprefill[0]]
                                             + sum([expand_part(self, part)
                                                    for part in rawprefill[1:]], start=[]))
                        if len(rawprefill) == 1:
                            prefill += " "
                        self.execute_command("enter-command", prefill)
                    else:
                        args = None
                        if commandname.startswith('::'):
                            args = shlex.split(commandname[2:])
                            commandname = args.pop(0)
                            args = sum([expand_part(self, part)
                                        for part in args],
                                       start=[])

                        command = resolve_command(commandname)
                        if command is not None and \
                           isinstance(self.current_panel, command.ACCEPT_IN):
                            if args is None:
                                self.execute_command(commandname)
                            else:
                                self.execute_command(commandname, *args)
                else:
                    self.update_key_help()

                    if self.key_help_panel is None:
                        # last resort: maybe a panel has some use for this special key
                        self.current_panel.handle_key(seq)

            if self.info_text_timestamp is not None and \
               datetime.datetime.now() > self.info_text_timestamp + self.info_text_timeout:
                self.clear_info_text()

    def run(self):
        stored_exc = None
        try:
            retval = super().run()
        except Exception as exc:
            retval = -1
            stored_exc = exc

        self.cache.quit()

        try:
            history_size = int(self.configuration.get(shared.ALL_SCOPE,
                                                      PREF_HIST_SIZE,
                                                      DEFAULT_HIST_SIZE))
        except ValueError:
            history_size = int(DEFAULT_HIST_SIZE)

        try:
            HISTORYFILE.write_text("\n".join([command
                                              for command in self.command_history[-1*history_size:]
                                              if len(command.strip()) > 0]))
        except Exception as exc:
            logger.error(f"Could not write to the history file {HISTORYFILE}: {exc}")

        if stored_exc is not None:
            raise stored_exc

        if self.select_file_mode:
            if self.selected_file is None:
                return -1

            fn = self.select_file_output
            if fn == '-':
                fh = sys.stdout
            else:
                fh = open(self.select_file_output, "wt", encoding="utf-8")
            fh.write(str(self.selected_file))
            fh.close()

        return retval

    def execute_command(self, command, *args, **kwargs):
        """Accepts either a Command instance, a Command class or a name of a command"""
        if isinstance(command, str):
            command = resolve_command(command)

        if command is not None and \
           type(command).__name__ == 'type' and \
           issubclass(command, Command):
            command = command()

        if command is None:
            logger.info("None command executed. Probably programmer problem.")
            return

        cleanup = False

        if not self.prevent_paint:
            self.prevent_paint = True
            self.queued_paint = []
            cleanup = True

        try:
            command.execute(self.make_context(), *args, **kwargs)
        except Exception as exc:
            logger.error("Execution of %s failed: %s", command.NAME, exc)
            logger.debug(''.join(traceback.format_tb(exc.__traceback__)))
            self.error(f"Command failed: {exc}")

        if cleanup:
            self.prevent_paint = False
            if len(self.queued_paint) > 0:
                self.paint(any(self.queued_paint))
            self.queued_paint = None

    def resolve_key_sequence(self):
        tplkeys = tuple(self.key_sequence)
        for scope, keys, commands in self.keys:
            if scope not in [shared.ANY_SCOPE, getattr(self.current_panel, 'SCOPE', None)]:
                continue
            if keys == tplkeys:
                return commands
        return None

    def update_key_help(self):
        if len(self.key_sequence) == 0:
            return
        curseq = self.key_sequence
        candidates = []
        for scope, keys, cmd in self.keys:
            if scope not in [shared.ANY_SCOPE, getattr(self.current_panel, 'SCOPE', None)]:
                continue
            if list(keys)[:len(curseq)] != curseq:
                continue
            cmdname = cmd[0]
            if cmdname.startswith(':') and not cmdname.startswith('::'):
                candidates.append((keys, cmd))
                continue
            if cmdname.startswith('::'):
                cmdname = shlex.split(cmdname)[0][2:]
            logger.debug('resolving %s', cmdname)
            command = resolve_command(cmdname)
            if command in LIST_SCROLL_COMMANDS:
                candidates.append((keys, cmd))
                continue
            if command is None:
                logger.debug(f"Invalid command in keys: {cmdname}")
                continue
            if not isinstance(self.current_panel, command.ACCEPT_IN):
                logger.debug(f"Inconsistent ACCEPT_IN / scope for command {cmd[0]}")
                continue
            candidates.append((keys, cmd))

        lines = []
        prefix = self.key_sequence
        for item in candidates:
            keys, item = item
            doc = ""
            if len(item) == 1:
                fnc = item[0]
            else:
                fnc, doc = item
            cmd = resolve_command(fnc)
            doc = cmd.__doc__.split("\n")[0] if cmd is not None else doc
            lines.append(["".join(keys[len(prefix):]), fnc, doc])

        if len(candidates) == 0:
            self.key_sequence = []
            self.hide_key_help()
        elif self.key_help_panel is None:
            self.key_help_panel = KeyHelpPanel(lines, self)
            self.key_help_panel.autosize()
            self.paint()
        else:
            self.key_help_panel.candidates = lines
            self.key_help_panel.autosize()
            self.paint()

    def hide_key_help(self):
        if self.key_help_panel is not None:
            self.key_help_panel.destroy()
            self.key_help_panel = None
            self.paint()

    def resize_panels(self):
        if len(self.panels) < 1:
            return

        maxheight, maxwidth = self.size()
        maxheight -= 2

        self.layout.resize_panels()

        if self.command_input is not None:
            self.command_input.resize(1, maxwidth)
            self.command_input.move(maxheight+1, 0)

        if self.key_help_panel is not None:
            self.key_help_panel.autosize()

        if self.blocking_task is not None:
            self.blocking_task.autoresize()

    def refresh(self, force=False):
        logger.debug("global refresh called")
        if len(self.panels) < 1:
            return

        super().refresh(force)

        self.layout.refresh(force)

        if self.command_input is not None:
            self.command_input.refresh(force)
        if self.key_help_panel is not None:
            self.key_help_panel.refresh(force)
        if self.blocking_task is not None:
            self.blocking_task.refresh(force)

    def add_panel(self, panel):
        """Add this panel to the list of active panels"""
        self.panels.append(panel)
        self.resize_panels()
        self.paint()

    def activate_panel(self, panel):
        """Activate this panel.
        """
        assert isinstance(panel, Panel)
        if panel in self.panels:
            logger.debug(f"activating panel {panel} #{self.panels.index(panel)}")
        else:
            logger.debug(f"activating panel {panel}")

        if self.current_panel in self.panels:
            self.previous_focus = self.current_panel
        elif self.previous_focus not in self.panels:
            self.previous_focus = None if len(self.panels) == 0 else self.panels[0]
        self.current_panel = panel

        if self.previous_focus is not None and hasattr(self.previous_focus, 'on_focus_lost'):
            self.previous_focus.on_focus_lost()
        self.layout.activated_panel(panel)
        if hasattr(panel, 'on_focus'):
            panel.on_focus()

    def close_panel(self, panel):
        if panel not in self.panels:
            return
        panel.on_close()
        idx = self.panels.index(panel)
        refocus = panel is self.current_panel
        self.panels = self.panels[:idx] + self.panels[idx+1:]
        if refocus:
            self.current_panel = None
            if len(self.panels) > 0:
                self.activate_panel(self.panels[max(0, idx-1)])
        self.resize_panels()
        self.paint()

    def paint(self, clear=False):
        if self.screen is None:
            return

        if self.prevent_paint:
            if self.queued_paint is None:
                self.queued_paint = [clear]
            else:
                self.queued_paint.append(clear)
            return
        logger.debug("global paint called")
        if clear:
            height, width = self.size()
            # don't erase the full screen, panels will do that
            # only clear the lines that are outside the regular panels
            try:
                self.screen.addstr(0, 0, " "*width)
                self.screen.addstr(0, height-1, " "*width)
            except curses.error:
                pass
        self.screen.noutrefresh()

        try:
            self.layout.paint(clear)
        except curses.error:
            pass

        try:
            self.paint_focus_bar()
        except curses.error:
            pass

        try:
            if self.blocking_task is not None:
                self.blocking_task.paint()
            if self.command_input is not None:
                self.command_input.paint()
            if self.current_panel is not None and self.current_panel not in self.panels:
                self.current_panel.paint()
        except curses.error:
            pass

    def paint_focus_bar(self):
        _, width = self.size()
        try:
            self.screen.addstr(0, 0, " "*width)
        except curses.error:
            pass
        panels = [f' {nr+1}' for nr in range(len(self.panels))]

        curidx = -1
        if self.current_panel in self.panels:
            curidx = self.panels.index(self.current_panel)
        elif self.previous_focus in self.panels:
            curidx = self.panels.index(self.previous_focus)
        logger.debug(f"focus bar #{curidx} ({panels})")

        title = ""
        if 0 <= curidx < len(self.panels):
            activepanel = self.panels[curidx]
            title = activepanel.title()
        try:
            self.screen.addstr(0, 0, title[:width-1])
        except curses.error:
            pass
        self.screen.noutrefresh()

        x = width - len(''.join(panels))
        for idx, text in enumerate(panels):
            attr = curses.A_STANDOUT if idx == curidx else curses.A_NORMAL
            try:
                self.screen.addstr(0, x, text, attr)
            except curses.error:
                pass
            x += len(text)
        self.screen.noutrefresh()

    def save_bookmark(self, mark, panel, path, item):
        """Store this bookmark"""
        self.bookmarks[mark] = (type(panel), path, item)
        self.store_bookmarks()
        self.clear_info_text()

    def load_bookmark(self, mark):
        """Restore this bookmark, create a panel if required"""

        if mark not in self.bookmarks:
            self.error("No such bookmark '{mark}'")
            return

        paneltype, path, item = self.bookmarks[mark]

        if type(self.current_panel) is paneltype and \
           (not hasattr(self.current_panel, 'is_busy') or not self.current_panel.is_busy):
            self.current_panel.jump_to(item, path)
        else:
            try:
                panel = paneltype(self, path)
            except Exception as exc:
                msg = f"Error loading bookmark for {paneltype}: {exc}"
                logger.error(msg)
                self.error(msg)
                return
            self.add_panel(panel)
            self.activate_panel(panel)

            panel.jump_to(item)
        self.clear_info_text()

    def restore_bookmarks(self):
        """Load the previously defined bookmarks from disk

        Bookmarks are stored one per line in plain text in this format:

            <mark> <panel type> <path> <path to item>

        """
        if not BOOKMARKFILE.is_file():
            return

        for line in BOOKMARKFILE.read_text().split("\n"):
            parts = shlex.split(line)
            if len(parts) != 4:
                continue

            mark, typename, path, item = parts
            if len(item) == 0:
                item = None
            if item is not None:
                item = pathlib.Path(item)

            paneltype = find_panel_type(typename)
            if paneltype is None:
                logger.warning(f"Unknown panel type {typename}")
                continue

            self.bookmarks[mark] = (paneltype, path, item)

    def store_bookmarks(self):
        """Save the bookmarks to disk"""
        with open(BOOKMARKFILE, 'wt', encoding='utf-8') as fh:
            for mark in sorted(self.bookmarks.keys()):
                typename = self.bookmarks[mark][0].SCOPE
                line = [mark, typename] + [str(v) for v in self.bookmarks[mark][1:]]
                fh.write(shlex.join(line) + "\n")

    def configuration_changed(self, change):
        if self.queued_config_change is not None:
            self.queued_config_change.append(change)
        else:
            self.queued_config_change = [change]
            self.apply_config_changes()

    def apply_config_changes(self):
        must_repaint = False
        if self.queued_config_change is not None and len(self.queued_config_change) == 0:
            self.queued_config_change = None
        if self.queued_config_change is None:
            return

        for scope, name in self.queued_config_change:
            if scope == shared.ALL_SCOPE and \
               name == shared.PREF_BORDER and \
               self.layout is not None and self.screen is not None:
                self.layout.resize_panels()
                must_repaint = True
            elif scope == shared.ALL_SCOPE and name == PREF_INFO_TIMEOUT:
                raw_value = self.configuration.get(scope, name, DEFAULT_INFO_TIMEOUT)
                try:
                    value = utils.parse_duration(raw_value)
                    self.info_text_timeout = value
                except ValueError as exc:
                    self.error(f"{raw_value} is not a valid duration: {exc}")
            for panel in self.panels:
                if scope in [panel.SCOPE, shared.ALL_SCOPE]:
                    panel.configuration_changed(name)
        if must_repaint and self.layout is not None:
            self.layout.paint(True)
        self.queued_config_change = None

    def load_config_file(self, path, context=None):
        path = path.resolve()

        if not path.is_file():
            return

        if path in self.load_config_stack:
            return

        if context is None:
            context = Context(application=self, panel=None)

        if self.queued_config_change is None:
            self.queued_config_change = []

        # prevent duplicate loading of this file
        self.loading_config = True
        self.load_config_stack.append(path)

        logger.info(f"Loading configuration file {path}")

        with open(path, 'rt', encoding='utf-8') as fh:
            for linenr, line in enumerate(fh.readlines()):
                tokens = shlex.split(line.strip())
                if len(tokens) == 0 or tokens[0] == '#':
                    continue

                cmdname = tokens[0]
                args = tokens[1:]

                cmd = resolve_command(cmdname)
                if cmd is None:
                    logger.error(f"Error in configuration file {path}, line {linenr+1}: command '{cmdname}' not found")
                    continue

                cmd().execute(context, *args)

        self.load_config_stack.pop()
        self.loading_config = len(self.load_config_stack) > 0
        if not self.loading_config:
            self.apply_config_changes()

    def open_file(self, path):
        assert path.is_file()
        opener = shlex.split(self.configuration.get(shared.ALL_SCOPE, PREF_OPENER, DEFAULT_OPENER))
        if len(opener) == 0:
            # TODO: check for existing file
            return
        self.open_with(path, opener)

    def open_with(self, path, cmd):
        use_shell = len(cmd) == 0

        with ShellContext(self.screen):
            subprocess.run(cmd + [str(path)], shell=use_shell, check=True)
        self.paint(True)
        self.set_term_title(shared.PROGRAMNAME)

    def get_text_editor(self, show_error=False):
        """Resolve the external text editor to use"""
        editor = [self.configuration.get('all', 'editor', None)] \
               + [os.getenv(name) for name in ['VISUAL', 'EDITOR']]
        for value in editor[:]:
            if value is None:
                continue
            editor = shutil.which(value)
            if editor is not None:
                return shlex.split(editor)

        if show_error:
            msg = "Don't know what editor to use. Please set the 'editor' configuration option"
            logger.error(msg)
            self.error(msg)
        return None

    def make_command_input(self, text=""):
        assert self.command_input is None
        self.clear_info_text()
        self.command_input = CommandInput(self, 1, (0, 0), prefix=":", text=text)
        self.command_input.cursor = len(text)
        self.resize_panels()
        return self.command_input

    def make_context(self):
        return Context(application=self,
                       panel=self.current_panel)

    def confirm(self, text, default, callback):
        height, width = self.size()
        yes = 'Y' if default == 'y' else 'y'
        no = 'N' if default == 'n' else 'n'
        options = f' ({yes}/{no}) '
        text = text[:width - len(options) - 1] + options
        panel = YesNoConfirmation(callback, default, self, width, (height-1, 0), prefix=text)
        self.activate_panel(panel)
        self.paint()
        panel.paint()

    def error(self, text):
        logger.debug(f"Logging error: {text}")
        if self.screen is not None:
            self.info(text, colors.attr(colors.RED))

    def info(self, text, attr=0):
        if self.screen is None:
            return

        size = self.size()
        display = text[:size[1]] + " "*max(0, size[1]-len(text))
        self.info_text_timestamp = datetime.datetime.now()
        try:
            self.screen.addstr(size[0]-1, 0, display, attr)
        except curses.error:
            pass
        self.screen.refresh()

    def clear_info_text(self):
        if self.info_text_timestamp is None:
            return
        self.info_text_timestamp = None
        size = self.size()
        try:
            self.screen.addstr(size[0]-1, 0, " "*size[1])
        except curses.error:
            pass
        self.screen.noutrefresh()
        self.current_panel.focus()
        self.current_panel.win.noutrefresh()
        curses.doupdate()

    def refresh_known_programs(self):
        threading.Thread(target=self._do_refresh_known_programs).start()

    def _do_refresh_known_programs(self):
        paths = [pathlib.Path(p)
                 for p in os.getenv('PATH', os.defpath).split(os.pathsep)]
        programs = set()
        for path in paths:
            try:
                if not path.is_dir() or not os.access(path, os.X_OK):
                    continue
            except OSError:
                continue
            for item in path.iterdir():
                try:
                    if item.is_file() and os.access(item, os.F_OK | os.X_OK):
                        programs.add(item)
                except OSError:
                    pass
        self.known_programs = list(sorted(programs))

    @staticmethod
    def as_printable(value, shorten=100):
        """Clean up a string to make it printable

        Shorten the value to ``shorten`` characters.
        If ``shorten`` is None, no shortening will happend.
        """
        if value is None:
            return ''
        text = str(value)
        if shorten is not None:
            text = text[:shorten]
        return (''.join(letter
                        for letter in text
                        if letter.isprintable())).strip().replace('\t', ' ')

    @property
    def collection_metadata(self):
        return self.configuration.list('General', 'collection-metadata', 'metadata')


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('-m', '--metaindex-config',
                        default=None,
                        type=str,
                        help="The metaindex configuration file to use. Defaults "
                            f"to {metaindex.configuration.CONFIGFILE}.")

    parser.add_argument('-c', '--config',
                        default=CONFIGFILE,
                        type=str,
                        help="Location of the configuration file. Defaults to %(default)s.")

    parser.add_argument('-v', '--version',
                        action='version',
                        version=f'%(prog)s {version.__version__}')
    parser.add_argument('--check-for-update',
                        default=False,
                        action="store_true",
                        help="Check online whether a new version is available")

    parser.add_argument('-l', '--log-level',
                        default='warning',
                        choices=['debug', 'info', 'warning', 'error', 'fatal'],
                        help="The level of logging. Defaults to %(default)s.")
    parser.add_argument('--log-file',
                        default=LOGFILE,
                        type=str,
                        help="Where to write the log file to. Defaults to %(default)s.")

    parser.add_argument('--select-file-mode',
                        default=False,
                        action="store_true",
                        help="Run in mode to select a file.")
    parser.add_argument('--select-file-output',
                        default="-",
                        type=str,
                        help="Where to write the selected file to. Defaults to -, i.e. stdout")

    parser.add_argument("location",
                        type=str,
                        nargs='*',
                        default=None,
                        help="Start with these locations. May either be paths in the filesystem "
                             "or metaindex search terms.")

    result = parser.parse_args()

    return result


def run():
    args = parse_args()

    logger.setup(level=args.log_level.upper(), filename=args.log_file)

    if args.check_for_update:
        try:
            response = urllib.request.urlopen('https://vonshednob.cc/metaindexmanager/latest')
            remote_version = str(response.read(), 'ascii')
            if remote_version.startswith('v'):
                remote_version = remote_version[1:]
        except Exception as exc:
            print(f"Could get the latest version from vonshednob.cc: {exc}")
            return 1

        if remote_version > version.__version__:
            print("A newer version of metaindexmanager is available.")
        elif version.__version__ > remote_version:
            print("Your version is NOT in line with the released version!")
        else:
            print("You are up to date.")

        return 0

    logger.debug("Starting metaindexmanager")
    logging.getLogger().addHandler(logger.handler)

    if args.log_level.lower() in ['debug']:
        metaindex.logger.setup(level=logging.DEBUG, filename=args.log_file.parent / 'metaindex.log')
    else:
        metaindex.logger.setup(logging.ERROR, logger.handler)

    if ADDONSPATH.exists():
        prev_sys_path = sys.path.copy()
        sys.path = [str(ADDONSPATH)] + sys.path
        for item in ADDONSPATH.iterdir():
            if item.is_file() and item.suffix == '.py':
                importlib.import_module(item.stem)
            elif item.is_dir() and (item / '__init__.py').is_file():
                importlib.import_module(item.stem)
        sys.path = prev_sys_path

    try:
        return Application(args).run()
    except Exception as exc:
        callstack = ''.join(traceback.format_tb(exc.__traceback__))
        logger.fatal(f"The program ended with this exception: {exc}, "
                     f"please report this to the developer\n{callstack}")
        print(f"The program ended with this exception: {exc}. "
               "Please report it to the developers.")
        if args.log_file is not None:
            print(f"Details can be found in the log file at {args.log_file}")
        if args.log_level.lower() == 'debug':
            raise
        return 1


if __name__ == '__main__':
    sys.exit(run())
