================
metaindexmanager
================
---------------------------------
extendable metaindex file manager
---------------------------------

Synopsis
========

::

  metaindexmanager [-h] [-m metaindex config file] [-l loglevel] [--log-file logfile] [--select-file-mode] [--select-file-output file] [location ...]


Description
===========

metaindexmanager is a text user interface (TUI) file manager that allows
you to browse and manipulate your documents and files by their metadata
tags.

You can also use metaindexmanager from other applications to select files.
See below in `Select file mode`_.


Options
=======

The general parameters are:

  ``-h``
    Show the help and exit.

  ``-m metaindex config file``
    Location of your metaindex config file. If not specified, the default
    location is used. Usually that’s ``~/.config/metaindex.conf``.

  ``-l loglevel``
    The the level of details shown in the log file. Your options are
    ``fatal``, ``error``, ``warning``, ``info``, and ``debug``. Defaults to
    ``warning``.

  ``--log-file logfile``
    Where to write the log to. Defaults to ``~/.local/share/metaindexmenager/ui.log``

    Very useful if the application crashes or shows errors in the status
    line.

  ``--select-file-mode``
    Run in select file mode. See below in `Select file mode`_ for details.

    Not used by default.

  ``--select-file-output file``
    What file to write the selected file(s) to. See `Select file mode`_
    for details on how to use this.
    
    Defaults to ``-`` (standard output).

  ``location``
    Provide any locations or search queries to open on startup.

    If the location you provide is a path to a folder, it will open a file
    panel. Otherwise the location is interpreted as a search query and a
    metadata panel is opened with that search query.

    This, for example, will open two panels. One in your home folder and
    one showing all indexed files that are images::

      metaindexmanager ~ "mimetype:image"



Shortcuts
=========

The following default shortcuts are available in the various panels.

General
-------

These shortcuts work in every panel:

- ``q``, close the current panel
- ``X``, quit metaindexmanager
- ``:``, enter a command
- ``Tab``, next panel
- ``gt``, next panel
- ``gT``, previous panel
- ``gp``, go to panel by number
- ``gnf``, new file browser panel
- ``gnd``, new document browser panel
- ``y0``, clear clipboard
- ``zs``, use the horizontal split layout
- ``zt``, use the tabbed layout
- ``^L``, repaint
- ``'``, jump to mark
- ``arrow down``, next item
- ``arrow up``, previous item
- ``page down``, next page
- ``page up``, previous page
- ``home``, go to start
- ``end``, go to end

These shortcuts only work in the file browser:

- ``R``, refresh
- ``arrow right``, open the file in an external viewer or enter the folder
- ``arrow left``, go up in the folder hierarchy
- ``zh``, toggle display of hidden files
- ``gh``, go to your home folder
- ``gd``, show the metadata details for the selected item
- ``e``, edit metadata of the selected item
- ``E``, edit metadata with an external text editor
- ``!``, run a shell command or open a shell
- ``cd``, change directory
- ``dD``, delete the selected item (experimental)
- ``yy``, copy the selected path to clipboard
- ``ya``, append the selected path to clipboard
- ``m``, mark the selected item for quick access
- ``space``, select the item
- ``uv``, clear selection
- ``v``, invert selection

These shortcuts only work in the document browser:

- ``R``, refresh
- ``arrow right``, open the selected item in an external viewer
- ``/``, enter a new search term
- ``F3``, enter a new search term
- ``gs``, enter a new search term
- ``gl``, open currently selected item in new file browser
- ``gd``, open the metadata viewer for the selected item
- ``yy``, copy the path of the selected item to clipboard
- ``ya``, append the path of the selected item to clipboard
- ``m``, mark the selected item for quick access
- ``e``, edit metadata of the selected item
- ``E``, edit metadata with an external text editor

These shortcuts only work in the metadata editor:

- ``arrow right``, open the file in an external viewer
- ``gl``, open currently selected item in new file browser
- ``E``, edit metadata with an external text editor
- ``return``, edit the selected metadata tag
- ``i``, edit the selected metadata tag
- ``o``, add a new value with the same tag
- ``c``, clear the selected metadata tag value and start editing
- ``a``, add a new tag
- ``dd``, delete the selected tag
- ``u``, undo the most recent change
- ``U``, undo all changes
- ``r``, redo change
- ``^R``, redo change
- ``yy``, copy tag to clipboard
- ``ya``, append tag to clipboard
- ``pp``, paste tag from clipboard
- ``pP``, paste tag from clipboard



Files
=====

The configuration file of metaindexmanager is by default expected at
``~/.config/metaindexmanager/config.rc`` and consists of one command per
line (usually ``bind`` and ``set`` commands, see `Commands`_ below).
Empty or commented lines (starting with a ``#``) are ignored.

Python files in ``~/.local/share/metaindexmanager/addons/`` are considered
addons and will be loaded upon startup. See `Addons`_ below for details.

metaindexmanager will create a logfile to report unexpected or erroneous
behaviour. The location of that logfile can be manually configured by
providing the ``--log-file`` parameter upon startup. The default location
is ``~/.local/share/metaindexmanager/ui.log``.


Select file mode
================

You can run metaindexmanager in ``--select-file-mode`` to use it as an
"open file dialog" in various applications, like (neo)mutt.

When running in select file mode, the ``<Return>`` key will be used to
select the current file, exit the program and write the full path to the
selected file into ``--select-file-output`` (by default the standard
output).

To select any indexed text file or something from your home folder you
could run this::

  metaindexmanager --select-file-mode "mimetype:plain/text" "~"

In actual use cases, you will likely have to write the result to a file
with the ``--select-file-output=file`` parameter.


Example use case: (neo)mutt
---------------------------

If you wanted to use this in (neo)mutt to select email attachments, you
could use the script file ``mtattach.sh`` (in ``extras``) and set
it up in mutt with this macro::

  # example (neo)mutt configuration to use 'a' in the mail composition
  # screen to attach a file using metaindexmanager select file mode
  macro  compose  a  "<shell-escape>mtattach.sh<return><enter-command>source /run/user/`id -u`/mtattach.rc<return><shell-escape>rm /run/user/`id -u`/mtattach.rc<return>" "Attach file"

The ``mtattach.sh`` script launches metaindexmanager with the
``--select-file--mode`` and writes the selected file name into
``/run/user/`id -u`/mtattach.rc``. (neo)mutt will then read that file as a
command to execute the attaching.


Addons
======

**Beware** that addons are just python files. They can in theory do
anything on your computer with your permissions. If you install a malicious
addon, it could upload all your files to the internet and/or encrypt all
your files and ask you for ransom.

**Never install addons from untrusted sources!**


Installing
----------

To install an addon, copy the corresponding ``.py`` file into your addons
folder (usually at ``~/.local/share/metaindexmanager/addons/``).


Writing your own
----------------

Currently there are two possible type of addons:

 - commands, extending ``metaindexmanager.command.Command``, and
 - layouts, extending ``metaindexmanager.layouts.Layout``

Be sure to add the ``@registered_command`` or ``@registered_layout``
decorators to your classes.

Have a look at the layouts in ``metaindexmanager.layouts`` and the commands
in ``metaindexmanager.commands`` to understand how commands work.
``metaindexmanager.docpanel`` and ``metaindexmanager.filepanel`` also have
a bunch of commands defined that are restricted to these panels.



Configuration options
=====================

Configuration options can be set using the ``set`` command. Either during
runtime from the command line or in the configuration file.

The following options exist:

  ``all.editor``
    What text editor to use when a text editor should be launched from
    within metaindexmanager.

  ``all.opener``
    What program to use to open files for viewing in an external program.

    A good program to use is ``rifle`` of the ranger file manager.

    The default is ``xdg-open``.

  ``all.history-size``
    How many entries should be remembered in the command history.

    Defaults to ``1000``.

  ``files.use-icons``
    Set this to ``yes`` (or ``1``, ``y``, ``on``) to use icons in the
    file and folder listing. That means that the shell variables
    ``USERDIR_ICONS`` and ``LS_ICONS`` will be used to find out what icon
    to show per entry.

    The format of ``LS_ICONS`` and ``USERDIR_ICONS`` is based on
    ``LS_COLORS``: a ``:`` separated list of filetype/folder names assigned
    to font awesome/nerdfont icons (the following examples will look broken
    if you don’t have font awesome or nerdfont installed).
    For example, if you want to use a special icon for your downloads and
    music folders, you could set your ``USERDIR_ICONS`` variable to
    ``downloads=:music=``.
    Similarly, to show all normal files as ``f``, folders as ``F`` and only
    JPEG files as ````, you could set your ``LS_ICONS`` variable to
    ``fi=f:di=F:*.jpeg=:*.jpg=``.

    metaindexmanager has some defaults built-in.

  ``documents.columns``
    Defines the default columns for any new documents panel.

    Columns are metadata tag names, like ``extra.title`` or ``mimetype``.
    You may also use synonyms (``author`` instead of only
    ``extra.author``).
    To show more than just the first value (in case a document has multiple
    values for one metadata tag), you can add a ``+`` after the tag name.

    The special column ``icon`` is not a metadata tag, but instead shows an
    icon (see ``files.use-icons`` option above) based on the file type.

    The default is ``title filename tags+ mimetype``.

  ``editor.multiline-indicator``
    What single character to show when a metadata tag has line breaks.

    Defaults to ``…``.

  ``editor.cutoff-indicator``
    What single character to show when a metadata tag is longer than can be
    shown with the screen size.

    Defaults to ``→``.



Commands
========

Commands can be bound to shortcuts or entered directly in the command line.
The command to open the command line is called ``enter-command`` and
usually bound to ``:``.

Based on what panel is currently in focus (file browser, document browser,
editor, etc.) different commands may be available.
The autocompletion in the command line should be aware of that and provide
only valid suggestions.

Some commands accept or even require additional parameters that can be
given on the commandline, but are a bit more tricky when bound to
shortcuts. See details for that below in the ``bind`` command.

Here is a list of all commands:

  ``close``
    Closes the currently focused panel. Once the last panel is closed,
    metaindexmanager will end.

  ``quit``
    Quit metaindexmanager.

  ``next-panel``
    Focus the next panel.

  ``previous-panel``
    Focus the previous panel.

  ``focus``
    Focus the given panel. If called with a parameter, e.g. ``focus 2``, it
    will focus panel with label ``2``. If called without a parameter, it
    will ask the user for the panel to focus on.

  ``new-file-panel``
    Open a new file browser panel.

  ``new-documents-panel``
    Open a new document browser panel.

  ``enter-command``
    Open the command line so the user can enter commands.

  ``cancel-command``
    Close the command line and return focus to the previous panel.

  ``repaint``
    Enforce a repaint of the screen.

  ``layout``
    Change the layout of the panels. Provide the name of the layout you
    want to use as the first parameter. If you don't give a parameter, the
    available layouts will be listed for you.

  ``source``
    Load the configuration file given in the first parameter to this
    command. Usually only used from your configuration file.

  ``bind``
    Bind a command to a shortcut. Expects three parameters: scope, key(s),
    and command.

    The scope is either ``any`` (meaning any panel; file browser, document
    browser, metadata editor, etc.) or either of ``documents`` (a document
    browser panel), ``files`` (a file browser panel), ``editor`` (a
    metadata editor panel).

    Keys can be single keys, like ``c`` or ``C`` (to indicate the use of
    the shift key), ``^H`` (to indicate the use of a control key), or
    special key names like ``<return>`` or ``<escape>``.
    Keys can also be sequences of keys, like ``gTx<backspace>^Y`` to
    indicate the the user must do this magic dance on the keyboard in
    sequence to call the bound command.

    Commands can be given in three different ways. The basic case is to
    just give a command name, like ``enter-command``. This command does not
    expect any parameters, to nothing more is required.
    If a command expects parameters, you can provide them right in this
    parameter, but you must prefix the command with ``::``, for example to
    bind a shortcut to switch to the tabbed layout, you could write ``bind
    any LT "::layout tabbed"``.
    The third possibility is to only open the command line, type the first
    part of the command and let the user input the rest, like this: ``bind
    any L? :layout``.

    An optional last parameter may be used to give a command a nice help
    text.

  ``set``
    Set a configuration option. Expects two parameters: configuration
    option name and value. If only the configuration name is given, the
    current value is shown.
    The configuration option name is ``scope.name``, with scope either
    being ``all`` (meaning, generic application level configuration) or
    either of the panel scopes (``documents``, ``files``, ``editor``,
    etc.).

    Example: ``set all.opener xdg-open``

    For available configuration options, see above in `Configuration options`_

  ``details``
    Open the metadata viewer to show all metadata for the currently
    selected file.

    Only available in document browser and file browser.

  ``edit-metadata``
    Edit the metadata of the currently selected file.

    Only available in document browser, metadata viewer, and file browser.

  ``edit-metadata-external``
    Edit the metadata of the selected item in an external text editor. If
    you set the configuration option ``all.editor``, this text editor will
    be used. Otherwise the environment variables ``VISUAL`` and ``EDITOR``
    are checked in that order to find an existing program.

    Only available in document browser, metadata editor, and file browser.

  ``open``
    Open the selected item in the currently selected panel. This will
    usually open the file in an external program or, if a folder is
    selected, navigate to that folder.

    Only available in document browser, metadata editor, and file browser.

  ``select-and-exit``
    If started in ``--select-file-mode`` this command can be called to quit
    metaindexmanager and have the currently selected item be the file to
    use (for whatever purpose you called metaindexmanager with that
    option).

    Only available in document browser and file browser.

  ``copy``
    Copy the path of the currently selected item to the metaindexmanager
    internal clipboard.
    This command accepts a parameter to identify the clipboard that you
    want to copy the path into. If no parameter is provided, the default
    clipboard is used.

    Only available in document browser and file browser.

  ``append``
    Append the path of the currently selected item to the metaindexmanager
    internal clipboard.
    This command accepts a parameter to identift the clipboard that you
    want to use. See ``copy`` for more details on clipboard naming.

    Only available in document browser and file browser.

  ``clear-clipboard``
    Clear the named clipboard (identified by the first parameter), or clear
    the default clipboard. See ``copy`` for more details on clipboards.

  ``refresh``
    Refresh the current panel. This means reloading the content, not just
    redrawing.

    Only available in document browser and file browser.

  ``mark``
    Bookmark the currently selected item. If no parameter is given, the
    user will be asked to provide an identifier for that bookmark (single
    ASCII letters only). Otherwise the parameter will be used as the
    identifier.

    Only available in document browser and file browser.

  ``ocr``
    Run optical character recognition on the selected item. This requires
    that OCR is configured.

    Only available in document browser, file browser, and metadata editor.

  ``index``
    Run the indexer on the selected item. If a folder is selected, the
    indexer is run in recursive mode, indexing everything in the folder and
    the subfolders.

    Only available in document browser, file browser, and metadata editor.

  ``jump-to-mark``
    Jump to the bookmark identified by the first parameter to this command.
    If no parameter is given, the user will be asked to select from the
    available bookmarks.
    If the current panel is suitable to display that bookmark, the bookmark
    will be opened in it. Otherwise a new panel will open.

    Only available in document browser and file browser.

  ``select``
    Toggle the selection of the current item.

    Only available in document browser and file browser.

  ``clear-selection``
    Unselect all selected items.

    Only available in document browser and file browser.

  ``invert-selection``
    Invert the selection of the currently visible items.

    Only available in document browser and file browser.

  ``go-to-location``
    Open the path to the currently selected item in a new file browser
    panel.

    Only available in document browser, metadata viewer, and metadata
    editor.

  ``rm``
    Delete the selected item.

    Only available in the file browser.

  ``mkdir``
    Create a new folder here. The first parameter is the name of the
    folder.

    Only available in the file browser.

  ``cd``
    Open the path given as the first parameter to this command.

    Only available in the file browser.

  ``shell``
    Execute a command in the shell in this folder. Either the command is
    given as the parameter(s) to ``shell`` or a shell is simply being
    launched at this point, which you will have to exit to return to the
    metaindexmanager.

  ``toggle-hidden``
    Toggle whether or not hidden files should be shown.

    Only available in the file browser.

  ``go-to-parent``
    Go up in the file hierarchy.

    Only available in the file browser.

  ``search``
    Search your documents using the search term given as the first
    parameter.

    The search term is passed into metaindex. Please check the syntax of
    search queries there. You can also find the documentation here:
    https://github.com/vonshednob/metaindex/blob/main/doc/metaindex.rst#search-query-syntax

    Only available in the document browser.

  ``columns``
    Set the visible columns to the parameters. If no parameters are given,
    the current configuration is shown.

    This commands overrides the default column configuration that is set
    through ``set documents.columns`` (see `Configuration options`_ above)
    for the current panel.

    Only available in the document browser.

  ``edit-mode``
    Edit the value of the selected metadata tag.

    Only available in the metadata editor.

  ``edit-multiline``
    Edit this metadata tag value in an external editor to allow editing
    values that have line breaks.
    See configuration option ``all.editor``.

    Only available in the metadata editor.

  ``add-tag``
    Add the first parameter as a metadata tag.

    Only available in the metadata editor.

  ``add-value``
    Add a new value of the metadata tag that you have currently selected.

    Only available in the metadata editor.

  ``replace-value``
    Clear the selected metadata value and start editing.

    Only available in the metadata editor.

  ``del-tag``
    Delete the selected tag and value.

    Only available in the metadata editor.

  ``write``
    Save all changes made in the metadata editor.

    Only available in the metadata editor.

  ``rules``
    Run the rule-based indexers on the current document.

    Only available in the metadata editor.

  ``undo-change``
    Undo the most recent change.

    Only available in the metadata editor.

  ``redo-change``
    Redo the most recently undone change.

    Only available in the metadata editor.

  ``undo-all-changes``
    Discards all changes.

    Only available in the metadata editor.

  ``reset``
    Discards all changes, but also deletes the edit history.
    ``redo-change`` will not work after this.

    Only available in the metadata editor.

  ``copy-tag``
    Copy the currently selected tag and value to the clipboard. If no
    parameter is given, the default clipboard is used.

    Only available in the metadata editor.

  ``copy-append-tag``
    Add the currently selected tag and value to the clipboard. If no
    parameter is given, the default clipboard is used.

    Only available in the metadata editor.

  ``paste-tag``
    Paste a copied tag from the clipboard. If no parameter is given, the
    default clipboard's content is used.

    Only available in the metadata editor.


Usage Examples
==============


Bugs
====

To be expected. Please report anything that you find at
https://github.com/vonshednob/metaindexmanager or via email to the authors.

Be sure to inspect your logfile for crash reports and add them to the bug
report!

