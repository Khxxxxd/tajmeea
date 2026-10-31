import tempfile
import unittest
from pathlib import Path

from tajmeea_engine.naming import (build_filename, caption_title, classify, is_generic, other_extension, sanitize,
                                   unique_path)


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(classify("application/pdf", "x.pdf"), "pdf")
        self.assertEqual(classify("application/octet-stream", "تقرير.PDF"), "pdf")
        self.assertEqual(classify("audio/ogg", None), "audio")
        self.assertEqual(classify("", "book.epub"), "books")
        self.assertEqual(classify("video/mp4", "clip.mp4"), "videos")
        self.assertEqual(classify("image/jpeg", None), "images")
        self.assertIsNone(classify("application/x-msdownload", "setup.exe"))

    def test_unknown_extensions_are_kept_not_forced(self):
        self.assertIsNone(classify("image/vnd.adobe.photoshop", "logo.psd"))
        self.assertEqual(classify("video/x-msvideo", "clip.avi"), "videos")
        self.assertEqual(classify("image/png", None), "images")
        self.assertEqual(build_filename("logo.psd", "", 1, "other", "image/vnd.adobe.photoshop", True), "logo.psd")
        self.assertEqual(other_extension("README"), "")
        for program in ("setup.EXE", "app.apk", "run.command", "Tool.dmg", "x.pkg", "profile.mobileconfig"):
            self.assertIsNone(other_extension(program), program)

    def test_disguised_file_never_keeps_its_extension(self):
        self.assertEqual(classify("application/pdf", "invoice.command"), "pdf")
        self.assertEqual(build_filename("invoice.command", "", 5, "pdf", "application/pdf", True), "invoice.pdf")
        self.assertEqual(build_filename("agent.plist", "", 6, "word", "application/msword", True), "agent.docx")


class NamesTest(unittest.TestCase):
    def test_slash_in_law_names_is_kept(self):
        name = build_filename("قانون رقم 6/2010 بشأن العمل.pdf", "", 1, "pdf", "application/pdf", True)
        self.assertEqual(name, "قانون رقم 6-2010 بشأن العمل.pdf")

    def test_generic_names_take_the_caption(self):
        caption = "📌 مرسوم بقانون رقم 67 لسنة 1980 #قانون_مدني\nhttps://t.me/x/1"
        self.assertEqual(
            build_filename("document.pdf", caption, 2, "pdf", "application/pdf", True),
            "مرسوم بقانون رقم 67 لسنة 1980 قانون مدني.pdf",
        )
        self.assertEqual(build_filename("document.pdf", caption, 2, "pdf", "application/pdf", False), "document.pdf")
        self.assertEqual(build_filename(None, "", 9, "pdf", "application/pdf", True), "ملف 9.pdf")

    def test_generic_detection(self):
        for stem in ["document", "Document_5", "IMG_2041", "file (1)", "12345", "scan0003", "ملف", ""]:
            self.assertTrue(is_generic(stem), stem)
        for stem in ["قانون العمل", "Annual report", "تعميم 12"]:
            self.assertFalse(is_generic(stem), stem)

    def test_long_names_fit_the_disk(self):
        name = build_filename("مرسوم " * 80 + ".pdf", "", 3, "pdf", "application/pdf", True)
        self.assertLessEqual(len(name.encode("utf-8")), 255)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / name).write_bytes(b"ok")

    def test_invisible_and_unsafe_characters_are_removed(self):
        self.assertEqual(sanitize("‫تقرير‬: 2024?"), "تقرير- 2024")
        self.assertEqual(caption_title("@channel\n\n   \n🔥🔥 عنوان الملف 🔥"), "عنوان الملف")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = unique_path(folder, "a.pdf", 7)
            first.write_bytes(b"1")
            second = unique_path(folder, "a.pdf", 7)
            self.assertEqual(second.name, "a (7).pdf")
            second.write_bytes(b"2")
            self.assertEqual(unique_path(folder, "a.pdf", 7).name, "a (7-2).pdf")


if __name__ == "__main__":
    unittest.main()
