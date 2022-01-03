import threading
import curses

from cursedspace import ScrollPanel, Key

from metaindexmanager.utils import logger


NEXT_ITEM = 'next-item'
PREV_ITEM = 'previous-item'
NEXT_PAGE = 'next-page'
PREV_PAGE = 'previous-page'
TO_START = 'go-to-start'
TO_END = 'go-to-end'
LIST_SCROLL_COMMANDS = [
    NEXT_ITEM,
    PREV_ITEM,
    NEXT_PAGE,
    PREV_PAGE,
    TO_START,
    TO_END,
]

OPTION_PAGING = 'paging'
OPTION_SCROLL_MARGIN = 'scroll-margin'


class BlockingTask(ScrollPanel):
    INDICATOR_1 = '-\\|/'
    # INDICATOR_2 = '.oOo'
    INDICATOR_2 = '▂▃▄▅▆▇▆▅▄▃▂'

    def __init__(self, app):
        super().__init__(app)
        self.border = ScrollPanel.BORDER_ALL
        self.target = None
        self.task = None
        self._title = "Blocking task"
        self._changed = False
        self._progress = None
        self._description = []
        self._status = None
        self.indicator = self.INDICATOR_1
        self.indicator_pos = (0, 0)
        self.indicator_idx = 0
        self.autoresize()

    def handle_key(self, key):
        return False

    def check(self):
        if self.task is None or not self.task.is_alive():
            return False

        if self._changed:
            self._changed = False
            self.paint(True)
        else:
            self.paint_indicator()
        
        threading.Timer(0.5, lambda: self.app.callbacks.put((self, self.check))).start()

        return True

    def paint(self, clear=False):
        super().paint(clear)

        height, width = self.dim

        text = self._title[:width-3]
        self.win.addstr(1, 1, text, curses.A_BOLD)

        if self._progress is not None:
            y = 3
            x = 2
            bar_w = width - 4
            if isinstance(self._progress, tuple):
                percent = float(self._progress[0])/self._progress[1]
            else:
                percent = self._progress/100.0
            percent = min(1.0, max(0.0, percent))
            completed_w = int(bar_w*percent)
            self._indicator_pos = (y, x + completed_w)
            self.win.addstr(y, x, "▒"*bar_w)
            self.win.addstr(y, x, "█"*completed_w)

        self.win.addstr(4, 1, " "*(width-2))
        if self._status is not None:
            self.win.addstr(4, 1, self._status[:width-2])

        self.win.noutrefresh()
        self.paint_indicator()

    def paint_indicator(self):
        self.win.addstr(self._indicator_pos[0], self._indicator_pos[1], self.indicator[self.indicator_idx])
        self.indicator_idx = (self.indicator_idx + 1) % len(self.indicator)
        self.win.noutrefresh()

    def autoresize(self):
        maxheight, maxwidth = self.app.size()
        width = min(maxwidth, max(20, 3*maxwidth//4))
        height = min(maxheight, max(5, maxheight//3))
        y = (maxheight-height)//2
        x = (maxwidth-width)//2
        logger.debug(f"Autoresizing blocking task window to {height}x{width} +{x}:{y}")
        if self._progress is None:
            self._indicator_pos = (0, width-3)
        self.resize(height, width)
        self.move(y, x)

    def status(self, status):
        """Update the status text"""
        self._status = status
        self._changed = True

    def title(self, title):
        """Set the title of the task"""
        self._title = title
        self._changed = True

    def progress(self, current):
        """Update the progress of the task

        current may be an int with the progress in percent (0..100)
        or it may be a tuple with (completed subtasks, number of subtasks)"""
        self._progress = current
        if self._progress is None:
            self.indicator = self.INDICATOR_1
        else:
            self.indicator = self.INDICATOR_2
        self._changed = True

    def destroy(self):
        super().destroy()
        self.app.blocking_task = None
        self.app.paint()
        return True

    def run(self):
        self.task = threading.Thread(target=self.do_run)
        self.task.start()
        # only paint if the task takes longer than 0.1
        self.task.join(0.1)
        logger.debug("Blocking task launched")

    def do_run(self):
        self.app.callbacks.put((self, self.check))
        try:
            self.target()
        except Exception as exc:
            logger.error(f"Blocking task failed: {exc}")
        self.app.callbacks.put((self, self.destroy))


class ListPanel(ScrollPanel):
    def __init__(self, application, *args, **kwargs):
        super().__init__(application, *args, **kwargs)
        self.reload_keybindings()
        self._is_busy = threading.Lock()
        self.multi_selection = []
    
    def reload_keybindings(self):
        self.SCROLL_NEXT = extract_key_sequence(self.app, NEXT_ITEM)
        self.SCROLL_PREVIOUS = extract_key_sequence(self.app, PREV_ITEM)
        self.SCROLL_NEXT_PAGE = extract_key_sequence(self.app, NEXT_PAGE)
        self.SCROLL_PREVIOUS_PAGE = extract_key_sequence(self.app, PREV_PAGE)
        self.SCROLL_TO_START = extract_key_sequence(self.app, TO_START)
        self.SCROLL_TO_END = extract_key_sequence(self.app, TO_END)

    def title(self):
        raise NotImplementedError()

    @property
    def selected_items(self):
        if len(self.multi_selection) == 0:
            return [self.selected_item]
        return self.multi_selection

    @property
    def is_busy(self):
        return self._is_busy.locked()

    def run_blocking(self, target, *args, **kwargs):
        """Run the function 'target' as a blocking task

        Pass *args, and **kwargs along to target.
        'target' must accept the blockingtask class as its first argument.
        """
        if self.app.blocking_task is not None:
            self.app.error("Another blocking task is already running")

        self.app.blocking_task = BlockingTask(self.app)
        self.app.blocking_task.target = lambda: target(self.app.blocking_task, *args, **kwargs)
        self.app.blocking_task.run()

    def run_in_background(self, target):
        """Run the function 'target' as a thread in the background
        """
        if self.is_busy:
            raise RuntimeError("Already busy")
        thread = threading.Thread(target=lambda: self._do_run_in_background(target))
        logger.debug(f"{self} starts a background task")
        thread.start()

    def _do_run_in_background(self, target):
        with self._is_busy:
            target()

    def handle_key(self, key):
        if self.is_busy:
            return

        return super().handle_key(key)

    def configuration_changed(self, name=None):
        changed = False

        if name == OPTION_PAGING or name is None:
            new_value = self.app.configuration.bool('all', OPTION_PAGING, str(self.SCROLL_PAGING))
            changed = new_value != self.SCROLL_PAGING
            self.SCROLL_PAGING = new_value

        if name == OPTION_SCROLL_MARGIN or name is None:
            new_value = self.app.configuration.number('all', OPTION_SCROLL_MARGIN, str(self.SCROLL_MARGIN))
            if new_value is not None and new_value >= 0:
                changed = changed or new_value != self.SCROLL_MARGIN
                self.SCROLL_MARGIN = new_value

        if changed and self.win is not None:
            self.scroll()
            self.paint(True)

    def focus(self):
        retval = super().focus()
        self.on_focus()
        return retval

    def on_close(self):
        pass

    def on_focus(self):
        pass


def extract_key_sequence(application, commandname):
    return [keys
            for scope, keys, cmd in application.keys
            if cmd[0] == commandname and scope == 'any']


