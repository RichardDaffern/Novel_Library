"""Offline regression for FanFicFare OPF subjects surviving chapter assembly."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_STORED

from tools.epub_source_metadata import clean_genres, read_source_metadata, source_metadata_from_package
from tools.chunked_download import assemble, chapter_plan
from novel_downloader import epub_chapters
from test_chunked_download import make_piece, URL


def fake_fanficfare_source(path: Path, subjects: list[str], description: str):
    container = ('<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
    from xml.sax.saxutils import escape
    package = ('<package xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<metadata>' + ''.join(f'<dc:subject>{escape(s)}</dc:subject>' for s in subjects)
               + f'<dc:description>{escape(description)}</dc:description></metadata></package>')
    with ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=ZIP_STORED)
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', package)


class GenreRegressionTests(unittest.TestCase):
    def test_filters_source_timestamps_and_status_without_dropping_genres(self):
        self.assertEqual(clean_genres(['Action', 'Martial Arts', 'Harem', 'Action', 'Last Update: 2026/11/08',
                                       'In-Progress', 'Fantasy', 'Last Update Year/Month: 2026/11']),
                         ['Action', 'Martial Arts', 'Harem', 'Fantasy'])

    def test_read_raw_original_batch_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'source.epub'
            fake_fanficfare_source(path, ['Action', 'Xuanhuan', 'In-Progress'], 'A concrete synopsis with <symbols>')
            self.assertEqual(read_source_metadata(path), {
                'genres': ['Action', 'Xuanhuan'], 'status': 'Ongoing',
                'description': 'A concrete synopsis with <symbols>',
            })

    def test_assembled_novel_restores_genres_status_synopsis_from_batch_epub(self):
        plan = chapter_plan(URL, 4, '1-4', chunk_size=2)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = make_piece(root / 'parts', URL, plan['key'], 1, 2)
            make_piece(root / 'parts', URL, plan['key'], 3, 4)
            fake_fanficfare_source(first / 'book' / 'source.epub',
                                   ['Action', 'Mystery', 'Supernatural', 'Last Update: 2026/11/08', 'Completed'],
                                   'A recovered source description & real characters')
            book = assemble(plan, root / 'parts', root / 'downloads')
            meta = json.loads((book / 'metadata.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['genres'], ['Action', 'Mystery', 'Supernatural'])
            self.assertEqual(meta['status'], 'Completed')
            self.assertEqual(meta['description'], 'A recovered source description & real characters')
            epub_meta, chapters = epub_chapters(book / 'source.epub')
            self.assertEqual(len(chapters), 4)
            self.assertEqual(epub_meta['genres'], meta['genres'])
            self.assertEqual(epub_meta['status'], 'Completed')
            self.assertEqual(epub_meta['description'], meta['description'])
            with ZipFile(book / 'source.epub') as z:
                opf = z.read('OEBPS/content.opf').decode()
                self.assertIn('<dc:subject>Supernatural</dc:subject>', opf)
                self.assertNotIn('Last Update:', opf)
                self.assertIn('A recovered source description &amp; real characters', opf)

    def test_assembly_prefers_existing_manifest_when_original_epub_missing_metadata(self):
        plan = chapter_plan(URL, 2, '1-2')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = make_piece(root / 'parts', URL, plan['key'], 1, 2)
            meta_path = first / 'book' / 'metadata.json'
            metadata = json.loads(meta_path.read_text())
            metadata['genres'] = ['Comedy', 'Romance']
            metadata['status'] = 'Ongoing'
            meta_path.write_text(json.dumps(metadata))
            book = assemble(plan, root / 'parts', root / 'downloads')
            exported = json.loads((book / 'metadata.json').read_text())
            self.assertEqual(exported['genres'], ['Comedy', 'Romance'])
            self.assertEqual(exported['status'], 'Ongoing')
            self.assertEqual(epub_chapters(book / 'source.epub')[0]['genres'], ['Comedy', 'Romance'])

if __name__ == '__main__':
    unittest.main()