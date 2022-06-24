# Changelog

This file contains the changes made between released versions.

The format is based on [Keep a changelog](https://keepachangelog.com/) and the versioning tries to follow
[Semantic Versioning](https://semver.org).

## 0.8.0
### Fixed
- The `shell` command is now executed in a shell (shock.gif) and will expand things like `*.md` correctly
- Keybindings that start with `::` will now expand the `%` placeholders (like `%f` or `%p`)

### Added
- `files.show-hidden-files` configuration option
- `files.show-sidecar-files` configuration option
- `editor.no-completion` configuration option to prevent completion for some tags
- `editor.tags` configuration option to suggest standard extra tags
- Introduced `paste-overwrite` and `paste-append` in the file browser
- `launch` command (in file browser)
- Blocking processes (e.g. long copy operations) can be cancelled by pressing `Esc` or `^C` (at least you can request it; the file browser will try to listen to it)

### Changed
- The regular `paste` in the file browser will no longer paste with a new file name when a file with the same name already exists. Instead you will see an error message. See `paste-append` and `paste-overwrite` in the documentation.


## 0.7.0
### Added
- Help panel added. Try `F1`, `?`, or `:help` to show all shortcuts and available commands
- `find` command (on shortcut `/`, `find-next` is on `n` and `find-prev` on `N`)
- `all.find-case-sensitive` configuration option
- `open-with` command
- `files.selection-icon` configuration option (what symbol to use to indicate a selected file or folder)
- `files.info` configuration option (extra info columns, like file size)
- Completion box for extra metadata values in the editor panel
- `dictionary.` configuration option to define dictionaries of allowed words per metadata tag

### Fixed
- Addons could not access packages when importing
- Fix editing through external editor


### Changed
- Depend on metaindex version 1.2.0


## 0.6.1
### Fixed
- `filename` and `last_modified` were not accessible for `documents.columns` and in the metadata editor


## 0.6.0
### Fixed
- A couple of bugfixes, mostly UI related

### Changed
- Use metaindex 1.0.0


## 0.5.0
### Changed
- Switched most references from github.com to vonshednob.cc
- Auto-index a file when the editor panel is launched and no metadata is available yet

### Added
- `--version` command line flag
- `--check-for-update` command line flag
- Support for addons in form of directories
- `is_hidden` and `is_executable` helper functions
- Autocompletion in `cd` command
- `cut` for cut and paste in file panel

### Fixed
- `set` command used to show the completion for the parameter’s values, too
- The completion used to cause quite some flickering
- Pasting a file (and outside changes) could change the selected item in the file panel


## 0.4.0
### Changed
- Depends on metaindex 0.7.0
- Refactoring of copy and paste, see `clipboard.py` for developer instructions

### Added
- `paste` command can paste files in the file browser

### Removed
- `copy-tag`, `copy-append-tag`, `paste-tag` have been removed. Use `copy`, `append`, and `paste` instead


## 0.3.1
### Fixed
- Selecting the last item in the filepanel did not show the selection marker ([#1](https://github.com/vonshednob/metaindexmanager/issues/1))
- Fixed crash when pasting in the metadata editor while the clipboard is empty
- Fixed crash when humanizing values that are of unusual types
- Fixed crash when attempting to edit metadata of a file in an external editor

### Added
- Document panel supports multi-selection in theory (ie. it can display the selection marks, but there is not command to select)


## 0.3.0
### Changed
- Depend on metaindex 0.6.0

### Added
- `all.history-size` configuration option
- Proper support for renaming files (updates the cache, rename of directories)

### Fixed
- `index` command used to only index the first file, even when indexing a whole folder
- Attempting to open an no longer existing file from the document panel, will no longer crash


## 0.2.0
### Added
- Autocompletion for 'add-tag' command (when editing metadata)

### Changed
- Depending on metaindex-0.5.0 now

### Fixed
- Various breaking incompatibilities there were following the switch from
  metaindex.ThreadedCache to metaindex.MemoryCache

## 0.1.0
- Initial release

