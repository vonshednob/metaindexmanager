# metaindexmanager

A filemanager-like program to inspect your indexed documents.


## Installation

Easiest way is to go through PyPi:

    pip install metaindexmanager

It depends on `metaindex` and `cursedspace`. You probably want to install
`metaindex` manually though, to be able to select all the delicious extra
features that are not enabled by default, because they depend on more packets.

You could also clone the git repository and pip install from there:

    git clone <location to be decided>
    cd metaindexmanager
    pip install .


## Usage

Just start it with

    metaindexmanager

Open a file manager panel with `gf`, open another metadata panel with `gm`. To
search for documents in a metadata panel, try `:search ` followed by any valid
metaindex search terms, e.g. `:search mimetype:image`.

To immediately have a search panel and a file panel, you could start like
this:

    metaindexmanager "mimetype:image" ~

Which will open with two panels: one the search results of `mimetype:image`
and the other a file manager panel in your home directory.
You could also start with two file manager panels, like this:

    metaindexmanager ~ ~/Documents

Another good use case is to run in **file select mode**:

    metaindexmanager --file-select-mode

It’ll provide the exact same experience as before, but when you press Enter,
the path of the selected document or file will be written to stdout.
That way you can use metaindexmanager as a file selection utility in other
applications.

The `--file-select-output` allows you to write the path to the selected file
to a file instead of stdout.

