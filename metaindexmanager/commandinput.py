import traceback
import shlex

from cursedspace import InputLine, Key, Completion

import metaindexmanager.command
from .utils import logger
from .command import resolve_command


class CommandCompletion(Completion):
    def update(self, y, x):
        targetpanel = self.app.previous_focus
        alternatives = []
        text = self.inputline.text[:self.inputline.cursor]
        try:
            parts = shlex.split(text)
        except ValueError:
            return

        if len(parts) <= 1:
            if len(parts) == 0:
                parts = [""]
            alternatives = [name for name, cmd in sorted(metaindexmanager.command._registered_commands.items())
                            if (len(parts[0]) == 0 or name.startswith(parts[0])) and isinstance(targetpanel, cmd.ACCEPT_IN)]

        if len(parts) > 1 or text.endswith(' '):
            cmd = resolve_command(parts[0])
            if cmd is not None and isinstance(targetpanel, cmd.ACCEPT_IN):
                alternatives = cmd().completion_options(self.app.make_context(), *parts[1:])

        if len(alternatives) > 0:
            self.set_alternatives(alternatives, (y, x))
            self.app.paint()
        elif self.is_visible:
            self.close()
            self.app.paint()


class CommandInput(InputLine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history_cursor = None
        self.cached_text = None
        self.cached_cursor = None
        self.candidates = []

        self.completion = CommandCompletion(self)

    def handle_key(self, key):
        must_repaint = False

        if key in [Key.TAB, "^N"] and self.completion is not None and not self.completion.is_visible:
            self.update_completion()
        elif self.completion is not None and self.completion.is_visible and self.completion.handle_key(key):
            pass
        elif key in [Key.ESCAPE, "^C"]:
            self.app.execute_command('cancel-command')
        
        elif key in [Key.BACKSPACE] and (self.text is None or len(self.text) == 0):
            self.app.execute_command('cancel-command')
        
        elif key in [Key.UP]:
            if self.history_cursor is None:
                self.cached_text = self.text
                self.cached_cursor = self.cursor
                self.candidates = [line for line in self.app.command_history
                                        if line.startswith(self.cached_text[:self.cursor])]
            if len(self.candidates) > 0:
                if self.history_cursor is None:
                    self.history_cursor = len(self.candidates) - 1
                elif self.history_cursor > 0:
                    self.history_cursor -= 1
                self.text = self.candidates[self.history_cursor]
                self.cursor = min(len(self.text), self.cursor)
                must_repaint = True
        
        elif key in [Key.DOWN] and self.history_cursor is not None:
            if self.history_cursor == len(self.candidates) - 1:
                self.text = self.cached_text
                self.cursor = self.cached_cursor
                self.history_cursor = None
            else:
                self.history_cursor += 1
                self.text = self.candidates[self.history_cursor]
                self.cursor = min(len(self.text), self.cursor)
            must_repaint = True

        elif key in [Key.RETURN]:
            self.app.execute_command('cancel-command')
            seq = shlex.split(self.text)
            if len(seq) == 0:
                command = None
            else:
                command = resolve_command(seq[0])

            if command is not None:
                if not isinstance(self.app.current_panel, command.ACCEPT_IN):
                    error = f"Command {seq[0]} not valid in this panel"
                    logger.error(error)
                    self.app.error(error)
                else:
                    try:
                        if len(seq) > 1:
                            expanded = sum([expand_part(self.app, part) for part in seq[1:]], start=[])
                            self.app.execute_command(command, *expanded)
                        else:
                            self.app.execute_command(command)
                        self.app.command_history.append(self.text)
                        self.text = ""
                    except Exception as exc:
                        error = f"Failed to execute {seq[0]}: {exc}"
                        self.app.error(error)
                        logger.error(error)
                        logger.debug(''.join(traceback.format_tb(exc.__traceback__)))
            elif len(seq) > 0:
                error = f"No such command: {seq[0]}"
                logger.warning(error)
                self.app.error(error)
            self.history_cursor = None
            self.cached_text = None
            self.cached_cursor = None
        
        else:
            text = self.text
            super().handle_key(key)

            if text != self.text and self.history_cursor is not None:
                self.history_cursor = None
                self.cached_text = None
                self.cached_cursor = None

            elif text != self.text and self.completion is not None:
                self.update_completion()

        if must_repaint:
            self.paint()
            self.focus()

    def destroy(self):
        if self.win is not None:
            self.win.erase()
            self.win.refresh()
        super().destroy()


def expand_part(app, part):
    """Expand the single string 'part' into a list of strings

    Expands:
     - '%n' to [filename of the selected item]
     - '%f' to [full path of selected item]
     - '%s' to [full path of selected item 1, full path of selected item 2, ...]
     - '%p' to [full path of folder of selected item]
    """
    if part == '%n':
        return [str(app.current_panel.selected_path.name)]
    elif part == '%f':
        return [str(app.current_panel.selected_path)]
    elif part == '%s':
        return [str(p) for p in app.current_panel.selected_paths]
    elif part == '%p':
        return [str(app.current_panel.selected_path.parent)]
    return [part]

