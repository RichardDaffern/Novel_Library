"""Fully offline regression tests for the verified FicHub author-crosspost route."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from tools.chunked_download import _epub
from tools.verified_crosspost_download import (
    CrosspostDownloadError, _epub_url, download_verified_crosspost,
)

SH = "https://www.scribblehub.com/series/445037/the-adventurous-gamer-ninja--daichi-hekima/"
FF = "https://www.fanfiction.net/s/14031894/1/The-Adventurous-Gamer-Ninja-Daichi-Hekima"
META = {
    "title": "The Adventurous Gamer Ninja - Daichi Hekima",
    "author": "MonkWithAPen", "chapters": 2, "source": FF,
}
ENTRY = {
    "title": META["title"], "author": META["author"],
    "minimum_chapters": 2, "fanfiction_url": FF,
    "first_chapter_title": "My Second Chance",
    "front_matter": ["Introduction", "The Adventurous Gamer Ninja - Daichi Hekima"],
    "chapter_checkpoints": [{"position": 2, "title": "Waking up as Daichi Hekima"}],
}
REGISTRY = {"445037": ENTRY}
EPUB_URL = "/cache/epub/Example8/Test_by_Author-Example8.epub?h=1234567890abcdef1234567890abcdef"


class FakeResponse:
    def __init__(self, code, *, json_body=None, data=b"", headers=None):
        self.status_code = code
        self._json_body = json_body
        self._data = data
        self.headers = headers or {}
        self.closed = False

    def json(self):
        if self._json_body is None:
            raise ValueError("No JSON")
        return self._json_body

    def iter_content(self, chunk_size=65536):
        for index in range(0, len(self._data), chunk_size):
            yield self._data[index:index + chunk_size]

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, manifest=None, epub=b"", api_status=200, epub_status=200):
        self.requests = []
        self.manifest = (
            {"err": 0, "meta": META.copy(), "epub_url": EPUB_URL}
            if manifest is None else manifest
        )
        self.epub = epub
        self.api_status = api_status
        self.epub_status = epub_status

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if url == "https://fichub.net/api/v0/epub":
            return FakeResponse(self.api_status, json_body=self.manifest)
        if url.startswith("https://fichub.net/cache/epub/"):
            return FakeResponse(self.epub_status, data=self.epub)
        raise AssertionError(f"Unexpected network request {url}")


def synthetic_epub(folder: Path, *, front=True, missing_last=False) -> bytes:
    folder.mkdir()
    headings = (
        ["Introduction", "The Adventurous Gamer Ninja - Daichi Hekima"]
        if front else []
    ) + ["My Second Chance"]
    if not missing_last:
        headings.append("Waking up as Daichi Hekima")
    rows = []
    for number, title in enumerate(headings, 1):
        file = f"chapter_{number:05d}.txt"
        data = (
            f"{title}\n\n"
            + ("This is wholly invented regression-only story text. " * 14)
            + f"Section number {number}.\n"
        ).encode("utf-8")
        (folder / file).write_bytes(data)
        rows.append({
            "position": number, "chapter_number": number, "title": title,
            "file": file, "sha256": sha256(data).hexdigest(), "word_count": 140,
        })
    _epub(folder, rows, META["title"], META["author"], "en", FF,
          description="An invented test-only synopsis", genres=["Fantasy"])
    return (folder / "source.epub").read_bytes()


class CrosspostDownloadTests(unittest.TestCase):
    def test_success_uses_one_provider_export_and_one_epub_download(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = synthetic_epub(root / "fixture")
            client = FakeClient(epub=book)
            result = download_verified_crosspost(
                SH, root / "output", confirm_rights=True,
                client=client, registry=REGISTRY,
            )
            self.assertEqual(len(client.requests), 2)
            self.assertEqual(client.requests[0][1]["params"]["q"], FF)
            self.assertFalse(client.requests[0][1]["allow_redirects"])
            self.assertFalse(client.requests[1][1]["allow_redirects"])
            self.assertTrue(result.name.startswith("novel-"))
            with ZipFile(result) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertTrue(any(name.endswith("/source.epub") for name in names))
                manifest_name = next(n for n in names if n.endswith("/chapters.json"))
                meta_name = next(n for n in names if n.endswith("/metadata.json"))
                prefix = manifest_name[:-len("chapters.json")]
                rows = json.loads(archive.read(manifest_name))
                metadata = json.loads(archive.read(meta_name))
                self.assertEqual(len(rows), 2)
                self.assertEqual([r["title"] for r in rows],
                                 ["My Second Chance", "Waking up as Daichi Hekima"])
                self.assertEqual([r["position"] for r in rows], [1, 2])
                self.assertEqual(metadata["source_url"], SH)
                self.assertEqual(metadata["description"], "An invented test-only synopsis")
                for row in rows:
                    contents = archive.read(prefix + row["file"])
                    self.assertNotIn(b"\r\n", contents)
                    self.assertEqual(sha256(contents).hexdigest(), row["sha256"])

    def test_absence_of_frontmatter_also_supported_for_future_provider_change(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = synthetic_epub(root / "fixture", front=False)
            client = FakeClient(epub=epub)
            archive = download_verified_crosspost(
                SH, root / "output", confirm_rights=True,
                client=client, registry=REGISTRY,
            )
            self.assertTrue(archive.is_file())

    def test_missing_last_chapter_is_not_published(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = synthetic_epub(root / "fixture", missing_last=True)
            client = FakeClient(epub=epub)
            with self.assertRaisesRegex(CrosspostDownloadError, "readable sections"):
                download_verified_crosspost(
                    SH, root / "output", confirm_rights=True,
                    client=client, registry=REGISTRY,
                )
            self.assertEqual(list((root / "output").glob("*.zip")), []) if (root / "output").exists() else None

    def test_permission_and_unregistered_id_refused_without_network(self):
        client = FakeClient()
        with self.assertRaisesRegex(CrosspostDownloadError, "confirm-rights"):
            download_verified_crosspost(SH, Path("unused"), client=client, registry=REGISTRY)
        with self.assertRaisesRegex(CrosspostDownloadError, "No author-verified"):
            download_verified_crosspost(
                SH.replace("/445037/", "/445038/"), Path("unused"),
                confirm_rights=True, client=client, registry=REGISTRY,
            )
        self.assertEqual(client.requests, [])

    def test_unverified_source_author_and_chapters_rejected(self):
        altered = [
            dict(META, author="Different Writer"),
            dict(META, source="https://www.fanfiction.net/s/99999999/1/Other"),
            dict(META, chapters=1),
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for idx, meta in enumerate(altered):
                with self.subTest(meta=meta), self.assertRaises(CrosspostDownloadError):
                    download_verified_crosspost(
                        SH, root / f"output{idx}", confirm_rights=True,
                        client=FakeClient(manifest={
                            "err": 0, "meta": meta, "epub_url": EPUB_URL,
                        }), registry=REGISTRY,
                    )

    def test_provider_declines_or_rate_limits_without_chapter_requests(self):
        for manifest, status in (
            ({"err": -7, "meta": META, "epub_url": EPUB_URL}, 200),
            ({"err": 0, "meta": META, "epub_url": EPUB_URL}, 429),
        ):
            with self.subTest(status=status, err=manifest["err"]):
                client = FakeClient(manifest=manifest, api_status=status)
                with self.assertRaises(CrosspostDownloadError):
                    download_verified_crosspost(
                        SH, Path("unused"), confirm_rights=True,
                        client=client, registry=REGISTRY,
                    )
                self.assertEqual(len(client.requests), 1)

    def test_unsafe_provider_urls_rejected(self):
        for link in (
            "https://other.example/evil.epub",
            "//evil.example/cache/epub/abc/file.epub",
            "/cache/epub/../admin/secrets.epub",
            "/cache/epub/123/file.epub#frag",
        ):
            with self.subTest(link=link), self.assertRaises(CrosspostDownloadError):
                _epub_url({"epub_url": link})

    def test_existing_archive_preserved_and_series_slug_not_part_of_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = synthetic_epub(root / "fixture")
            old_client = FakeClient(epub=book)
            output = download_verified_crosspost(
                SH, root / "output", confirm_rights=True,
                client=old_client, registry=REGISTRY,
            )
            prior = output.read_bytes()
            no_requests = FakeClient(epub=book)
            changed_slug = "https://www.scribblehub.com/series/445037/renamed-story/"
            with self.assertRaisesRegex(CrosspostDownloadError, "already exists"):
                download_verified_crosspost(
                    changed_slug, root / "output", confirm_rights=True,
                    client=no_requests, registry=REGISTRY,
                )
            self.assertEqual(no_requests.requests, [])
            self.assertEqual(prior, output.read_bytes())
            with self.assertRaises(CrosspostDownloadError):
                download_verified_crosspost(
                    SH, root / "output", confirm_rights=True, replace=True,
                    client=FakeClient(api_status=503), registry=REGISTRY,
                )
            self.assertEqual(prior, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
