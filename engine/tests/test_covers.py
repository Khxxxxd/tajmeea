import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from tajmeea_engine.thumbs import Covers

from fakes import Events

TINY_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 280]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")


@unittest.skipUnless(sys.platform == "darwin", "covers come from macOS Quick Look")
class CoversTest(unittest.TestCase):
    def test_a_cover_is_made_once_in_the_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "قانون.pdf"
            pdf.write_bytes(TINY_PDF)
            events = Events()
            covers = Covers(Path(tmp) / "covers", events)

            async def scenario():
                covers.request({"channel_id": 7, "msg_id": 1, "kind": "pdf", "path": str(pdf)})
                covers.request({"channel_id": 7, "msg_id": 2, "kind": "audio", "path": str(pdf)})
                await covers._worker

            asyncio.run(scenario())
            self.assertTrue(covers.has(7, 1))
            self.assertFalse(covers.has(7, 2))
            self.assertEqual([e["event"] for e in events.items], ["file.cover"])
            covers.forget_channel(7)
            self.assertFalse(covers.has(7, 1))


if __name__ == "__main__":
    unittest.main()
