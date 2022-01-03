import curses
import collections
import tempfile
import subprocess

import multidict

from metaindex import shared
import metaindex.cache
import metaindex.indexer

from cursedspace import Key, InputLine, ShellContext

from metaindexmanager import command
from metaindexmanager import utils
from metaindexmanager.utils import logger
from metaindexmanager.panel import ListPanel
from metaindexmanager.detailpanel import DetailPanel
from metaindexmanager.docpanel import DocPanel
from metaindexmanager.filepanel import FilePanel


Change = collections.namedtuple("Change", ['index', 'new_value', 'prefix', 'tag', 'old_value'])
Insert = collections.namedtuple("Insert", ['prefix', 'tag', 'value'])
Delete = collections.namedtuple("Delete", ['index', 'prefix', 'tag', 'value'])
GroupedChange = collections.namedtuple("GroupedChange", ['changes'])

Line = collections.namedtuple("Line", ['group', 'prefix', 'tag', 'value'])
Header = collections.namedtuple("Header", ['group', 'title', 'prefix', 'tag', 'value'], defaults=['', '', ''])


class EditorLine(InputLine):
    def __init__(self, panel, *args, text=None, **kwargs):
        y = panel.pos[0] + panel.cursor - panel.offset + 1
        x = panel.pos[1] + panel.columns[0] + 1
        if text is None:
            text = panel.selected_line.value or ''
        super().__init__(panel.app, panel.columns[1], (y, x), text=text, background='░') # background='░.')

        self.item = panel.selected_line
        self.parent = panel
        self.app.previous_focus = panel
        self.app.current_panel = self
        self.original_text = self.text

        logger.debug(f"Enter tag edit mode for {self.item} (text: '{text}')")

    def handle_key(self, key):
        if key in [Key.ESCAPE, "^C"]:
            self.destroy()

        elif key in [Key.RETURN, "^S"]:
            self.destroy()
            if self.text != self.original_text:
                idx = self.parent.items.index(self.item)
                self.parent.changed(Change(idx, self.text,
                                           self.item.prefix,
                                           self.item.tag,
                                           self.item.value))

        else:
            super().handle_key(key)

    def destroy(self):
        super().destroy()
        self.parent.editor = None
        self.app.current_panel = self.parent
        self.parent.paint_item(self.parent.cursor)


class EditorPanel(ListPanel):
    SCOPE = 'editor'
    SPACING = 3

    CONFIG_ICON_MULTILINE = 'multiline-indicator'
    CONFIG_ICON_CUTOFF = 'cutoff-indicator'

    def __init__(self, filepath, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = filepath
        self.columns = []
        # the history of changes
        self.changes = []
        # the pointer into the history of changes, usually points beyond the end of the list of changes
        self.change_ptr = 0
        # list of items directly after reload
        self.unchanged_items = []
        self.editor = None
        self.metadata = multidict.MultiDict()

        self._multiline_icon = None
        self._cutoff_icon = None
        self.configuration_changed()
        
        self.reload()
        self.cursor = 1

    @property
    def selected_path(self):
        return self.item

    @property
    def selected_paths(self):
        return [self.item]

    @property
    def selected_item(self):
        return str(self.item)

    @property
    def selected_line(self):
        if 0 <= self.cursor < len(self.items):
            return self.items[self.cursor]
        return None

    def open_selected(self):
        if self.item is None:
            return
        self.app.open_file(self.item)

    def changed(self, change):
        logger.debug(f"Added change to stack: {change}")
        self.changes = self.changes[:self.change_ptr]
        self.changes.append(change)
        self.change_ptr = len(self.changes)
        self.rebuild_items()
        self.rebuild_columns()
        self.scroll()
        self.paint(True)

    def paint(self, clear=False):
        super().paint(clear)

        if self.change_ptr > 0:
            self.win.addstr(0, 1, " Modified ")
            self.win.noutrefresh()

    def title(self):
        return str(self.item)

    def focus(self):
        y, x = super().focus()
        if self.editor is not None:
            self.editor.focus()
        else:
            self.win.move(y, x+self.columns[0])
            self.win.noutrefresh()

    def multiline_edit(self):
        logger.debug(f"start multi-line editing {self.selected_line}")
        item = self.selected_line
        if not isinstance(item, Line):
            return
        original = item.value
        new_content = original
        can_edit = item.prefix == 'extra'

        editor = self.app.get_text_editor(True)
        if editor is None:
            return

        with tempfile.NamedTemporaryFile("w+t", encoding="utf-8", suffix='.txt') as fh:
            fh.write(original)
            fh.flush()
            with ShellContext(self.app.screen):
                subprocess.run(editor + [fh.name])
            self.app.paint(True)

            # only actually apply changes when editing the 'extra' tags
            if can_edit:
                fh.flush()
                fh.seek(0)
                new_content = fh.read()
        logger.debug(f"Can change? {can_edit} -- has changes? {new_content != original}")

        if can_edit and new_content != original:
            self.changed(Change(self.cursor, new_content, item.prefix, item.tag, original))

    def start_edit(self, text=None):
        logger.debug(f"start editing {self.selected_line}")
        if self.editor is not None:
            self.editor.destroy()
            del self.editor

        if (text is not None and '\n' in text) or (text is None and '\n' in self.selected_line.value):
            self.multiline_edit()
        else:
            self.editor = EditorLine(self, text=text)
            self.app.paint(True)

    def cancel_edit(self):
        if self.editor is None:
            return
        self.editor.destroy()
        del self.editor
        self.editor = None
        self.paint(True)

    def resize(self, *args):
        super().resize(*args)
        self.rebuild_columns()

    def reset(self):
        self.changes = []
        self.change_ptr = 0
        self.reload()
        self.paint(True)

    def save(self, blocker):
        logger.debug(f"The file is {self.selected_path.name}")
        blocker.title(f"Saving changes to {self.selected_path.name}")

        # Read in the current sidecar file, if it exists
        collection_extra = None
        sidecar_file, is_collection, store = self.app.get_editable_sidecar_file(self.selected_path)

        if sidecar_file is None:
            self.app.error(f"No usable metadata storage available")
            return

        if sidecar_file.exists():
            if is_collection:
                collection_extra = store.get_for_collection(sidecar_file, prefix='')

                collection_extra = utils.collection_meta_as_writable(collection_extra, sidecar_file.parent)
                logger.debug(f"Read collection metadata: {collection_extra}")

                if self.selected_path.name in collection_extra:
                    extra = collection_extra.pop(self.selected_path.name)
                else:
                    extra = multidict.MultiDict()
                logger.debug(f"Extra for {self.selected_path.name} is: {extra}")

            else:
                extra = store.get(sidecar_file, prefix='')
                # remove control data
                extra.popall(shared.IS_RECURSIVE, [])
        else:
            if is_collection:
                collection_extra = multidict.MultiDict()
            extra = multidict.MultiDict()

        # apply all changes to the extra metadata
        for change in self.expand_changes():
            logger.debug(f" ... processing {change}")
            prefix = ''
            if change.prefix != 'extra':
                prefix = change.prefix + '.'

            if isinstance(change, Change):
                values = extra.popall(prefix + change.tag, None)
                if values is None:
                    values = []

                applied = False
                for value in values:
                    if value == change.old_value and not applied:
                        extra.add(prefix + change.tag, change.new_value)
                        applied = True
                    else:
                        extra.add(prefix + change.tag, value)

                if not applied:
                    logger.info(f"Change to {prefix + change.tag} is actually an insert because of different sources")
                    extra.add(prefix + change.tag, change.new_value)

            elif isinstance(change, Insert):
                extra.add(prefix + change.tag, change.value)
            
            elif isinstance(change, Delete):
                values = extra.popall(prefix + change.tag, None)
                if values is None:
                    logger.warning(f"Skipping deletion of {prefix + change.tag}: not found")
                    continue
                if change.value in values:
                    values.remove(change.value)
                for value in values:
                    extra.add(prefix + change.tag, value)

        # 'store' will not remove the 'extra.' prefix per tag,
        # so we have to do that here
        for key in set(extra.keys()):
            if not key.startswith('extra.'):
                continue
            values = extra.popall(key)
            _, key = key.split('.', 1)
            for value in values:
                extra.add(key, value)
        logger.debug(f"Writing new metadata: {extra}")

        # save the extra metadata to the sidecar file
        if is_collection:
            collection_extra[self.selected_path.name] = extra
            logger.debug(f"Updating collection sidecar to {collection_extra}")
            store.store(collection_extra, sidecar_file)
        else:
            store.store(extra, sidecar_file)

        # reload the cache
        with ShellContext(self.app.screen):
            self.app.cache.refresh(self.selected_path)
        self.app.paint(True)

        # reset
        self.reset()

    def reload(self):
        filepath = str(self.item)
        metadata = [entry.metadata for entry in self.app.cache.get(self.item) if entry.path == self.item]

        if len(metadata) == 0:
            self.metadata = multidict.MultiDict({'filename': str(self.selected_path.name)})
        else:
            self.metadata = metadata[0]

        self.rebuild_items()
        self.rebuild_columns()

    def rebuild_columns(self):
        if len(self.items) > 1:
            self.columns = [max([1 if isinstance(row, Header) else len(str(row.tag))+self.SPACING
                                 for row in self.items]), 0]
            self.columns[1] = self.dim[1] - self.columns[0] - 2
        else:
            half_w = self.dim[1]//2
            self.columns = [half_w, self.dim[1] - half_w]

    def rebuild_items(self):
        self.items = []
        self.unchanged_items = []

        if len(self.metadata) == 0:
            self.unchanged_items = []
            self.cursor = 0
            return

        keys = list(set(self.metadata.keys()))
        keys.sort(key=lambda k: [not k.startswith('extra.'), '.' in k, k.lower()])

        # prepare the unchanged items
        for key in keys:
            displaykey = key
            prefix = 'general'
            if '.' in key:
                prefix, displaykey = key.split('.', 1)
            for value in self.metadata.getall(key, []):
                self.unchanged_items.append(Line(prefix, prefix, displaykey, value))

        # apply all changes in order to the point where we are
        self.items = self.unchanged_items[:]
        for change in [None] + self.expand_changes():
            if isinstance(change, Change):
                original = self.items[change.index]
                self.items[change.index] = Line(original.group,
                                                original.prefix,
                                                original.tag,
                                                change.new_value)
            elif isinstance(change, Insert):
                group = change.prefix
                if len(group) == 0:
                    group = 'general'
                self.items.append(Line(group, change.prefix, change.tag, change.value))
            elif isinstance(change, Delete):
                self.items = self.items[:change.index] + self.items[change.index+1:]

            self.items = [i for i in self.items if isinstance(i, Line)]
            self.items += [Header(g, g.title())
                           for g in set([i.group for i in self.items])]

            self.items.sort(key=lambda k: [k.group != 'extra', k.group, isinstance(k, Line), k.tag.lower(), self.app.humanize(k.value).lower()])

    def do_paint_item(self, y, x, maxwidth, is_selected, item):
        if isinstance(item, Header):
            self.win.addstr(y, x, item.title[:self.dim[1]-x-2], curses.A_BOLD)
        else:
            for colidx, text in enumerate([item.tag, item.value]):
                self.win.addstr(y, x, " "*self.columns[colidx])
                maxlen = self.dim[1]-x-2

                if text is None:
                    text = ''
                if colidx == 1 and is_selected and self.editor is not None:
                    self.editor.paint()
                else:
                    # make it a human-readable string
                    text = self.app.humanize(text)

                    # multi-line is special
                    is_multiline = '\r' in text or '\n' in text
                    text = utils.first_line(text)
                    if is_multiline:
                        text += ' ' + self._multiline_icon

                    # shorten the text to visible width
                    shortened = text[:maxlen]

                    if len(shortened) < len(text):
                        icon = self._cutoff_icon
                        if is_multiline:
                            icon = self._multiline_icon
                        shortened = shortened[:-1-len(icon)] + ' ' + icon

                    self.win.addstr(y, x, shortened[:maxlen])
                x += self.columns[colidx]

    def configuration_changed(self, name=None):
        super().configuration_changed(name)

        changed = False

        if name is None or name == self.CONFIG_ICON_MULTILINE:
            new_value = self.app.configuration.get(self.SCOPE, self.CONFIG_ICON_MULTILINE, '…')
            changed = self._multiline_icon != new_value
            self._multiline_icon = new_value

        if name is None or name == self.CONFIG_ICON_CUTOFF:
            new_value = self.app.configuration.get(self.SCOPE, self.CONFIG_ICON_CUTOFF, '→')
            changed = self._multiline_icon != new_value
            self._cutoff_icon = new_value

        if changed:
            if self.win is not None:
                self.scroll()
                self.paint(True)

    def add_tag(self, name):
        if self.editor is not None:
            self.cancel_edit()
        tagname = f'extra.{name}'

        self.changed(Insert('extra', name, ''))

        for nr, item in enumerate(self.items):
            if not isinstance(item, Line):
                continue
            if item.prefix == 'extra' and item.tag == name and item.value == '':
                self.cursor = nr
        self.scroll()

        self.paint(True)

    def remove_tag(self, line):
        if line not in self.items or isinstance(line, str):
            return

        if self.editor is not None:
            self.cancel_edit()

        idx = self.items.index(line)
        self.changed(Delete(idx, line.prefix, line.tag, line.value))

    def undo(self):
        if self.change_ptr <= 0:
            return

        self.change_ptr -= 1
        self.rebuild_items()
        self.rebuild_columns()
        self.scroll()
        self.paint(True)

    def redo(self):
        if self.change_ptr >= len(self.changes):
            return
        self.change_ptr += 1
        self.rebuild_items()
        self.rebuild_columns()
        self.scroll()
        self.paint(True)

    def expand_changes(self):
        if len(self.changes[:self.change_ptr]) == 0:
            return []
        return sum([change.changes if isinstance(change, GroupedChange) else [change]
                    for change in self.changes[:self.change_ptr]], start=[])


@command.registered_command
class EditMetadata(command.Command):
    """Edit metadata of the selected file"""
    NAME = 'edit-metadata'
    ACCEPT_IN = (DocPanel, FilePanel, DetailPanel)

    def execute(self, context):
        if context.panel.is_busy:
            return
        item = context.panel.selected_path

        if not item.is_file():
            context.application.error(f"{item.stem} is not a file")
            return

        panel = EditorPanel(item, context.application)
        context.application.add_panel(panel)
        context.application.activate_panel(panel)


@command.registered_command
class EnterEditMode(command.Command):
    """Start editing the metadata"""
    NAME = 'edit-mode'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        item = context.panel.selected_line

        if not isinstance(item, Line):
            return

        if item.prefix == 'extra' or (isinstance(item.value, str) and ('\n' in item.value or '\r' in item.value)):
            context.panel.start_edit()


@command.simple_command("edit-multiline", (EditorPanel,))
def edit_multiline_command(context):
    target = context.panel
    if target.is_busy:
        return

    context.panel.multiline_edit()


@command.simple_command('add-tag', (EditorPanel,))
def execute(context, name=None):
    """Add a new metadata field"""
    if context.panel.is_busy:
        return
    if name is None:
        context.application.error(f"Usage: add-attr name")
        return

    context.panel.add_tag(name)


@command.registered_command
class AddValueForAttribute(command.Command):
    """Add a new metadata value for this field"""
    NAME = 'add-value'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        item = context.panel.selected_line

        if not isinstance(item, Line) or item.prefix != 'extra':
            return

        context.panel.add_tag(item.tag)


@command.registered_command
class ReplaceValueForAttribute(command.Command):
    """Replace the selected metadata value"""
    NAME = 'replace-value'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        item = context.panel.selected_line

        if not isinstance(item, Line) or item.prefix != 'extra':
            return

        context.panel.start_edit(text='')

@command.registered_command
class RemoveAttribute(command.Command):
    """Remove the selected metadata field"""
    NAME = 'del-tag'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        item = context.panel.selected_line

        if isinstance(item, Header):
            context.application.error(f"Selected field cannot be deleted")
            return
        if item.prefix != 'extra':
            # TODO support the null override of values
            context.application.error(f"Selected field cannot be deleted")
            return
        context.panel.remove_tag(context.panel.selected_line)


@command.registered_command
class ResetEdits(command.Command):
    """Reset all unsaved changes"""
    NAME = 'reset'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.reset()


@command.registered_command
class SaveChanges(command.Command):
    """Save metadata changes"""
    NAME = 'write'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.run_blocking(context.panel.save)
        context.application.paint(True)


@command.registered_command
class UndoChange(command.Command):
    """Undo the previous change"""
    NAME = 'undo-change'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.undo()


@command.registered_command
class RedoChange(command.Command):
    """Redo the next change (i.e. undo the undo)"""
    NAME = 'redo-change'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        context.panel.redo()


@command.registered_command
class UndoAllChanges(command.Command):
    """Undo all changes"""
    NAME = 'undo-all-changes'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return
        if context.panel.change_ptr <= 0:
            return
        context.panel.change_ptr = 1
        context.panel.undo()


@command.simple_command("copy-tag", (EditorPanel,))
def copy_tag_command(context, clipboard=None):
    """Copy the selected tag and value to clipboard"""
    source = context.panel
    if source.is_busy:
        return

    context.application.clear_clipboard(clipboard)

    line = source.selected_line

    if line is None or isinstance(line, Header):
        return

    context.application.append_to_clipboard((line,), clipboard)


@command.simple_command("copy-append-tag", (EditorPanel,))
def copy_append_tag_command(context, clipboard=None):
    """Add the selected tag and value to clipboard"""
    source = context.panel
    if source.is_busy:
        return

    line = source.selected_line

    if line is None or isinstance(line, Header):
        return

    context.application.append_to_clipboard((line,), clipboard)


@command.simple_command("paste-tag", (EditorPanel,))
def paste_tag_command(context, clipboard=None):
    target = context.panel
    if target.is_busy:
        return

    items = [item for item in context.application.get_clipboard_content(clipboard)
             if isinstance(item, (Line,))]
    if len(items) == 0:
        return

    changes = [Insert('extra', line.tag, line.value) for line in items]
    grouped = GroupedChange(changes)
    target.changed(grouped)


@command.registered_command
class RunRules(command.Command):
    """Run tag rules on this document"""
    NAME = 'rules'
    ACCEPT_IN = (EditorPanel,)

    def execute(self, context):
        if context.panel.is_busy:
            return

        if metaindex.indexer.get('rule-based') is None:
            context.application.error("Rule based indexer not found")
            return

        path = context.panel.selected_path
        context.panel.run_blocking(self.run_rules, context, path)
        context.application.paint(True)

    def run_rules(self, blocker, context, path):
        blocker.title(f"Running rules on {path.name}")
        
        item = context.panel.selected_item

        base = context.application.cache.get(path, False)
        if len(base) == 0:
            info = metaindex.cache.Cache.Entry(path)
        else:
            info = base[0]

        fulltext = shared.get_all_fulltext(info.metadata)
        if len(fulltext) == 0:
            # this will also run the rule-based indexer
            logger.debug(f"No fulltext available, running indexer on {path}")
            results = metaindex.indexer.index_files([path],
                                                    1,
                                                    metaindex.ocr.TesseractOCR(True),
                                                    True,
                                                    context.application.metaindexconf)
            if len(results) == 0:
                logger.debug(f"Indexers returned no results")
                return
            _, success, base = results[0]

            info = metaindex.cache.Cache.Entry(path, base, shared.get_last_modified(path))

        else:
            # there is some fulltext, just rerun the rules
            logger.debug(f"Fulltext is already here: {len(fulltext)}")

            cache = metaindex.indexer.IndexerCache(metaindex.ocr.Dummy(),
                                                   False,
                                                   context.application.metaindexconf,
                                                   {},
                                                   info)
            indexer = metaindex.indexer.get('rule-based')(cache)
            success, extra = indexer.run(path, info.metadata.copy(), info)

            if not success:
                logger.debug(f"Indexer did not succeed")
                return
            
            # extend the cached metadata with the newly indexed data
            new_info = False
            for key in set(extra.keys()):
                for value in extra.getall(key):
                    if value in info.metadata.getall(key, []):
                        continue
                    info.metadata.add(key, value)
                    new_info = True

            if not new_info:
                logger.debug("Nothing new here")
                return

        context.application.cache.insert(path, info.metadata)

        context.application.callbacks.put((context.panel,
                                           lambda: context.panel.reload()))

