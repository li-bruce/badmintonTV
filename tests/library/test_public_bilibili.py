import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.library.acquire_public_bilibili import resolve
from scripts.library.acquire_classic_matches import validate_config


class PublicBilibiliTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / "configs/library/classic_matches.json"
        self.config = json.loads(path.read_text(encoding="utf-8"))
        self.config["sources"] = self.config["sources"][:1]
        pin = self.config["sources"][0]["source_metadata"]
        self.view = {
            "bvid": pin["bvid"], "cid": pin["cid"],
            "owner": {"mid": pin["expected_owner_mid"], "name": "Olympics"},
            "duration": pin["expected_duration_seconds"],
            "rights": {"download": 1, "pay": 0, "no_reprint": 1},
            "title": "Fixture replay", "pubdate": 1692280800,
        }
        self.play = {"format": "mp4720", "quality": 64, "durl": [{
            "url": "https://fixture.bilivideo.com/file.mp4?sign=PRIVATE_SIGNATURE",
            "size": 482738928, "length": 3337000,
        }]}

    def test_private_transport_stays_out_of_persistable_plan(self):
        with patch("scripts.library.acquire_public_bilibili.public_json", side_effect=[self.view, self.play]):
            config = resolve(self.config)
        _, sources, transports = validate_config(config)
        self.assertNotIn("PRIVATE_SIGNATURE", json.dumps(sources))
        self.assertIn("PRIVATE_SIGNATURE", next(iter(transports.values())))
        self.assertEqual(sources[0]["expected_size_bytes"], 482738928)
        self.assertEqual(sources[0]["source_metadata"]["rights"]["no_reprint"], 1)
        self.assertNotIn("resolved_url", self.config["sources"][0])

    def test_download_denial_or_payment_stops_before_resolving_media(self):
        for rights in ({"download": 0}, {"download": 1, "pay": 1}, {"download": 1, "ugc_pay": 1}):
            view = copy.deepcopy(self.view)
            view["rights"] = rights
            with self.subTest(rights=rights), patch(
                "scripts.library.acquire_public_bilibili.public_json", return_value=view
            ) as fetch:
                with self.assertRaisesRegex(ValueError, "permit free download"):
                    resolve(self.config)
                self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
