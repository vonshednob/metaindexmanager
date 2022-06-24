import curses
import collections
import tempfile
import subprocess

from metaindex import shared
from metaindex.ocr import Dummy, TesseractOCR
from metaindex.humanizer import humanize
from metaindex.shared import DUBLINCORE_TAGS
import metaindex.cache
import metaindex.indexer

from cursedspace import Key, InputLine, ShellContext, Completion, colors

from metaindexmanager import clipboard
from metaindexmanager import command
from metaindexmanager.shared import DICTIONARY_SCOPE
from metaindexmanager.utils import logger, first_line
from metaindexmanager.panel import ListPanel
from metaindexmanager.docpanel import DocPanel
from metaindexmanager.filepanel import FilePanel
from metaindexmanager.detailpanel import DetailPanel


Change = collections.namedtuple("Change", ['index', 'new_value', 'prefix', 'tag', 'old_value'])
Insert = collections.namedtuple("Insert", ['prefix', 'tag', 'value'])
Delete = collections.namedtuple("Delete", ['index', 'prefix', 'tag', 'value'])
GroupedChange = collections.namedtuple("GroupedChange", ['changes'])


class LineBase:
    def __init__(self, group):
        self.group = group

    def comparator(self):
        return [self.group != shared.EXTRA[:-1],
                self.group]

    def __lt__(self, other):
        return self.comparator() < other.comparator()


class Header(LineBase):
    @property
    def title(self):
        return self.group.title()

class Line(LineBase):
    def __init__(self, group, prefix, tag, value):
        super().__init__(group)
        self.prefix = prefix
        self.tag = tag
        self.value = value

    def comparator(self):
        return super().comparator() + [self.tag.lower(), str(self.value).lower()]


class EditorLineCompletion(Completion):
    COLOR = colors.BLUE

    def __init__(self, editorline, words):
        super().__init__(editorline)
        self.words = words

    def update(self, y, x):
        text = self.inputline.text[:self.inputline.cursor]
        if text.endswith(' '):
            text = ''
        else:
            text = text.split(' ')[-1]

        options = [word
                   for word in sorted(self.words, key=lambda a: str(a))
                   if str(word).startswith(text)]
        if len(options) == 1 and str(options[0]) == text:
            # only available option typed out
            self.close()
            self.app.paint()
        elif len(options) > 0:
            # there are options? show them
            self.set_alternatives(options, (y, x))
            self.app.paint()
        elif self.is_visible:
            # no options, but the box is still visible? close it
            self.close()
            self.app.paint()

    def handle_key(self, key):
        result = super().handle_key(key)
        if result and self.suggestions is None:
            self.inputline.paint(True)
        return result


class EditorLine(InputLine):
    def __init__(self, panel, text=None, suggestions=None):
        if text is None:
            text = panel.app.as_printable(panel.selected_line.value, None)
        super().__init__(panel.app,
                         panel.columns[1],
                         (1, 1),
                         text=text,
                         background='░')

        self.item = panel.selected_line
        self.parent = panel
        self.app.previous_focus = panel
        self.app.current_panel = self
        self.original_text = self.text

        self.reposition()

        if suggestions is not None and len(suggestions) > 0:
            self.completion = EditorLineCompletion(self, suggestions)

        logger.debug(f"Enter tag edit mode for {self.item} (text: '{text}')")

    def reposition(self):
        y, x, _, _ = self.parent.content_area()
        y += self.parent.pos[0] + self.parent.cursor - self.parent.offset
        x += self.parent.pos[1] + self.parent.columns[0]
        self.move(y, x)

    def handle_key(self, key):
        if key in [Key.TAB, "^N"] and \
           (self.completion is None or not self.completion.is_visible):
            self.update_completion()

        elif self.completion is not None and \
             self.completion.is_visible and \
             self.completion.handle_key(key):
            pass

        elif key in [Key.ESCAPE, "^C"]:
            self.destroy()

        elif key in [Key.RETURN, "^S"]:
            self.destroy()
            if self.text != self.original_text:
                idx = self.parent.items.index(self.item)
                humanized = humanize(self.item.prefix + '.' + self.item.tag,
                                     self.text)
                self.parent.changed(Change(idx,
                                           shared.MetadataValue(self.text, humanized),
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
    """Metadata editing panel"""
    SCOPE = 'editor'
    SPACING = 3

    CONFIG_ICON_MULTILINE = 'multiline-indicator'
    CONFIG_ICON_CUTOFF = 'cutoff-indicator'
    CONFIG_NO_COMPLETION = 'no-completion'
    CONFIG_TAGS = 'tags'
    CONFIG_TAGS_DEFAULT = ','.join({'*'} | DUBLINCORE_TAGS)

    def __init__(self, filepath, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = filepath
        self.columns = []
        # the history of changes
        self.changes = []
        # the pointer into the history of changes,
        # usually points beyond the end of the list of changes
        self.change_ptr = 0
        # list of items directly after reload
        self.unchanged_items = []
        self.editor = None
        self.metadata = shared.CacheEntry(filepath)

        self.auto_index_if_not_in_cache = True

        self._multiline_icon = ' '
        self._cutoff_icon = ' '
        self.suggested_tags = set()
        self._no_completion = set()
        self.configuration_changed()

        self.reload()
        # signal to self.paint() that we have to recalculate the columns,
        # as the panel will not have the correct size just now
        self.columns = [0, 0]
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
    def selected_items(self):
        if len(self.multi_selection) == 0:
            line = self.selected_line
            if isinstance(line, Line):
                return [line]
            return []
        return self.multi_selection

    @property
    def selected_line(self):
        if 0 <= self.cursor < len(self.items):
            return self.items[self.cursor]
        return None

    def on_copy(self, item):
        return clipboard.ClipboardItem(item, self)

    def on_paste(self, items, behaviour):
        if self.is_busy:
            raise RuntimeError("Cannot paste right now, editor is busy")

        # TODO - make use of the 'behaviour' flag
        changes = [Insert(shared.EXTRA[:-1], item.data.tag, item.data.value)
                   for item in items if isinstance(item.data, Line)]
        if len(changes) == 0:
            raise RuntimeError("Cannot paste this here")

        grouped = GroupedChange(changes)
        self.changed(grouped)

    def open_selected(self):
        if self.item is None:
            return
        self.app.open_file(self.item)

    def open_selected_with(self, cmd):
        if self.item is None:
            return
        self.app.open_with(self.item, cmd)

    def changed(self, change):
        logger.debug(f"Added change to stack: {change}")
        self.changes = self.changes[:self.change_ptr]
        self.changes.append(change)
        self.change_ptr = len(self.changes)
        self.rebuild_items()
        self.rebuild_columns()
        self.scroll()
        self.paint(True)
        self.app.paint_focus_bar()

    def paint(self, clear=False):
        if self.columns == [0, 0]:
            self.rebuild_columns()
        super().paint(clear)

        if self.change_ptr > 0 and (self.border & self.BORDER_TOP) > 0:
            self.win.addstr(0, 1, " Modified ")
            self.win.noutrefresh()

    def title(self):
        title = str(self.item)
        if self.change_ptr > 0:
            title = "[Modified] " + title
        return title

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
        can_edit = item.prefix == shared.EXTRA[:-1]

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
                humanized = humanize(item.prefix + '.' + item.tag, new_content)
                new_content = shared.MetadataValue(new_content, humanized)
        logger.debug(f"Can change? {can_edit} -- has changes? {new_content != original}")

        if can_edit and new_content != original:
            self.changed(Change(self.cursor, new_content, item.prefix, item.tag, original))

    def start_edit(self, text=None):
        if self.selected_line is None:
            return

        logger.debug(f"start editing {self.selected_line}")
        if self.editor is not None:
            self.editor.destroy()
            del self.editor

        if (text is not None and '\n' in text) or \
           (text is None and '\n' in str(self.selected_line.value.raw_value)):
            self.multiline_edit()
        else:
            self._create_editor(text)
            self.app.paint(True)

    def _create_editor(self, text):
        if self.selected_line is None:
            return
        words = None
        if self.selected_line.tag not in self._no_completion:
            tag = self.selected_line.prefix + "." + self.selected_line.tag
            words = set(self.app.configuration.list(DICTIONARY_SCOPE,
                                                    self.selected_line.tag,
                                                    ''))
            use_all_values = len(words) == 0
            if len(words) > 0:
                if '*' in words:
                    use_all_values = True
                    words.remove('*')
            if use_all_values:
                words |= set(sum([[str(v.raw_value) for v in result[tag]]
                                  for result in self.app.cache.find(tag + "?")],
                                 start=[]))
        self.editor = EditorLine(self,
                                 text=text,
                                 suggestions=words)

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
        self.scroll()
        if self.editor is not None:
            self.editor.resize(self.columns[1])

    def move(self, *args):
        super().move(*args)
        if self.editor is not None:
            self.editor.reposition()

    def reset(self):
        self.changes = []
        self.change_ptr = 0
        self.reload()
        self.paint(True)

    def save(self, blocker):
        logger.debug(f"The file is {self.selected_path.name}")
        if blocker is not None:
            blocker.title(f"Saving changes to {self.selected_path.name}")

        self._apply_changes_to(self.selected_path)

        # reload the cache
        with ShellContext(self.app.screen):
            self.app.cache.refresh(self.selected_path)
            self.app.cache.wait_for_reload()
        self.app.paint(True)

        # reset
        self.reset()

    def _apply_changes_to(self, targetfile):
        # Read in the current sidecar file, if it exists
        collection_extra = None
        sidecar_file, is_collection, store = \
            self.app.metaindexconf.resolve_sidecar_for(targetfile)

        if sidecar_file is None:
            self.app.error("No usable metadata storage available")
            return

        if sidecar_file.exists():
            if is_collection:
                collection_extra = store.get_for_collection(sidecar_file)

                logger.debug("Read collection metadata: %s", collection_extra)

                if self.selected_path in collection_extra:
                    extra = collection_extra.pop(targetfile)
                    del extra[shared.IS_RECURSIVE]
                else:
                    extra = shared.CacheEntry(self.selected_path)
                logger.debug("Extra for %s is: %s", targetfile.name, extra)

            else:
                logger.debug(" ... reading metadata from %s", sidecar_file)
                extra = store.get(sidecar_file)
                extra.path = targetfile
                # remove control data
                del extra[shared.IS_RECURSIVE]
        else:
            logger.debug(" ... no sidecar file there yet")
            if is_collection:
                collection_extra = {}
            extra = shared.CacheEntry(targetfile)

        logger.debug(f" ... {extra.metadata}")

        # apply all changes to the extra metadata
        for change in self.expand_changes():
            logger.debug(f" ... processing {change}")
            prefix = shared.EXTRA
            if change.prefix != prefix[:-1]:
                prefix = change.prefix + '.'

            if isinstance(change, Change):
                values = extra.pop(prefix + change.tag)

                applied = False
                for value in values:
                    if value == change.old_value and not applied:
                        extra.add(prefix + change.tag, change.new_value)
                        applied = True
                    else:
                        extra.add(prefix + change.tag, value)

                if not applied:
                    logger.info("Change to %s is actually an insert because of different sources",
                                prefix+change.tag)
                    extra.add(prefix + change.tag, change.new_value)

            elif isinstance(change, Insert):
                extra.add(prefix + change.tag, change.value)

            elif isinstance(change, Delete):
                values = extra.pop(prefix + change.tag)
                if len(values) == 0:
                    logger.warning(f"Skipping deletion of {prefix + change.tag}: not found")
                    continue
                if change.value in values:
                    values.remove(change.value)
                for value in values:
                    extra.add(prefix + change.tag, value)

        # 'store' will not remove the 'extra.' prefix per tag,
        # so we have to do that here
        logger.debug("Writing new metadata: %s to %s",
                     extra.metadata, sidecar_file)

        # save the extra metadata to the sidecar file
        if is_collection:
            assert collection_extra is not None
            collection_extra[targetfile.name] = extra
            logger.debug(f"Updating collection sidecar to {collection_extra}")
            logger.debug("%s", extra.metadata)
            store.store(list(collection_extra.values()), sidecar_file)
        else:
            store.store(extra, sidecar_file)

    def reload(self):
        logger.debug("Reloading %s", self.item)

        metadata = [entry
                    for entry in self.app.cache.get(self.item)
                    if entry.path == self.item]

        if len(metadata) == 0 and self.auto_index_if_not_in_cache:
            self.auto_index_if_not_in_cache = False
            index_cmd = command.resolve_command('index')
            if index_cmd is not None:
                self.run_blocking(index_cmd.run_indexers, self.app, self, self.item)
                return

        if len(metadata) == 0:
            self.metadata = shared.CacheEntry(self.item)
        else:
            self.metadata = metadata[0]

        logger.debug("Reload: %s (%s)", self.metadata.keys(), self.app.cache)

        self.rebuild_items()
        self.rebuild_columns()

    def rebuild_columns(self):
        if len(self.items) > 1:
            labelwidth = max([len(str(row.tag)) + self.SPACING
                              for row in self.items
                              if not isinstance(row, Header)])
            labelwidth = min(labelwidth, self.dim[1]//3)
            self.columns = [labelwidth,
                            self.dim[1] - labelwidth - 2]
        else:
            labelwidth = self.dim[1]//3
            self.columns = [labelwidth, self.dim[1] - labelwidth - 2]
        logger.debug(f"maxwidth: {self.dim[1]}, columns: {self.columns}")

    def rebuild_items(self):
        self.items = []
        self.unchanged_items = []

        if len(self.metadata) == 0:
            self.cursor = 0
            return

        keys = list(set(self.metadata.keys()))
        keys.sort(key=lambda k: [not k.startswith(shared.EXTRA), '.' in k, k.lower()])
        logger.debug("editor uses these keys: %s", keys)

        # prepare the unchanged items
        for key in keys:
            displaykey = key
            prefix = 'general'
            if '.' in key:
                prefix, displaykey = key.split('.', 1)
            for value in self.metadata[key]:
                logger.debug(" ... adding %s: %s", key, value)
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
            self.items += [Header(g)
                           for g in {i.group for i in self.items}]

            self.items.sort()

    def do_paint_item(self, y, x, maxwidth, is_selected, item):
        if isinstance(item, Header):
            self.win.addstr(y, x, " "*(self.content_area()[3]-1))
            self.win.addstr(y, x, item.title[:self.columns[0]], curses.A_BOLD)
        else:
            for colidx, text in enumerate([item.tag, item.value]):
                self.win.addstr(y, x, " "*self.columns[colidx])
                # maxlen = self.dim[1]-x-2
                maxlen = self.columns[colidx]
                if colidx == 0:
                    maxlen -= self.SPACING

                if text is None:
                    text = ''
                if colidx == 1 and is_selected and self.editor is not None:
                    self.editor.paint()
                else:
                    # make it a human-readable string
                    text = self.app.as_printable(text)

                    # multi-line is special
                    is_multiline = '\r' in text or '\n' in text
                    text = first_line(text)
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
            new_value = self.app.configuration.get(self.SCOPE,
                                                   self.CONFIG_ICON_MULTILINE,
                                                   '…')
            changed = self._multiline_icon != new_value
            self._multiline_icon = new_value

        if name is None or name == self.CONFIG_ICON_CUTOFF:
            new_value = self.app.configuration.get(self.SCOPE,
                                                   self.CONFIG_ICON_CUTOFF,
                                                   '→')
            changed = self._multiline_icon != new_value
            self._cutoff_icon = new_value

        if name is None or name == self.CONFIG_NO_COMPLETION:
            new_value = self.app.configuration.list(self.SCOPE,
                                                    self.CONFIG_NO_COMPLETION,
                                                    'title')
            self._no_completion = set(new_value)

        if name is None or name == self.CONFIG_TAGS:
            new_values = set(self.app.configuration.list(self.SCOPE,
                                                         self.CONFIG_TAGS,
                                                         self.CONFIG_TAGS_DEFAULT))
            self.suggested_tags = new_values

        if changed:
            if self.win is not None:
                self.scroll()
                self.paint(True)

    def add_tag(self, name):
        if self.editor is not None:
            self.cancel_edit()

        self.changed(Insert(shared.EXTRA[:-1], name, shared.MetadataValue('')))

        for nr, item in enumerate(self.items):
            if not isinstance(item, Line):
                continue
            if item.prefix == shared.EXTRA[:-1] and item.tag == name and item.value == '':
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

        text = str(item.value.raw_value)
        if item.prefix == shared.EXTRA[:-1] or \
           ('\n' in text or '\r' in text):
            context.panel.start_edit()


@command.simple_command("edit-multiline", (EditorPanel,))
def edit_multiline_command(context):
    """Edit the tag value in an external editor"""
    target = context.panel
    if target.is_busy:
        return

    context.panel.multiline_edit()


@command.registered_command
class AddTagCommand(command.Command):
    """Add a new metadata field"""
    NAME = 'add-tag'
    ACCEPT_IN = (EditorPanel,)

    def completion_options(self, context, *args):
        text = "" if len(args) == 0 else args[0]
        keys = context.application.previous_focus.suggested_tags.copy()
        if '*' in keys:
            keys.remove('*')
            keys |= {key.split('.', 1)[1]
                     for key in context.application.cache.keys()
                     if key.startswith(shared.EXTRA)}
        return list(key for key in sorted(keys) if key.startswith(text))

    def execute(self, context, name=None):
        if context.panel.is_busy:
            return
        if name is None:
            context.application.error("Usage: add-attr name")
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

        if not isinstance(item, Line) or item.prefix != shared.EXTRA[:-1]:
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

        if not isinstance(item, Line) or item.prefix != shared.EXTRA[:-1]:
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
            context.application.error("Selected field cannot be deleted")
            return
        if item.prefix != shared.EXTRA[:-1]:
            # TODO support the null override of values
            context.application.error("Selected field cannot be deleted")
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

        base = context.application.cache.get(path, False)
        if len(base) == 0:
            info = shared.CacheEntry(path)
        else:
            info = base[0]

        fulltext = shared.get_all_fulltext(info.metadata)
        if len(fulltext) == 0:
            # this will also run the rule-based indexer
            logger.debug(f"No fulltext available, running indexer on {path}")
            results = metaindex.indexer.index_files([path],
                                                    1,
                                                    TesseractOCR(True),
                                                    True,
                                                    context.application.metaindexconf)
            if len(results) == 0:
                logger.debug("Indexers returned no results")
                return
            info = results[0].info
            info.ensure_last_modified()

        else:
            # there is some fulltext, just rerun the rules
            logger.debug(f"Fulltext is already here: {len(fulltext)}")

            runner = metaindex.indexer.IndexerRunner(context.application.metaindexconf,
                                                     ocr=Dummy(),
                                                     fulltext=False,
                                                     base_info=info)
            indexer = runner.get('rule-based')
            result = indexer.run(path, info.copy(), info)

            if not result.success:
                logger.debug("Indexer did not succeed")
                return

            # extend the cached metadata with the newly indexed data
            new_info = False
            for key in set(result.info.keys()):
                for value in result.info[key]:
                    if value in info[key]:
                        continue
                    info.add(key, value)
                    new_info = True

            if not new_info:
                logger.debug("Nothing new here")
                return

        context.application.cache.insert(info)

        context.application.callbacks.put((context.panel,
                                           context.panel.reload))
