"""Regression coverage for the age-restricted, staff-moderated Grower Showcase."""
from io import BytesIO
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from lab.bot import bot
from lab.growers import GrowerHub, clean_caption, photo_as_jpeg, verified_strain
from lab.strain_profiles import StrainProfileStore


class GrowerPhotoTests(unittest.TestCase):
    def test_strips_all_exif_and_applies_orientation(self):
        image = Image.new("RGB", (120, 80), (18, 90, 40))
        original = BytesIO()
        exif = Image.Exif()
        exif[270] = "PRIVATE DEVICE AND LOCATION DETAILS"
        exif[274] = 6
        image.save(original, "JPEG", exif=exif)
        sanitized = photo_as_jpeg(original.getvalue())
        with Image.open(BytesIO(sanitized)) as public:
            self.assertEqual(public.format, "JPEG")
            self.assertEqual(public.size, (80, 120))
            self.assertFalse(public.getexif())
        self.assertNotIn(b"PRIVATE DEVICE", sanitized)

    def test_rejects_bad_files_and_image_bombs(self):
        for content in (b"", b"not an image", b"x" * (8 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                photo_as_jpeg(content)
        image = Image.new("RGB", (4000, 3000))
        data = BytesIO()
        image.save(data, "PNG")
        with self.assertRaises(ValueError):
            photo_as_jpeg(data.getvalue())

    def test_exact_strain_and_safe_captions(self):
        self.assertEqual(verified_strain("Blue Dream").casefold(), "blue dream")
        for name in ("Blue Dreem", "fake made up strain zzz"):
            with self.assertRaises(ValueError):
                verified_strain(name)
        for caption in ("visit https://example.com", "click http://spam.test"):
            with self.assertRaises(ValueError):
                clean_caption(caption, maximum=220)
        self.assertNotIn("@", clean_caption("<@123> my garden", maximum=220))


class GrowerStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name) / "profiles.sqlite3")
        self.profiles = StrainProfileStore(self.path)
        self.hub = GrowerHub(self.profiles)
        self.guild = 100
        self.hub.configure(self.guild, 101, 102)

    def submit(self, user=123, strain="Blue Dream", stage="flowering", message=1001):
        return self.hub.submit(self.guild, user, "GardenGamer", strain,
                               stage, "Real progress photo", message, 101)

    def test_server_opt_in_and_suspension(self):
        self.assertEqual(self.hub.configuration(self.guild), ("101", "102", 1))
        with self.assertRaises(ValueError):
            self.hub.configure(self.guild, 101, 101)
        with self.assertRaises(ValueError):
            self.hub.submit(999, 123, "User", "Blue Dream", "flowering", "", 50, 101)
        self.hub.configure(self.guild, 101, 102, enabled=False)
        with self.assertRaises(ValueError):
            self.submit()
        self.assertEqual(self.hub.configuration(self.guild)[2], 0)
        self.hub.configure(self.guild, 101, 102, enabled=True)
        self.assertIsInstance(self.submit(), int)

    def test_review_approval_and_contributor_milestones(self):
        item_id = self.submit()
        self.assertEqual(self.hub.stats(self.guild, 123)[:3], (0, 1, 0))
        self.assertEqual(self.hub.my_uploads(self.guild, 123)[0][0], item_id)
        self.assertEqual(self.hub.my_uploads(self.guild, 999), [])
        self.assertEqual(self.hub.pending(self.guild)[0][0], item_id)
        self.assertEqual(self.hub.pending(self.guild)[0][5], "101")
        locked = self.hub.lock(self.guild, item_id, purpose="review")
        self.assertEqual(locked[8], "pending")
        with self.assertRaises(ValueError):
            self.hub.lock(self.guild, item_id, purpose="review")
        self.hub.approve(self.guild, item_id, 5001, 102)
        self.assertEqual(self.hub.item(self.guild, item_id)[8], "approved")
        self.assertEqual(self.hub.item(self.guild, item_id)[7], "5001")
        self.assertEqual(self.hub.item(self.guild, item_id)[9:], ("101", "102"))
        self.assertEqual(self.hub.stats(self.guild, 123),
                         (1, 0, 1, "🌱 First Showcase"))
        journal = self.hub.journal(self.guild, 123, "Blue Dream")
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0][4], "5001")
        self.assertEqual(journal[0][6], "102")
        self.assertFalse(self.hub.journal(self.guild, 999))
        self.assertEqual(self.hub.stats(self.guild, 999)[:3], (0, 0, 0))
        self.assertFalse(self.hub.pending(self.guild))

    def test_member_only_removal_and_persistent_reload(self):
        item_id = self.submit()
        with self.assertRaises(ValueError):
            self.hub.lock(self.guild, item_id, purpose="remove", user_id=999)
        locked = self.hub.lock(self.guild, item_id, purpose="remove", user_id=123)
        self.hub.unlock(self.guild, item_id, locked[8])
        reloaded = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(len(reloaded.pending(self.guild)), 1)
        reloaded.lock(self.guild, item_id, purpose="remove", user_id=123)
        reloaded.delete(self.guild, item_id, "removing")
        self.assertIsNone(self.hub.item(self.guild, item_id))
        self.assertEqual(self.hub.stats(self.guild, 123)[0], 0)
        self.assertEqual(self.hub.my_uploads(self.guild, 123), [])

    def test_limits_and_validation(self):
        for offset in range(3):
            self.submit(message=1000 + offset)
        with self.assertRaises(ValueError):
            self.submit(message=1009)
        with self.assertRaises(ValueError):
            self.hub.submit(self.guild, 101, "Me", "Blue Dreem", "flowering", "", 99, 101)
        with self.assertRaises(ValueError):
            self.hub.submit(self.guild, 101, "Me", "Blue Dream", "purchase", "", 99, 101)
        self.assertEqual(len(self.hub.pending(self.guild)), 3)

    def test_channel_reconfiguration_preserves_previous_submission_locations(self):
        first_id = self.submit()
        self.hub.configure(self.guild, 201, 202)
        old = self.hub.lock(self.guild, first_id, purpose="review")
        self.assertEqual(old[9], "101")
        self.hub.approve(self.guild, first_id, 5001, 202)
        self.assertEqual(self.hub.journal(self.guild, 123)[0][6], "202")
        self.hub.configure(self.guild, 301, 302)
        row = self.hub.lock(self.guild, first_id, purpose="remove", user_id=123)
        self.assertEqual(row[9], "101")
        self.assertEqual(row[10], "202")
        self.hub.delete(self.guild, first_id, "removing")
        self.assertIsNone(self.hub.item(self.guild, first_id))
        with self.assertRaises(ValueError):
            self.hub.submit(self.guild, 555, "Grower", "Blue Dream", "harvest", "", 5, 101)

    def test_anonymized_identity_does_not_store_discord_user_id(self):
        self.submit(user=987654321987654321)
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT author_hash,byline FROM grower_submissions").fetchone()
        self.assertEqual(len(row[0]), 64)
        self.assertNotIn("987654321987654321", repr(row))
        self.assertEqual(row[1], "GardenGamer")
        self.assertEqual(self.profiles.member_hash(self.guild, 123),
                         self.profiles.member_hash(self.guild, 123))
        self.assertNotEqual(self.profiles.member_hash(self.guild, 123),
                            self.profiles.member_hash(101, 123))

    def test_existing_strain_ratings_remain_intact(self):
        self.profiles.set_reviews_enabled(self.guild, True)
        self.profiles.rate(self.guild, 123, "Blue Dream", 5)
        self.submit()
        self.assertEqual(self.profiles.review_stats(self.guild, "Blue Dream"), (1, 5.0))


class GrowerCommandsTests(unittest.TestCase):
    def test_commands_are_registered_on_existing_bot(self):
        names = {command.name: command for command in bot.tree.get_commands()}
        for cmd in ("growerconfig", "growersubmit", "growerqueue", "growerreview",
                    "growerprofile", "growerjournal", "growerwithdraw", "growerremove"):
            self.assertIn(cmd, names)
        for manager in ("growerconfig", "growerqueue", "growerreview", "growerremove"):
            self.assertTrue(names[manager].default_permissions.manage_guild)

    def test_upload_and_profile_are_private_by_default(self):
        from inspect import signature
        commands = {command.name: command for command in bot.tree.get_commands()}
        for command_name in ("growerprofile", "growerjournal"):
            self.assertIs(signature(commands[command_name].callback)
                          .parameters["public"].default, False)


class GrowerPermissionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_withdraw_uses_original_channels_after_manager_reconfigures(self):
        from lab.grower_commands import _remove_submission
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.submit(22, 400, "Grower", "Blue Dream", "flowering",
                             "Original photo", 301, 101)
            hub.lock(22, sid, purpose="review")
            hub.approve(22, sid, 302, 102)
            hub.configure(22, 201, 202)
            interaction = SimpleNamespace(guild_id=22)
            fake_bot = SimpleNamespace(growers=hub)
            async def historical_channel(_interaction, cid):
                return f"channel-{cid}"
            with patch("lab.grower_commands._saved_channel", side_effect=historical_channel) as resolve, \
                 patch("lab.grower_commands._remove_message", new_callable=AsyncMock) as remove:
                await _remove_submission(interaction, fake_bot, sid, user_id=400)
                self.assertEqual([call.args[1] for call in resolve.await_args_list],
                                 ["102", "101"])
                self.assertEqual([call.args[:2] for call in remove.await_args_list],
                                 [("channel-102", 302), ("channel-101", 301)])
                self.assertIsNone(hub.item(22, sid))

    async def test_failed_removal_unwinds_state_for_retry(self):
        from lab.grower_commands import _remove_submission
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.submit(22, 400, "Grower", "Blue Dream", "flowering",
                             "Original photo", 301, 101)
            hub.lock(22, sid, purpose="review")
            hub.approve(22, sid, 302, 102)
            interaction = SimpleNamespace(guild_id=22)
            async def historical_channel(_interaction, cid):
                return f"channel-{cid}"
            with patch("lab.grower_commands._saved_channel", side_effect=historical_channel), \
                 patch("lab.grower_commands._remove_message", new_callable=AsyncMock,
                       side_effect=PermissionError("forbidden")):
                with self.assertRaises(PermissionError):
                    await _remove_submission(interaction, SimpleNamespace(growers=hub),
                                             sid, user_id=400)
            self.assertEqual(hub.item(22, sid)[8], "approved")

    async def test_no_consent_does_not_read_or_upload_attachment(self):
        command = bot.tree.get_command("growersubmit")
        photo = SimpleNamespace(size=500, read=AsyncMock())
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(response=response)
        await command.callback(interaction, "Blue Dream", "flowering",
                               photo, False)
        photo.read.assert_not_awaited()
        self.assertTrue(response.send_message.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
