# Changelog

This file contains the changes made between released versions.

The format is based on [Keep a changelog](https://keepachangelog.com/) and the versioning tries to follow
[Semantic Versioning](https://semver.org).

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

