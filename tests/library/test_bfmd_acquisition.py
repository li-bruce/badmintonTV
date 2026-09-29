"""BFMD selection boundaries, using only the checked-in catalog and deep copies."""

import copy
import json
from pathlib import Path
import unittest

from scripts.library import acquire_bfmd_annotations as acquisition


class BfmdAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.reviewed = json.loads((root / "configs/library/bfmd_sources.json").read_text(encoding="utf-8-sig"))

    def changed(self, **fields):
        config = copy.deepcopy(self.reviewed)
        config["files"][0].update(fields)
        return config

    def test_reviewed_annotation_and_archive_only_source_selection_is_accepted(self):
        sources = acquisition.validate_config(copy.deepcopy(self.reviewed))
        self.assertEqual(121, len(sources))
        self.assertEqual(1_825_439_459, sum(item["expected_bytes"] for item in sources))
        self.assertEqual(115, sum(Path(item["relative_path"]).suffix == ".json" for item in sources))
        self.assertEqual(1, sum(Path(item["relative_path"]).suffix == ".bak" for item in sources))

    def test_media_and_nonportable_paths_are_rejected(self):
        for path in ("match.mp4", "annotations/match.MKV", "../escape.json", "/absolute.json",
                     "annotations/../escape.json", "annotations\\file.json", "D:/source.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(relative_path=path))

    def test_url_must_bind_the_selected_public_drive_id(self):
        for url in ("https://example.invalid/source.json", "http://drive.usercontent.google.com/uc",
                    self.reviewed["files"][0]["url"] + "&other=1", self.reviewed["files"][1]["url"]):
            with self.subTest(url=url), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(url=url))

    def test_media_kind_or_mime_is_rejected_even_under_json_filename(self):
        for fields in ({"kind": "media"}, {"mime_type": "video/mp4"},
                       {"kind": "media", "mime_type": "video/mp4"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(**fields))

    def test_same_size_substitute_drive_id_and_matching_url_is_rejected(self):
        substituted = "unreviewedDriveFile123456789"
        changed = self.changed(google_drive_id=substituted,
                               url=f"https://drive.usercontent.google.com/uc?id={substituted}&export=download")
        self.assertEqual(self.reviewed["files"][0]["expected_bytes"], changed["files"][0]["expected_bytes"])
        with self.assertRaisesRegex(ValueError, "identities changed"):
            acquisition.validate_config(changed)

    def test_sizes_require_finite_integer_bound_and_exact_reviewed_total(self):
        for value in (False, 0, -1, 200_000_001, float("inf"),
                      self.reviewed["files"][0]["expected_bytes"] + 1):
            with self.subTest(size=value), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(expected_bytes=value))

    def test_duplicate_case_insensitive_paths_and_drive_ids_are_rejected(self):
        config = copy.deepcopy(self.reviewed)
        config["files"][1]["relative_path"] = config["files"][0]["relative_path"].upper()
        with self.assertRaises(ValueError):
            acquisition.validate_config(config)
        config = copy.deepcopy(self.reviewed)
        config["files"][1].update(google_drive_id=config["files"][0]["google_drive_id"],
                                  url=config["files"][0]["url"])
        with self.assertRaises(ValueError):
            acquisition.validate_config(config)

    def test_dataset_scope_revision_and_file_count_are_fixed(self):
        for key, value in (("schema_version", "2.0"), ("dataset_id", "other"),
                           ("usage_scope", "general"), ("repository_commit", "0" * 40)):
            config = copy.deepcopy(self.reviewed)
            config[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                acquisition.validate_config(config)
        config = copy.deepcopy(self.reviewed)
        config["files"].pop()
        with self.assertRaises(ValueError):
            acquisition.validate_config(config)


if __name__ == "__main__":
    unittest.main()
