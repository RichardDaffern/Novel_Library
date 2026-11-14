"""Cross-platform regression for actual novel chapter bytes and manifest hashes."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from novel_downloader import export_epub
from tools.chunked_download import _epub


class ExportByteHashTests(unittest.TestCase):
    def test_export_epub_writes_exact_manifest_hash_bytes_on_windows_and_linux(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "source"
            original.mkdir()
            original_text = (
                "Chapter 1\n\n"
                "This is an entirely synthetic example chapter.\n"
                "It has two short lines and no real source material.\n"
            )
            (original / "chapter_00001.txt").write_bytes(original_text.encode("utf-8"))
            rows = [{"position": 1, "chapter_number": 1, "title": "Chapter 1",
                     "file": "chapter_00001.txt", "word_count": 16,
                     "sha256": sha256(original_text.encode("utf-8")).hexdigest()}]
            _epub(original, rows, "Synthetic Example", "Original Writer", "en",
                  "https://example.org/book", description="Test synopsis")
            target = root / "converted"
            exported = export_epub(original / "source.epub", target, "https://example.org/book")
            self.assertEqual(exported["chapter_count"], 1)
            manifest = json.loads((target / "chapters.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest), 1)
            contents = (target / manifest[0]["file"]).read_bytes()
            self.assertNotIn(b"\r\n", contents, "Chapter content must be stable across OS")
            self.assertEqual(sha256(contents).hexdigest(), manifest[0]["sha256"])


if __name__ == "__main__":
    unittest.main()
