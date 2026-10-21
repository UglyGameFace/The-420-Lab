"""Regression coverage for the age-restricted, staff-moderated Grower Showcase."""
from io import BytesIO
from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, PropertyMock

from PIL import Image

from lab.bot import bot
from lab.grower_commands import _submission_card
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

    def test_large_jpeg_downsamples_and_removes_metadata(self):
        image = Image.new("RGB", (3264, 2448), (25, 116, 68))
        photo = BytesIO()
        exif = Image.Exif()
        exif[270] = "PRIVATE CAMERA MODEL AND LOCATION"
        image.save(photo, "JPEG", exif=exif)
        cleaned = photo_as_jpeg(photo.getvalue())
        with Image.open(BytesIO(cleaned)) as preview:
            self.assertEqual(preview.format, "JPEG")
            self.assertLessEqual(max(preview.size), 2048)
            self.assertFalse(preview.getexif())
        self.assertNotIn(b"PRIVATE CAMERA", cleaned)

    def test_png_and_webp_are_reencoded_as_plain_rgb_jpeg(self):
        for format in ("PNG", "WEBP"):
            with self.subTest(format=format):
                original = BytesIO()
                Image.new("RGBA", (256, 180), (31, 112, 64, 255)).save(
                    original, format=format)
                cleaned = photo_as_jpeg(original.getvalue())
                with Image.open(BytesIO(cleaned)) as preview:
                    self.assertEqual(preview.format, "JPEG")
                    self.assertEqual(preview.mode, "RGB")
                    self.assertEqual(preview.size, (256, 180))
                    self.assertFalse(preview.getexif())

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
        reserved = self.hub.begin_upload(
            self.guild, user, "GardenGamer", strain, stage, "Real progress photo", 101)
        self.hub.finish_upload(self.guild, reserved, message)
        return reserved

    def _age_operation(self, item_id):
        old = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE grower_submissions SET operation_utc=? WHERE id=?",
                       (old, item_id))

    def test_storage_probe_requires_new_process_and_survives_reinstantiation(self):
        self.assertEqual(self.hub.storage_status(), ("unarmed", ""))
        self.assertFalse(self.hub.storage_ready())
        with self.assertRaisesRegex(ValueError, "First run"):
            self.hub.verify_storage_probe()
        self.hub.arm_storage_probe()
        self.assertEqual(self.hub.storage_status()[0], "armed_this_process")
        self.assertFalse(self.hub.storage_ready())
        with self.assertRaisesRegex(ValueError, "Still in the same"):
            self.hub.verify_storage_probe()
        new_process = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(new_process.storage_status()[0], "ready_to_verify")
        verified = new_process.verify_storage_probe()
        self.assertEqual(new_process.storage_status(), ("verified", verified))
        self.assertTrue(self.hub.storage_ready())
        restarted_again = GrowerHub(StrainProfileStore(self.path))
        self.assertTrue(restarted_again.storage_ready())
        restarted_again.arm_storage_probe()
        self.assertFalse(restarted_again.storage_ready())
        self.assertEqual(restarted_again.storage_status()[0], "armed_this_process")

    def test_storage_probe_does_not_change_member_records_or_curated_content(self):
        self.profiles.save_curated(
            "Blue Dream", "Original carefully attributed botanical cultivar description.",
            "https://example.org/attribution", "", "original")
        upload_id = self.submit()
        self.hub.arm_storage_probe()
        check = GrowerHub(StrainProfileStore(self.path))
        check.verify_storage_probe()
        self.assertEqual(self.hub.item(self.guild, upload_id)[8], "pending")
        self.assertTrue(self.profiles.curated("Blue Dream"))
        self.assertNotIn("secret", repr(check.storage_status()))

    def test_upload_reservation_persists_across_restart_and_can_be_adopted(self):
        upload_id = self.hub.begin_upload(
            self.guild, 123, "GardenGamer", "Blue Dream", "flowering", "", 101)
        reserved = self.hub.item(self.guild, upload_id)
        self.assertEqual(reserved[8], "uploading")
        self.assertEqual(reserved[6], "0")
        self.assertEqual(reserved[9], "101")
        self.assertEqual(self.hub.stats(self.guild, 123)[:3], (0, 1, 0))
        self.assertEqual(self.hub.my_uploads(self.guild, 123)[0][2], "uploading")
        self.assertEqual(self.hub.pending(self.guild), [])
        with self.assertRaises(ValueError):
            self.hub.lock(self.guild, upload_id, purpose="review")
        with self.assertRaises(ValueError):
            self.hub.finish_upload(self.guild, upload_id, 0)
        self._age_operation(upload_id)
        again = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(again.interrupted(self.guild), [(upload_id, "uploading")])
        self.assertTrue(again.upload_is_interrupted(self.guild, upload_id))
        again.finish_upload(self.guild, upload_id, 6001)
        self.assertEqual(again.item(self.guild, upload_id)[8], "pending")
        self.assertEqual(again.item(self.guild, upload_id)[6], "6001")
        self.assertFalse(again.upload_is_interrupted(self.guild, upload_id))
        with self.assertRaises(ValueError):
            again.finish_upload(self.guild, upload_id, 6002)

    def test_interrupted_upload_can_be_discarded_but_not_while_active(self):
        upload_id = self.hub.begin_upload(
            self.guild, 123, "GardenGamer", "Blue Dream", "flowering", "", 101)
        with self.assertRaises(ValueError):
            self.hub.discard_interrupted_upload(self.guild, upload_id)
        self._age_operation(upload_id)
        self.hub.discard_interrupted_upload(self.guild, upload_id)
        self.assertIsNone(self.hub.item(self.guild, upload_id))

    def test_unconfirmed_uploads_count_toward_daily_and_pending_caps(self):
        uploads = [self.hub.begin_upload(
            self.guild, 123, "GardenGamer", "Blue Dream", "flowering", "", 101)
            for _ in range(3)]
        self.assertEqual(len(set(uploads)), 3)
        with self.assertRaises(ValueError):
            self.hub.begin_upload(
                self.guild, 123, "GardenGamer", "Blue Dream", "flowering", "", 101)
        self.assertEqual(self.hub.stats(self.guild, 123)[1], 3)
        self.assertFalse(self.hub.pending(self.guild))

    def test_review_interrupt_reconciliation_and_safe_requeue(self):
        item_id = self.submit()
        self.hub.lock(self.guild, item_id, purpose="review")
        self.hub.prepare_review(self.guild, item_id, 102)
        self.assertEqual(self.hub.item(self.guild, item_id)[10], "102")
        self.assertFalse(self.hub.review_is_interrupted(self.guild, item_id))
        with self.assertRaises(ValueError):
            self.hub.requeue_interrupted_review(self.guild, item_id)
        self._age_operation(item_id)
        self.assertEqual(self.hub.interrupted(self.guild), [(item_id, "reviewing")])
        reloaded = GrowerHub(StrainProfileStore(self.path))
        self.assertTrue(reloaded.review_is_interrupted(self.guild, item_id))
        reloaded.requeue_interrupted_review(self.guild, item_id)
        self.assertEqual(reloaded.item(self.guild, item_id)[8], "pending")
        self.assertIsNone(reloaded.item(self.guild, item_id)[10])
        self.assertEqual(len(reloaded.pending(self.guild)), 1)

    def test_removal_resume_after_restart_is_owner_scoped(self):
        item_id = self.submit()
        self.hub.lock(self.guild, item_id, purpose="remove", user_id=123)
        with self.assertRaises(ValueError):
            self.hub.lock(self.guild, item_id, purpose="remove", user_id=123)
        self._age_operation(item_id)
        reloaded = GrowerHub(StrainProfileStore(self.path))
        with self.assertRaises(ValueError):
            reloaded.lock(self.guild, item_id, purpose="remove", user_id=999)
        stale = reloaded.lock(self.guild, item_id, purpose="remove", user_id=123)
        self.assertEqual(stale[8], "removing")
        reloaded.delete(self.guild, item_id, "removing")
        self.assertIsNone(reloaded.item(self.guild, item_id))

    def test_schema_migrates_old_existing_submissions_in_place(self):
        with sqlite3.connect(self.path) as db:
            db.execute("ALTER TABLE grower_submissions RENAME TO previous_table")
            db.execute("""CREATE TABLE grower_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild TEXT NOT NULL,
                author_hash TEXT NOT NULL, byline TEXT NOT NULL,
                strain TEXT NOT NULL, stage TEXT NOT NULL, caption TEXT NOT NULL,
                review_message TEXT NOT NULL, gallery_message TEXT,
                status TEXT NOT NULL DEFAULT 'pending', created_utc TEXT NOT NULL,
                review_channel TEXT NOT NULL, gallery_channel TEXT)""")
            db.execute("""INSERT INTO grower_submissions
                (id,guild,author_hash,byline,strain,stage,caption,review_message,
                 status,created_utc,review_channel)
                VALUES(1,'100','hash','Old Grower','Blue Dream','flowering','',
                       '312','pending','2026-10-01T00:00:00Z','101')""")
            db.execute("DROP TABLE previous_table")
        upgraded = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(upgraded.item(self.guild, 1)[2], "Old Grower")
        with sqlite3.connect(self.path) as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(grower_submissions)")}
            self.assertIn("operation_utc", cols)
        upgraded_again = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(upgraded_again.item(self.guild, 1)[2], "Old Grower")

    def test_gallery_cards_include_recoverable_submission_marker(self):
        approved = _submission_card("Grower", "Blue Dream", "flowering", "",
                                    approved=True, submission_id=19)
        self.assertTrue(approved.footer.text.startswith("Grower submission #19 | "))
        pending = _submission_card("Grower", "Blue Dream", "flowering", "",
                                   approved=False, submission_id=19)
        self.assertTrue(pending.footer.text.startswith("Grower upload #19 | "))

    def test_server_opt_in_and_suspension(self):
        self.assertEqual(self.hub.configuration(self.guild), ("101", "102", 1))
        with self.assertRaises(ValueError):
            self.hub.configure(self.guild, 101, 101)
        with self.assertRaises(ValueError):
            self.hub.begin_upload(999, 123, "User", "Blue Dream", "flowering", "", 101)
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
            self.hub.begin_upload(self.guild, 101, "Me", "Blue Dreem", "flowering", "", 101)
        with self.assertRaises(ValueError):
            self.hub.begin_upload(self.guild, 101, "Me", "Blue Dream", "purchase", "", 101)
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
            self.hub.begin_upload(self.guild, 555, "Grower", "Blue Dream", "harvest", "", 101)

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
                    "growerprofile", "growerjournal", "growerwithdraw", "growerremove",
                    "growerrecover", "growerstorage"):
            self.assertIn(cmd, names)
        for manager in ("growerconfig", "growerqueue", "growerreview", "growerremove",
                        "growerrecover"):

            self.assertTrue(names[manager].default_permissions.manage_guild)
        self.assertTrue(names["growerstorage"].default_permissions.administrator)

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
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream", "flowering",
                                   "Original photo", 101)
            hub.finish_upload(22, sid, 301)
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

    async def test_ambiguous_delete_retains_recoverable_removal_state(self):
        from lab.grower_commands import _remove_submission
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream", "flowering",
                                   "Original photo", 101)
            hub.finish_upload(22, sid, 301)
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
            self.assertEqual(hub.item(22, sid)[8], "removing")
            with self.assertRaises(ValueError):
                hub.lock(22, sid, purpose="remove", user_id=400)
            aged = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE grower_submissions SET operation_utc=? WHERE id=?",
                           (aged, sid))
            hub.lock(22, sid, purpose="remove", user_id=400)
            hub.delete(22, sid, "removing")
            self.assertIsNone(hub.item(22, sid))

    async def test_recover_adopts_existing_gallery_post_without_republishing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream", "flowering",
                                   "Original photo", 101)
            hub.finish_upload(22, sid, 301)
            hub.lock(22, sid, purpose="review")
            hub.prepare_review(22, sid, 102)
            old = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE grower_submissions SET operation_utc=? WHERE id=?",
                           (old, sid))
            post = SimpleNamespace(
                id=9001, author=SimpleNamespace(id=777),
                embeds=[SimpleNamespace(footer=SimpleNamespace(
                    text=f"Grower submission #{sid} | credited original photo"))])
            class FakeGallery:
                def history(self, limit):
                    self.limit = limit
                    async def entries():
                        yield post
                    return entries()
            gallery = FakeGallery()
            interaction = SimpleNamespace(
                guild_id=22, response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch.object(type(bot), "user", new_callable=PropertyMock) as user, \
                 patch("lab.grower_commands._saved_channel", new_callable=AsyncMock,
                       return_value=gallery):
                user.return_value = SimpleNamespace(id=777)
                await bot.tree.get_command("growerrecover").callback(interaction, sid)
            self.assertEqual(hub.item(22, sid)[8], "approved")
            self.assertEqual(hub.item(22, sid)[7], "9001")
            self.assertEqual(gallery.limit, 250)
            self.assertIn("No duplicate", interaction.followup.send.await_args.args[0])

    async def test_recover_requires_explicit_confirmation_to_requeue(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream", "flowering",
                                   "Original photo", 101)
            hub.finish_upload(22, sid, 301)
            hub.lock(22, sid, purpose="review")
            hub.prepare_review(22, sid, 102)
            old = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE grower_submissions SET operation_utc=? WHERE id=?",
                           (old, sid))
            class EmptyGallery:
                def history(self, limit):
                    async def empty():
                        if False:
                            yield None
                    return empty()
            interaction = SimpleNamespace(
                guild_id=22, response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch("lab.grower_commands._saved_channel", new_callable=AsyncMock,
                       return_value=EmptyGallery()):
                await bot.tree.get_command("growerrecover").callback(interaction, sid)
                self.assertEqual(hub.item(22, sid)[8], "reviewing")
                self.assertIn("entire", interaction.followup.send.await_args.args[0])
                await bot.tree.get_command("growerrecover").callback(
                    interaction, sid, confirmed_not_published=True)
            self.assertEqual(hub.item(22, sid)[8], "pending")

    async def test_upload_blocked_without_verified_storage_or_photo_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            review = SimpleNamespace(
                id=101, is_nsfw=lambda: True,
                permissions_for=lambda _: SimpleNamespace(view_channel=False),
                send=AsyncMock())
            interaction = SimpleNamespace(
                guild_id=22, guild=SimpleNamespace(default_role=object(), me=object()),
                user=SimpleNamespace(id=400, display_name="Grower"),
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            photo = SimpleNamespace(size=350, read=AsyncMock())
            with patch.object(bot, "growers", hub), \
                 patch.dict("os.environ", {"LAB_GROWER_REQUIRE_STORAGE_PROOF": "true"}), \
                 patch("lab.grower_commands._configured_channels",
                       return_value=(review, None, True)), \
                 patch("lab.grower_commands._post_permissions", return_value=True):
                await bot.tree.get_command("growersubmit").callback(
                    interaction, "Blue Dream", "flowering", photo, True)
            photo.read.assert_not_awaited()
            review.send.assert_not_awaited()
            self.assertIn("/growerstorage", interaction.response.send_message.await_args.args[0])
            self.assertFalse(hub.storage_ready())

    async def test_storage_command_enforces_application_ownership(self):
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=987),
            response=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, "is_owner", new_callable=AsyncMock, return_value=False):
            await bot.tree.get_command("growerstorage").callback(interaction, "arm")
        self.assertIn("application owner",
                      interaction.response.send_message.await_args.args[0])
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_storage_command_arm_verify_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=987),
                response=SimpleNamespace(send_message=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch.object(bot, "is_owner", new_callable=AsyncMock, return_value=True):
                cmd = bot.tree.get_command("growerstorage").callback
                await cmd(interaction, "arm")
                self.assertFalse(hub.storage_ready())
                await cmd(interaction, "verify")
                self.assertFalse(hub.storage_ready())
                self.assertIn("Still in the same", interaction.response.send_message.await_args.args[0])
                bot.growers = GrowerHub(StrainProfileStore(store.path))
                await cmd(interaction, "verify")
                self.assertTrue(bot.growers.storage_ready())
                await cmd(interaction, "status")
                self.assertIn("previously verified",
                              interaction.response.send_message.await_args.args[0])

    async def test_photo_processor_refuses_queue_without_reading_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            hub.arm_storage_probe()
            GrowerHub(StrainProfileStore(store.path)).verify_storage_probe()
            review = SimpleNamespace(
                id=101, is_nsfw=lambda: True,
                permissions_for=lambda _: SimpleNamespace(view_channel=False),
                send=AsyncMock())
            interaction = SimpleNamespace(
                guild_id=22, guild=SimpleNamespace(default_role=object(), me=object()),
                user=SimpleNamespace(id=400, display_name="Grower"),
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            photo = SimpleNamespace(size=350, read=AsyncMock())
            await bot.grower_image_slots.acquire()
            try:
                with patch.object(bot, "growers", hub), \
                     patch.dict("os.environ", {"LAB_GROWER_REQUIRE_STORAGE_PROOF": "true"}), \
                     patch.object(bot, "admit_interaction", new_callable=AsyncMock,
                                  return_value=True), \
                     patch("lab.grower_commands.GROWER_IMAGE_QUEUE_WAIT", 0.01), \
                     patch("lab.grower_commands._configured_channels",
                           return_value=(review, None, True)), \
                     patch("lab.grower_commands._post_permissions", return_value=True):
                    await bot.tree.get_command("growersubmit").callback(
                        interaction, "Blue Dream", "flowering", photo, True)
            finally:
                bot.grower_image_slots.release()
            photo.read.assert_not_awaited()
            review.send.assert_not_awaited()
            self.assertIn("busy", interaction.followup.send.await_args.args[0])
            self.assertEqual(hub.pending(22), [])

    async def test_photo_slot_covers_discord_send_not_just_processing(self):
        import asyncio
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            hub.arm_storage_probe()
            GrowerHub(StrainProfileStore(store.path)).verify_storage_probe()
            entered, finish = asyncio.Event(), asyncio.Event()
            async def slow_send(**kwargs):
                entered.set()
                await finish.wait()
                return SimpleNamespace(id=9012)
            review = SimpleNamespace(
                id=101, is_nsfw=lambda: True,
                permissions_for=lambda _: SimpleNamespace(view_channel=False),
                send=AsyncMock(side_effect=slow_send))
            def interaction(uid):
                return SimpleNamespace(
                    guild_id=22, guild=SimpleNamespace(default_role=object(), me=object()),
                    user=SimpleNamespace(id=uid, display_name="Grower"),
                    response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                    followup=SimpleNamespace(send=AsyncMock()))
            first, second = interaction(400), interaction(401)
            first_photo = SimpleNamespace(size=350, read=AsyncMock(return_value=b"source"))
            second_photo = SimpleNamespace(size=350, read=AsyncMock(return_value=b"source"))
            with patch.object(bot, "growers", hub), \
                 patch.dict("os.environ", {"LAB_GROWER_REQUIRE_STORAGE_PROOF": "true"}), \
                 patch.object(bot, "admit_interaction", new_callable=AsyncMock, return_value=True), \
                 patch("lab.grower_commands.GROWER_IMAGE_QUEUE_WAIT", 0.02), \
                 patch("lab.grower_commands._configured_channels",
                       return_value=(review, None, True)), \
                 patch("lab.grower_commands._post_permissions", return_value=True), \
                 patch("lab.grower_commands.photo_as_jpeg", return_value=b"cleaned"):
                sending = asyncio.create_task(
                    bot.tree.get_command("growersubmit").callback(
                        first, "Blue Dream", "flowering", first_photo, True))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=3)
                    await bot.tree.get_command("growersubmit").callback(
                        second, "Blue Dream", "flowering", second_photo, True)
                    second_photo.read.assert_not_awaited()
                    self.assertIn("busy", second.followup.send.await_args.args[0])
                finally:
                    finish.set()
                    await sending
            self.assertEqual(len(hub.pending(22)), 1)
            self.assertEqual(hub.pending(22)[0][4], "9012")
            self.assertEqual(bot.grower_image_slots._value, 1)

    async def test_uncertain_upload_send_keeps_reservation_for_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            hub.arm_storage_probe()
            GrowerHub(StrainProfileStore(store.path)).verify_storage_probe()
            review = SimpleNamespace(
                id=101, is_nsfw=lambda: True,
                permissions_for=lambda _: SimpleNamespace(view_channel=False),
                send=AsyncMock(side_effect=TimeoutError("response lost")))
            interaction = SimpleNamespace(
                guild_id=22, guild=SimpleNamespace(default_role=object(), me=object()),
                user=SimpleNamespace(id=400, display_name="Grower"),
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            photo = SimpleNamespace(size=350, read=AsyncMock(return_value=b"test-photo"))
            with patch.object(bot, "growers", hub), \
                 patch.object(bot, "admit_interaction", new_callable=AsyncMock, return_value=True), \
                 patch("lab.grower_commands._configured_channels", return_value=(review, None, True)), \
                 patch("lab.grower_commands._post_permissions", return_value=True), \
                 patch("lab.grower_commands.photo_as_jpeg", return_value=b"sanitized-image"):
                await bot.tree.get_command("growersubmit").callback(
                    interaction, "Blue Dream", "flowering", photo, True)
            with sqlite3.connect(store.path) as db:
                records = db.execute(
                    "SELECT id,status,review_message FROM grower_submissions").fetchall()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0][1:], ("uploading", "0"))
            embed = review.send.await_args.kwargs["embed"]
            self.assertTrue(embed.footer.text.startswith(
                f"Grower upload #{records[0][0]} | "))
            self.assertIn("Do not resend", interaction.followup.send.await_args.args[0])

    async def test_upload_confirmation_creates_pending_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            hub.arm_storage_probe()
            GrowerHub(StrainProfileStore(store.path)).verify_storage_probe()
            review = SimpleNamespace(
                id=101, is_nsfw=lambda: True,
                permissions_for=lambda _: SimpleNamespace(view_channel=False),
                send=AsyncMock(return_value=SimpleNamespace(id=6001)))
            interaction = SimpleNamespace(
                guild_id=22, guild=SimpleNamespace(default_role=object(), me=object()),
                user=SimpleNamespace(id=400, display_name="Grower"),
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            photo = SimpleNamespace(size=350, read=AsyncMock(return_value=b"test-photo"))
            with patch.object(bot, "growers", hub), \
                 patch.object(bot, "admit_interaction", new_callable=AsyncMock, return_value=True), \
                 patch("lab.grower_commands._configured_channels", return_value=(review, None, True)), \
                 patch("lab.grower_commands._post_permissions", return_value=True), \
                 patch("lab.grower_commands.photo_as_jpeg", return_value=b"sanitized-image"):
                await bot.tree.get_command("growersubmit").callback(
                    interaction, "Blue Dream", "flowering", photo, True)
            self.assertEqual(len(hub.pending(22)), 1)
            self.assertEqual(hub.pending(22)[0][4], "6001")
            self.assertIn("awaiting staff review", interaction.followup.send.await_args.args[0])

    async def test_recover_interrupted_upload_adopts_review_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream",
                                   "flowering", "Original photo", 101)
            old = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE grower_submissions SET operation_utc=? WHERE id=?",
                           (old, sid))
            post = SimpleNamespace(
                id=9001, author=SimpleNamespace(id=777),
                embeds=[SimpleNamespace(footer=SimpleNamespace(
                    text=f"Grower upload #{sid} | credited original photo"))])
            class ReviewHistory:
                def history(self, limit):
                    self.limit = limit
                    async def rows():
                        yield post
                    return rows()
            review = ReviewHistory()
            interaction = SimpleNamespace(
                guild_id=22, response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch.object(type(bot), "user", new_callable=PropertyMock) as user, \
                 patch("lab.grower_commands._saved_channel", new_callable=AsyncMock,
                       return_value=review):
                user.return_value = SimpleNamespace(id=777)
                await bot.tree.get_command("growerrecover").callback(interaction, sid)
            self.assertEqual(hub.item(22, sid)[8], "pending")
            self.assertEqual(hub.item(22, sid)[6], "9001")
            self.assertEqual(review.limit, 250)
            self.assertIn("No duplicate", interaction.followup.send.await_args.args[0])

    async def test_recover_upload_requires_manual_confirmation_before_discard(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream",
                                   "flowering", "Original photo", 101)
            old = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE grower_submissions SET operation_utc=? WHERE id=?",
                           (old, sid))
            class EmptyReview:
                def history(self, limit):
                    async def rows():
                        if False:
                            yield None
                    return rows()
            interaction = SimpleNamespace(
                guild_id=22, response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch("lab.grower_commands._saved_channel", new_callable=AsyncMock,
                       return_value=EmptyReview()):
                await bot.tree.get_command("growerrecover").callback(interaction, sid)
                self.assertEqual(hub.item(22, sid)[8], "uploading")
                self.assertIn("entire original channel", interaction.followup.send.await_args.args[0])
                await bot.tree.get_command("growerrecover").callback(
                    interaction, sid, confirmed_not_published=True)
            self.assertIsNone(hub.item(22, sid))

    async def test_rejection_removes_pending_using_same_durable_removal_path(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream",
                                   "flowering", "Original photo", 101)
            hub.finish_upload(22, sid, 301)
            interaction = SimpleNamespace(
                guild_id=22, response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch("lab.grower_commands._saved_channel",
                       new_callable=AsyncMock, return_value="old-review"), \
                 patch("lab.grower_commands._remove_message", new_callable=AsyncMock) as deleted:
                await bot.tree.get_command("growerreview").callback(interaction, sid, False)
            self.assertIsNone(hub.item(22, sid))
            deleted.assert_awaited_once()
            self.assertIn("rejected and deleted", interaction.followup.send.await_args.args[0])

    async def test_rejection_refuses_to_delete_an_already_approved_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream",
                                   "flowering", "Original photo", 101)
            hub.finish_upload(22, sid, 301)
            hub.lock(22, sid, purpose="review")
            hub.approve(22, sid, 902, 102)
            interaction = SimpleNamespace(
                guild_id=22, response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch("lab.grower_commands._remove_message", new_callable=AsyncMock) as deleted:
                await bot.tree.get_command("growerreview").callback(interaction, sid, False)
            self.assertEqual(hub.item(22, sid)[8], "approved")
            deleted.assert_not_awaited()
            self.assertIn("already being processed", interaction.followup.send.await_args.args[0])

    async def test_ambiguous_gallery_send_keeps_review_locked_for_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StrainProfileStore(str(Path(directory) / "photos.sqlite3"))
            hub = GrowerHub(store)
            hub.configure(22, 101, 102)
            sid = hub.begin_upload(22, 400, "Grower", "Blue Dream",
                                   "flowering", "Original photo", 101)
            hub.finish_upload(22, sid, 301)
            review = SimpleNamespace(
                is_nsfw=lambda: True,
                permissions_for=lambda _: SimpleNamespace(view_channel=False),
                fetch_message=AsyncMock(return_value=SimpleNamespace(
                    author=SimpleNamespace(id=777),
                    attachments=[SimpleNamespace(to_file=AsyncMock(return_value=b"photo"))])))
            gallery = SimpleNamespace(
                id=102, is_nsfw=lambda: True,
                send=AsyncMock(side_effect=TimeoutError("unknown publish result")))
            interaction = SimpleNamespace(
                guild_id=22, guild=SimpleNamespace(default_role=object(),me=object()),
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(bot, "growers", hub), \
                 patch.object(type(bot), "user", new_callable=PropertyMock) as user, \
                 patch("lab.grower_commands._saved_channel", new_callable=AsyncMock,
                       return_value=review), \
                 patch("lab.grower_commands._configured_channels",
                       return_value=(review, gallery, True)), \
                 patch("lab.grower_commands._post_permissions", return_value=True):
                user.return_value = SimpleNamespace(id=777)
                await bot.tree.get_command("growerreview").callback(
                    interaction, sid, True)
            self.assertEqual(hub.item(22, sid)[8], "reviewing")
            self.assertEqual(hub.item(22, sid)[10], "102")
            self.assertIn("/growerrecover", interaction.followup.send.await_args.args[0])

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
