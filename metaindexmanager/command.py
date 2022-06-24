"""Command registry"""
import re

from cursedspace import Panel

from metaindexmanager import shared


_registered_commands = {}
LEGAL_COMMAND_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9\-_]*$')


def registered_command(cls):
    """Decorator to register a Command"""
    assert issubclass(cls, Command)
    assert isinstance(cls.NAME, str)
    assert LEGAL_COMMAND_NAME_RE.match(cls.NAME)
    assert cls.NAME not in _registered_commands

    _registered_commands[cls.NAME] = cls

    return cls


def resolve_command(name):
    """Find the command of the given name and return it

    May return None if no such command is defined"""
    return _registered_commands.get(name, None)


class Command:
    """Abstract command for user commands in metaindexmanager

    NAME must be the unique name of the command. It will be used """
    ACCEPT_IN = (Panel,)
    NAME = None

    def execute(self, context):
        """Called when the user executes this command"""
        raise NotImplementedError()

    def completion_options(self, context, *args):
        """Return all possible alternatives for the last argument of *args"""
        return []

    @classmethod
    def scopes(cls):
        """Return the scopes that this command is valid in"""
        return [getattr(p, 'SCOPE', shared.ANY_SCOPE) for p in cls.ACCEPT_IN]


def simple_command(name, accept_in=None):
    """Decorator to register a plain function as a command"""
    if accept_in is None:
        accept_in = (Panel,)

    def register_simple_command(fnc):
        docstr = fnc.__doc__
        if docstr is None or len(docstr) == 0:
            docstr = name
        cls = type('SimpleCommand', (Command,), {'__doc__': docstr})
        cls.NAME = name
        cls.ACCEPT_IN = accept_in
        cls.execute = lambda self, context, *args, **kwargs: fnc(context, *args, **kwargs)
        return registered_command(cls)
    return register_simple_command
