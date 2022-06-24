"""Internal clipboard types

There are two ways, for you as the developer, to interact with the clipboard.
You can be a provider of clipboard content (e.g. make calls to app.clipboard.set)
or you can be a receiver of clipboard content (e.g. make calls to app.clipboard.get).

TL;DR:

    class SimpleClipboardProvider:
        @property
        def selected_items(self):
            # whatever the user selected
            return ['a', 'b', 'c']

        def on_copy(self, item):
            # item will be something from self.selected_items
            if item is None:
                return None
            return ClipboardItem(item, self)

        def on_clipboard_item_pasted(self, item):
            # item has been pasted, the operation succeeded,
            # here you could make the item disappear from the clipboard again:
            item.valid = False

    class SimpleClipboardReceiver:
        def on_paste(self, items):
            for item in items:
                if item == 'a':
                    raise RuntimeError('Only accepts "b"')
                # or otherwise use item

And once more, but in clumsy human language:

As a provider, you must fulfill the following requirements:
- Have a property ``selected_items`` with the instances that the user selected
- Have a function ``on_copy`` that accepts any item that can be in
  ``selected_items`` and returns the corresponding ClipboardItem instance.
As a provider, you can receive a callback when a clipboard item is being used
(i.e. when the user triggers ``on_paste``). For that purpose, make sure you provide
the ``source`` parameter by handing in ``self`` (or whatever provides a
``on_clipboard_item_cut`` function) to ClipboardItem.
This is useful when the pasted item has been 'cut' in the first place and you
want to handle the deletion on your end.

As a receiver, you are expected to implement the ``on_paste`` function which will
be called from the command by the same name. The paste function will receive
a list of ClipboardItems.
If the paste operation at any point in time fails for any of the items, you should
raise a RuntimeError. This is the only way to prevent the potential destruction
of the items by the provider (if the provider chose to do that).
"""
import weakref
from enum import Enum

from metaindexmanager.utils import logger
from metaindexmanager.command import registered_command, Command


class PasteBehaviour(Enum):
    """Possible behaviours of a paste operation when encountering
    conflicting items (e.g. when pasting a file when that filename
    already exists)"""

    ERROR = 'error'
    """Treat as an error and do not paste"""

    APPEND = 'append'
    """Paste, but give the pasted file a new, non-conflicting name"""

    OVERWRITE = 'overwrite'
    """Paste, overwrite the conflicting item"""


class ClipboardItem:
    """An item that can be on the clipboard

    ``data`` is the actual data that the user wanted to put on the clipboard.
    ``extra`` is any type of extra data that the provider wanted to keep around,
    e.g. the mimetype of the data.
    ``source`` is a weak reference to the provider of the clipboard item (or
    None if the provider does not need any feedback on consumption of the item).

    ``valid`` indicates if the clipboard item is still valid. The provider may
    set this to False upon callback after use, to indicate that the item is gone
    stale and must be removed from the clipboard and/or disregarded during paste.
    """
    def __init__(self, data, source=None, extra=None):
        self.data = data
        self.extra = extra
        self.source = None
        self.valid = True

        if source is not None and hasattr(source, 'on_clipboard_item_use'):
            self.source = weakref.ref(source)


class Clipboard:
    """The clipboard instance type

    There should be one instance of this in app.
    """
    DEFAULT = ''

    def __init__(self, app):
        self.app = app
        self.stores = {}

    def set(self, content, name=None):
        """Set the content of the clipboard with the given identifier

        A named clipboard is always a flat list of things (usually pathlib.Path items).
        """
        if content is None:
            self.clear(name)
            return

        if not isinstance(content, (list, tuple, set)):
            content = [content]

        if not all(isinstance(c, ClipboardItem) for c in content):
            raise TypeError("Only ClipboardItem can be put on the clipboard")

        if name is None:
            name = self.DEFAULT

        self.stores[name] = content
        logger.debug("Clipboard '%s' is now: %s", name, [i.data for i in self.stores[name]])

    def append(self, content, name=None):
        """Append the content to the clipboard with the given identifier

        See set for more details
        """
        if content is None:
            return

        if name is None:
            name = self.DEFAULT

        if name not in self.stores:
            self.stores[name] = []

        if not isinstance(content, (list, tuple, set)):
            content = [content]

        if not all(isinstance(c, ClipboardItem) for c in content):
            raise TypeError("Only ClipboardItem can be put on the clipboard")

        self.stores[name] += content

        logger.debug("Clipboard '%s' is now %s", name, [i.data for i in self.stores[name]])

    def clear(self, name=None):
        """Clear the clipboard with the given identifier

        See set for more details
        """
        if name is None:
            name = self.DEFAULT

        if name in self.stores:
            del self.stores[name]
        logger.debug("Cleared clipboard '%s'", name)

    def is_empty(self, name=None):
        """Whether or not the clipboard ``name`` is empty"""
        return name not in self.stores or len(self.stores[name]) == 0


@registered_command
class PasteItem(Command):
    """Paste content of clipboard here"""
    NAME = 'paste'
    BEHAVIOUR = PasteBehaviour.ERROR

    def execute(self, context, name=None):
        if not hasattr(context.panel, 'on_paste'):
            return

        if name is None:
            name = Clipboard.DEFAULT

        clipboard = context.application.clipboard.stores.get(name)
        if clipboard is None or len(clipboard) == 0:
            return

        items = [i for i in clipboard if i.valid]
        try:
            context.panel.on_paste(items[:], self.BEHAVIOUR)
        except RuntimeError as exc:
            logger.error("Error while pasting in '%s': %s",
                         context.panel, exc)
            context.application.error(f"Error while pasting: {exc}")
            return

        # after use, tell the provider and delete items that are no longer valid
        remaining = []
        for item in items:
            if item.source is not None and item.source() is not None:
                item.source().on_clipboard_item_use(item)
            if item.valid:
                remaining.append(item)
        context.application.clipboard.set(remaining, name)


@registered_command
class PasteOverwrite(PasteItem):
    """Paste content from clipboard here, overwriting existing items"""
    NAME = 'paste-overwrite'
    BEHAVIOUR = PasteBehaviour.OVERWRITE


@registered_command
class PasteAppend(PasteItem):
    """Paste content from clipboard here but with new name if existing items conflict"""
    NAME = 'paste-append'
    BEHAVIOUR = PasteBehaviour.APPEND


@registered_command
class CopyToClipboard(Command):
    """Copy the selected item to clipboard"""
    NAME = 'copy'

    def execute(self, context, clipboard=None):
        source = context.panel
        if not hasattr(source, 'on_copy'):
            context.application.error("Copy is not supported here")
            return

        context.application.clipboard.clear(clipboard)
        for item in source.selected_items:
            cbitem = source.on_copy(item)
            if cbitem is not None:
                context.application.clipboard.append(cbitem, clipboard)


@registered_command
class CutToClipboard(Command):
    """Cut the selected item to clipboard"""
    NAME = 'cut'

    def execute(self, context, clipboard=None):
        source = context.panel
        if not hasattr(source, 'on_cut'):
            context.application.error("Cut is not supported here")
            return

        context.application.clipboard.clear(clipboard)
        for item in source.selected_items:
            cbitem = source.on_cut(item)
            if cbitem is not None:
                context.application.clipboard.append(cbitem, clipboard)


@registered_command
class AppendToClipboard(Command):
    """Append the selected item to clipboard"""
    NAME = 'append'

    def execute(self, context, clipboard=None):
        if not hasattr(context.panel, 'on_copy'):
            context.application.error("Copy is not supported here")
            return

        for item in context.panel.selected_items:
            context.application.clipboard.append(context.panel.on_copy(item),
                                                 clipboard)


@registered_command
class CutAppendToClipboard(Command):
    """Cut and append the selected item to clipboard"""
    NAME = 'cut-append'

    def execute(self, context, clipboard=None):
        if not hasattr(context.panel, 'on_cut'):
            context.application.error("Cut is not supported here")
            return

        for item in context.panel.selected_items:
            context.application.clipboard.append(context.panel.on_cut(item),
                                                 clipboard)


@registered_command
class ClearClipboard(Command):
    """Clear the clipboard of items to copy"""
    NAME = 'clear-clipboard'

    def execute(self, context, clipboard=None):
        context.application.clipboard.clear(clipboard)
        context.application.info(f"Cleared clipboard {clipboard}")
