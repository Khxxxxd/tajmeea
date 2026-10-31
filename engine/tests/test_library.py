import tempfile
import unittest
from pathlib import Path

from tajmeea_engine.library import Library, fold

CHANNEL = {"id": 1, "username": "law_library", "title": "مكتبة القوانين"}
OPTIONS = {"folder": "/tmp/x", "kinds": ["pdf"]}


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = Library(self.root / "library.sqlite3")
        self.library.save_channel(CHANNEL, {**OPTIONS, "folder": str(self.root)})

    def tearDown(self):
        self.library.close()
        self.tmp.cleanup()

    def add(self, msg_id, name, caption="", status="done", exists=True):
        path = self.root / name
        if exists:
            path.write_bytes(b"x")
        self.library.record(channel_id=1, msg_id=msg_id, doc_id=500 + msg_id, kind="pdf", name=name,
                            path=str(path), size=10, mime="application/pdf", date="2024-03-03T00:00:00",
                            caption=caption, status=status)

    def test_search_forgives_arabic_spelling(self):
        self.add(1, "قانون العمل في القطاع الأهلي.pdf")
        self.add(2, "تعميم.pdf", caption="بخصوص مادة 64 من قانون العمل")
        self.add(3, "لائحة الإدارة.pdf")
        names = [r["name"] for r in self.library.search("قانون العمل")]
        self.assertEqual(names[0], "قانون العمل في القطاع الأهلي.pdf")
        self.assertIn("تعميم.pdf", names)
        self.assertEqual(self.library.search("الاهلي")[0]["msgId"], 1)
        self.assertEqual(self.library.search("لائحه الادارة")[0]["msgId"], 3)
        self.assertEqual(self.library.search("قانون")[0]["link"], "https://t.me/law_library/1")
        self.assertEqual(self.library.search("مادة 64")[0]["matchedIn"], "caption")

    def test_failed_and_missing_files_come_back(self):
        self.add(1, "ok.pdf")
        self.add(2, "gone.pdf", exists=False)
        self.add(3, "bad.pdf", status="failed", exists=False)
        # A file the person deleted is not fetched again unless they ask for it back.
        self.assertEqual(self.library.ids_to_retry(1), [3])
        self.assertEqual(sorted(self.library.ids_to_retry(1, restore_missing=True)), [2, 3])
        self.assertEqual((self.library.channel(1)["files"], self.library.channel(1)["missing"]), (2, 1))

    def test_a_removed_file_leaves_the_library_and_comes_back_when_put_back(self):
        self.add(1, "قانون العمل.pdf")
        self.add(2, "قانون المرور.pdf")
        self.library.put_on_shelf(1, 1, 1, True)
        removed = self.library.remove_file(1, 1)
        self.assertEqual(removed["path"], str(self.root / "قانون العمل.pdf"))
        self.assertIsNone(self.library.remove_file(1, 1))  # only a saved file can be removed

        # Until the Mac app says it reached the Trash, the file sitting there is not taken as put back.
        self.assertEqual([f["msgId"] for f in self.library.search("قانون")], [2])
        # The app moves it to the Trash; from then on it is nowhere in the library, and not "missing" either.
        (self.root / "قانون العمل.pdf").unlink()
        self.library.trashed(1, 1, moved=True)
        self.assertEqual([f["msgId"] for f in self.library.search("قانون")], [2])
        self.assertEqual([f["msgId"] for f in self.library.recent_files(1)], [2])
        self.assertEqual((self.library.shelves()[0]["files"], self.library.shelf_files(1)), (0, []))
        self.assertEqual((self.library.channel(1)["files"], self.library.channel(1)["missing"]), (1, 0))
        self.assertEqual(self.library.ids_to_retry(1, restore_missing=True), [])

        # Another file in its place is not the one that was removed.
        (self.root / "قانون العمل.pdf").write_bytes(b"something else")
        self.assertEqual(len(self.library.search("قانون")), 1)
        # Put back from the Trash: back in search, on its shelf, and counted again.
        (self.root / "قانون العمل.pdf").write_bytes(b"x" * 10)
        self.assertEqual(sorted(f["msgId"] for f in self.library.search("قانون")), [1, 2])
        self.assertEqual(self.library.shelves()[0]["files"], 1)
        self.assertEqual(self.library.file(1, 1)["status"], "done")

    def test_a_file_the_trash_could_not_take_stays(self):
        self.add(1, "قانون العمل.pdf")
        self.library.remove_file(1, 1)
        self.library.trashed(1, 1, moved=False)  # open in another app, say
        self.assertEqual([f["msgId"] for f in self.library.search("قانون")], [1])
        self.assertEqual(self.library.file(1, 1)["status"], "done")

    def test_files_deleted_in_finder_stop_showing(self):
        self.add(1, "قانون العمل.pdf")
        self.add(2, "قانون المرور.pdf", exists=False)
        self.library.put_on_shelf(1, 1, 2, True)
        self.assertEqual([f["msgId"] for f in self.library.search("قانون")], [1])
        self.assertEqual([f["msgId"] for f in self.library.recent_files(1)], [1])
        self.assertEqual((self.library.shelves()[0]["files"], self.library.shelf_files(1)), (0, []))
        # Still counted as deleted, so the channel can offer to bring it back.
        self.assertEqual(self.library.channel(1)["missing"], 1)

        # A folder that is away (moved, or on a drive that isn't plugged in) keeps its files listed.
        self.library.save_channel(CHANNEL, {**OPTIONS, "folder": str(self.root / "moved away")})
        self.assertEqual(sorted(f["msgId"] for f in self.library.search("قانون")), [1, 2])
        self.assertEqual(self.library.shelves()[0]["files"], 1)

    def test_damaged_file_does_not_stop_the_app(self):
        self.library.close()
        damaged = self.root / "broken.sqlite3"
        damaged.write_bytes(b"this is not a database at all" * 100)
        recovered = Library(damaged)
        self.assertIsNotNone(recovered.recovered_from)
        self.assertEqual(recovered.channels(), [])
        recovered.close()
        self.library = Library(self.root / "library.sqlite3")

    def test_index_for_excel(self):
        self.add(1, "قانون.pdf", caption="سطر\nثاني")
        target = self.library.export_index(1, self.root / "out")
        text = target.read_text(encoding="utf-8-sig")
        self.assertIn("قانون.pdf", text)
        self.assertIn("https://t.me/law_library/1", text)
        # A private channel has no name to link by.
        self.library.save_channel({"id": 9, "username": "", "title": "خاصة"}, {**OPTIONS, "folder": str(self.root)})
        self.library.record(channel_id=9, msg_id=4, kind="pdf", name="ملف.pdf", path=str(self.root / "ملف.pdf"), status="done")
        text = self.library.export_index(9, self.root / "private").read_text(encoding="utf-8-sig")
        self.assertIn("https://t.me/c/9/4", text)

    def test_fold(self):
        self.assertEqual(fold("أَحْمَد إبراهيم مدرسة مستشفى ٢٠٢٤"), "احمد ابراهيم مدرسه مستشفي 2024")

    def test_favorites_and_your_own_shelves(self):
        self.add(1, "قانون العمل.pdf")
        self.add(2, "تعميم.pdf")
        favorites, = self.library.shelves()
        self.assertEqual((favorites["id"], favorites["favorites"], favorites["files"]), (1, True, 0))

        research = self.library.create_shelf("بحثي")
        self.library.put_on_shelf(1, 1, 1, True)
        self.library.put_on_shelf(research, 1, 1, True)
        self.library.put_on_shelf(research, 1, 2, True)
        self.library.put_on_shelf(research, 1, 2, True)  # twice is still once
        self.assertEqual([(s["name"], s["files"]) for s in self.library.shelves()], [("", 1), ("بحثي", 2)])
        self.assertEqual([f["name"] for f in self.library.shelf_files(research)], ["تعميم.pdf", "قانون العمل.pdf"])
        self.assertEqual(self.library.search("قانون")[0]["shelves"], [1, research])

        self.library.put_on_shelf(research, 1, 2, False)
        self.library.rename_shelf(research, "مراجع")
        self.assertEqual(self.library.shelf(research)["name"], "مراجع")
        self.library.delete_shelf(1)  # Favorites always stays
        self.library.delete_shelf(research)
        self.assertEqual([s["id"] for s in self.library.shelves()], [1])

    def test_removing_a_channel_takes_its_files_off_shelves(self):
        self.add(1, "قانون.pdf")
        self.library.put_on_shelf(1, 1, 1, True)
        self.library.remove_channel(1)
        self.assertEqual(self.library.shelves()[0]["files"], 0)
        self.assertEqual(self.library.db.execute("SELECT count(*) FROM shelf_files").fetchone()[0], 0)

    def test_files_for_the_trash_leave_out_what_other_channels_use(self):
        self.add(1, "قانون.pdf")
        self.add(2, "تعميم.pdf")
        self.add(3, "انحذف.pdf", exists=False)
        self.library.save_channel({"id": 2, "username": "other", "title": "ثانية"}, OPTIONS)
        shared = str(self.root / "تعميم.pdf")
        self.library.record(channel_id=2, msg_id=9, kind="pdf", name="تعميم.pdf", path=shared, status="duplicate")
        paths, kept = self.library.files_only_here(1)
        self.assertEqual(([Path(p).name for p in paths], kept), (["قانون.pdf"], 1))

    def test_a_moved_folder_is_not_deleted_files_and_can_be_found_again(self):
        folder = self.root / "قناة"
        self.library.save_channel(CHANNEL, {**OPTIONS, "folder": str(folder)})
        for msg_id, name in ((1, "2024/قانون.pdf"), (2, "2024/تعميم.pdf")):
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            self.library.record(channel_id=1, msg_id=msg_id, kind="pdf", name=path.name, path=str(path), status="done")

        moved = self.root / "هارد" / "قناة"
        moved.parent.mkdir()
        folder.rename(moved)
        channel = self.library.channel(1)
        self.assertEqual((channel["folderState"], channel["missing"]), ({"state": "missing"}, 0))

        self.assertEqual(self.library.relink(1, self.root)["found"], 0)  # wrong place: nothing changes
        self.assertEqual(self.library.channel(1)["folder"], str(folder))
        result = self.library.relink(1, moved.parent)  # picked the folder that holds it
        self.assertEqual((result["found"], result["folder"]), (2, str(moved)))
        self.assertEqual(self.library.file(1, 1)["path"], str(moved / "2024" / "قانون.pdf"))
        self.assertEqual(self.library.channel(1)["folderState"], {"state": "ok"})

    def test_a_drive_that_is_not_plugged_in(self):
        self.library.save_channel(CHANNEL, {**OPTIONS, "folder": "/Volumes/No Such Drive/تجميعة/قناة"})
        self.assertEqual(self.library.channel(1)["folderState"], {"state": "volume", "volume": "No Such Drive"})

    def test_private_channel_links_and_filters(self):
        self.library.save_channel({"id": 9, "username": "", "title": "خاصة", "accessHash": 4242, "group": True},
                                  {**OPTIONS, "filters": {"since": "2024-01-01", "until": "nonsense", "words": "  تعميم  ",
                                                          "maxMb": "50"}})
        channel = self.library.channel(9)
        self.assertEqual((channel["accessHash"], channel["private"], channel["group"]), (4242, True, True))
        self.assertEqual(channel["filters"], {"since": "2024-01-01", "until": "", "words": "تعميم", "maxMb": 50})
        self.library.record(channel_id=9, msg_id=5, kind="pdf", name="تعميم.pdf", path="", status="done")
        self.assertEqual(self.library.search("تعميم", channel_id=9)[0]["link"], "https://t.me/c/9/5")

        self.library.mark_synced(9, 300)
        self.library.set_filters(9, {})
        self.assertEqual(self.library.channel(9)["lastScannedId"], 0)  # look through the whole channel again


if __name__ == "__main__":
    unittest.main()
