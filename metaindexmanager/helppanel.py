"""Help panel to show all existing keybindings and unbound commands"""

from metaindexmanager import command
from metaindexmanager import shared
from metaindexmanager import panel


@panel.register
class HelpPanel(panel.ListPanel):
    def __init__(self, application, *args, **kwargs):
        super().__init__(application, *args, **kwargs)
        self.build_items()

    def title(self):
        return "Help"

    def build_items(self):
        """Just build the entire help screen"""
        self.items = [ "METAINDEXMANAGER HELP", "", "", "General Commands", ""] \
                   + self._build_scope(shared.ANY_SCOPE) \
                   + [""]

        for scope, paneltype in panel._registered_panels.items():
            name = paneltype.__doc__
            if name is None or len(name) == 0:
                name = paneltype.__name__
            else:
                name = name.split('\n')[0]
            rows = self._build_scope(scope)
            if len(rows) > 0:
                self.items += ["", "", name, ""] + rows

    def _build_scope(self, scope):
        rows = []
        column_widths = [0, 0, 0]
        candidates = [(visualise_keys(keys),
                       cmd[0].lstrip(':').split(' ')[0],
                       None if len(cmd) == 1 else cmd[-1])
                      for iscope, keys, cmd in self.app.keys
                      if iscope == scope]
        candidates += [('', cmd.NAME, None)
                       for cmd in sorted(command._registered_commands.values(),
                                         key=lambda c: c.NAME)
                       if scope in cmd.scopes() and
                          cmd.NAME not in [n for _, n, _ in candidates]]
        for keys, cmdname, helptext in candidates:
            docstr = command.resolve_command(cmdname)
            if docstr is None:
                continue
            if helptext is None:
                docstr = docstr.__doc__.split("\n")[0]
            else:
                docstr = helptext
            rows.append([keys, cmdname, docstr])
            column_widths = [max(column_widths[0], len(keys)),
                             max(column_widths[1], len(cmdname)),
                             max(column_widths[2], len(docstr))]
        return [" ".join([f"{row[i]:<{column_widths[i]}}"
                          for i in range(len(column_widths))])
                for row in rows]


def visualise_keys(keys):
    text = ""
    for k in keys:
        if k == ' ':
            text += '<space>'
        elif k in '\n\r':
            text += '<return>'
        else:
            text += k
    return text


@command.simple_command('help')
def show_help_command(context):
    """Show the help"""
    panel = HelpPanel(context.application)
    context.application.add_panel(panel)
    context.application.activate_panel(panel)
