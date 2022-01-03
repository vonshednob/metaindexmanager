import curses

from metaindexmanager import command
from metaindexmanager.utils import logger
from metaindexmanager.panel import ListPanel
from metaindexmanager.docpanel import DocPanel
from metaindexmanager.filepanel import FilePanel


class DetailPanel(ListPanel):
    META_TAG_ORDER = {'title': 10,
                      'series': 11,
                      'series_index': 12,
                      'author': 20,
                      'tags': 30,
                      'subject': 30,
                      'contributors': 40,
                      'language': 50,
                      'type': 60,
                      'filename': 100,
                      'mimetype': 100,
                      'last_modified': 200,
                      }

    def __init__(self, filepath, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filepath = filepath

        self.rev_synonyms = {}
        self.synonyms = self.app.metaindexconf.synonyms
        for key, names in self.synonyms.items():
            for name in names:
                if name not in self.rev_synonyms:
                    self.rev_synonyms[name] = []
                self.rev_synonyms[name].append(key)

        self.reload()

    def title(self):
        return str(self.filepath)

    @property
    def selected_path(self):
        return self.filepath

    @property
    def selected_paths(self):
        return [self.selected_path]

    def reload(self):
        self.items = []
        metadata = [entry.metadata for entry in self.app.cache.get(self.filepath) if entry.path == self.filepath]

        if len(metadata) == 0:
            return
        metadata = metadata[0]

        keys = set(metadata.keys())
        keys = list(keys | set(sum([synonyms for key, synonyms in self.rev_synonyms.items()
                                             if key in metadata.keys()], start=[])))
        keys.sort(key=lambda k: [DetailPanel.META_TAG_ORDER.get(k, 999), '.' in k, k.lower()])

        prefix = ''
        self.items.append(('General', curses.A_BOLD))
        for key in keys:
            displaykey = key
            if '.' in key:
                keyprefix, displaykey = key.split('.', 1)
                if keyprefix != prefix:
                    prefix = keyprefix
                    self.items.append(("", curses.A_NORMAL))
                    self.items.append((prefix.title(), curses.A_BOLD))
            self.items.append((displaykey.title(), curses.A_NORMAL))

            expanded = self.synonyms.get(key, [key])
            for expkey in expanded:
                for value in metadata.getall(expkey, []):
                    self.items.append((" "*3 + self.app.humanize(value), curses.A_NORMAL))

    def do_paint_item(self, y, x, maxwidth, is_selected, item):
        text, attr = item
        self.win.addstr(y, x, " "*maxwidth)
        self.win.addstr(y, x, text[:maxwidth], attr)


@command.registered_command
class ShowDetails(command.Command):
    """Show all (metadata) details of the selected file"""
    NAME = 'details'
    ACCEPT_IN = (DocPanel, FilePanel)

    def execute(self, context):
        item = context.panel.selected_path

        panel = DetailPanel(item, context.application)
        context.application.add_panel(panel)
        context.application.activate_panel(panel)

