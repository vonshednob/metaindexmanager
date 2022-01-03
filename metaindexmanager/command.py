from abc import ABC

from cursedspace import Panel


_registered_commands = {}


def registered_command(cls):
    assert issubclass(cls, Command)
    global _registered_commands
    assert cls.NAME not in _registered_commands
    _registered_commands[cls.NAME] = cls
    return cls


def resolve_command(name):
    global _registered_commands
    return _registered_commands.get(name, None)


class Command:
    ACCEPT_IN = (Panel,)

    def execute(self, context):
        raise NotImplementedError()

    def completion_options(self, context, *args):
        """Return all possible alternatives for the last argument of *args"""
        return []


def simple_command(name, accept_in=None):
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

