import unittest

from tajmeea_engine.errors import UserError
from tajmeea_engine.parsing import parse_api_key, parse_channel_link, scan_api_key

MY_TELEGRAM_PAGE = """App configuration
App api_id:
2041733
App api_hash:
7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60
App title:\ttajmeati
Short name:\ttajmeati
Available MTProto servers
Test configuration:
149.154.167.40:443
Production configuration:
149.154.167.50:443
Public keys:
-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAyMEdY1aR+sCR3ZSJrtztKTKqigvO/vBfqACJLZtS7QMgCGXJ6XIR
-----END RSA PUBLIC KEY-----
"""


# The page as Telegram showed it on 2026-10-29 (copied with ⌘A ⌘C, values replaced).
NEW_PAGE = """my.telegram.org
API development tools
tajmeati
+965 9999 0000
Delete account
Log out
tajmeati
Active
Desktop · created 23 Mar 2025. Use these credentials to sign requests to the Telegram API.

Credentials
Keep api_hash private. Anyone who has it can use your app’s quota.

App api_id
2041733

App api_hash
secret
{hash}


Each account can have one api_id
Don’t publish your api_hash or commit it to public repositories.

App configuration
Only the title and short name can be changed.

Test configuration
DC 2
Address
149.154.167.40:443
Protocol
MTProto 2.0
Public keys
"""
HASH = "7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60"


class KeyParsingTest(unittest.TestCase):
    def test_new_page_with_the_hash_revealed(self):
        key = parse_api_key(NEW_PAGE.format(hash=HASH))
        self.assertEqual((key.api_id, key.api_hash), (2041733, HASH))

    def test_values_copied_one_at_a_time(self):
        self.assertEqual(scan_api_key(" 37527307\n"), {"apiId": 37527307, "apiHash": None, "hashHidden": False})
        self.assertEqual(scan_api_key(HASH.upper()), {"apiId": None, "apiHash": HASH, "hashHidden": False})
        hidden = scan_api_key(NEW_PAGE.format(hash="•" * 32))
        self.assertEqual((hidden["apiId"], hidden["apiHash"], hidden["hashHidden"]), (2041733, None, True))
        self.assertEqual(scan_api_key("hello there"), {"apiId": None, "apiHash": None, "hashHidden": False})

    def test_new_page_with_the_hash_hidden_says_so(self):
        hidden = NEW_PAGE.format(hash="•" * 32)
        with self.assertRaises(UserError) as caught:
            parse_api_key(hidden)
        self.assertEqual(caught.exception.code, "hash_hidden")
        # Then the person copies the hash on its own and it lands under the page.
        key = parse_api_key(hidden + "\n" + HASH)
        self.assertEqual((key.api_id, key.api_hash), (2041733, HASH))

    def test_whole_my_telegram_page(self):
        key = parse_api_key(MY_TELEGRAM_PAGE)
        self.assertEqual(key.api_id, 2041733)
        self.assertEqual(key.api_hash, "7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60")

    def test_bare_values(self):
        key = parse_api_key("2041733\n7F3C1E9A0B2D4C6E8F0A1B2C3D4E5F60")
        self.assertEqual((key.api_id, key.api_hash), (2041733, "7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60"))

    def test_masked_never_shows_whole_hash(self):
        masked = parse_api_key(MY_TELEGRAM_PAGE).masked()
        self.assertNotIn("0b2d4c6e8f0a1b2c3d4e", masked)

    def test_rejects_text_without_key(self):
        two_numbers = "2041733 and 99887766 and 7f3c1e9a0b2d4c6e8f0a1b2c3d4e5f60"
        for text in ["", "hello", "App api_id: 2041733", two_numbers]:
            with self.assertRaises(UserError):
                parse_api_key(text)


class LinkParsingTest(unittest.TestCase):
    def test_everything_people_paste(self):
        cases = {
            "@law_library": "law_library",
            "law_library": "law_library",
            "t.me/law_library": "law_library",
            "https://t.me/law_library": "law_library",
            "HTTPS://T.ME/law_library": "law_library",
            "https://t.me/s/law_library": "law_library",
            "https://t.me/law_library/1234": "law_library",
            "https://t.me/law_library/1234?single": "law_library",
            "https://telegram.me/law_library": "law_library",
            "tg://resolve?domain=law_library&post=5": "law_library",
            "  <https://t.me/law_library>  ": "law_library",
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_channel_link(raw), expected, raw)

    def test_private_and_foreign_links_get_clear_errors(self):
        for raw, code in [
            ("https://t.me/+AbCdEf123", "private"),
            ("https://t.me/joinchat/AbCdEf", "private"),
            ("https://t.me/c/123456/7", "private"),
            ("https://example.com/law_library", "not_telegram"),
            ("", "empty"),
            ("@x", "bad_name"),
        ]:
            with self.assertRaises(UserError) as caught:
                parse_channel_link(raw)
            self.assertEqual(caught.exception.code, code, raw)


if __name__ == "__main__":
    unittest.main()
