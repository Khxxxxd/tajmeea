"""The whole path a person takes: sign in, look at a channel, download it, update it, search it."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import keyring
from telethon import types
from telethon.tl.functions.channels import GetFullChannelRequest

from tajmeea_engine.errors import UserError
from tajmeea_engine.library import Library
from tajmeea_engine.telegram import TelegramService, qr_matrix
from tajmeea_engine.vault import ApiKey, Vault

from fakes import Events, FakeClient, FakeMessage, MemoryKeyring


NOW = datetime.now(timezone.utc)
LAW = types.Channel(id=77, title="مكتبة القوانين", photo=types.ChatPhotoEmpty(), date=NOW, username="law_library",
                    access_hash=1)
PRIVATE_GROUP = types.Channel(id=88, title="ملفات الدفعة", photo=types.ChatPhotoEmpty(), date=NOW, username=None,
                              access_hash=555, megagroup=True)
LOCKED = types.Channel(id=99, title="قناة مقفلة", photo=types.ChatPhotoEmpty(), date=NOW, username="locked",
                       access_hash=9, noforwards=True)
CHATS = [LAW, types.User(id=5, first_name="صديق"), PRIVATE_GROUP, LOCKED,
         types.Chat(id=6, title="قروب قديم", photo=types.ChatPhotoEmpty(), participants_count=3, date=NOW, version=1)]


def make_factory(fake: FakeClient):
    class FakeTelegram:
        def __init__(self, session, api_id, api_hash, **kwargs):
            self.connected = False
            self.session = SimpleNamespace(save=lambda: "saved-session")

        def is_connected(self):
            return self.connected

        async def connect(self):
            self.connected = True

        async def disconnect(self):
            self.connected = False

        async def is_user_authorized(self):
            return True

        async def get_me(self):
            return SimpleNamespace(first_name="سارة", last_name="", username="sara", phone="96512345678")

        async def get_entity(self, wanted):
            if isinstance(wanted, types.InputPeerChannel):
                for chat in (LAW, PRIVATE_GROUP, LOCKED):
                    if (chat.id, chat.access_hash) == (wanted.channel_id, wanted.access_hash):
                        return chat
                raise ValueError("Could not find the input entity")
            if wanted in ("law_library", "locked"):
                return LAW if wanted == "law_library" else LOCKED
            if wanted == "some_person":
                return types.User(id=5, first_name="x")
            raise ValueError(f'No user has "{wanted}" as username')

        async def iter_dialogs(self):
            for chat in CHATS:
                yield SimpleNamespace(entity=chat)

        async def __call__(self, request):
            if isinstance(request, GetFullChannelRequest):
                return SimpleNamespace(full_chat=SimpleNamespace(participants_count=18400, about="قوانين الكويت"))
            raise AssertionError(request)

        async def download_profile_photo(self, entity, file=None, download_big=False):
            return b"\xff\xd8photo"

        def iter_messages(self, *args, **kwargs):
            return fake.iter_messages(*args, **kwargs)

        async def get_messages(self, *args, **kwargs):
            return await fake.get_messages(*args, **kwargs)

    return FakeTelegram


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        keyring.set_keyring(MemoryKeyring())
        self.vault = Vault("Tajmeea (test)")
        self.vault.save_api_key(ApiKey(2041733, "7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60"))
        self.library = Library(self.root / "library.sqlite3")
        self.events = Events()
        self.telegram = FakeClient([
            FakeMessage(1, "قانون العمل.pdf"),
            FakeMessage(2, "تعميم.pdf", caption="بخصوص ساعات العمل"),
            FakeMessage(3, "جدول.xlsx", mime="application/vnd.ms-excel", body=b"PK.."),
        ])
        self.service = TelegramService(self.vault, self.library, self.events, client_factory=make_factory(self.telegram))

    def tearDown(self):
        self.library.close()
        self.tmp.cleanup()

    async def finish_jobs(self):
        while self.service._worker and not self.service._worker.done():
            await self.service._worker

    def test_full_journey(self):
        async def journey():
            state = await self.service.status()
            self.assertTrue(state["authorized"])
            self.assertEqual(state["me"]["phone"], "+965•••78")

            scan = await self.service.inspect("https://t.me/law_library/1")
            self.assertEqual(scan["channel"]["members"], 18400)
            self.assertTrue(scan["channel"]["photo"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(scan["kinds"]["pdf"]["count"], 2)
            self.assertEqual(scan["kinds"]["excel"]["count"], 1)
            self.assertIsNone(scan["existing"])

            folder = self.root / "مكتبة القوانين"
            added = await self.service.add(channelId=77, kinds=["pdf"], folder=str(folder), yearFolders=False)
            self.assertEqual(added["job"]["state"], "queued")
            await self.finish_jobs()

            detail = self.service.channel_detail(77)
            self.assertEqual((detail["files"], detail["job"]["state"]), (2, "done"))
            self.assertEqual(len(detail["recent"]), 2)
            self.assertTrue((folder / "قانون العمل.pdf").exists())

            self.telegram.add(FakeMessage(4, "جديد.pdf"))
            await self.service.update(77)
            await self.finish_jobs()
            self.assertEqual(self.service.channel_detail(77)["files"], 3)
            self.assertEqual(self.service.job_snapshot(77)["total"], 1)

            results = self.library.search("ساعات العمل")
            self.assertEqual(results[0]["name"], "تعميم.pdf")
            self.assertTrue(any(e["event"] == "channels.changed" for e in self.events.items))

        asyncio.run(journey())

    def test_auto_update_runs_for_stale_channels_only(self):
        async def scenario():
            await self.service.inspect("law_library")
            await self.service.add(channelId=77, kinds=["pdf"], folder=str(self.root / "out"), autoUpdate=True)
            await self.finish_jobs()
            self.telegram.add(FakeMessage(5, "لاحق.pdf"))
            await self.service.auto_sync()
            await self.finish_jobs()
            self.assertEqual(self.service.channel_detail(77)["files"], 2)
            self.library.db.execute("UPDATE channels SET last_sync='2020-01-01T00:00:00+00:00'")
            await self.service.auto_sync()
            await self.finish_jobs()
            self.assertEqual(self.service.channel_detail(77)["files"], 3)

        asyncio.run(scenario())

    def test_wrong_links_get_clear_errors(self):
        async def scenario():
            for link, code in [("t.me/some_person", "not_channel"), ("t.me/nobody_here", "not_found")]:
                with self.assertRaises(UserError) as caught:
                    await self.service.inspect(link)
                self.assertEqual(caught.exception.code, code)
            with self.assertRaises(UserError) as caught:
                await self.service.add(channelId=999, kinds=["pdf"], folder=str(self.root))
            self.assertEqual(caught.exception.code, "rescan")
            await self.service.inspect("law_library")
            with self.assertRaises(UserError) as caught:
                await self.service.add(channelId=77, kinds=["pdf"], folder="/System/not-allowed")
            self.assertEqual(caught.exception.code, "folder")

        asyncio.run(scenario())

    def test_pick_a_channel_from_your_own_chats(self):
        async def scenario():
            mine = await self.service.my_channels()
            self.assertEqual([(c["id"], c["private"], c["group"], c["protected"]) for c in mine],
                             [(77, False, False, False), (88, True, True, False), (99, False, False, True)])

            scan = await self.service.inspect(channelId=88)
            self.assertEqual((scan["channel"]["title"], scan["channel"]["private"]), ("ملفات الدفعة", True))
            self.assertNotIn("accessHash", scan["channel"])
            await self.service.add(channelId=88, kinds=["pdf"], folder=str(self.root / "دفعة"))
            await self.finish_jobs()
            self.assertEqual(self.service.channel_detail(88)["files"], 2)

            # Later, with no username to go by, the saved hash finds it again.
            self.telegram.add(FakeMessage(4, "جديد.pdf"))
            await self.service.update(88)
            await self.finish_jobs()
            self.assertEqual(self.service.channel_detail(88)["files"], 3)
            self.assertTrue((await self.service.my_channels())[1]["added"])

            for attempt in (lambda: self.service.inspect(channelId=99), lambda: self.service.inspect("t.me/locked")):
                with self.assertRaises(UserError) as caught:
                    await attempt()
                self.assertEqual(caught.exception.code, "protected")

        asyncio.run(scenario())

    def test_filters_count_before_and_apply_after(self):
        async def scenario():
            await self.service.inspect("law_library")
            counted = self.service.count(77, {"words": "تعميم"})
            self.assertEqual((counted["kinds"]["pdf"]["count"], counted["kinds"]["excel"]["count"]), (1, 0))

            await self.service.add(channelId=77, kinds=["pdf"], folder=str(self.root / "out"), yearFolders=False,
                                   filters={"words": "تعميم"})
            await self.finish_jobs()
            self.assertEqual(sorted(p.name for p in (self.root / "out").glob("*.pdf")), ["تعميم.pdf"])

            await self.service.set_filters(77, {})  # filter removed: the rest of the channel comes down
            await self.finish_jobs()
            self.assertEqual(sorted(p.name for p in (self.root / "out").glob("*.pdf")), ["تعميم.pdf", "قانون العمل.pdf"])

        asyncio.run(scenario())

    def test_removing_a_channel_can_hand_its_files_to_the_trash(self):
        async def scenario():
            await self.service.inspect("law_library")
            folder = self.root / "تجميعة" / "مكتبة القوانين"
            await self.service.add(channelId=77, kinds=["pdf"], folder=str(folder), yearFolders=False)
            await self.finish_jobs()
            with mock.patch("tajmeea_engine.paths.default_download_root", return_value=self.root / "تجميعة"):
                result = self.service.remove(77, trashFiles=True)
            trash = result["trash"]
            self.assertEqual(sorted(Path(p).name for p in trash["paths"]), ["تعميم.pdf", "فهرس تجميعة.csv", "قانون العمل.pdf"])
            self.assertEqual((trash["folder"], trash["ownFolder"], trash["shared"]), (str(folder), True, 0))
            self.assertIsNone(self.library.channel(77))
            self.assertTrue((folder / "قانون العمل.pdf").exists())  # the engine itself never deletes anything

            await self.service.inspect("law_library")
            await self.service.add(channelId=77, kinds=["pdf"], folder=str(self.root / "elsewhere"))
            await self.finish_jobs()
            self.assertIsNone(self.service.remove(77)["trash"])  # plain remove: files stay, nothing to trash

        asyncio.run(scenario())

    def test_scan_lists_other_formats_and_the_programs_it_leaves_out(self):
        async def scenario():
            for message in (
                FakeMessage(10, "شعار.psd", mime="image/vnd.adobe.photoshop", body=b"8BPS"),
                FakeMessage(11, "شعار 2.psd", mime="image/vnd.adobe.photoshop", body=b"8BPS2"),
                FakeMessage(12, "خط.ttf", mime="font/ttf", body=b"ttf"),
                FakeMessage(13, "setup.exe", mime="application/x-msdownload", body=b"MZ"),
                FakeMessage(14, None, mime="audio/ogg", body=b"OggS", voice=True),
            ):
                self.telegram.add(message)
            scan = await self.service.inspect("law_library")
            self.assertEqual([(o["ext"], o["count"]) for o in scan["others"]], [(".psd", 2), (".ttf", 1)])
            self.assertEqual(scan["blocked"], {"count": 1, "exts": [".exe"]})
            self.assertEqual((scan["kinds"]["other"]["count"], scan["kinds"]["voice"]["count"]), (3, 1))
            counted = self.service.count(77, {"words": "شعار"})
            self.assertEqual([(o["ext"], o["count"]) for o in counted["others"]], [(".psd", 2)])

            await self.service.add(channelId=77, kinds=["other"], folder=str(self.root / "o"), yearFolders=False,
                                   skipExts=[".TTF"])
            await self.finish_jobs()
            self.assertEqual(self.library.channel(77)["skipExts"], [".ttf"])
            self.assertEqual(sorted(p.name for p in (self.root / "o").iterdir()), ["شعار 2.psd", "شعار.psd", "فهرس تجميعة.csv"])

        asyncio.run(scenario())

    def test_a_download_cut_off_by_quitting_carries_on_at_the_next_start(self):
        async def scenario():
            stuck = FakeMessage(5, "عالق.pdf", hang=True)
            self.telegram.add(stuck)
            await self.service.inspect("law_library")
            folder = self.root / "out"
            await self.service.add(channelId=77, kinds=["pdf"], folder=str(folder), yearFolders=False)
            while not (folder / ".عالق.pdf.part").exists():
                await asyncio.sleep(0.01)
            await self.service.stop_all()  # what quitting the app does
            self.assertEqual(self.library.channel(77)["pending"], 1)

            stuck.hang = False
            again = TelegramService(self.vault, self.library, self.events, client_factory=make_factory(self.telegram))
            await again.resume_pending()
            while again._worker and not again._worker.done():
                await again._worker
            self.assertTrue((folder / "عالق.pdf").exists())
            self.assertEqual(self.library.channel(77)["pending"], 0)

        asyncio.run(scenario())

    def test_pausing_or_cancelling_means_no_restart_by_itself(self):
        async def scenario():
            self.telegram.add(FakeMessage(5, "عالق.pdf", hang=True))
            await self.service.inspect("law_library")
            await self.service.add(channelId=77, kinds=["pdf"], folder=str(self.root / "out"))
            await asyncio.sleep(0.05)
            self.service.pause(77)
            self.assertEqual(self.library.channel(77)["pending"], 0)
            self.service.resume(77)
            self.assertEqual(self.library.channel(77)["pending"], 1)
            self.service.cancel(77)
            self.assertEqual(self.library.channel(77)["pending"], 0)
            await self.finish_jobs()

        asyncio.run(scenario())

    def test_a_missing_folder_is_never_filled_by_surprise(self):
        async def scenario():
            await self.service.inspect("law_library")
            folder = self.root / "out"
            await self.service.add(channelId=77, kinds=["pdf"], folder=str(folder), yearFolders=False)
            await self.finish_jobs()
            folder.rename(self.root / "moved")
            with self.assertRaises(UserError) as caught:
                await self.service.update(77)
            self.assertEqual(caught.exception.code, "folder_missing")
            with self.assertRaises(UserError) as caught:
                self.service.relink(77, str(self.root / "nowhere"))
            self.assertEqual(caught.exception.code, "relink_none")

            # Asked for on purpose: the folder is made again and everything comes back.
            await self.service.update(77, recreateFolder=True)
            await self.finish_jobs()
            self.assertEqual(sorted(p.name for p in folder.glob("*.pdf")), ["تعميم.pdf", "قانون العمل.pdf"])

        asyncio.run(scenario())

    def test_no_space_is_reported_and_not_retried_at_every_start(self):
        async def scenario():
            await self.service.inspect("law_library")
            with mock.patch("tajmeea_engine.paths.free_bytes", return_value=1024):
                self.assertEqual(self.service.free_space(str(self.root))["free"], 0)
                await self.service.add(channelId=77, kinds=["pdf"], folder=str(self.root / "out"))
                await self.finish_jobs()
            self.assertEqual(self.service.job_snapshot(77)["errorCode"], "disk_space")
            self.assertEqual(self.library.channel(77)["pending"], 0)

        asyncio.run(scenario())

    def test_qr_matrix_is_square(self):
        matrix = qr_matrix("tg://login?token=AbCdEf123456")
        self.assertEqual(len(matrix), len(matrix[0]))
        self.assertTrue(set("".join(matrix)) <= {"0", "1"})


if __name__ == "__main__":
    unittest.main()
