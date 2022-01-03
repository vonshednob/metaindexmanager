import datetime
import pathlib
import shlex
import curses

from cursedspace import Panel

from metaindexmanager import command
from metaindexmanager import utils
from metaindexmanager.utils import logger
from metaindexmanager.panel import ListPanel


DEFAULT_COLUMNS = "title, filename, tags+, mimetype"


class DocPanel(ListPanel):
    SCOPE = 'documents'
    
    CONFIG_COLUMNS = 'columns'

    def __init__(self, *args, searchterm='', **kwargs):
        super().__init__(*args, **kwargs)
        self.col_widths = []
        self.fieldkeys = []
        self.query = None
        self.post_load = None
        self.results = []

        self.configuration_changed()
        self.search(searchterm)

    @property
    def synonyms(self):
        return self.app.metaindexconf.synonyms

    def title(self):
        return str(self.query)

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

    def make_row(self, result):
        fields = []
        for key in self.fieldkeys:
            multivalue = False
            if key.endswith('+'):
                multivalue = True
                key = key[:-1]

            if key == 'icon':
                values = [utils.get_ls_icon(pathlib.Path(result[0]), {})]
            else:
                values = []
                for expandedkey in set(self.synonyms.get(key, [key])):
                    values += result[1].getall(expandedkey, [])

            if len(values) == 0:
                fields.append("")
            elif len(values) > 1 and multivalue:
                fields.append(', '.join([self.app.humanize(v) for v in values if len(v) > 0]))
            else:
                fields.append(self.app.humanize(values[0]))
            fields[-1] = fields[-1].replace("\n", " ").replace("\r", " ").replace("\t", " ")

        fields.append(result)
        return fields

    def calculate_grid_size(self):
        if self.win is None:
            return
        # calculate the spread of the grid prior to calling super.paint
        maxheight, maxwidth = self.dim
        margin = 0
        if self.border & Panel.BORDER_LEFT != 0:
            margin += 1
        if self.border & Panel.BORDER_RIGHT != 0:
            margin += 1

        if len(self.fieldkeys) == 0:
            self.col_widths = [0]
            return

        # recalculate how wide each column is
        equal_colwidth = (maxwidth - margin)//len(self.fieldkeys)
        self.col_widths = [max([0] + [max(1 if fkey == 'icon' else equal_colwidth,
                                      len(row[fkidx]))+1 for row in self.items])
                           for fkidx, fkey in enumerate(self.fieldkeys)]

        # shrink each column if its wider than the equal_colwidths, start from
        # the last column (it's probably the least important)
        if len(self.col_widths) > 2:
            to_shrink = len(self.col_widths)-1
            while sum(self.col_widths) > maxwidth-margin and to_shrink >= 0:
                self.col_widths[to_shrink] = min(equal_colwidth, self.col_widths[to_shrink])
                to_shrink -= 1
        # expand/shrink the last column to the rest of the available space
        self.col_widths[-1] = maxwidth - margin - sum(self.col_widths[:-1])

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
        assert sum(self.col_widths) < self.dim[1]
        attr = curses.A_STANDOUT if is_selected else curses.A_NORMAL
        self.win.addstr(y, x, " "*maxwidth, attr)
        for column in range(len(self.fieldkeys)):
            if self.col_widths[column] < 2:
                continue
            text = item[column][:self.col_widths[column]]
            if column < len(self.fieldkeys) - 1 and len(text) >= self.col_widths[column]:
                text = text[:-1] + ' '
            assert len(text) + x < self.dim[1]
            try:
                self.win.addstr(y, x, text, attr)
            except:
                pass
            x += self.col_widths[column]

    def jump_to(self, item, path=None):
        if path is None:
            path = self.query

        if path != self.query:
            self.search(path)

        if self.is_busy:
            self.post_load = lambda: self.do_jump_to(item)
            return

        self.do_jump_to(item)

    def do_jump_to(self, item):
        targetitem = str(item)

        for cursor, item in enumerate(self.items):
            if item[-1][0] == targetitem:
                self.cursor = cursor
                break

        self.scroll()
        if not self.is_busy:
            self.paint()

    @property
    def selected_path(self):
        result = self.selected_item
        if result is not None:
            result = pathlib.Path(result[-1][0])
        return result

    @property
    def selected_paths(self):
        return [pathlib.Path(i[-1][0]) for i in self.selected_items]

    def open_selected(self):
        if self.selected_item is None:
            self.app.error("Nothing selected")
            return
        path = pathlib.Path(self.selected_item[-1][0])
        self.app.open_file(path)


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
