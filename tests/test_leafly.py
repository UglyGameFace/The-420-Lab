"""Verify actual Leafly reference URLs, safe fallbacks, and licensed CSV support."""
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from lab.leafly import (
    VERIFIED_PROFILES, canonical, is_valid_query, profile_for,
    leafly_search_url, leafly_reference, leafly_answer,
)
from lab.leafly_csv import local_profile, licensed_data_summary, _read_csv


class LeaflyReferenceTests(unittest.TestCase):
    def test_verified_pages_are_a_fixed_allowlist(self):
        self.assertGreaterEqual(len(VERIFIED_PROFILES), 10)
        examples = (
            ("Super Boof", "super-boof"),
            ("Blockberry", "super-boof"),
            ("Animal Face", "animal-face"),
            ("G41", "gelato-41"),
            ("Gelato #41", "gelato-41"),
            ("RS-11", "rs11"),
            ("Blue Dream", "blue-dream"),
            ("Permanent Marker", "permanent-marker"),
        )
        for name, slug in examples:
            found = profile_for(name)
            self.assertIsNotNone(found)
            self.assertEqual(found[1], "https://www.leafly.com/strains/" + slug)
            self.assertIn("Verified Leafly profile", leafly_reference(name))

    def test_unverified_name_uses_site_search_not_fake_slug(self):
        text = leafly_reference("Completely Made Up Xyz")
        self.assertIn("site-restricted external search", text)
        self.assertIn("google.com/search?q=", text)
        self.assertNotIn("leafly.com/strains/completely-made-up", text)
        self.assertIn("https://www.leafly.com/strains", text)

    def test_nasty_input_never_becomes_profile_url(self):
        for query in ("@everyone", "<@123>", "http://example.org", "test" + chr(96), "\nweed"):
            self.assertIsNone(profile_for(query))
            self.assertIsNone(leafly_search_url(query))
            self.assertNotIn("https://evil", leafly_reference(query))

    def test_existing_strain_lookup_includes_leafly_reference(self):
        text = leafly_answer("Super Boof")
        self.assertIn("The Weed Doctor", text)
        self.assertIn("https://www.leafly.com/strains/super-boof", text)
        self.assertLessEqual(len(text), 2000)

    def test_unverified_strain_is_not_mislabeled_as_verified(self):
        text = leafly_answer("Unlisted Whatever Strain")
        self.assertIn("not", text.lower())
        self.assertNotIn("**Verified Leafly profile:**", text)


class LeaflyLicensedCsvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv_file = Path(self.temp.name) / "authorized.csv"
        self.csv_file.write_text(
            "Strain,Type,Rating,Effects,Flavor,Description\n"
            "Blue Dream,Hybrid,4.5,\"Creative, Happy\",\"Berry, Sweet\",Some text\n"
            "Super Boof,Hybrid,6,\"Focused, Giggly\",Orange,Unreliable text\n",
            encoding="utf-8")
        _read_csv.cache_clear()

    def test_with_no_owner_csv_environment_no_import_occurs(self):
        with patch.dict(os.environ, {"LEAFLY_LICENSED_CSV_PATH": ""}):
            self.assertIsNone(local_profile("Blue Dream"))
            self.assertEqual(licensed_data_summary("Blue Dream"), "")

    def test_opt_in_csv_shows_only_safe_fields_and_user_report_warning(self):
        with patch.dict(os.environ, {"LEAFLY_LICENSED_CSV_PATH": str(self.csv_file)}):
            record = local_profile("Blue Dream")
            self.assertIsNotNone(record)
            self.assertEqual(record.rating, "4.5/5")
            message = licensed_data_summary("Blue Dream")
            self.assertIn("Historically reported effects (not predictive): Creative, Happy", message)
            self.assertIn("not current live Leafly data", message)
            self.assertNotIn("Some text", message)
            self.assertNotIn("Unreliable text", licensed_data_summary("Super Boof"))

    def test_bad_rating_does_not_claim_valid_measurement(self):
        with patch.dict(os.environ, {"LEAFLY_LICENSED_CSV_PATH": str(self.csv_file)}):
            record = local_profile("Super Boof")
            self.assertEqual(record.rating, "")
            self.assertEqual(record.effects, ("Focused", "Giggly"))

    def test_real_4762_row_header_format_extracts_cautious_context(self):
        fixture = Path(self.temp.name) / "leafly-legacy.csv"
        fixture.write_text(
            "name,img_url,type,thc_level,most_common_terpene,description,"
            "relaxed,happy,euphoric,sleepy,creative\n"
            "GG4,,Hybrid,20%,Caryophyllene,Marketing claim,"
            "80%,50%,bad,0%,60%\n",
            encoding="utf-8")
        with patch.dict(os.environ, {"LEAFLY_LICENSED_CSV_PATH": str(fixture)}):
            row = local_profile("GG4")
            self.assertEqual(row.catalog_type, "Hybrid")
            self.assertEqual(row.listed_terpene, "Caryophyllene")
            self.assertEqual(row.effects, ("Relaxed", "Creative", "Happy"))
            message = licensed_data_summary("GG4")
            self.assertIn("unknown", message)
            self.assertNotIn("Marketing claim", message)
            self.assertNotIn("20%", message)
            self.assertNotIn("80%", message)

    def test_missing_csv_fails_safely(self):
        with patch.dict(os.environ, {"LEAFLY_LICENSED_CSV_PATH": str(self.csv_file) + ".missing"}):
            self.assertEqual(licensed_data_summary("Blue Dream"), "")


if __name__ == "__main__":
    unittest.main()
