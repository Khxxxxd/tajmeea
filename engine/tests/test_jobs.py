import asyncio
import errno
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tajmeea_engine.jobs import DownloadJob, Filters, JobOptions
from tajmeea_engine.library import Library

from fakes import PDF, Events, FakeClient, FakeMessage, RecordingSleep, expired_reference, flood

CHANNEL = {"id": 77, "username": "law_library", "title": "مكتبة القوانين"}


class CountedMessage(FakeMessage):
    """Counts how many downloads run at the same moment."""
    running = 0
    peak = 0

    async def download_media(self, file, progress_callback=None):
        CountedMessage.running += 1
        CountedMessage.peak = max(CountedMessage.peak, CountedMessage.running)
        try:
            await asyncio.sleep(0.01)
            return await super().download_media(file, progress_callback)
        finally:
            CountedMessage.running -= 1


class JobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.library = Library(self.root / "library.sqlite3")
        self.events = Events()
        self.sleep = RecordingSleep()

    def tearDown(self):
        self.library.close()
        self.tmp.cleanup()

    def job(self, client, kinds=("pdf",), year_folders=False, smart=True, channel=CHANNEL, prefetched=None):
        self.library.save_channel(channel, {"folder": str(self.out), "kinds": list(kinds)})
        return DownloadJob(
            channel=self.library.channel(channel["id"]),
            entity=object(),
            client=client,
            library=self.library,
            emit=self.events,
            options=JobOptions(kinds=set(kinds), folder=self.out, year_folders=year_folders, smart_names=smart),
            prefetched=prefetched,
            sleep=self.sleep,
        )

    def run_job(self, job):
        return asyncio.run(job.run())

    def files(self, folder=None):
        folder = folder or self.out
        return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())

    def test_normal_channel(self):
        client = FakeClient([
            FakeMessage(1, "قانون رقم 6/2010 بشأن العمل.pdf"),
            FakeMessage(2, "notes.docx", mime="application/msword", body=b"PK..."),
            FakeMessage(3, "document.pdf", caption="مرسوم بقانون رقم 67 لسنة 1980"),
        ])
        result = self.run_job(self.job(client))
        self.assertEqual(result["state"], "done")
        self.assertEqual((result["total"], result["done"], result["processed"]), (2, 2, 2))
        self.assertEqual(result["bytesDone"], result["bytesTotal"])
        self.assertEqual(self.files(), [
            "فهرس تجميعة.csv",
            "قانون رقم 6-2010 بشأن العمل.pdf",
            "مرسوم بقانون رقم 67 لسنة 1980.pdf",
        ])
        self.assertEqual(self.library.channel(77)["lastScannedId"], 3)
        self.assertEqual(self.events.states()[:3], ["scanning", "running", "done"])

    def test_second_run_only_takes_new_files(self):
        client = FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, "b.pdf")])
        self.run_job(self.job(client))
        again = self.run_job(self.job(client))
        self.assertEqual(again["total"], 0)
        client.add(FakeMessage(3, "c.pdf"))
        third = self.run_job(self.job(client))
        self.assertEqual((third["total"], third["done"]), (1, 1))
        self.assertIn("c.pdf", self.files())

    def test_network_drop_is_retried_without_leftovers(self):
        flaky = FakeMessage(2, "b.pdf", failures=[ConnectionError("drop")])
        client = FakeClient([FakeMessage(1, "a.pdf"), flaky, FakeMessage(3, "c.pdf")])
        result = self.run_job(self.job(client))
        self.assertEqual((result["done"], result["failed"]), (3, 0))
        self.assertEqual((flaky.attempts, client.resumed), (1, [(2, 0)]))  # the second try continued the part
        self.assertEqual((self.out / "b.pdf").read_bytes(), flaky.body)
        self.assertFalse([p for p in self.out.rglob("*.part")])

    def test_one_broken_file_never_stops_the_rest(self):
        broken = FakeMessage(2, "b.pdf", failures=[ConnectionError("x")] * 10)
        client = FakeClient([FakeMessage(1, "a.pdf"), broken, FakeMessage(3, "c.pdf")])
        result = self.run_job(self.job(client))
        self.assertEqual((result["state"], result["done"], result["failed"]), ("done", 2, 1))
        self.assertEqual(self.library.file(77, 2)["status"], "failed")
        broken.failures = []
        retry = self.run_job(self.job(client))
        self.assertEqual((retry["total"], retry["done"]), (1, 1))
        self.assertTrue((self.out / "b.pdf").exists())

    def test_telegram_wait_is_shown_and_respected(self):
        slow = FakeMessage(2, "b.pdf", failures=[flood(120)])
        client = FakeClient([FakeMessage(1, "a.pdf"), slow], scan_flood_once=True)
        result = self.run_job(self.job(client))
        self.assertEqual(result["done"], 2)
        self.assertIn(121, self.sleep.calls)
        self.assertIn(3, self.sleep.calls)
        self.assertIn("waiting", self.events.states())

    def test_expired_file_reference_is_refreshed(self):
        message = FakeMessage(1, "a.pdf", failures=[expired_reference()])
        result = self.run_job(self.job(FakeClient([message])))
        self.assertEqual(result["done"], 1)

    def test_fake_pdf_is_rejected_and_extensions_are_forced(self):
        client = FakeClient([
            FakeMessage(1, "invoice.command", body=b"#!/bin/sh\necho pwned\n"),
            FakeMessage(2, "agent.plist", body=PDF),
        ])
        result = self.run_job(self.job(client))
        self.assertEqual((result["done"], result["rejected"]), (1, 1))
        self.assertEqual(self.files(), ["agent.pdf", "فهرس تجميعة.csv"])
        self.assertEqual(self.library.file(77, 1)["status"], "rejected")

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_files_are_tagged_like_browser_downloads(self):
        self.run_job(self.job(FakeClient([FakeMessage(1, "a.pdf")])))
        attrs = subprocess.run(["xattr", str(self.out / "a.pdf")], capture_output=True, text=True).stdout
        self.assertIn("com.apple.quarantine", attrs)

    def test_same_file_in_two_channels_is_kept_once(self):
        self.run_job(self.job(FakeClient([FakeMessage(1, "a.pdf", doc_id=999)])))
        other = {"id": 78, "username": "other_channel", "title": "قناة ثانية"}
        result = self.run_job(self.job(FakeClient([FakeMessage(50, "copy.pdf", doc_id=999)]), channel=other))
        self.assertEqual((result["done"], result["skipped"]), (0, 1))
        self.assertEqual(self.library.file(78, 50)["status"], "duplicate")
        self.assertNotIn("copy.pdf", self.files())

    def test_year_folders_and_name_clashes(self):
        client = FakeClient([FakeMessage(1, "a.pdf", year=2019), FakeMessage(2, "a.pdf", year=2019),
                             FakeMessage(3, "a.pdf", year=2024)])
        self.run_job(self.job(client, year_folders=True))
        self.assertEqual(self.files(), ["2019/a (2).pdf", "2019/a.pdf", "2024/a.pdf", "فهرس تجميعة.csv"])

    def test_prefetched_scan_is_used_and_kinds_are_respected(self):
        messages = [FakeMessage(1, "a.pdf"), FakeMessage(2, "song.mp3", mime="audio/mpeg", body=b"ID3...")]
        client = FakeClient([])
        result = self.run_job(self.job(client, kinds=("pdf", "audio"), prefetched=messages))
        self.assertEqual(result["done"], 2)
        self.assertIn("song.mp3", self.files())

    def test_pause_and_resume(self):
        async def scenario():
            job = self.job(FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, "b.pdf")]))
            job.pause()
            task = asyncio.ensure_future(job.run())
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            self.assertFalse((self.out / "a.pdf").exists())
            job.resume()
            return await task
        result = asyncio.run(scenario())
        self.assertEqual(result["done"], 2)

    def test_stop_mid_file_leaves_no_half_file_under_its_name(self):
        async def scenario():
            job = self.job(FakeClient([FakeMessage(1, "a.pdf", hang=True)]))
            task = asyncio.ensure_future(job.run())
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return job
        job = asyncio.run(scenario())
        self.assertEqual(job.progress.state, "stopped")
        # Only the hidden part stays, for the next run to continue.
        self.assertEqual([p.name for p in self.out.rglob("*") if p.is_file()], [".a.pdf.part"])

    def test_stopping_and_coming_back_days_later_continues_without_duplicates(self):
        stuck = FakeMessage(3, "c.pdf", hang=True)
        client = FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, "b.pdf"), stuck, FakeMessage(4, "d.pdf")])

        async def stop_while_one_file_is_stuck():
            job = self.job(client)
            task = asyncio.ensure_future(job.run())
            # Three download at once, so the others finish while c hangs.
            while not ((self.out / ".c.pdf.part").exists() and (self.out / "d.pdf").exists()):
                await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(stop_while_one_file_is_stuck())
        self.assertEqual(self.files(), [".c.pdf.part", "a.pdf", "b.pdf", "d.pdf"])

        stuck.hang = False
        client.add(FakeMessage(5, "e.pdf"))  # posted while we were away
        result = self.run_job(self.job(client))
        self.assertEqual((result["total"], result["done"]), (2, 2))
        self.assertEqual(self.files(), ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf", "فهرس تجميعة.csv"])
        self.assertEqual([client.messages[i].attempts for i in (1, 2, 4)], [1, 1, 1])

    def test_same_file_posted_twice_is_kept_once(self):
        same = PDF + b"the very same law"
        client = FakeClient([FakeMessage(1, "قانون.pdf", body=same), FakeMessage(9, "قانون (نسخة).pdf", body=same)])
        result = self.run_job(self.job(client))
        self.assertEqual((result["done"], result["skipped"]), (1, 1))
        self.assertEqual(self.files(), ["فهرس تجميعة.csv", "قانون.pdf"])
        self.assertEqual(self.library.file(77, 9)["status"], "duplicate")

    def test_files_you_deleted_stay_deleted_until_you_ask(self):
        client = FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, "b.pdf")])
        self.run_job(self.job(client))
        (self.out / "a.pdf").unlink()
        again = self.run_job(self.job(client))
        self.assertEqual(again["total"], 0)
        self.assertFalse((self.out / "a.pdf").exists())
        job = self.job(client)
        job.options.restore_missing = True
        back = self.run_job(job)
        self.assertEqual((back["total"], back["done"]), (1, 1))
        self.assertTrue((self.out / "a.pdf").exists())

    def test_a_file_removed_in_the_app_is_never_downloaded_again(self):
        client = FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, "b.pdf")])
        self.run_job(self.job(client))
        self.library.remove_file(77, 1)
        (self.out / "a.pdf").unlink()  # what the Trash does
        self.library.trashed(77, 1, moved=True)
        self.library.set_filters(77, {})  # the whole channel is looked through again
        job = self.job(client)
        job.options.restore_missing = True  # even «bring back what I deleted» leaves it out
        again = self.run_job(job)
        self.assertEqual(again["total"], 0)
        self.assertFalse((self.out / "a.pdf").exists())
        self.assertEqual(self.library.file(77, 1)["status"], "trashed")

    def test_folder_per_section(self):
        client = FakeClient([
            FakeMessage(1, "محاضرة 1.pdf"), FakeMessage(2, "محاضرة 2.pdf"), FakeMessage(3, "المحاضرة 3.pdf"),
            FakeMessage(4, "ملخص الباب الأول.pdf"), FakeMessage(5, "ملخص الباب الثاني.pdf"),
            FakeMessage(6, "ملخص الباب الثالث.pdf"), FakeMessage(7, "جدول الامتحانات.pdf", year=2020),
        ])
        job = self.job(client, year_folders=True)
        job.options.topic_folders = True
        self.run_job(job)
        self.assertEqual(self.files(), [
            "أخرى/2020/جدول الامتحانات.pdf", "فهرس تجميعة.csv",
            "محاضرة/2024/المحاضرة 3.pdf", "محاضرة/2024/محاضرة 1.pdf", "محاضرة/2024/محاضرة 2.pdf",
            "ملخص/2024/ملخص الباب الأول.pdf", "ملخص/2024/ملخص الباب الثالث.pdf", "ملخص/2024/ملخص الباب الثاني.pdf",
        ])
        self.assertEqual({t["topic"]: t["files"] for t in self.library.topics()}, {"محاضرة": 3, "ملخص": 3, "أخرى": 1})

    def test_sections_follow_the_channel_as_it_grows(self):
        client = FakeClient([FakeMessage(1, "تعميم 1.pdf"), FakeMessage(2, "تعميم 2.pdf")])
        self.run_job(self.job(client))
        self.assertEqual(self.library.topics(), [{"topic": "أخرى", "files": 2}])
        client.add(FakeMessage(3, "تعميم 3.pdf"))
        self.run_job(self.job(client))
        self.assertEqual(self.library.topics(), [{"topic": "تعميم", "files": 3}])

    def test_photos_and_videos(self):
        client = FakeClient([
            FakeMessage(1, "a.pdf"),
            FakeMessage(2, None, body=b"\xff\xd8jpeg", mime="image/jpeg", photo=True, caption="صورة الوثيقة الأصلية"),
            FakeMessage(3, "clip.mp4", body=b"....ftypmp4", mime="video/mp4"),
        ])
        result = self.run_job(self.job(client, kinds=("pdf", "images", "videos")))
        self.assertEqual(result["done"], 3)
        self.assertEqual(self.files(), ["a.pdf", "clip.mp4", "صورة الوثيقة الأصلية.jpg", "فهرس تجميعة.csv"])

    def test_full_disk_stops_with_a_clear_message(self):
        full = OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        result = self.run_job(self.job(FakeClient([FakeMessage(1, "a.pdf", failures=[full])])))
        self.assertEqual((result["state"], result["errorCode"]), ("failed", "disk_full"))
        self.assertIn("المساحة", result["error"])


    # Filters

    def test_filters_keep_only_what_you_asked_for(self):
        client = FakeClient([
            FakeMessage(1, "تعميم الدوام.pdf", year=2023),
            FakeMessage(2, "تعميم العطلة.pdf", year=2024),
            FakeMessage(3, "قرار وزاري.pdf", year=2024, caption="تعميم مرفق"),
            FakeMessage(4, "تعميم كبير.pdf", year=2024, body=PDF + b"x" * (2 * 1024 * 1024)),
            FakeMessage(5, "جدول.pdf", year=2024),
        ])
        job = self.job(client)
        job.options.filters = Filters(since="2024-01-01", words="تعميم", max_mb=1)
        result = self.run_job(job)
        self.assertEqual(result["done"], 2)
        self.assertEqual(self.files(), ["تعميم العطلة.pdf", "فهرس تجميعة.csv", "قرار وزاري.pdf"])

    def test_filter_words_ignore_arabic_spelling_differences(self):
        allowed = Filters(words="لائحة").allows
        self.assertTrue(allowed({"date": None, "size": 1, "name": "اللائحه التنفيذية.pdf", "caption": ""}))
        self.assertFalse(allowed({"date": None, "size": 1, "name": "قانون.pdf", "caption": ""}))

    # Several at once

    def test_three_files_download_at_once_and_progress_adds_up(self):
        CountedMessage.peak = 0
        client = FakeClient([CountedMessage(i, f"ملف {i}.pdf") for i in range(1, 8)])
        result = self.run_job(self.job(client))
        self.assertEqual(CountedMessage.peak, 3)
        self.assertEqual(result["done"], 7)
        self.assertEqual(result["bytesDone"], result["bytesTotal"])
        self.assertEqual((result["active"], result["current"]), ([], None))

    def test_files_with_the_same_name_at_the_same_time_never_overwrite(self):
        client = FakeClient([CountedMessage(i, "تعميم.pdf") for i in (1, 2, 3)])
        result = self.run_job(self.job(client))
        self.assertEqual(result["done"], 3)
        self.assertEqual(self.files(), ["تعميم (2).pdf", "تعميم (3).pdf", "تعميم.pdf", "فهرس تجميعة.csv"])

    def test_posts_with_saving_turned_off_are_left_alone(self):
        locked = FakeMessage(2, "خاص.pdf")
        locked.noforwards = True
        result = self.run_job(self.job(FakeClient([FakeMessage(1, "عام.pdf"), locked])))
        self.assertEqual((result["total"], result["done"]), (1, 1))
        self.assertEqual(self.files(), ["عام.pdf", "فهرس تجميعة.csv"])

    # Tracks, voice notes, round videos

    def test_tracks_voice_notes_and_round_videos_come_from_their_own_lists(self):
        client = FakeClient([
            FakeMessage(1, "a.pdf"),
            FakeMessage(2, None, mime="audio/mpeg", body=b"ID3track", music=True, performer="مشاري", title="سورة الكهف"),
            FakeMessage(3, None, mime="audio/ogg", body=b"OggSone", voice=True, caption="درس الفجر"),
            FakeMessage(4, None, mime="audio/ogg", body=b"OggStwo", voice=True),
            FakeMessage(5, None, mime="video/mp4", body=b"....ftypround", round_video=True),
        ])
        result = self.run_job(self.job(client, kinds=("pdf", "audio", "voice", "videos")))
        self.assertEqual(result["done"], 5)
        self.assertEqual(self.files(), ["a.pdf", "بصمة 4.ogg", "درس الفجر.ogg", "فهرس تجميعة.csv", "فيديو 5.mp4",
                                        "مشاري - سورة الكهف.mp3"])

    def test_only_the_lists_for_what_you_chose_are_read(self):
        client = FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, None, mime="audio/ogg", body=b"OggS", voice=True)])
        self.run_job(self.job(client, kinds=("pdf",)))
        self.assertEqual(client.asked, ["Document"])
        self.assertEqual(self.files(), ["a.pdf", "فهرس تجميعة.csv"])

    # Other files

    def test_other_files_keep_their_extension_and_programs_never_land(self):
        client = FakeClient([
            FakeMessage(1, "شعار.psd", mime="image/vnd.adobe.photoshop", body=b"8BPS"),
            FakeMessage(2, "خط جميل.ttf", mime="font/ttf", body=b"\x00\x01ttf"),
            FakeMessage(3, "ترجمة.srt", mime="application/x-subrip", body=b"1\n00:00"),
            FakeMessage(4, "README", mime="application/octet-stream", body=b"read me"),
            FakeMessage(5, "setup.exe", mime="application/x-msdownload", body=b"MZ"),
            FakeMessage(6, "تطبيق.apk", mime="application/vnd.android.package-archive", body=b"PK"),
            FakeMessage(7, "invoice.pdf.command", mime="application/octet-stream", body=b"#!/bin/sh"),
            FakeMessage(8, "clip.avi", mime="video/x-msvideo", body=b"RIFFavi"),
        ])
        job = self.job(client, kinds=("other", "videos"))
        job.options.skip_exts = {".srt"}
        result = self.run_job(job)
        self.assertEqual((result["total"], result["done"]), (4, 4))  # programs and the turned-off .srt never count
        self.assertEqual(self.files(), ["README", "clip.avi", "خط جميل.ttf", "شعار.psd", "فهرس تجميعة.csv"])

    # Space

    def test_not_enough_space_stops_before_any_file(self):
        client = FakeClient([FakeMessage(1, "a.pdf"), FakeMessage(2, "b.pdf")])
        with mock.patch("tajmeea_engine.paths.free_bytes", return_value=100 * 1024 * 1024):
            result = self.run_job(self.job(client))
        self.assertEqual((result["state"], result["errorCode"], result["done"]), ("failed", "disk_space", 0))
        self.assertIn("المساحة ما تكفي", result["error"])
        self.assertFalse(self.out.exists() and any(self.out.rglob("*.pdf")))

    # Continuing a cut-off file

    def stop_midway(self, client, part):
        async def scenario():
            task = asyncio.ensure_future(self.job(client).run())
            while not part.exists():
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(scenario())

    def test_a_cut_off_file_continues_from_where_it_stopped(self):
        body = PDF + b"x" * (3 * 1024 * 1024)
        big = FakeMessage(1, "كبير.pdf", body=body, hang=True)
        client = FakeClient([big])
        self.stop_midway(client, self.out / ".كبير.pdf.part")
        big.hang = False
        result = self.run_job(self.job(client))
        self.assertEqual((result["done"], result["bytesDone"]), (1, len(body)))
        self.assertEqual((self.out / "كبير.pdf").read_bytes(), body)
        self.assertEqual(client.resumed, [(1, 3 * 512 * 1024)])  # half the file, rounded down to a 512 KB step
        self.assertEqual(big.attempts, 1)  # the whole-file download never ran again

    def test_a_part_that_cannot_be_continued_starts_over(self):
        body = PDF + b"y" * (2 * 1024 * 1024)
        big = FakeMessage(1, "كبير.pdf", body=body, hang=True)
        client = FakeClient([big])
        self.stop_midway(client, self.out / ".كبير.pdf.part")
        big.hang = False
        client.resume_fails = True
        result = self.run_job(self.job(client))
        self.assertEqual(result["done"], 1)
        self.assertEqual((self.out / "كبير.pdf").read_bytes(), body)
        self.assertEqual(big.attempts, 2)

    # Files already in the folder

    def test_files_already_in_the_folder_are_kept_not_downloaded_again(self):
        client = FakeClient([FakeMessage(1, "قانون.pdf"), FakeMessage(2, "تعميم.pdf")])
        self.out.mkdir(parents=True)
        (self.out / "قانون.pdf").write_bytes(client.messages[1].body)  # left from before the channel was removed
        (self.out / "تعميم.pdf").write_bytes(PDF + b"another file, another size")
        result = self.run_job(self.job(client))
        self.assertEqual((result["done"], result["skipped"]), (1, 1))
        self.assertEqual(client.messages[1].attempts, 0)
        self.assertEqual(self.library.file(77, 1)["status"], "done")
        self.assertEqual(self.files(), ["تعميم (2).pdf", "تعميم.pdf", "فهرس تجميعة.csv", "قانون.pdf"])


if __name__ == "__main__":
    unittest.main()
