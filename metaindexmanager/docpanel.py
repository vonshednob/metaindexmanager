import pathlib
import shlex
import curses

from cursedspace import Panel

from metaindexmanager import command
from metaindexmanager import utils
from metaindexmanager import clipboard
from metaindexmanager.utils import logger
from metaindexmanager.panel import ListPanel, register


DEFAULT_COLUMNS = "title filename tags+ mimetype"


@register
class DocPanel(ListPanel):
    SCOPE = 'documents'

    CONFIG_COLUMNS = 'columns'

    def __init__(self, application, searchterm=''):
        super().__init__(application)
        self.col_widths = []
        self.fieldkeys = []
        self.query = None
        self.post_load = None
        self.results = []

        self.configuration_changed()
        self.search(searchterm)

        self.show_overflow_error = False

    @property
    def synonyms(self):
        return self.app.metaindexconf.synonyms

    def title(self):
        if self.query is None or len(self.query.strip()) == 0:
            return '(all documents)'
        return str(self.query)

    def on_focus(self):
        if self.selected_item is not None:
            self.paint_item(self.selected_item)

    def on_focus_lost(self):
        if self.selected_item is not None:
            self.paint_item(self.selected_item)
            self.win.noutrefresh()

    def on_copy(self, item):
        if self.is_busy:
            raise RuntimeError("Cannot copy right now: busy")
        return clipboard.ClipboardItem(item[-1].path, self)

    def configuration_changed(self, name=None):
        super().configuration_changed(name)

        changed = False

        if name is None or name == self.CONFIG_COLUMNS:
            keys = self.app.configuration.list(self.SCOPE,
                                               self.CONFIG_COLUMNS,
                                               DEFAULT_COLUMNS,
                                               separator=' ')

            changed = self.fieldkeys != keys
            self.fieldkeys = keys

        if changed:
            self.rebuild_items()
            self.calculate_grid_size()
            if self.win is not None:
                self.scroll()
                self.paint(True)

    def search(self, query):
        logger.debug(f"DocPanel: search for {query}")
        self.query = query
        self.run_in_background(self.do_search)

    def do_search(self):
        if not self.app.cache.is_initialized:
            self.app.cache.wait_for_reload()
        self.results = list(self.app.cache.find(self.query))
        self.cursor = 0
        self.rebuild_items()
        self.calculate_grid_size()
        if self.post_load is not None:
            self.post_load()
            self.post_load = None
        self.app.callbacks.put((self, lambda: True))

    def rebuild_items(self):
        self.items = [self.make_row(result) for result in self.results]
        self.items = [item for item in self.items if sum([len(field) for field in item[:-1]]) > 0]
        self.items.sort(key=lambda i: [len(i[0]) == 0] + [v.lower() for v in i[:-1]])

    def make_row(self, entry):
        fields = []
        logger.debug("make_row %s", entry.metadata)
        for key in self.fieldkeys:
            multivalue = False
            if key.endswith('+'):
                multivalue = True
                key = key[:-1]

            if key == 'icon':
                # the '{}' parameter prevents that path.stat() is being called,
                # speeding up the display by a lot
                values = [utils.get_ls_icon(pathlib.Path(entry.path), {})]
            else:
                values = []
                for expandedkey in set(self.synonyms.get(key, [key])):
                    values += [self.app.as_printable(v)
                               for v in entry[expandedkey]]

            if len(values) == 0:
                fields.append("")
            elif len(values) > 1 and multivalue:
                fields.append(', '.join([v for v in values if len(v) > 0]))
            else:
                fields.append(values[0])
            fields[-1] = fields[-1].replace("\n", " ").replace("\r", " ").replace("\t", " ")

        fields.append(entry)
        return fields

    def calculate_grid_size(self):
        if self.win is None:
            return
        # calculate the spread of the grid prior to calling super.paint
        _, _, _, maxwidth = self.content_area()

        if len(self.fieldkeys) == 0:
            self.col_widths = [0]
            return

        # recalculate how wide each column is
        equal_colwidth = maxwidth//len(self.fieldkeys)
        self.col_widths = [max([0] + [max(1 if fkey == 'icon' else equal_colwidth,
                                      len(row[fkidx]))+1 for row in self.items])
                           for fkidx, fkey in enumerate(self.fieldkeys)]

        # shrink each column if its wider than the equal_colwidths, start from
        # the last column (it's probably the least important)
        if len(self.col_widths) > 2:
            to_shrink = len(self.col_widths)-1
            while sum(self.col_widths) > maxwidth and to_shrink >= 0:
                self.col_widths[to_shrink] = min(equal_colwidth, self.col_widths[to_shrink])
                to_shrink -= 1
        # expand/shrink the last column to the rest of the available space
        self.col_widths[-1] = maxwidth - sum(self.col_widths[:-1])

        assert sum(self.col_widths) <= maxwidth
        logger.debug("Resized columns: %s (maxwidth: %s)",
                     self.col_widths, maxwidth)

    def resize(self, *args):
        super().resize(*args)
        self.calculate_grid_size()

    def paint(self, clear=False):
        if self.is_busy:
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
        attr = curses.A_STANDOUT \
               if is_selected and self.app.current_panel is self \
               else curses.A_NORMAL

        # clean up
        try:
            self.win.addstr(y, x, " "*maxwidth, attr)
        except curses.error:
            pass

        # paint value per column
        for column in range(len(self.fieldkeys)):
            if self.col_widths[column] < 2:
                continue
            text = item[column]
            if column == 0 and item in self.multi_selection:
                text = '✔ ' + text
            text = text[:self.col_widths[column]]
            if column < len(self.fieldkeys) - 1 and len(text) >= self.col_widths[column]:
                text = text[:-1] + ' '
            if len(text) + x > maxwidth:
                text = text[:maxwidth-x]
                if self.show_overflow_error:
                    self.show_overflow_error = False
                    logger.error("text of size %s (offset %s) does not fit "
                                 "in column %s (%s) with maxwidth %s",
                                 len(text), x, column, self.col_widths, maxwidth)
            try:
                self.win.addstr(y, x, text, attr)
            except curses.error:
                pass
            x += self.col_widths[column]

    def display_text(self, item):
        """Returns an array of all columns that should be displayed for this item"""
        return [item[column] for column in range(len(self.fieldkeys))]

    def line_matches_find(self, cursor):
        if self.items is None or self.find_text is None:
            return False
        item = self.items[cursor]
        texts = self.display_text(item)
        if self.app.configuration.find_is_case_sensitive:
            return any(self.find_text in text for text in texts)
        return any(self.find_text.lower() in text.lower() for text in texts)

    def jump_to(self, item, path=None):
        if path is None:
            path = self.query

        if path != self.query:
            self.search(path)

        if self.is_busy:
            logger.debug("postponing jump to %s", item)
            self.post_load = lambda: self.do_jump_to(item)
            return

        self.do_jump_to(item)

    def do_jump_to(self, item):
        targetitem = str(item)

        for cursor, rowitem in enumerate(self.items):
            if str(rowitem[-1].path) == targetitem:
                self.cursor = cursor
                break

        self.scroll()
        if not self.is_busy:
            self.paint()

    @property
    def selected_path(self):
        result = self.selected_item
        if result is not None:
            result = pathlib.Path(result[-1].path)
        return result

    @property
    def selected_paths(self):
        return [pathlib.Path(i[-1].path)
                for i in self.selected_items
                if i is not None]

    def open_selected(self):
        if self.selected_item is None:
            self.app.error("Nothing selected")
            return
        path = pathlib.Path(self.selected_item[-1].path)
        if path.is_file():
            self.app.open_file(path)
        else:
            self.app.error(f"File '{path}' not found")

    def open_selected_with(self, cmd):
        if self.selected_item is None:
            self.app.error("Nothing selected")
            return
        path = pathlib.Path(self.selected_item[-1].path)
        if path.is_file():
            self.app.open_with(path, cmd)
        else:
            self.app.error(f"File '{path}' not found")


@command.registered_command
class NewMetaPanel(command.Command):
    """Create a new metadata panel"""
    NAME = 'new-documents-panel'

    def execute(self, context):
        if context.panel.is_busy:
            return

        panel = DocPanel(context.application)
        context.application.add_panel(panel)
        context.application.activate_panel(panel)


@command.registered_command
class Search(command.Command):
    """Search documents with this metaindex search term"""
    NAME = 'search'
    ACCEPT_IN = (DocPanel,)

    def execute(self, context, *args):
        if context.panel.is_busy:
            return

        term = shlex.join(args)
        context.panel.search(term)
        context.panel.paint(clear=True)
        context.application.paint_focus_bar()


@command.registered_command
class SetColumns(command.Command):
    """Set the columns of this panel"""
    NAME = 'columns'
    ACCEPT_IN = (DocPanel,)

    def execute(self, context, *args):
        if len(args) == 0:
            context.application.info(f"columns = {' '.join(context.panel.fieldkeys)}")
            return

        if context.panel.is_busy:
            return

        context.panel.fieldkeys = args
        context.panel.rebuild_items()
        if context.panel.cursor >= len(context.panel.items):
            context.panel.cursor = len(context.panel.items)-1
        if context.panel.win is not None:
            context.panel.calculate_grid_size()
            context.panel.scroll()
            context.panel.paint(True)
