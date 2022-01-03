import pathlib
import curses
import os
import shutil
import threading
import subprocess
import time

from cursedspace import Key, Panel, colors, ShellContext

from metaindexmanager import command
from metaindexmanager import utils
from metaindexmanager.utils import logger
from metaindexmanager.panel import ListPanel


class Line:
    def __init__(self, panel, path, stat=None):
        self.panel = panel
        self.path = path
        self.is_dir = path.is_dir()
        self.is_symlink = path.is_symlink()
        if stat is not None:
            self.stat = stat
        else:
            try:
                self.stat = path.stat()
            except:
                self.stat = None
        self.name = path.name
        self.stem = path.stem
        self.suffix = path.suffix
        self.fullpath = path
        self.icon = utils.get_ls_icon(path, self.stat)
        self.attr, fg, bg = utils.get_ls_colors(path, self.stat)

        self.fg = colors.DEFAULT.foreground if fg is None else fg
        self.bg = -1 if bg is None else bg

    def copy(self):
        return Line(self.panel, self.path, self.stat)

    def __eq__(self, other):
        return other is self \
            or (isinstance(other, pathlib.Path) and other == self.path) \
            or (isinstance(other, str) and other == str(self.path)) \
            or (isinstance(other, Line) and other.path == self.path)

    def __lt__(self, other):
        return self.name < other.name

    def __str__(self):
        prefix = "d" if self.is_dir else "f"
        return f"{prefix}{self.name}"


class FolderObserver(threading.Thread):
    def __init__(self, panel, path, items=None):
        super().__init__()
        self.path = path
        self.panel = panel
        self.items = items[:] if items else []
        self.active = False
        self.do_interrupt = threading.Event()
    
    def run(self):
        self.active = True
        text = None
        while self.active:
            items = [item for item in self.path.iterdir()]
            newtext = "\n".join([str(i) for i in sorted(items)])
            if text is None or text != newtext:
                text = newtext
                self.panel.app.callbacks.put((self.panel, lambda: self.on_change(items)))
            self.do_interrupt.wait(2)  # TODO: should be configurable

    def on_change(self, items):
        if self.active:
            return self.panel.finish_change_path([Line(self.panel, i) for i in items])
        return False

    def close(self):
        self.active = False
        self.do_interrupt.set()
        self.join()


class FilePanel(ListPanel):
    SCOPE = 'files'

    CONFIG_ICONS = 'use-icons'

    def __init__(self, *args, path='.', **kwargs):
        super().__init__(*args, **kwargs)
        self.path = None
        self.previous_path = None
        self.post_load = None
        self.show_hidden_files = False
        self.fancy_icons = False
        self.observer = None
        self.cursor_cache = {}
        self.configuration_changed()
        self.change_path(path)

    def configuration_changed(self, name=None):
        super().configuration_changed(name)

        changed = False

        if name is None or name == self.CONFIG_ICONS:
            value = self.app.configuration.bool(self.SCOPE, self.CONFIG_ICONS, 'no')
            changed = self.fancy_icons != value
            self.fancy_icons = value

        if changed:
            if self.win is not None:
                self.scroll()
                self.paint(True)

    def change_path(self, path):
        logger.debug(f"FilePanel: changing to path {path}")
        if self.path is not None:
            self.cursor_cache[self.path] = self.cursor
        self.previous_path = self.path
        path = pathlib.Path(path).expanduser().resolve()
        if path != self.path and self.observer is not None:
            self.observer.active = False
            self.observer = None
        self.path = path
        self.offset = 0
        self.cursor = 0
        self.items = None
        if self.observer is None:
            self.observer = FolderObserver(self, path)
            self.observer.start()

    def finish_change_path(self, items):
        self.items = [i.copy() for i in sorted(items, key=lambda f: [not f.is_dir, f.name])
                      if self.show_hidden_files or not i.name.startswith('.')]

        if self.path in self.cursor_cache:
            self.cursor = self.cursor_cache[self.path]

        elif self.previous_path is not None and self.path == self.previous_path.parent:
            self.cursor = 0
            for nr, that in enumerate(self.items):
                if that.fullpath == self.previous_path:
                    self.cursor = nr
                    break

        self.scroll()
        # drop elements from the multi selection that are no longer there
        self.multi_selection = [item for item in self.multi_selection if item in self.items]
        # trigger repaint of focus bar to update the location
        self.app.callbacks.put((self, lambda: self.app.paint_focus_bar()))

        if self.post_load is not None:
            self.post_load()
            self.post_load = None

        return True

    def title(self):
        return str(self.path)

    @property
    def selected_path(self):
        return self.selected_item.fullpath

    @property
    def selected_paths(self):
        return [i.fullpath for i in self.selected_items]

    def open_selected(self):
        item = self.selected_item

        if item is None:
            self.app.error("Nothing selected")
            return

        if item.is_dir:
            self.change_path(item.fullpath)
            self.paint(True)
        else:
            self.app.open_file(item.fullpath)

    def mkdir(self, name):
        if len(name) == '':
            self.app.error("No folder name given")
            return

        new_path = self.path / name

        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.app.error(f"Failed to create directory: {exc}")

        self.reload()

    def delete(self, items):
        self.app.confirm(f"Are you sure you want to delete '{', '.join([item.name for item in items])}'?",
                         'n',
                         lambda: self.run_blocking(self.do_delete, items))

    def do_delete(self, context, items):
        for nr, item in enumerate(items):
            if len(items) > 1:
                context.progress((nr, len(items)))
            if item.is_dir():
                try:
                    shutil.rmtree(item)
                except Exception as exc:
                    self.app.error(f"Failed to delete the folder '{item.name}': {exc}")
            elif item.exists():
                try:
                    item.unlink()
                except Exception as exc:
                    self.app.error(f"Failed to delete '{item.name}': {exc}")

    def reload(self):
        self.change_path(self.path)

    def paint(self, clear=False):
        if self.items is None:
            Panel.paint(self, clear)
            x, y = 0, 0
            if (self.border & self.BORDER_TOP) != 0:
                y += 1
            if (self.border & self.BORDER_LEFT) != 0:
                x += 1
            self.win.addstr(y, x, "...")
            self.win.noutrefresh()
        else:
            super().paint(clear)

    def do_paint_item(self, y, x, maxwidth, is_selected, item):
        attr = item.attr

        if is_selected:
            attr |= curses.A_STANDOUT

        attr |= colors.attr((item.fg, item.bg))

        icon = '' if not self.fancy_icons else item.icon + " "

        text = f"{icon}{item.name}"
        if item in self.multi_selection:
            text = "✔ " + text
            attr |= curses.A_BOLD
        textlen = len(text)
        try:
            self.win.addstr(y, x, " "*maxwidth, attr)
        except:
            pass
        self.win.addstr(y, x, text[:maxwidth], attr)

    def jump_to(self, item, path=None):
        logger.debug(f"Jump to {path}/{item}")
        if path is None:
            path = item.parent

        if path != self.path:
            self.post_load = lambda: self.do_jump_to(item)
            self.change_path(path)
        elif self.items is None:
            self.post_load = lambda: self.do_jump_to(item)
        else:
            self.do_jump_to(item)

    def do_jump_to(self, item):
        logger.debug(f"jump to {item}")
        if item in self.items:
            self.cursor = self.items.index(item)
            self.scroll()
            if not self.is_busy:
                self.paint()

    def on_focus(self):
        if pathlib.Path.cwd() != self.path:
            os.chdir(self.path)

    def on_close(self):
        logger.debug(f"Closing {self}")
        if self.observer is not None:
            self.observer.close()


@command.registered_command
class GoToParent(command.Command):
    """Go up the file hierarchy"""
    NAME = 'go-to-parent'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.change_path(context.panel.path.parent)
        context.panel.paint(True)


@command.registered_command
class NewFilePanel(command.Command):
    """Create a new file manager panel"""
    NAME = 'new-file-panel'

    def execute(self, context, *args):
        logger.debug(f'new file panel at {args}')
        path = '.'
        if len(args) > 0:
            path = args[0]
        panel = FilePanel(context.application, path=path)
        context.application.add_panel(panel)
        context.application.activate_panel(panel)


@command.registered_command
class MakeFolder(command.Command):
    """Create a new folder"""
    NAME = 'mkdir'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context, *args):
        if context.panel.is_busy:
            return
        context.panel.mkdir(" ".join(args))


@command.registered_command
class PasteItem(command.Command):
    """Paste content of clipboard here"""
    NAME = 'paste'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context, clipboard=None):
        if clipboard is None:
            clipboard = context.application.DEFAULT_CLIPBOARD
        # TODO: implement this
        context.application.error("Not implemented yet")


@command.registered_command
class ChangeDirectory(command.Command):
    """Change directory"""
    NAME = 'cd'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context, target=None):
        if target is None:
            context.application.error("No path given")
            return

        if context.panel.is_busy:
            return

        if not isinstance(target, pathlib.Path):
            try:
                target = pathlib.Path(target).expanduser().resolve()
            except:
                context.application.error(f"{target} is not a valid path")
                return

        if not target.is_dir():
            context.application.error(f"{target} does not exist")
            return

        context.panel.change_path(target)
        context.panel.focus()
        context.panel.paint(True)


@command.registered_command
class ToggleShowHiddenFiles(command.Command):
    """Toggle show hidden files"""
    NAME = 'toggle-hidden'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.show_hidden_files = not context.panel.show_hidden_files
        context.panel.change_path(context.panel.path)
        context.panel.paint(True)


@command.simple_command('shell', accept_in=(FilePanel,))
def shell_command(context, *args):
    """Start a shell here"""
    if context.panel.is_busy:
        return

    wait_after_execution = True

    if len(args) == 0:
        shell = shutil.which(os.getenv('SHELL') or "")
        if shell is None:
            context.application.error("No SHELL found")
            return
        wait_after_execution = False
        args = [shell]

    logger.debug(f"Running in shell: {args}")
    scr = context.application.screen
    with ShellContext(scr, True):
        try:
            subprocess.run(args, shell=True, check=False)
        except (KeyboardInterrupt,):
            pass

        if wait_after_execution:
            scr.timeout(-1)
            scr.addstr("Press return to continue...")
            scr.get_wch()
            scr.timeout(context.application.key_timeout)
    context.application.paint(True)
