"""Regression for converting old downloaded GitHub artifacts into one-novel ZIPs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "download_all_artifacts.ps1"


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell 5.1 integration test")
class WindowsNovelZipTests(unittest.TestCase):
    def test_abe_bulk_artifact_packs_only_the_expected_book(self):
        with tempfile.TemporaryDirectory(prefix="Novel Library With Spaces ") as temp:
            root = Path(temp)
            destination = root / "Downloaded_Novels"
            old = destination / "Abe the Wizard"
            abe = old / "downloads" / "86170fb9a61f117b" / "abe-the-wizard"
            unrelated = old / "downloads" / "16c3cf444f183f8d" / "alchemy-emperor-of-the-divine-dao"
            abe.mkdir(parents=True)
            unrelated.mkdir(parents=True)
            self.write_book(abe, "Abe the Wizard", "abe-the-wizard", 2)
            self.write_book(unrelated, "Alchemy Emperor", "alchemy-emperor-of-the-divine-dao", 1)
            partial = unrelated / "chapters_in_progress" / "chapter_00002.txt"
            partial.parent.mkdir()
            partial.write_text("Unfinished chapter", encoding="utf-8")
            (old / ".download-complete.json").write_text(
                json.dumps({"title": "Abe the Wizard", "artifact_id": 13592251409, "run_id": 42393126629}),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            registry.write_text(json.dumps({
                "version": 1,
                "novels": [{
                    "title": "Abe the Wizard",
                    "url": "https://novelfull.com/abe-the-wizard.html",
                    "downloads": [{
                        "range": "all", "status": "complete",
                        "artifact_id": 13592251409, "run_id": 42393126629,
                        "completed_at_utc": "2026-11-07T21:53:01Z",
                        "expires_at_utc": "2030-11-14T21:53:01Z",
                    }]
                }]
            }), encoding="utf-8")
            args = [
                "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SCRIPT), "-RepackOnly", "-RegistryFile", str(registry),
                "-Destination", str(destination),
            ]
            self.run_successfully(args)
            archive_path = destination / "novel-13592251409.zip"
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                expected = {
                    "abe-the-wizard/chapter_0001.txt",
                    "abe-the-wizard/chapter_0002.txt",
                    "abe-the-wizard/chapters.json",
                    "abe-the-wizard/metadata.json",
                    "abe-the-wizard/source.epub",
                }
                self.assertEqual(set(archive.namelist()), expected)
                metadata = json.loads(archive.read("abe-the-wizard/metadata.json"))
                self.assertEqual(metadata["source_url"], "https://novelfull.com/abe-the-wizard.html")
                self.assertEqual(len(json.loads(archive.read("abe-the-wizard/chapters.json"))), 2)
            self.assertFalse(old.exists(), "Old extracted directories must not remain inside ZIP output.")
            preserved = Path(str(destination) + "_Originals") / "Abe the Wizard"
            self.assertTrue((preserved / partial.relative_to(old)).is_file(), "Unrelated content must be preserved outside ZIP.")
            first_size = archive_path.stat().st_size
            self.run_successfully(args)
            self.assertEqual(archive_path.stat().st_size, first_size)

    def test_existing_zip_skipped_regardless_of_artifact_id_or_name(self):
        with tempfile.TemporaryDirectory(prefix="Novel Library Local ZIP ") as temp:
            root = Path(temp)
            destination = root / "Downloaded_Novels"
            destination.mkdir()
            source = root / "novel source"
            source.mkdir()
            self.write_book(source, "True Martial World", "true-martial-world", 2)
            # The filename is from a different Actions run than the registry.
            zip_path = destination / "novel-42368674563.zip"
            self.make_zip(source, zip_path, "true-martial-world")
            registry = root / "registry.json"
            self.write_registry(registry, "True Martial World", "true-martial-world", 98765432101)
            args = [
                "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SCRIPT), "-RegistryFile", str(registry),
                "-Destination", str(destination),
            ]
            result = self.run_successfully(args)
            self.assertIn("Already downloaded locally; skipping", result.stdout)
            self.assertIn("already local=1", result.stdout)
            self.assertEqual([f.name for f in destination.glob("*.zip")], [zip_path.name])
            self.assertFalse((destination / "novel-98765432101.zip").exists())

    def test_existing_zip_in_alternate_local_directory_is_skipped(self):
        with tempfile.TemporaryDirectory(prefix="Novel Library External ZIP ") as temp:
            root = Path(temp)
            destination = root / "Downloaded_Novels"
            existing_dir = root / "Uploader Novels"
            existing_dir.mkdir()
            source = root / "novel source"
            source.mkdir()
            self.write_book(source, "True Martial World", "true-martial-world", 2)
            # The local copy need not use the standard novel-ID filename.
            self.make_zip(source, existing_dir / "existing-book-copy.zip", "true-martial-world")
            registry = root / "registry.json"
            self.write_registry(registry, "True Martial World", "true-martial-world", 98765432101)
            args = [
                "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SCRIPT), "-RegistryFile", str(registry),
                "-Destination", str(destination),
                "-ExistingZipDirectory", str(existing_dir),
            ]
            result = self.run_successfully(args)
            self.assertIn("Already downloaded locally; skipping", result.stdout)
            self.assertIn("already local=1", result.stdout)
            self.assertFalse(list(destination.glob("*.zip")))
            self.assertTrue((existing_dir / "existing-book-copy.zip").exists())

    def test_corrupt_local_zip_is_not_treated_as_complete(self):
        with tempfile.TemporaryDirectory(prefix="Novel Library Invalid ZIP ") as temp:
            root = Path(temp)
            destination = root / "Downloaded_Novels"
            destination.mkdir()
            invalid_zip = destination / "novel-98765432101.zip"
            invalid_zip.write_bytes(b"not a zip archive")
            registry = root / "registry.json"
            self.write_registry(registry, "True Martial World", "true-martial-world", 98765432101)
            args = [
                "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SCRIPT), "-RegistryFile", str(registry),
                "-Destination", str(destination), "-RepackOnly",
            ]
            result = subprocess.run(
                args, cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=180
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("failed/unavailable=1", result.stdout)
            self.assertTrue(invalid_zip.exists(), "An invalid local ZIP must not be silently deleted")

    @staticmethod
    def make_zip(source, target, slug):
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for item in source.iterdir():
                if item.is_file():
                    out.write(item, f"{slug}/{item.name}")

    @staticmethod
    def write_registry(path, title, slug, artifact_id):
        path.write_text(json.dumps({
            "version": 1,
            "novels": [{
                "title": title,
                "url": f"https://novelfull.com/{slug}.html",
                "downloads": [{
                    "range": "all", "status": "complete",
                    "artifact_id": artifact_id, "run_id": 123456,
                    "completed_at_utc": "2026-11-07T21:53:01Z",
                    "expires_at_utc": "2030-11-14T21:53:01Z"
                }]
            }]
        }), encoding="utf-8")

    def run_successfully(self, command):
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        return result

    @staticmethod
    def write_book(folder, title, slug, count):
        (folder / "source.epub").write_bytes(b"PK" + b"A" * 256)
        (folder / "metadata.json").write_text(
            json.dumps({
                "title": title,
                "source_url": f"https://novelfull.com/{slug}.html",
                "chapter_count": count
            }), encoding="utf-8"
        )
        (folder / "chapters.json").write_text(
            json.dumps([{"position": i, "file": f"chapter_{i:04d}.txt"} for i in range(1, count + 1)]),
            encoding="utf-8",
        )
        for i in range(1, count + 1):
            (folder / f"chapter_{i:04d}.txt").write_text(f"{title}: chapter {i}", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
