"""Real photo fallback and bounded Pexels / Cannlytics enrichment tests."""
from __future__ import annotations
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from lab.strain_media import (
    StrainPhotoService, commons_fallback, _safe_pexels_photo, source_attributed_photo)
from lab.cannlytics_client import parse_profile, strain_summary, _CACHE
from lab.strain_profiles import StrainProfileStore
from lab.profile_reply import build_strain_profile


class PhotoValidationTests(unittest.TestCase):
    def test_source_specific_image_requires_exact_strain(self):
        photo = source_attributed_photo("Northern Lights")
        self.assertEqual(photo.label, "Northern Lights")
        self.assertIn("upload.wikimedia.org", photo.image_url)
        self.assertEqual(photo.license_name, "CC BY-SA 3.0")
        for term in ("Blue Dream", "Northern Lightz", "Northern Lights XL"):
            self.assertIsNone(source_attributed_photo(term))

    def test_no_key_fallback_is_real_credited_cc0_photo(self):
        photo = commons_fallback()
        self.assertEqual(photo.source, "Wikimedia Commons • CC0")
        self.assertIn("CannabisBud.jpg", photo.image_url)
        self.assertIn("CannabisBud.jpg", photo.source_page)
        self.assertEqual(photo.photographer, "Thomas Elliott")
        self.assertFalse(photo.is_cultivar_verified)

    def test_pexels_photographer_and_hosts_validated(self):
        entry = {
            "alt": "Close up of cannabis flower bud",
            "src": {"large": "https://images.pexels.com/photos/123/flower.jpeg"},
            "url": "https://www.pexels.com/photo/cannabis-123/",
            "photographer": "Jane Plant",
        }
        pic = _safe_pexels_photo(entry)
        self.assertEqual(pic.source, "Pexels")
        self.assertEqual(pic.photographer, "Jane Plant")
        self.assertFalse(pic.is_cultivar_verified)
        for change in (
            {"alt": "A random nature landscape"},
            {"src": {"large": "https://evil.example/steal.png"}},
            {"url": "https://www.pexels.com.evil.org/photo/abc"},
        ):
            self.assertIsNone(_safe_pexels_photo({**entry, **change}))


class PhotoServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_has_no_network_and_no_key(self):
        http = MagicMock()
        service = StrainPhotoService(http, quota=MagicMock())
        with patch.dict(os.environ, {"PEXELS_API_KEY": ""}):
            result = await service.photo()
        self.assertEqual(result.source, "Wikimedia Commons • CC0")
        http.get.assert_not_called()

    async def test_pexels_caches_actual_photo_and_limits_calls(self):
        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value={"photos": [
            {"alt": "Cannabis bud flowers",
             "src": {"large": "https://images.pexels.com/photos/420/bud.jpeg"},
             "url": "https://www.pexels.com/photo/cannabis-420/",
             "photographer": "Botanical Photographer"}
        ]})
        context = AsyncMock()
        context.__aenter__.return_value = response
        http = MagicMock()
        http.get.return_value = context
        quota = MagicMock()
        service = StrainPhotoService(http, quota)
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test-not-real-key"}):
            a = await service.photo()
            b = await service.photo()
        self.assertEqual(a, b)
        self.assertEqual(a.source, "Pexels")
        http.get.assert_called_once()
        quota.take_provider.assert_called_once()

    async def test_bad_pexels_response_falls_back_and_is_cached(self):
        response = MagicMock()
        response.status = 429
        context = AsyncMock()
        context.__aenter__.return_value = response
        http = MagicMock()
        http.get.return_value = context
        service = StrainPhotoService(http)
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test-not-real-key"}):
            a = await service.photo()
            b = await service.photo()
        self.assertEqual(a.source, "Wikimedia Commons • CC0")
        self.assertEqual(b.source, a.source)
        http.get.assert_called_once()


class CannlyticsTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_record_only_and_no_batch_claims(self):
        payload = {"data": {"strain_name": "Blue Dream",
                            "aromas": ["Berry", "Floral"],
                            "effects": ["Creative"]}}
        text = parse_profile(payload, "Blue Dream")
        self.assertIn("Cannlytics", text)
        self.assertIn("Berry", text)
        self.assertNotIn("THC 25%", text)
        self.assertEqual(parse_profile(payload, "Blue Dreamz"), "")

    async def test_no_key_does_not_call_cannlytics(self):
        http = MagicMock()
        with patch.dict(os.environ, {"CANNLYTICS_API_KEY": ""}):
            self.assertEqual(await strain_summary(http, MagicMock(), "Blue Dream"), "")
        http.get.assert_not_called()

    async def test_authorized_request_exact_path_and_cached(self):
        _CACHE.clear()
        response = MagicMock()
        response.status = 200
        response.content.read = AsyncMock(return_value=(
            b'{"data":{"strain_name":"Blue Dream","aromas":["Berry"]}}'))
        context = AsyncMock()
        context.__aenter__.return_value = response
        http = MagicMock()
        http.get.return_value = context
        quota = MagicMock()
        with patch.dict(os.environ, {"CANNLYTICS_API_KEY": "test-not-real-key"}):
            first = await strain_summary(http, quota, "Blue Dream")
            second = await strain_summary(http, quota, "Blue Dream")
        self.assertEqual(first, second)
        self.assertIn("Cannlytics", first)
        http.get.assert_called_once()
        quota.take_provider.assert_called_once()


class RichProfilePictureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StrainProfileStore(self.temp.name + "/profiles.sqlite3")

    async def test_documented_northern_lights_photo_is_not_generic(self):
        bot = SimpleNamespace(http_session=None, quota=MagicMock(),
                              strain_profiles=self.store, strain_photo_service=None)
        with patch("lab.profile_reply.sourced_summary", new_callable=AsyncMock,
                   return_value="No extra source confirmed."), patch(
                   "lab.cannlytics_client.strain_summary", new_callable=AsyncMock,
                   return_value=""):
            embed = await build_strain_profile(bot, "Northern Lights", 901)
        self.assertIn("Northern-lights-flowering.jpg", embed.image.url)
        fields = {entry.name: entry.value for entry in embed.fields}
        self.assertIn("User Dan", fields["📷 Source-attributed strain photograph"])
        self.assertIn("CC BY-SA 3.0", fields["📷 Source-attributed strain photograph"])
        self.assertNotIn("📷 Real cannabis flower photograph", fields)
        self.assertNotIn("temporarily unavailable", "\n".join(str(x.value) for x in embed.fields))
        self.assertIn("Additional source status", fields)

    async def test_real_source_summary_is_preserved_without_pseudo_photo(self):
        bot = SimpleNamespace(http_session=None, quota=MagicMock(),
                              strain_profiles=self.store, strain_photo_service=None)
        with patch("lab.profile_reply.sourced_summary", new_callable=AsyncMock,
                   return_value="**Flower & Freedom:** Northern Lights"), patch(
                   "lab.cannlytics_client.strain_summary", new_callable=AsyncMock,
                   return_value=""):
            embed = await build_strain_profile(bot, "Northern Lights", 901)
        fields = {entry.name: entry.value for entry in embed.fields}
        self.assertIn("🧬 Source-confirmed details & community reports", fields)
        self.assertIn("Flower & Freedom", fields["🧬 Source-confirmed details & community reports"])
        self.assertIn("Northern-lights-flowering.jpg", embed.image.url)

    async def test_unverified_strain_has_no_stock_flower_image(self):
        bot = SimpleNamespace(http_session=None, quota=MagicMock(),
                              strain_profiles=self.store, strain_photo_service=None)
        with patch("lab.profile_reply.sourced_summary", new_callable=AsyncMock,
                   return_value="No verified source."), patch(
                   "lab.cannlytics_client.strain_summary", new_callable=AsyncMock,
                   return_value=""):
            embed = await build_strain_profile(bot, "Blue Dream", 901)
        self.assertIsNone(embed.image.url)
        self.assertIn("No source-attributed photograph",
                      {field.name: field.value for field in embed.fields}["Photo verification"])

    async def test_original_curated_photo_is_not_overwritten(self):
        self.store.save_curated(
            "Blue Dream", "This is an original description for the tested cultivar.",
            "https://example.com/blue-dream", "https://example.com/blue-dream.jpg",
            "original")
        bot = SimpleNamespace(http_session=None, quota=MagicMock(),
                              strain_profiles=self.store, strain_photo_service=None)
        with patch("lab.profile_reply.sourced_summary", new_callable=AsyncMock,
                   return_value="Source notes"), patch(
                   "lab.cannlytics_client.strain_summary", new_callable=AsyncMock,
                   return_value=""):
            embed = await build_strain_profile(bot, "Blue Dream", 901)
        self.assertEqual(embed.image.url, "https://example.com/blue-dream.jpg")
        self.assertNotIn("📷 Real cannabis flower photograph",
                         [field.name for field in embed.fields])


if __name__ == "__main__":
    unittest.main()
