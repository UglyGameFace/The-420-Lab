"""Strain catalog transparency, provenance, original ratings and curator media."""
import sqlite3
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace

from lab.strain_profiles import (
    FIRST_INDEXED, StrainProfileStore, catalog_counts,
    database_embed, strain_embed,
)
from lab.bot import bot


class StrainStatusTests(unittest.TestCase):
    def test_catalog_is_counted_from_local_files_not_a_marketing_constant(self):
        from lab.strains import _index
        counts = catalog_counts()
        self.assertEqual(counts["distinct"], len(_index()[0]))
        self.assertEqual(counts["distinct"], 30593)
        self.assertEqual(counts["kushy"], 9508)
        self.assertEqual(counts["ci"], 19751)
        self.assertEqual(counts["historical_leafly_added"], 2298)

    def test_public_database_card_distinguishes_source_dates_from_live_sync(self):
        embed = database_embed()
        self.assertIn("30,593", embed.description)
        lines = "\n".join(str(f.value) for f in embed.fields)
        self.assertIn(FIRST_INDEXED, lines)
        self.assertIn("2017-11-14", lines)
        self.assertIn("2026", lines)
        self.assertIn("No automatic Leafly sync", lines)
        self.assertIn("Cannlytics", lines)
        self.assertIn("Wikimedia Commons", lines)

    def test_manager_controls_are_registered(self):
        commands = {c.name: c for c in bot.tree.get_commands()}
        for name in ("straindb", "strainprofile", "strainreviews", "strainrate",
                     "doctorstrainset", "doctorstrainclear"):
            self.assertIn(name, commands)
        self.assertTrue(commands["strainreviews"].default_permissions.manage_guild)
        self.assertTrue(commands["doctorstrainset"].default_permissions.administrator)


class StrainProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "strain-profile.sqlite3")
        self.store = StrainProfileStore(self.path)

    def test_missing_license_keeps_external_image_and_description_offline(self):
        embed = strain_embed("Blue Dream", 999, self.store)
        self.assertIsNone(embed.image.url)
        self.assertIn("No reuse-authorized", "\n".join(f.value for f in embed.fields))

    def test_owner_can_add_and_remove_credited_description_and_photo(self):
        self.store.save_curated(
            "Blue Dream",
            "Originally written description for a reference cultivar, not medical advice.",
            "https://example.org/legal/source",
            "https://example.org/photo-original.jpg",
            "original")
        embed = strain_embed("Blue Dream", 999, self.store)
        self.assertEqual(embed.image.url, "https://example.org/photo-original.jpg")
        combined = "\n".join(str(f.value) for f in embed.fields)
        self.assertIn("Originally written", combined)
        self.assertIn("https://example.org/legal/source", combined)
        self.store.remove_curated("Blue Dream")
        self.assertIsNone(strain_embed("Blue Dream", 999, self.store).image.url)

    def test_unsafe_urls_or_invalid_rights_are_rejected(self):
        for image in ("http://example.org/pic.jpg", "https://127.0.0.1/p.png",
                      "https://private.local/p.png", "https://u:p@example.org/image.jpg"):
            with self.assertRaises(ValueError):
                self.store.save_curated(
                    "Blue Dream", "I own the description and supplied the original photo.",
                    "https://example.org/source", image, "original")
        with self.assertRaises(ValueError):
            self.store.save_curated(
                "Blue Dream", "This is a sufficiently long description.",
                "https://example.org/source", "", "unknown")

    def test_reviews_require_manager_opt_in_and_are_guild_scoped(self):
        with self.assertRaises(ValueError):
            self.store.rate(55, 1001, "Blue Dream", 5)
        self.store.set_reviews_enabled(55, True)
        self.store.rate(55, 1001, "Blue Dream", 5)
        self.store.rate(55, 1002, "Blue Dream", 3)
        self.assertEqual(self.store.review_stats(55, "Blue Dream"), (2, 4.0))
        self.assertEqual(self.store.review_stats(56, "Blue Dream"), (0, None))
        # Repeated ratings update a single member's vote; not duplicate reviews.
        self.store.rate(55, 1001, "Blue Dream", 1)
        self.assertEqual(self.store.review_stats(55, "Blue Dream"), (2, 2.0))
        self.store.set_reviews_enabled(55, False)
        self.assertEqual(self.store.review_stats(55, "Blue Dream"), (0, None))

    def test_reviews_do_not_store_discord_member_ids_or_messages(self):
        self.store.set_reviews_enabled(33, True)
        self.store.rate(33, 987654321987654321, "Blue Dream", 4)
        with sqlite3.connect(self.path) as db:
            data = repr(db.execute(
                "SELECT guild,name_key,voter_hash,rating FROM strain_votes").fetchall())
        self.assertNotIn("987654321987654321", data)
        self.assertIn("bluedream", data)
        self.store.clear_reviews(33)
        self.assertEqual(self.store.review_stats(33, "Blue Dream"), (0, None))

    def test_bogus_or_nonexact_names_cannot_be_rated(self):
        self.store.set_reviews_enabled(33, True)
        for name in ("Animel Face", "Nonexistent Name Xyz"):
            with self.assertRaises(ValueError):
                self.store.rate(33, 900, name, 5)

    def test_profiles_and_settings_survive_new_instance_same_database(self):
        self.store.save_curated(
            "Super Boof", "Custom original report with no unsupported health promises.",
            "https://example.org/custom", "", "original")
        self.store.set_reviews_enabled(55, True)
        self.store.rate(55, 77, "Super Boof", 5)
        other = StrainProfileStore(self.path)
        self.assertTrue(other.reviews_enabled(55))
        self.assertEqual(other.review_stats(55, "Super Boof"), (1, 5.0))
        self.assertIn("Custom original", other.curated("Super Boof")[0])


if __name__ == "__main__":
    unittest.main()
