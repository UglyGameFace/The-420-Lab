"""No-credential regression tests for durable staged photo queue."""
import tempfile
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lab.growers import GrowerHub
from lab.strain_profiles import StrainProfileStore
from lab.grower_intake import GrowerIntake


class QueueStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "growers.sqlite3")
        self.hub = GrowerHub(StrainProfileStore(self.path))
        self.hub.configure(5, 101, 102)

    def test_durable_queue_receipt_claim_finish_and_cleanup(self):
        sid, key = self.hub.start_staged_upload(5, 800, "Grower", "Blue Dream",
                                                 "flowering", "", 101)
        self.assertTrue(key.startswith(f"photos/5/{sid}/"))
        self.assertEqual(self.hub.stage_info(5, sid), (key, "receiving"))
        self.assertEqual(self.hub.item(5, sid)[8], "uploading")
        self.hub.stage_confirmed(5, sid)
        again = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(again.my_uploads(5, 800)[0][2], "queued")
        job = again.claim_stage()
        self.assertEqual(job[:3], ("5", sid, key))
        self.assertIsNone(again.claim_stage())
        again.finish_staged_upload(5, sid, 333)
        self.assertEqual(again.item(5, sid)[8], "pending")
        self.assertEqual(again.item(5, sid)[6], "333")
        self.assertEqual(again.cleanup_entries(), [("5", sid, key)])
        again.stage_cleanup(5, sid)
        self.assertEqual(again.cleanup_entries(), [])
        self.assertIsNone(again.stage_info(5, sid))

    def test_queue_limits_are_enforced_without_stranding_overflow_records(self):
        for i in range(20):
            self.hub.start_staged_upload(5, 1000+i, "Grower",
                                         "Blue Dream", "flowering", "", 101)
        with self.assertRaisesRegex(ValueError, "20-photo"):
            self.hub.start_staged_upload(5, 9999, "Grower",
                                         "Blue Dream", "flowering", "", 101)
        self.assertEqual(self.hub.my_uploads(5, 9999), [])

    def test_30_minute_expiry_cleans_queue_but_preserves_member_receipt(self):
        sid, key = self.hub.start_staged_upload(
            5, 404, "Grower", "Blue Dream", "flowering", "", 101)
        self.hub.stage_confirmed(5, sid)
        self.assertEqual(self.hub.expire_queued(), 0)
        old = (datetime.now(timezone.utc) - timedelta(minutes=31)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE grower_stage_queue SET created_utc=? WHERE submission=?",
                       (old, sid))
        restarted = GrowerHub(StrainProfileStore(self.path))
        self.assertEqual(restarted.expire_queued(), 1)
        self.assertIsNone(restarted.claim_stage())
        self.assertEqual(restarted.item(5, sid)[8], "expired")
        self.assertEqual(restarted.my_uploads(5, 404)[0][2], "expired")
        self.assertEqual(restarted.cleanup_entries(), [("5", sid, key)])
        restarted.stage_cleanup(5, sid)
        self.assertIsNone(restarted.stage_info(5, sid))
        row = restarted.lock(5, sid, purpose="remove", user_id=404)
        self.assertEqual(row[8], "expired")
        restarted.delete(5, sid, "removing")
        self.assertIsNone(restarted.item(5, sid))

    def test_processing_photo_does_not_expire_while_result_is_uncertain(self):
        sid, key = self.hub.start_staged_upload(
            5, 405, "Grower", "Blue Dream", "flowering", "", 101)
        self.hub.stage_confirmed(5, sid)
        old = (datetime.now(timezone.utc) - timedelta(minutes=31)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE grower_stage_queue SET created_utc=? WHERE submission=?",
                       (old, sid))
        job = self.hub.claim_stage()
        self.assertEqual(job[2], key)
        self.assertEqual(self.hub.expire_queued(), 0)
        self.assertEqual(self.hub.item(5, sid)[8], "uploading")
        self.assertEqual(self.hub.stage_info(5, sid)[1], "processing")

    def test_normal_submission_still_works(self):
        sid = self.hub.begin_upload(5, 777, "Grower", "Blue Dream",
                                     "flowering", "", 101)
        self.hub.finish_upload(5, sid, 151)
        self.assertEqual(self.hub.pending(5)[0][4], "151")


class IntakeValidationTests(unittest.TestCase):
    def test_original_urls_are_restricted(self):
        for url in ("http://cdn.discordapp.com/attachments/3/4/x.png",
                    "https://evil.example/attachments/3/4/x.png",
                    "https://cdn.discordapp.com.evil.test/attachments/3/4/x.png",
                    "https://cdn.discordapp.com/not-attachments/3"):
            with self.assertRaises(ValueError):
                GrowerIntake._source(url)

    def test_only_private_object_keys_accepted(self):
        mock_session = SimpleNamespace()
        store = GrowerIntake("https://stage.example.com", "x" * 48, mock_session)
        good = "photos/5/1/" + "0"*32
        self.assertTrue(store._endpoint(good).endswith(good))
        for key in ("../secret", "photos/5/1/hello", "photos/5/1/"+"Q"*32):
            with self.assertRaises(ValueError):
                store._endpoint(key)


if __name__ == "__main__":
    unittest.main()
