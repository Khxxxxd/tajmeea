import tempfile
import unittest
from pathlib import Path

from tajmeea_engine.library import Library
from tajmeea_engine.topics import MAX_SECTIONS, OTHER, Sections, sort_channel


def sort(files):
    sections = Sections(files)
    return [sections.of(name, caption) for name, caption in files]


def names(*titles):
    return [(f"{title}.pdf", "") for title in titles]


class SectionsTest(unittest.TestCase):
    def test_law_channel(self):
        files = names("قانون رقم 6 لسنة 2010 في شأن العمل", "القانون رقم 12 لسنة 2020", "قانون المرور",
                      "مرسوم بقانون رقم 1", "المرسوم رقم 5", "مرسوم أميري", "تعميم رقم 3", "تعميم بشأن الدوام",
                      "التعميم رقم 9", "الدستور")
        self.assertEqual(sort(files), ["قانون"] * 3 + ["مرسوم"] * 3 + ["تعميم"] * 3 + [OTHER])

    def test_study_channel_in_two_languages(self):
        files = names("محاضرة 1 - علم الأدوية", "مُحاضَرة 2", "المحاضرة الثالثة", "ملخص الفصل الأول", "ملخص 2",
                      "ملخص الباب الثالث", "Lecture 5 Pharmacology", "lecture 6", "Lecture 7")
        self.assertEqual(sort(files), ["محاضرة"] * 3 + ["ملخص"] * 3 + ["Lecture"] * 3)

    def test_hashtags_come_first_and_the_channel_signature_is_ignored(self):
        files = [(f"ملف {i}.pdf", f"شرح جديد\n#قناة_الطب #{'باطنية' if i % 2 else 'جراحة'}") for i in range(12)]
        self.assertEqual(sort(files), ["جراحة", "باطنية"] * 6)

    def test_hashtag_with_underscores_reads_as_words(self):
        files = [("x.pdf", "#قانون_المرور"), ("y.pdf", "#قانون_المرور"), ("z.pdf", "#قانون_المرور")]
        self.assertEqual(sort(files), ["قانون المرور"] * 3)

    def test_generic_file_names_use_the_post_title(self):
        files = [("document_55.pdf", "محاضرة 4 الكيمياء"), ("file.pdf", "محاضرة 5"), ("IMG_2231.pdf", "محاضرة 6")]
        self.assertEqual(sort(files), ["محاضرة"] * 3)

    def test_a_channel_with_no_pattern_has_no_sections(self):
        files = names("الأسود يليق بك", "مئة عام من العزلة", "Atomic Habits", "ساق البامبو", "The Alchemist")
        self.assertEqual(sort(files), [OTHER] * 5)

    def test_word_inside_another_word_does_not_count(self):
        self.assertEqual(sort(names("قرار 1", "قرار 2", "استقرار الأسعار")), [OTHER] * 3)

    def test_only_the_biggest_sections_are_kept(self):
        files = []
        for n in range(MAX_SECTIONS + 3):
            files += [(f"x{n}.pdf", f"#قسم{n}")] * (3 + n)
        kept = {section for section in sort(files) if section != OTHER}
        self.assertEqual(len(kept), MAX_SECTIONS)
        self.assertNotIn("قسم0", kept)


class SortChannelTest(unittest.TestCase):
    def test_old_files_are_resorted_with_new_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Library(Path(tmp) / "library.sqlite3")
            library.save_channel({"id": 5, "username": "c", "title": "c"}, {"folder": tmp, "kinds": ["pdf"]})
            for msg_id in (1, 2):
                library.record(channel_id=5, msg_id=msg_id, kind="pdf", name=f"ملخص {msg_id}.pdf", status="done",
                               topic="قوانين")
            sections = sort_channel(library, 5, [("ملخص 3.pdf", "")])
            self.assertEqual(sections.of("ملخص 3.pdf", ""), "ملخص")
            self.assertEqual(library.topics(), [{"topic": "ملخص", "files": 2}])
            library.close()


if __name__ == "__main__":
    unittest.main()
