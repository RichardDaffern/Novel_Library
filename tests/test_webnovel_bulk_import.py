"""Offline synthetic tests for bulk authorised saved-page import."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_STORED

from tools.webnovel_bulk_import import (
    BulkImportError, bulk_import, plan_import, parse_chapter_name, STATE_NAME, main,
)


def make_html(n):
    return (
        f'<html><nav>Unlock this chapter</nav><div class="cha-content">'
        f'<p>This is an entirely invented chapter number {n} set in a faraway '
        'fictional town. The characters share a mysterious map of a quiet island.</p>'
        '<p>A second original paragraph describes an ordinary afternoon, '
        'with enough detail to make the chapter content realistic.</p></div></html>'
    )


def write_chapters(folder, numbers):
    result = []
    for n in numbers:
        path = folder / f'Invented Novel Chapter {n} - Chapter {n}_ The Adventure - WebNovel.html'
        path.write_text(make_html(n), encoding='utf-8')
        result.append(path)
    return result


class BulkImportTests(unittest.TestCase):
    def test_chapter_title_from_browser_filename(self):
        n, title = parse_chapter_name(Path('Harry Potter_ Platinum Dragon Wizard Chapter 1 - Chapter 1_ On the Hogwarts Express - WebNovel.html'))
        self.assertEqual(n, 1)
        self.assertEqual(title, 'Chapter 1: On the Hogwarts Express')
        self.assertEqual(parse_chapter_name(Path('chapter_0002.html')), (2, 'Chapter 2'))
        with self.assertRaisesRegex(BulkImportError, 'Conflicting'):
            parse_chapter_name(Path('Novel Chapter 1 - Chapter 2.html'))

    def test_many_chapters_epub_and_metadata_and_order(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'input'
            inp.mkdir()
            write_chapters(inp, range(1, 131))
            events = []
            out = root / 'out'
            result = bulk_import(inp, out, 'My Fiction & Friends', 'An Author',
                                 confirm_rights=True, progress=events.append)
            self.assertEqual(result['chapter_count'], 130)
            self.assertEqual(result['chapters'][0]['position'], 1)
            self.assertEqual(result['chapters'][-1]['position'], 130)
            self.assertEqual(len(events), 131)
            self.assertIn('130/130', events[-2])
            combined = (out / 'book.txt').read_text(encoding='utf-8')
            self.assertLess(combined.index('chapter number 2 set'), combined.index('chapter number 10 set'))
            self.assertEqual(result, json.loads((out / 'metadata.json').read_text(encoding='utf-8')))
            with ZipFile(out / 'book.epub') as archive:
                self.assertEqual(archive.namelist()[0], 'mimetype')
                self.assertEqual(archive.getinfo('mimetype').compress_type, ZIP_STORED)
                self.assertIsNone(archive.testzip())
                ET.fromstring(archive.read('OEBPS/content.opf'))
                ET.fromstring(archive.read('OEBPS/toc.ncx'))
                pages = [name for name in archive.namelist() if name.endswith('.xhtml')]
                self.assertEqual(len(pages), 130)
                self.assertEqual(pages[0], 'OEBPS/chapter-000001.xhtml')
                self.assertEqual(pages[-1], 'OEBPS/chapter-000130.xhtml')
                self.assertIn('chapter number 1', ''.join(ET.fromstring(archive.read(pages[0])).itertext()))

    def test_range_selection_and_html_txt_mix(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1, 2, 3, 4])
            (inp / 'chapter_0005.txt').write_text('An entirely invented chapter set in an ordinary place. ' * 4)
            result = bulk_import(inp, root / 'out', 'Example', 'Author',
                                 chapter_range='2-5', confirm_rights=True,
                                 progress=lambda _: None)
            self.assertEqual([c['position'] for c in result['chapters']], [2, 3, 4, 5])
            self.assertFalse((root / 'out' / 'chapter-000001.txt').exists())

    def test_missing_chapter_fails_before_writing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1, 3])
            with self.assertRaisesRegex(BulkImportError, 'Missing 1 chapter.*2'):
                bulk_import(inp, root / 'out', 'Example', 'Author', confirm_rights=True)
            self.assertFalse((root / 'out').exists())

    def test_duplicates_fail_before_writing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1, 2])
            (inp / 'Chapter 01.txt').write_text('Some other original text. ' * 9)
            with self.assertRaisesRegex(BulkImportError, 'Duplicate chapter 1'):
                bulk_import(inp, root / 'out', 'Example', 'Author', confirm_rights=True)
            self.assertFalse((root / 'out').exists())

    def test_bad_filenames_are_not_silently_skipped(self):
        with TemporaryDirectory() as tmp:
            inp = Path(tmp)
            (inp / 'notes.txt').write_text('Notes that are not chapter material')
            with self.assertRaisesRegex(BulkImportError, 'No chapter number'):
                plan_import(inp)

    def test_dry_run_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1, 2])
            result = bulk_import(inp, root / 'out', 'Example', 'Author',
                                 confirm_rights=True, dry_run=True)
            self.assertEqual(result['chapter_count'], 2)
            self.assertFalse((root / 'out').exists())

    def test_interrupted_run_resumes_without_reextracting_chapter_one(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1, 2, 3])
            out = root / 'out'
            from tools import webnovel_bulk_import as module
            from tools.webnovel_saved_pages import SavedPageError
            original = module.read_saved_chapter

            def fail_second(path, title):
                if 'Chapter 2' in str(path):
                    raise SavedPageError('simulated temporary read failure')
                return original(path, title)

            with patch.object(module, 'read_saved_chapter', side_effect=fail_second):
                with self.assertRaisesRegex(BulkImportError, 'Chapter 2'):
                    bulk_import(inp, out, 'Example', 'Author', confirm_rights=True,
                                progress=lambda _: None)
            self.assertTrue((out / 'chapter-000001.txt').exists())
            self.assertFalse((out / 'book.epub').exists())
            self.assertEqual(len(json.loads((out / STATE_NAME).read_text())['completed']), 1)

            def ensure_not_first(path, title):
                if 'Chapter 1' in str(path):
                    raise AssertionError('first chapter unnecessarily extracted')
                return original(path, title)

            with patch.object(module, 'read_saved_chapter', side_effect=ensure_not_first):
                result = bulk_import(inp, out, 'Example', 'Author',
                                     confirm_rights=True, resume=True,
                                     progress=lambda _: None)
            self.assertEqual(result['chapter_count'], 3)
            self.assertTrue((out / 'book.epub').exists())

    def test_changed_source_detected_before_resume(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            paths = write_chapters(inp, [1, 2])
            out = root / 'out'
            bulk_import(inp, out, 'Example', 'Author',
                        confirm_rights=True, progress=lambda _: None)
            paths[0].write_text(make_html(1) + 'changed', encoding='utf-8')
            with self.assertRaisesRegex(BulkImportError, 'source changed'):
                bulk_import(inp, out, 'Example', 'Author',
                            confirm_rights=True, resume=True, progress=lambda _: None)

    def test_changed_output_detected_before_resume(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1])
            out = root / 'out'
            bulk_import(inp, out, 'Example', 'Author',
                        confirm_rights=True, progress=lambda _: None)
            (out / 'chapter-000001.txt').write_text('tampered', encoding='utf-8')
            with self.assertRaisesRegex(BulkImportError, 'output changed'):
                bulk_import(inp, out, 'Example', 'Author',
                            confirm_rights=True, resume=True, progress=lambda _: None)

    def test_resume_rejects_book_identity_changes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1])
            out = root / 'out'
            bulk_import(inp, out, 'Example', 'Author',
                        confirm_rights=True, progress=lambda _: None)
            with self.assertRaisesRegex(BulkImportError, 'mismatch'):
                bulk_import(inp, out, 'Different', 'Author',
                            confirm_rights=True, resume=True, progress=lambda _: None)

    def test_locked_saved_page_preserves_checkpoint(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            paths = write_chapters(inp, [1, 2])
            out = root / 'out'
            paths[1].write_text(
                '<html><div class="cha-content">Unlock this chapter to read</div></html>',
                encoding='utf-8',
            )
            with self.assertRaisesRegex(BulkImportError, 'Chapter 2'):
                bulk_import(inp, out, 'Example', 'Author',
                            confirm_rights=True, progress=lambda _: None)
            self.assertEqual(len(json.loads((out / STATE_NAME).read_text())['completed']), 1)
            self.assertFalse((out / 'book.epub').exists())

    def test_nonempty_output_requires_resume(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1])
            out = root / 'out'
            out.mkdir()
            (out / 'something.txt').write_text('not ours')
            with self.assertRaisesRegex(BulkImportError, '--resume'):
                bulk_import(inp, out, 'Example', 'Author',
                            confirm_rights=True, progress=lambda _: None)

    def test_rights_required_no_input_read(self):
        with patch('tools.webnovel_bulk_import.plan_import') as plan:
            with self.assertRaisesRegex(BulkImportError, 'confirm-rights'):
                bulk_import('anything', 'out', 'Example', 'Author')
            plan.assert_not_called()

    def test_input_and_output_must_differ(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BulkImportError, 'differ'):
                bulk_import(tmp, tmp, 'Example', 'Author', confirm_rights=True)

    def test_range_validation(self):
        from tools.webnovel_bulk_import import parse_range
        for invalid in ('abc', '2-1', '0-2', '1-10001', '1 to 3'):
            with self.subTest(invalid=invalid), self.assertRaises(BulkImportError):
                parse_range(invalid)

    def test_cli_dry_run_no_network(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / 'in'
            inp.mkdir()
            write_chapters(inp, [1, 2])
            with patch('urllib.request.urlopen', side_effect=AssertionError('network request not permitted')):
                exit_code = main([
                    '--input-dir', str(inp), '--output-dir', str(root / 'out'),
                    '--book-title', 'Example', '--author', 'Author',
                    '--dry-run', '--confirm-rights',
                ])
            self.assertEqual(exit_code, 0)
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
