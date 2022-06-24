import pathlib
import curses
import os
import shutil
import threading
import subprocess
import stat
import datetime
try:
    import pwd
except ImportError:
    pwd = None
try:
    import grp
except ImportError:
    grp = None

from cursedspace import Panel, colors, ShellContext, Completion

import metaindex.shared
from metaindex import stores
from metaindex.humanizer import format_filesize, format_datetime
from metaindex.configuration import SECTION_GENERAL, CONFIG_COLLECTION_METADATA

from metaindexmanager import command
from metaindexmanager import utils
from metaindexmanager import clipboard
from metaindexmanager.clipboard import PasteBehaviour
from metaindexmanager.utils import logger
from metaindexmanager.panel import ListPanel, register


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
            try:
                items = list(self.path.iterdir())
            except OSError as exc:
                items = exc

            if isinstance(items, list):
                newtext = "\n".join([str(i) for i in sorted(items)])
                if text is None or text != newtext and self.active:
                    text = newtext
                    self.panel.app.callbacks.put((self.panel, lambda: self.on_change(items)))
            else:
                self.panel.app.callbacks.put((self.panel, lambda: self.on_change(items)))
            self.do_interrupt.wait(2)  # TODO: should be configurable
            self.do_interrupt.clear()

    def wake_up(self):
        """Wake up the thread to re-read the folder"""
        self.do_interrupt.set()

    def on_change(self, items):
        """Called when the content of the currently watched folder changes"""
        if self.active:
            if isinstance(items, list):
                return self.panel.finish_change_path([Line(self.panel, i) for i in items])
            self.panel.change_path_failed(items)
        return False

    def close(self):
        """Close and exit this thread"""
        self.active = False
        self.do_interrupt.set()
        self.join()


class CopyOperation:
    def __init__(self, blocker):
        self.blocker = blocker
        self.counter = 0

    def cancel_requested(self):
        return self.blocker is not None and \
               self.blocker.cancel_requested

    def copy(self, src, dst, *args):
        if self.cancel_requested():
            return None
        retval = shutil.copy2(src, dst, *args, follow_symlinks=False)
        self.counter += 1
        return retval


@register
class FilePanel(ListPanel):
    SCOPE = 'files'

    CONFIG_ICONS = 'use-icons'
    CONFIG_SELECT = 'selection-icon'
    CONFIG_SHOW_HIDDEN = 'show-hidden-files'
    CONFIG_SHOW_SIDECARS = 'show-sidecar-files'
    CONFIG_INFO = 'info'

    INFO_COLUMNS = {'size', 'bytes', 'owner', 'group',
                    'rights', 'mode',
                    'num_rights', 'octmode',
                    'lm_abs', 'lm_duration'}

    def __init__(self, application, path='.'):
        super().__init__(application)
        path = pathlib.Path(path)
        self.path = None
        self.previous_path = None
        self.post_load = None
        self.show_hidden_files = False
        self.show_sidecar_files = True
        self.fancy_icons = False
        self.observer = None
        self.cursor_cache = {}
        self.select_icon = ' '
        self.info_columns = []
        self.info_columns_width = []
        self.info_columns_content = {}
        self.configuration_changed()
        self.change_path(path)

        # when copying, moving, or deleting files, do not attempt to move
        # sidecar files for sidecar files, e.g. copying a 'metadata.yaml'
        # should not result in the adjacent 'metadata.json' to be copied, too.
        self.metaindexfilenames = self.app.metaindexconf.list(SECTION_GENERAL,
                                                              CONFIG_COLLECTION_METADATA)

    def configuration_changed(self, name=None):
        super().configuration_changed(name)

        changed = False
        must_reload = False

        if name is None or name == self.CONFIG_ICONS:
            value = self.app.configuration.bool(self.SCOPE, self.CONFIG_ICONS, 'no')
            changed = self.fancy_icons != value
            self.fancy_icons = value

        if name is None or name == self.CONFIG_SELECT:
            value = self.app.configuration.get(self.SCOPE, self.CONFIG_SELECT, ' ')
            if len(value) < 1:
                value = ' '
            else:
                value = value[0]
            changed = value != self.select_icon
            self.select_icon = value

        if name is None or name == self.CONFIG_INFO:
            values = [c
                      for c in self.app.configuration.list(self.SCOPE, self.CONFIG_INFO, '')
                      if c in self.INFO_COLUMNS]
            changed = values != self.info_columns
            self.info_columns = values
            if changed:
                self.calculate_info_columns()

        if name is None or name == self.CONFIG_SHOW_HIDDEN:
            value = self.app.configuration.bool(self.SCOPE,
                                                self.CONFIG_SHOW_HIDDEN,
                                                'no')
            changed = value != self.show_hidden_files
            must_reload = changed
            self.show_hidden_files = value

        if name is None or name == self.CONFIG_SHOW_SIDECARS:
            value = self.app.configuration.bool(self.SCOPE,
                                                self.CONFIG_SHOW_SIDECARS,
                                                'yes')
            changed = value != self.show_sidecar_files
            must_reload = changed
            self.show_sidecar_files = value

        if changed:
            if self.win is not None:
                if must_reload:
                    self.reload()
                self.scroll()
                self.paint(True)

    def change_path(self, path):
        logger.debug(f"FilePanel: changing to path {path}")
        path = pathlib.Path(path).expanduser().resolve()
        if self.observer is not None:
            self.observer.active = False
            self.observer = None
        if self.path != path:
            if self.path is not None:
                self.cursor_cache[self.path] = self.cursor
            self.previous_path = self.path
            self.path = path
            self.offset = 0
            self.cursor = 0
        self.items = None
        if self.observer is None:
            self.observer = FolderObserver(self, path)
            self.observer.start()

    def finish_change_path(self, items):
        is_sidecar = self.app.metaindexconf.is_sidecar_file
        self.items = [i.copy() for i in sorted(items, key=lambda f: [not f.is_dir, f.name])
                      if (self.show_hidden_files or not utils.is_hidden(i)) and
                         (self.show_sidecar_files or not is_sidecar(i.path))]

        if self.path in self.cursor_cache:
            self.cursor = self.cursor_cache[self.path]

        elif self.previous_path is not None and self.path == self.previous_path.parent:
            self.cursor = 0
            for nr, that in enumerate(self.items):
                if that.fullpath == self.previous_path:
                    self.cursor = nr
                    break

        self.calculate_info_columns()
        self.scroll()
        # drop elements from the multi selection that are no longer there
        self.multi_selection = [item for item in self.multi_selection if item in self.items]
        # trigger repaint of focus bar to update the location
        self.app.callbacks.put((self, lambda: self.app.paint_focus_bar()))

        if self.post_load is not None:
            self.post_load()
            self.post_load = None

        return True

    def change_path_failed(self, exc):
        self.app.error(str(exc))
        if self.observer is not None:
            self.observer.close()
        self.observer = None

    def title(self):
        return str(self.path)

    @property
    def selected_path(self):
        if self.selected_item is None:
            return None
        return self.selected_item.fullpath

    @property
    def selected_paths(self):
        return [i.fullpath for i in self.selected_items if i is not None]

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

    def open_selected_with(self, cmd):
        item = self.selected_item

        if item is None:
            self.app.error("Nothing selected")
            return
        self.app.open_with(item.fullpath, cmd)

    def on_clipboard_item_use(self, item):
        """Called when a clipboard item copied/cut from here is being pasted"""
        if item.extra != 'CUT':
            return
        # drop the item from clipboard when it was a 'cut' operation
        item.valid = False

    def on_cut(self, item):
        if self.is_busy:
            raise RuntimeError("Cannot cut right now")
        if not os.access(item.fullpath, os.R_OK):
            raise RuntimeError(f"File '{item.fullpath}' can not be read")
        return clipboard.ClipboardItem(item, self, 'CUT')

    def on_copy(self, item):
        if self.is_busy:
            raise RuntimeError("Cannot copy right now")
        if not os.access(item.fullpath, os.R_OK):
            raise RuntimeError(f"File '{item.fullpath}' can not be read")
        return clipboard.ClipboardItem(item, self)

    def on_paste(self, items, behaviour):
        if self.is_busy:
            raise RuntimeError("Cannot paste. Busy")

        paths = []
        for item in items:
            is_cut = item.extra == 'CUT'
            if isinstance(item.data, str):
                item = pathlib.Path(item.data)
            elif isinstance(item.data, Line):
                item = item.data.path
            elif isinstance(item.data, pathlib.Path):
                item = item.data
            else:
                raise RuntimeError(f"Cannot paste a {type(item.data).__name__}")
            paths.append((item, is_cut))

        self.run_blocking(self.do_paste, paths, behaviour)

    def do_paste(self, blocker, paths, behaviour):
        copier = CopyOperation(blocker)

        if blocker is not None:
            if all(cut for _, cut in paths):
                blocker.title("Moving")
            else:
                blocker.title("Copying")

        # copy the files here
        copied_files = []
        copied_directories = []
        moved_files = []
        moved_directories = []
        cut_files = set()
        for path, is_cut in paths:
            if copier.cancel_requested():
                break

            new_fname = path.name
            if (self.path / new_fname).exists() and behaviour == PasteBehaviour.ERROR:
                self.app.error(f"File with the same name {new_fname} exists at destination.")
                continue

            if behaviour == PasteBehaviour.APPEND:
                # find a good name that doesn't clash with existing files
                # unless 'overwrite' is True
                extension = ''
                while True:
                    new_fname = path.stem + extension + path.suffix
                    if not (self.path / new_fname).exists():
                        break
                    if len(extension) == 0:
                        extension = '_1'
                    else:
                        extension = '_' + str(int(extension[1:])+1)

            elif behaviour not in [PasteBehaviour.OVERWRITE, PasteBehaviour.ERROR]:
                raise RuntimeError(f"Unknown paste behaviour {str(behaviour)}")

            new_path = self.path / new_fname

            if is_cut:
                # move
                try:
                    is_dir = path.is_dir()
                    shutil.move(path, new_path, copy_function=copier.copy)
                    if is_dir:
                        moved_directories.append((path, new_path))
                    elif path.stem not in self.metaindexfilenames:
                        cut_files.add(path)
                        moved_files.append((path, new_path))
                except OSError as exc:
                    self.app.error(f"Failed to move {path.name}: {exc}")

            else:
                # only copy
                try:
                    if path.is_dir():
                        shutil.copytree(path, new_path,
                                        symlinks=True,
                                        dirs_exist_ok=True,
                                        copy_function=copier.copy)
                        copied_directories.append(new_path)
                    elif path.stem:
                        shutil.copy2(path, new_path)
                        if path.stem not in self.metaindexfilenames:
                            copied_files.append((path, new_path))
                except OSError as exc:
                    self.app.error(f"Failed to copy {path.name}: {exc}")

        logger.debug("Copied files: %s", copied_files)

        # just a shortcut for convenience
        find_all_sidecars = self.app.metaindexconf.find_all_sidecar_files

        # keep all inserted operations around, to update the cache once
        # everything's done
        inserts = []

        # in case the transfer of metadata/sidecar files fails, make sure any
        # deletions are *not* carried out
        prevent_deletions = set()

        # collection metadata files that must be updated
        touched_collections = {}

        # direct sidecar files that should be deleted
        sidecars_to_delete = set()

        # handle the sidecar files of all copied and moved files
        for old_path, new_path in copied_files + moved_files:
            last_modified = metaindex.shared.get_last_modified(new_path)
            merged_metadata = metaindex.shared.CacheEntry(new_path,
                                                          last_modified=last_modified)

            sidecars = list(find_all_sidecars(new_path))
            if len(sidecars) > 0:
                if behaviour == PasteBehaviour.ERROR:
                    prevent_deletions.add(old_path)
                    self.app.error(f"Will not overwrite existing sidecar file at {new_path}")
                    continue
                if behaviour == PasteBehaviour.OVERWRITE:
                    sidecars = []
                # APPEND behaviour is automatic, as the existing sidecar will be considered
                # when copying the "old" metadata

            # find all sidecar files and merge their data for this old_path
            # file into one sidecar file
            sidecars += find_all_sidecars(old_path)
            for sidecar, is_collection in sidecars:
                if is_collection:
                    metadata = stores.get_for_collection(sidecar)
                    if old_path.parent in metadata:
                        merged_metadata.update(metadata[old_path.parent])
                    if old_path in metadata:
                        merged_metadata.update(metadata[old_path])
                        if old_path in cut_files and sidecar not in touched_collections:
                            touched_collections[sidecar] = metadata
                else:
                    metadata = stores.get(sidecar)
                    merged_metadata.update(metadata)
                    if old_path in cut_files:
                        sidecars_to_delete.add(sidecar)

            # make sure we're keeping this!
            # in case the target sidecar file existed already, merged_metadata
            # might have picked up a newer 'last_modified' from it
            merged_metadata.last_modified = last_modified

            if len(merged_metadata) == 0:
                # if there's no metadata to store, we are out
                continue

            sidecar, _, store = self.app.metaindexconf.resolve_sidecar_for(new_path)
            logger.debug("trying to put %s metadata tags into %s",
                         len(merged_metadata), sidecar)

            logger.debug("writing into direct sidecar %s: %s",
                         sidecar, merged_metadata)
            try:
                store.store(merged_metadata, sidecar)
            except (OSError, IOError, ValueError) as exc:
                logger.error("Could not write extra metadata of "
                             "%s (copy of %s): %s",
                             new_path, old_path, exc)
                prevent_deletions.add(old_path)

            # remember to write the new data into the cache
            inserts.append(merged_metadata)

        # write all metadata of pasted files into the cache
        if len(inserts) > 0:
            self.app.cache.bulk_insert(inserts)

        if len(moved_directories) > 0:
            self.app.cache.bulk_rename([(old, new, True) for old, new in moved_directories])

        # now delete old sidecar files
        deletes = []
        for old_path, _ in moved_files:
            # remember to delete the old path from the cache
            deletes.append(old_path)

            if old_path in prevent_deletions:
                # something went wrong when creating the sidecar file for this
                # old file, so don't touch/delete the old sidecar(s)
                continue

            for sidecar, metadata in touched_collections.items():
                if old_path in metadata:
                    del metadata[old_path]

        for sidecar, metadata in touched_collections.items():
            assert isinstance(metadata, dict)
            try:
                stores.store(list(metadata.values()), sidecar)
            except OSError as exc:
                self.app.error(f"Failed to update '{sidecar.name}': {exc}")

        for sidecar in sidecars_to_delete:
            try:
                sidecar.unlink()
            except OSError as exc:
                self.app.error(f"Failed to delete sidecar file '{sidecar.name}': {exc}")

        if len(deletes) > 0:
            self.app.cache.forget(deletes)

        if self.observer is not None:
            self.observer.wake_up()

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
        itemnames = ', '.join([item.name for item in items])
        self.app.confirm(f"Are you sure you want to delete '{itemnames}'?",
                         'n',
                         lambda: self.run_blocking(self.do_delete, items))

    def do_delete(self, context, items):
        for counter, item in enumerate(items):
            if len(items) > 1 and context is not None:
                context.progress((counter, len(items)))
            if item.is_dir():
                try:
                    shutil.rmtree(item)
                except OSError as exc:
                    self.app.error(f"Failed to delete the folder '{item.name}': {exc}")
            elif item.exists():
                delete_sidecars = False
                try:
                    item.unlink()
                    delete_sidecars = True
                except OSError as exc:
                    self.app.error(f"Failed to delete '{item.name}': {exc}")
                    logger.error("Failed to delete %s: %s", item, exc)

                if delete_sidecars and item.stem not in self.metaindexfilenames:
                    for sidecar, is_collection in self.app.metaindexconf.find_all_sidecar_files(item):
                        if is_collection:
                            # TODO: drop *specific* entries from this file
                            continue
                        try:
                            sidecar.unlink()
                        except OSError as exc:
                            logger.error("Failed to delete sidecar file %s: %s", sidecar, exc)
        if self.observer is not None:
            self.observer.wake_up()

    def rename(self, path, new_name):
        assert path.parent == new_name.parent

        is_sidecar = self.app.metaindexconf.is_sidecar_file(path)
        rename_sidecars = []
        rename_inside_sidecars = []
        if not is_sidecar:
            for sidecar, is_collection in self.app.metaindexconf.find_all_sidecar_files(path):
                if is_collection:
                    rename_inside_sidecars.append(sidecar)
                else:
                    rename_sidecars.append((sidecar,
                                            sidecar.parent / (new_name.stem + sidecar.suffix)))

        for sidecar, new_sidecar in rename_sidecars:
            if new_sidecar.exists():
                self.app.error(f"{new_sidecar.name} already exists. "
                               "Please delete or merge the metadata files yourself.")
                return

        try:
            os.rename(path, new_name)
        except OSError as exc:
            self.app.error(f"Failed to rename: {exc}")
            logger.error(f"Could not rename '{path}' to '{new_name}': {exc}")
            return

        self.app.cache.rename(path, new_name, new_name.is_dir())

        for sidecar, new_sidecar in rename_sidecars:
            try:
                os.rename(sidecar, new_sidecar)
            except OSError as exc:
                self.app.error(f"Failed to rename {sidecar.name}.")
                logger.error(f"Failed to rename {sidecar} to {new_sidecar}: {exc}")

        for sidecar in rename_inside_sidecars:
            metadata = stores.get_for_collection(sidecar, '')
            if path not in metadata:
                continue
            entry = metadata.pop(path)
            metadata[new_name] = entry
            stores.store(stores.as_collection(metadata), sidecar)

        logger.debug("Renamed %s to %s on disk and in cache", path, new_name)

        if self.observer is not None:
            self.observer.wake_up()

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

        if is_selected and self.app.current_panel is self:
            attr |= curses.A_STANDOUT

        attr |= colors.attr((item.fg, item.bg))

        icon = '' if not self.fancy_icons else item.icon + " "

        text = f" {icon}{item.name}"
        if item in self.multi_selection:
            text = self.select_icon + " " + text
            attr |= curses.A_BOLD

        try:
            self.win.addstr(y, x, " "*maxwidth, attr)
        except curses.error:
            pass
        try:
            self.win.addstr(y, x, text[:maxwidth], attr)
        except curses.error:
            pass

        if len(self.info_columns) == 0:
            return
        cut_off = x + 2*maxwidth//3
        for column in range(len(self.info_columns)):
            column = len(self.info_columns) - column - 1
            content = self.info_columns_content[item.path][column]

            ix = x + maxwidth - sum(self.info_columns_width[column:])
            ix += self.info_columns_width[column] - len(content)
            if ix < cut_off:
                break
            try:
                self.win.addstr(y, ix, content, attr)
            except curses.error:
                pass

    def handle_scrolling_key(self, key):
        handled, must_repaint, must_clear = super().handle_scrolling_key(key)
        if handled:
            self.cursor_cache[self.path] = self.cursor
        return handled, must_repaint, must_clear

    def line_matches_find(self, cursor):
        if self.items is None or self.find_text is None:
            return False
        item = self.items[cursor]
        if self.app.configuration.find_is_case_sensitive:
            return self.find_text in item.name
        return self.find_text.lower() in item.name.lower()

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

    def on_focus_lost(self):
        if self.selected_item is not None:
            logger.debug("lost focus, repaint line %s", self.selected_item)
            self.paint_item(self.selected_item)
            self.win.noutrefresh()

    def on_focus(self):
        try:
            here = pathlib.Path.cwd()
        except OSError:
            here = self.path
        if here != self.path:
            os.chdir(self.path)
        if self.items is not None and self.selected_item is not None:
            self.paint_item(self.selected_item)

    def on_close(self):
        logger.debug(f"Closing {self}")
        if self.observer is not None:
            self.observer.close()

    def calculate_info_columns(self):
        self.info_columns_width = [0]*len(self.info_columns)
        self.info_columns_content = {}

        if self.items is None or len(self.items) == 0:
            return

        for item in self.items:
            self.info_columns_content[item.path] = ["?"]*len(self.info_columns)
            for column, content in enumerate(self.info_columns):
                text = '?'
                if content == 'bytes' and item.stat is not None:
                    text = str(item.stat.st_size)
                if content == 'size' and item.stat is not None:
                    text = format_filesize(item.stat.st_size)
                if content == 'owner' and item.stat is not None and pwd is not None:
                    uid = item.stat.st_uid
                    try:
                        text = pwd.getpwuid(uid)[0]
                    except:
                        text = str(uid)
                if content == 'group' and item.stat is not None and grp is not None:
                    gid = item.stat.st_gid
                    try:
                        text = grp.getgrgid(gid)[0]
                    except:
                        text = str(gid)
                if content in ['num_rights', 'octmode'] and item.stat is not None:
                    text = oct(stat.S_IMODE(item.stat.st_mode))[2:]
                if content in ['rights', 'mode'] and item.stat is not None:
                    text = stat.filemode(item.stat.st_mode)
                if content == 'lm_abs' and item.stat is not None:
                    text = format_datetime(datetime.datetime.fromtimestamp(item.stat.st_mtime))
                    if text is None:
                        text = '?'
                if content == 'lm_duration' and item.stat is not None:
                    text = datetime.datetime.now() - \
                           datetime.datetime.fromtimestamp(item.stat.st_mtime)
                    text = duration_as_str(text)
                text = ' ' + text
                self.info_columns_content[item.path][column] = text
        for column in range(len(self.info_columns)):
            widths = {len(c[column])
                      for c in self.info_columns_content.values()}
            self.info_columns_width[column] = max(widths)


def duration_as_str(duration):
    seconds = int(duration.total_seconds())
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    
    result = ''
    if days > 0:
        result += f'{days}d'
    if hours > 0:
        result += f'{hours}h'
    if minutes > 0:
        result += f'{minutes}m'
    if days + hours == 0:
        result += f'{seconds % 60}s'

    return result


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
class ChangeDirectory(command.Command):
    """Change directory"""
    NAME = 'cd'
    ACCEPT_IN = (FilePanel,)

    def completion_options(self, context, *args):
        filepanel = context.application.previous_focus
        if not isinstance(filepanel, FilePanel):
            return []
        basedir = filepanel.path

        if basedir is None:
            return []

        userinput = None
        selected_dir = basedir
        if len(args) > 0 and len(args[0]) > 0:
            userinput = pathlib.Path(args[0])
            if userinput.is_absolute():
                basedir = userinput.parent
            if (basedir / userinput).is_dir():
                selected_dir = basedir / userinput
            else:
                selected_dir = (basedir / userinput).parent

        if selected_dir.is_dir():
            options = []
            for path in sorted(selected_dir.iterdir()):
                if not path.is_dir():
                    continue
                useful = userinput is None or \
                         (basedir / userinput).is_dir() or \
                         userinput.parts[-1] in path.name or \
                         str(userinput) in path.name

                if not useful:
                    continue
                # (userinput is None or userinput.is_dir() or userinput.name in path.name) and
                new_path = path
                if userinput is None or not userinput.is_absolute():
                    new_path = path.relative_to(basedir)
                new_path = str(new_path) + '/'
                options.append(Completion.Suggestion(new_path, path.name))
            return options

        return []

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
        context.panel.reload()
        context.panel.scroll()
        context.panel.paint(True)


@command.registered_command
class ToggleShowSidecarFiles(command.Command):
    """Toggle show sidecar files"""
    NAME = 'toggle-sidecar'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.show_sidecar_files = not context.panel.show_sidecar_files
        context.panel.reload()
        context.panel.scroll()
        context.panel.paint(True)


@command.registered_command
class RenameFile(command.Command):
    """Rename this file or folder"""
    NAME = 'rename'
    ACCEPT_IN = (FilePanel,)

    def execute(self, context, name=None):
        if context.panel.is_busy:
            return

        if name is None:
            context.application.error("Usage: rename new-file-name")
            return

        path = context.panel.selected_path
        new_name = path.parent / name

        if path.parent != new_name.parent:
            context.application.error("Only renaming allowed, no moving")
            return

        if new_name.exists():
            context.application.error("'{name}' already exists here")
            return

        context.panel.rename(path, new_name)


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
            subprocess.run(" ".join(args), shell=True, check=False)
        except (KeyboardInterrupt,):
            pass

        if wait_after_execution:
            scr.timeout(-1)
            scr.addstr("Press return to continue...")
            scr.get_wch()
            scr.timeout(context.application.key_timeout)
    context.application.paint(True)


@command.simple_command('launch', accept_in=(FilePanel,))
def launch_command(context, *args):
    """Launch a command here"""

    if len(args) == 0:
        shell = shutil.which(os.getenv('SHELL') or "")
        if shell is None:
            context.application.error("No SHELL found")
            return
        args = [shell]

    logger.debug(f"Launching in shell: {args}")

    try:
        subprocess.Popen(" ".join(args),
                         shell=True,
                         bufsize=0,
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        pass
