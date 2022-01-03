"""Layout definitions"""
from cursedspace import Panel

from metaindexmanager.utils import logger


_registered_layouts = {}


def registered_layout(cls):
    assert issubclass(cls, Layout)
    global _registered_layouts
    assert cls.NAME not in _registered_layouts
    _registered_layouts[cls.NAME] = cls
    return cls


def layouts():
    return list(_registered_layouts.keys())


def get_layout(name):
    """Return the layout by name or None if it doesn't exist"""
    return _registered_layouts.get(name, None)


class Layout:
    def __init__(self, application):
        self.app = application

    def refresh(self, force):
        """Called during Application.refresh"""
        raise NotImplementedError()

    def paint(self, clear=False):
        """Paint all panels on the screen"""
        raise NotImplementedError()

    def resize_panels(self):
        """Resize all panels to fit on the screen"""
        raise NotImplementedError()

    def activated_panel(self, panel):
        """Called after 'panel' has been activated"""
        self.app.paint_focus_bar()

    def is_visible(self, panel):
        """Whether on not this panel is visible"""
        raise NotImplementedError()


@registered_layout
class HorizontalLayout(Layout):
    NAME = 'horizontal'

    def refresh(self, force):
        for panel in self.app.panels:
            panel.refresh(force)

    def resize_panels(self):
        maxheight, maxwidth = self.app.size()
        maxheight -= 2  # border
        posx = 0

        width = maxwidth // len(self.app.panels)
        for panel in self.app.panels:
            panelwidth = width
            if panel is self.app.panels[-1]:
                panelwidth = maxwidth - posx
            panel.border = Panel.BORDER_ALL
            panel.resize(maxheight, panelwidth)
            panel.move(1, posx)
            logger.debug(f"Resized panel {panel} to {maxheight},{panelwidth}")
            posx += width

    def paint(self, clear=False):
        for panel in self.app.panels:
            panel.paint(clear)
            panel.win.refresh()

    def is_visible(self, panel):
        return True


@registered_layout
class TabbedLayout(Layout):
    NAME = 'tabbed'

    def active_panel(self):
        if self.app.current_panel in self.app.panels:
            return self.app.current_panel
        elif self.app.previous_focus in self.app.panels:
            return self.app.previous_focus

        if len(self.app.panels) > 0:
            logger.error(f"Tabbed layout could not determine active panel: current:{self.app.current_panel} prev_focus:{self.app.previous_focus}")
            return self.app.panels[0]
        return None

    def is_visible(self, panel):
        return panel is self.active_panel()

    def refresh(self, force):
        active = self.active_panel()

        if active is not None:
            active.refresh(force)

    def resize_panels(self):
        maxheight, maxwidth = self.app.size()
        maxheight -= 2  # border

        for panel in self.app.panels:
            panel.border = Panel.BORDER_ALL
            panel.resize(maxheight, maxwidth)
            panel.move(1, 0)

    def activated_panel(self, panel):
        self.app.paint(True)

    def paint(self, clear=False):
        activepanel = self.active_panel()

        if activepanel is not None:
            activepanel.paint(clear)
            activepanel.win.refresh()

