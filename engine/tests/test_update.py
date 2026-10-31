"""Requests the engine answers itself: the once-a-day update check (without touching the internet),
the language setting, and taking a file out of the library."""
import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tajmeea_engine import __main__ as main
from tajmeea_engine import __version__
from tajmeea_engine.errors import UserError


class Landed(io.BytesIO):
    """What urlopen hands back after following GitHub's redirect."""
    def __init__(self, address):
        super().__init__(b"")
        self.address = address

    def geturl(self):
        return self.address


def published(version):
    # /releases/latest goes on to the newest release's page; with no release yet, to the list of releases.
    page = f"https://github.com/Khxxxxd/tajmeea/releases/tag/v{version}" if version else "https://github.com/Khxxxxd/tajmeea/releases"
    return lambda request, timeout: Landed(page)


def offline(url, timeout):
    raise OSError("no network")


class EngineCase(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        patch = mock.patch.dict(os.environ, {"TAJMEEA_HOME": home.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.engine = main.Engine(write=lambda message: None)
        self.addCleanup(self.engine.library.close)

    def check(self, urlopen):
        with mock.patch.object(main.urllib.request, "urlopen", urlopen):
            return asyncio.run(self.engine.check_update())


class UpdateCheckTest(EngineCase):
    def test_newer_version_on_github(self):
        result = self.check(published("9.0.0"))
        self.assertEqual(result, {"current": __version__, "latest": "9.0.0", "available": True})

    def test_same_version_is_not_an_update(self):
        self.assertFalse(self.check(published(__version__))["available"])

    def test_versions_compare_as_numbers(self):
        self.assertTrue(main._newer("0.10.0", "0.9.9"))
        self.assertFalse(main._newer("0.1.0", "0.1.0"))

    def test_no_internet_or_no_repo_stays_quiet(self):
        self.assertEqual(self.check(offline), {"current": __version__, "latest": None, "available": False})

    def test_no_release_yet_stays_quiet(self):
        self.assertEqual(self.check(published(None)), {"current": __version__, "latest": None, "available": False})


class SettingsTest(EngineCase):
    def test_language_is_arabic_until_changed(self):
        self.assertEqual(self.engine.settings_get(), {"language": "ar"})
        self.assertEqual(self.engine.settings_set("language", "en"), {"language": "en"})
        self.assertEqual(self.engine.settings_get(), {"language": "en"})

    def test_unknown_setting_is_refused(self):
        with self.assertRaises(UserError):
            self.engine.settings_set("colour", "red")


class RemoveFileTest(EngineCase):
    def test_says_which_file_goes_to_the_trash_and_keeps_its_folder(self):
        root = Path(tempfile.mkdtemp(dir=os.environ["TAJMEEA_HOME"]))
        library = self.engine.library
        library.save_channel({"id": 5, "username": "law", "title": "قوانين"}, {"folder": str(root), "kinds": ["pdf"]})
        path = root / "2024" / "قانون.pdf"
        path.parent.mkdir()
        path.write_bytes(b"x")
        library.record(channel_id=5, msg_id=1, kind="pdf", name=path.name, path=str(path), size=1, status="done")
        library.record(channel_id=5, msg_id=2, kind="pdf", name="انحذف.pdf", path=str(root / "انحذف.pdf"), status="done")

        result = self.engine.file_remove(channelId=5, msgId=1)
        # The year folder is the limit, so it stays even when it's left empty.
        self.assertEqual(result["trash"], {"paths": [str(path)], "folder": str(path.parent), "ownFolder": False})
        self.assertTrue(path.exists())  # the engine itself never deletes anything
        self.assertIsNone(self.engine.file_remove(channelId=5, msgId=2)["trash"])  # already gone: nothing to trash
        with self.assertRaises(UserError):
            self.engine.file_remove(channelId=5, msgId=1)
        # The Trash couldn't take it: it is saved again, and can be removed again.
        self.assertEqual(self.engine.file_trashed(channelId=5, msgId=1, moved=False)["shelves"][0]["favorites"], True)
        self.assertEqual(library.file(5, 1)["status"], "done")
        self.assertIsNotNone(self.engine.file_remove(channelId=5, msgId=1)["trash"])


if __name__ == "__main__":
    unittest.main()
