"""Test suite for file panel's paste operation"""
import datetime
import unittest
import tempfile
import json
from pathlib import Path

from metaindex import MemoryCache
from metaindex import stores
from metaindex.configuration import BaseConfiguration, Configuration

from metaindexmanager.clipboard import PasteBehaviour
from metaindexmanager.utils import logger
from metaindexmanager.filepanel import FilePanel


class NoCacheBackend:
    """A fake cache backend providing the API but nothing else"""
    def __init__(self):
        self.is_started = True

    def find(self, *_):
        return []

    def get(self, *_):
        return []

    def rename(self, *_):
        pass

    def insert(self, *_):
        pass

    def refresh(self, *_):
        pass

    def forget(self, *_):
        pass

    def last_modified(self):
        return datetime.datetime.min

    def keys(self, *_):
        return set()

    def start(self):
        pass

    def quit(self):
        pass


class FakeQueue:
    def put(self, *args, **kwargs):
        pass


class FakeApplication:
    def __init__(self):
        self.errors = 0
        self.keys = []
        self.callbacks = FakeQueue()
        self.configuration = BaseConfiguration()
        self.metaindexconf = Configuration()
        self.cache = MemoryCache(self.metaindexconf)
        self.cache.tcache = NoCacheBackend()
        self.cache.start()
        self.cache.wait_for_reload()

    def error(self, *args):
        self.errors += 1


class TestablePanel:
    """Context manager for a testable file panel"""
    def __init__(self):
        self.app = None
        self.panel = None

    def __enter__(self):
        self.app = FakeApplication()
        self.panel = FilePanel(self.app)
        return self.panel

    def __exit__(self, *args, **kwargs):
        self.panel.on_close()
        self.app.cache.quit()


def tempdir():
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


class TestPasteOperation(unittest.TestCase):
    def setUp(self):
        logger.setup()
        self._src = tempdir()
        self.src_folder = Path(self._src.name)
        self._target = tempdir()
        self.target_folder = Path(self._target.name)

    def tearDown(self):
        self._src.cleanup()
        self._target.cleanup()

    def test_simple_copy(self):
        """Copy one file, no sidecars, paste into empty directory"""
        src_file = self.src_folder / "file.txt"
        src_file.write_text("Content")

        with TestablePanel() as panel:
            panel.path = self.target_folder
            panel.do_paste(None, [(src_file, False)], PasteBehaviour.ERROR)

        self.assertTrue((self.target_folder / "file.txt").exists())
        self.assertTrue(src_file.exists())
        self.assertEqual(len([i for i in self.target_folder.iterdir()
                              if i.is_file()]), 1)

    def test_conflicting_copy_append(self):
        """Copy one file, no sidecars, paste into directory where a
        file with that name already exists"""
        src_file = self.src_folder / "file.txt"
        src_file.write_text("Content")

        target_file = self.target_folder / "file.txt"
        target_file.write_text("Other content")

        with TestablePanel() as panel:
            panel.path = target_file.parent
            panel.do_paste(None, [(src_file, False)], PasteBehaviour.APPEND)

        self.assertTrue(target_file.exists())
        self.assertTrue(src_file.exists())
        self.assertEqual(target_file.read_text(), "Other content")
        self.assertTrue((target_file.parent / "file_1.txt").exists())
        self.assertEqual((target_file.parent / "file_1.txt").read_text(),
                         "Content")

    def test_conflicting_copy_fail(self):
        """Copy one file, no sidecars, paste into directory where a
        file with that name already exists"""
        src_file = self.src_folder / "file.txt"
        src_file.write_text("Content")

        target_file = self.target_folder / "file.txt"
        target_file.write_text("Other content")

        errors = 0
        with TestablePanel() as panel:
            panel.path = target_file.parent
            panel.do_paste(None, [(src_file, False)], PasteBehaviour.ERROR)
            errors = panel.app.errors

        self.assertTrue(target_file.exists())
        self.assertTrue(src_file.exists())
        self.assertEqual(errors, 1)

    def test_conflicting_copy_overwrite(self):
        """Copy one file, no sidecars, paste into directory where a
        file with that name already exists"""
        src_file = self.src_folder / "file.txt"
        src_file.write_text("Content")

        target_file = self.target_folder / "file.txt"
        target_file.write_text("Other content")

        with TestablePanel() as panel:
            panel.path = target_file.parent
            panel.do_paste(None, [(src_file, False)], PasteBehaviour.OVERWRITE)

        self.assertTrue(target_file.exists())
        self.assertTrue(src_file.exists())
        self.assertEqual(src_file.read_text(), target_file.read_text())

    def test_copy_sidecar(self):
        """Copy one file with a sidecar file into an empty directory"""
        src = self.src_folder / "file.txt"
        sidecar = self.src_folder / "file.json"

        sidecar.write_text(json.dumps({'tag': 'foo',
                                       'title': 'bar'}))
        src.write_text("Content")

        with TestablePanel() as panel:
            panel.path = self.target_folder
            panel.do_paste(None, [(src, False)], PasteBehaviour.ERROR)

        target = self.target_folder / src.name
        target_sidecar = self.target_folder / sidecar.name

        self.assertTrue(target.exists())
        self.assertTrue(target_sidecar.exists())
        metadata = stores.get(target_sidecar)
        self.assertIn(('extra.tag', 'foo'), metadata)
        self.assertIn(('extra.title', 'bar'), metadata)

    def test_merge_sidecar(self):
        """Copy one file with a few sidecar files into an empty directory"""
        src = self.src_folder / "file.txt"

        src.write_text("Content")
        (self.src_folder / "file.json").write_text(json.dumps({'tag': 'json'}))
        (self.src_folder / "metadata.json").write_text(json.dumps({
            '*': {'tag': 'collection'},
            'other.txt': {'tag': 'nope'},
            'file.txt': {'title': 'File'},
        }))
        (self.src_folder / "file.opf").write_text("""<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
<dc:title>Another Title</dc:title></metadata></package>""")

        with TestablePanel() as panel:
            panel.path = self.target_folder
            panel.do_paste(None, [(src, False)], PasteBehaviour.ERROR)

        self.assertTrue(src.exists())
        target = self.target_folder / src.name
        target_sidecar = self.target_folder / (src.stem + '.json')
        self.assertTrue(target.exists())
        self.assertTrue(target_sidecar.exists())

        metadata = stores.get(target_sidecar)
        self.assertIn(('extra.tag', 'json'), metadata)
        self.assertIn(('extra.tag', 'collection'), metadata)
        self.assertIn(('extra.title', 'File'), metadata)
        self.assertIn(('extra.title', 'Another Title'), metadata)
        self.assertNotIn(('extra.tag', 'nope'), metadata)

    def test_cut_merge_sidecar(self):
        """Cut one file with a few sidecar files into an empty directory"""
        src = self.src_folder / "file.txt"

        src.write_text("Content")
        (self.src_folder / "file.json").write_text(json.dumps({'tag': 'json'}))
        (self.src_folder / "metadata.json").write_text(json.dumps({
            '*': {'tag': 'collection'},
            'other.txt': {'tag': 'nope'},
            'file.txt': {'title': 'File'},
        }))
        (self.src_folder / "file.opf").write_text("""<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
<dc:title>Another Title</dc:title></metadata></package>""")

        with TestablePanel() as panel:
            panel.path = self.target_folder
            panel.do_paste(None, [(src, True)], PasteBehaviour.ERROR)

        self.assertFalse(src.exists())
        self.assertFalse((src.parent / (src.stem + '.json')).exists())
        self.assertFalse((src.parent / (src.stem + '.opf')).exists())
        self.assertTrue((src.parent / 'metadata.json').exists())

        metadata = stores.get_for_collection(src.parent / 'metadata.json')
        self.assertIn(src.parent, metadata)
        self.assertIn(src.parent / 'other.txt', metadata)
        self.assertNotIn(src, metadata)
        self.assertIn(('extra.tag', 'collection'), metadata[src.parent])
        self.assertIn(('extra.tag', 'nope'), metadata[src.parent / 'other.txt'])

        target = self.target_folder / src.name
        target_sidecar = self.target_folder / (src.stem + '.json')
        self.assertTrue(target.exists())
        self.assertTrue(target_sidecar.exists())

        metadata = stores.get(target_sidecar)
        self.assertIn(('extra.tag', 'json'), metadata)
        self.assertIn(('extra.tag', 'collection'), metadata)
        self.assertIn(('extra.title', 'File'), metadata)
        self.assertIn(('extra.title', 'Another Title'), metadata)
        self.assertNotIn(('extra.tag', 'nope'), metadata)

    def test_conflicting_copy_overwrite_sidecars(self):
        """Copy one file with sidecars, paste into directory where a
        file with that name already exists, overwrite the target sidecar"""
        src_file = self.src_folder / "file.txt"
        src_file.write_text("Content")
        src_sidecar = self.src_folder / "file.json"
        src_sidecar.write_text(json.dumps({'tag': 'new'}))

        target_file = self.target_folder / "file.txt"
        target_file.write_text("Other content")
        target_sidecar = target_file.parent / "file.json"
        target_sidecar.write_text(json.dumps({'tag': 'old'}))

        with TestablePanel() as panel:
            panel.path = target_file.parent
            panel.do_paste(None, [(src_file, False)], PasteBehaviour.OVERWRITE)

        self.assertTrue(target_file.exists())
        self.assertTrue(src_file.exists())
        self.assertTrue(target_sidecar.exists())
        self.assertEqual(src_file.read_text(), target_file.read_text())

        metadata = stores.get(target_sidecar)
        self.assertIn(('extra.tag', 'new'), metadata)
        self.assertNotIn(('extra.tag', 'old'), metadata)

    def test_conflicting_copy_join_sidecars(self):
        """Copy one file with sidecars, paste into directory where a
        sidecar file with that name already exists, merge the target sidecar

        It's a bit of an odd case.
        """
        src_file = self.src_folder / "file.txt"
        src_file.write_text("Content")
        src_sidecar = self.src_folder / "file.json"
        src_sidecar.write_text(json.dumps({'tag': 'new'}))

        target_file = self.target_folder / "file.txt"
        target_sidecar = target_file.parent / "file.json"
        target_sidecar.write_text(json.dumps({'tag': 'old'}))

        with TestablePanel() as panel:
            panel.path = target_file.parent
            panel.do_paste(None, [(src_file, False)], PasteBehaviour.APPEND)

        self.assertTrue(target_file.exists())
        self.assertTrue(src_file.exists())
        self.assertTrue(target_sidecar.exists())
        self.assertEqual(src_file.read_text(), target_file.read_text())

        metadata = stores.get(target_sidecar)
        self.assertIn(('extra.tag', 'new'), metadata)
        self.assertIn(('extra.tag', 'old'), metadata)
