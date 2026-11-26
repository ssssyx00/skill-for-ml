import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('index_courseware', ROOT / 'scripts/index_courseware.py')
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/study_state.py'),
                            '--file', str(self.base / 'progress.json'), *args],
                           capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        else:
            self.assertNotEqual(r.returncode, 0)
        return r

    def test_pdf_retains_different_figures_and_new_formula(self):
        import fitz
        src = self.base / 'lesson.pdf'
        doc = fitz.open()
        for color, formula in [((1, 0, 0), 'x = 1'), ((0, 0, 1), 'x = 1'), ((0, 0, 1), 'x = 2')]:
            p = doc.new_page()
            p.insert_text((50, 60), 'Same heading; this text has more than forty characters. ' + formula)
            p.draw_rect(fitz.Rect(50, 100, 150, 200), fill=color)
        doc.save(src)
        doc.close()
        before = src.read_bytes()
        result = index.index_file(src, self.base / 'out', 'all')
        data = json.loads(Path(result['index']).read_text())
        self.assertEqual(len(data['pages']), 3)
        self.assertEqual(data['duplicate_candidates'][0]['page'], 2)
        self.assertEqual(len(data['duplicate_candidates']), 1)
        self.assertIn('x = 2', data['pages'][2]['text'])
        self.assertTrue(all(p['printed_page'] is None for p in data['pages']))
        image1 = Path(result['index']).parent / data['pages'][0]['render']
        image2 = Path(result['index']).parent / data['pages'][1]['render']
        self.assertNotEqual(image1.read_bytes(), image2.read_bytes())
        self.assertEqual(before, src.read_bytes())
        self.assertEqual(data['source_sha256'], hashlib.sha256(before).hexdigest())
        with self.assertRaises(FileExistsError):
            index.index_file(src, self.base / 'out')
        part = index.index_file(src, self.base / 'part', 'all', '2-3')
        subset = json.loads(Path(part['index']).read_text())
        self.assertEqual([p['page'] for p in subset['pages']], [2, 3])
        self.assertEqual(subset['page_count'], 3)
        self.assertEqual(subset['indexed_page_count'], 2)

    def test_pptx_uses_presentation_order_and_note_relationship(self):
        src = self.base / 'slides.pptx'
        P, A, R = index.P, index.A, index.R
        relns = 'http://schemas.openxmlformats.org/package/2006/relationships'
        def xml(text):
            return f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>'
        with zipfile.ZipFile(src, 'w') as z:
            z.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst><p:sldId id="2" r:id="b"/><p:sldId id="1" r:id="a"/></p:sldIdLst></p:presentation>')
            z.writestr('ppt/_rels/presentation.xml.rels', f'<Relationships xmlns="{relns}"><Relationship Id="a" Target="slides/slide1.xml" Type="{R}/slide"/><Relationship Id="b" Target="slides/slide2.xml" Type="{R}/slide"/></Relationships>')
            z.writestr('ppt/slides/slide1.xml', xml('Shown second'))
            z.writestr('ppt/slides/slide2.xml', xml('Shown first'))
            z.writestr('ppt/slides/_rels/slide2.xml.rels', f'<Relationships xmlns="{relns}"><Relationship Id="note" Target="../notesSlides/notesSlide17.xml" Type="{R}/notesSlide"/></Relationships>')
            z.writestr('ppt/notesSlides/notesSlide17.xml', f'<p:notes xmlns:p="{P}" xmlns:a="{A}"><p:sp><p:ph type="body"/><a:p><a:r><a:t>17</a:t></a:r></a:p></p:sp><p:sp><p:ph type="sldNum"/><a:p><a:r><a:t>99</a:t></a:r></a:p></p:sp></p:notes>')
        data = list(index.pptx_pages(src))
        self.assertEqual([p['text'] for p in data], ['Shown first', 'Shown second'])
        self.assertEqual(data[0]['notes'], '17')
        self.assertEqual(data[0]['page'], 1)
        self.assertTrue(data[0]['needs_visual_review'])
        self.assertEqual(list(index.pptx_pages(src, '2'))[0]['text'], 'Shown second')

    def test_invalid_ranges_and_partial_cli_failure_are_explicit(self):
        import fitz
        for value in ('0', '2-1', '1-4', 'abc'):
            with self.assertRaises(ValueError):
                index.select_pages(value, 3)
        bad = self.base / 'bad.pdf'
        bad.write_bytes(b'not a PDF')
        good = self.base / 'good.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_text((50, 50), 'A readable source')
            doc.save(good)
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/index_courseware.py'),
                            str(bad), str(good), '--out', str(self.base / 'out')], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(json.loads(r.stdout)['errors']), 1)
        self.assertEqual(len(json.loads(r.stdout)['files']), 1)
        self.assertEqual(len(list((self.base / 'out').rglob('INCOMPLETE.txt'))), 1)

    def test_record_merge_evidence_and_history(self):
        self.state('record', 'entropy', '--source', 'lesson.pdf | PDF page 21', '--coverage', 'covered')
        data = json.loads(self.state('show').stdout)
        self.assertEqual(data['topics']['entropy']['evidence'], 'unverified')
        self.state('record', 'entropy', '--evidence', 'basic-problem-passed', ok=False)
        self.state('record', 'entropy', '--evidence', 'self-reported', '--evidence-note', 'User said understood')
        self.state('record', 'entropy', '--next', 'information gain')
        data = json.loads(self.state('show').stdout)
        self.assertEqual(data['topics']['entropy']['source'], 'lesson.pdf | PDF page 21')
        self.assertEqual(data['topics']['entropy']['evidence'], 'self-reported')
        self.assertEqual(len(data['history']), 3)
        self.assertEqual(data['history'][0]['after']['evidence'], 'unverified')

    def test_park_resolve_preserves_original_gap(self):
        self.state('park', 'jensen', '--topic', 'em', '--source', 'slides.pdf | PDF page 84',
                   '--gap', 'equality', '--understood', 'E and M steps', '--reason', 'nonblocking detail', '--return-when', 'second pass')
        self.state('resolve', 'jensen', '--evidence-note', 'Explained equality with a numeric example')
        data = json.loads(self.state('show').stdout)
        self.assertEqual(data['blockers']['jensen']['status'], 'resolved')
        self.assertEqual(data['blockers']['jensen']['gap'], 'equality')
        self.assertEqual(data['history'][0]['after']['status'], 'open')
        self.state('resolve', 'missing', '--evidence-note', 'test', ok=False)

    def test_corruption_and_lock_never_overwrite_progress(self):
        state = self.base / 'progress.json'
        state.write_text('{broken')
        self.state('record', 'em', ok=False)
        self.assertEqual(state.read_text(), '{broken')
        state.unlink()
        self.state('record', 'em')
        before = state.read_bytes()
        (self.base / 'progress.json.lock').write_text('another writer')
        self.state('record', 'em', '--coverage', 'covered', ok=False)
        self.assertEqual(state.read_bytes(), before)

    def test_show_does_not_invent_saved_state(self):
        self.state('show', ok=False)
        self.assertFalse((self.base / 'progress.json').exists())


if __name__ == '__main__':
    unittest.main()
