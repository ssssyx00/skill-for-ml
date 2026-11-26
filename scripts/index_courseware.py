#!/usr/bin/env python3
"""Index PDF/PPTX pages without dropping content. See references/scripts.md."""
import argparse
import hashlib
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def paragraphs(root):
    return '' if root is None else '\n'.join(
        ''.join(t.text or '' for t in p.iter('{' + A + '}t'))
        for p in root.iter('{' + A + '}p'))


def relationships(z, part):
    folder, name = posixpath.split(part)
    relpath = posixpath.join(folder, '_rels', name + '.rels')
    if relpath not in z.namelist():
        return {}
    result = {}
    for rel in ET.fromstring(z.read(relpath)):
        if rel.get('TargetMode') == 'External':
            continue
        target = rel.get('Target', '')
        target = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(folder, target))
        result[rel.get('Id')] = (target, rel.get('Type', ''))
    return result


def select_pages(spec, total):
    if not spec:
        return set(range(1, total + 1))
    selected = set()
    for part in spec.split(','):
        match = re.fullmatch(r'\s*(\d+)(?:-(\d+))?\s*', part)
        if not match:
            raise ValueError('Use one-based page ranges, e.g. --pages 21-28,43')
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= total:
            raise ValueError(f'Page range {part} is outside 1..{total}')
        selected.update(range(start, end + 1))
    return selected


def pptx_pages(path, pages_spec=None):
    with zipfile.ZipFile(path) as z:
        part = 'ppt/presentation.xml'
        rels = relationships(z, part)
        presentation = ET.fromstring(z.read(part))
        # Presentation order can differ from slide1.xml, slide2.xml order.
        slides = list(presentation.iter('{' + P + '}sldId'))
        selected = select_pages(pages_spec, len(slides))
        for ordinal, node in enumerate(slides, 1):
            if ordinal not in selected:
                continue
            slide, _ = rels[node.attrib['{' + R + '}id']]
            root = ET.fromstring(z.read(slide))
            notes = []
            for target, kind in relationships(z, slide).values():
                if kind.endswith('/notesSlide'):
                    nr = ET.fromstring(z.read(target))
                    for shape in nr.iter('{' + P + '}sp'):
                        ph = shape.find('.//{' + P + '}ph')
                        if ph is not None and ph.get('type') in ('sldNum', 'hdr', 'ftr', 'dt', 'sldImg'):
                            continue
                        notes.append(paragraphs(shape))
            yield {'page': ordinal, 'total_pages': len(slides), 'text': paragraphs(root), 'notes': '\n'.join(notes),
                   'printed_page': None, 'needs_visual_review': True,
                   'visual_reason': 'PPTX text does not preserve diagrams, equations, layout or animations; inspect original or export to PDF.',
                   'part': slide}


def pdf_pages(path, output, render, pages_spec=None):
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PDF reading needs PyMuPDF: python -m pip install pymupdf') from exc
    with fitz.open(path) as doc:
        if doc.needs_pass:
            raise ValueError('Password-protected PDF; provide an unlocked copy.')
        selected = select_pages(pages_spec, len(doc))
        for n in sorted(selected):
            page = doc[n - 1]
            text = page.get_text(sort=True)
            visual = len(text.strip()) < 80 or bool(page.get_images()) or bool(page.get_drawings())
            row = {'page': n, 'total_pages': len(doc), 'text': text, 'notes': '', 'printed_page': None,
                   'needs_visual_review': visual,
                   'visual_reason': 'Sparse text, images or vector graphics.' if visual else 'Text extraction may still lose math notation.'}
            if render == 'all' or (render == 'needed' and visual):
                image_path = output / 'pages' / ('p%04d.png' % n)
                image_path.parent.mkdir(parents=True, exist_ok=True)
                page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(image_path)
                row['render'] = str(image_path.relative_to(output))
            yield row


def index_file(path, out, render='none', pages_spec=None):
    path = Path(path).resolve()
    if path.suffix.lower() not in ('.pdf', '.pptx'):
        raise ValueError('Supported inputs: PDF and PPTX. Export legacy PPT to PDF/PPTX.')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    slug = re.sub(r'[^\w.-]+', '_', path.stem)
    unit = Path(out) / (slug + '-' + digest[:12])
    # Refuse to overwrite any previous extraction or a source directory.
    unit.mkdir(parents=True, exist_ok=False)
    try:
        source = pdf_pages(path, unit, render, pages_spec) if path.suffix.lower() == '.pdf' else pptx_pages(path, pages_spec)
        pages, seen, candidates = [], {}, []
        for row in source:
            n = row['page']
            row.update(locator=f'{path.name} | {"PDF page" if path.suffix.lower()==".pdf" else "slide position"} {n}')
            normalized = re.sub(r'\s+', ' ', row['text']).strip()
            # Conservative: compare all extracted text INCLUDING numbers and notes.
            # No title-only match, fuzzy deletion, footer stripping or visual equivalence claim.
            key = (normalized, re.sub(r'\s+', ' ', row['notes']).strip())
            if len(normalized) >= 40 and key in seen:
                candidates.append({'page': n, 'same_text_as': seen[key],
                                   'status': 'candidate_only', 'action': 'Inspect BOTH original pages; retain new graphics/formulas.'})
            elif len(normalized) >= 40:
                seen[key] = n
            pages.append(row)
        if not pages:
            raise ValueError('No pages extracted.')
        record = {'schema_version': 1, 'source_name': path.name, 'source_path': str(path),
                  'source_sha256': digest, 'page_count': pages[0]['total_pages'], 'indexed_page_count': len(pages),
                  'page_numbering': 'One-based file order; printed slide numbers are NOT inferred.',
                  'warnings': ['Extraction is an index, not a substitute for viewing mathematical notation and figures.'],
                  'duplicate_candidates': candidates, 'pages': pages}
        (unit / 'index.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        (unit / 'pages.txt').write_text('\n\n'.join(
            f'--- {p["locator"]} ---\n{p["text"]}' + (f'\n[Speaker notes]\n{p["notes"]}' if p['notes'] else '')
            for p in pages), encoding='utf-8')
        return {'source_name': path.name, 'source_sha256': digest, 'page_count': pages[0]['total_pages'], 'indexed_page_count': len(pages),
                'index': str(unit / 'index.json'), 'duplicate_candidates': len(candidates)}
    except Exception:
        # Preserve partial renders for diagnosis, but mark them explicitly incomplete.
        (unit / 'INCOMPLETE.txt').write_text('Extraction failed. Do not use as a complete course index.\n', encoding='utf-8')
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inputs', nargs='+', type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--render', choices=['none', 'needed', 'all'], default='none')
    ap.add_argument('--pages', help='One-based file page/slide positions, e.g. 21-28,43. Default: all.')
    args = ap.parse_args()
    results, errors = [], []
    for path in args.inputs:
        try:
            results.append(index_file(path, args.out, args.render, args.pages))
        except Exception as exc:
            errors.append({'source': str(path), 'error': str(exc)})
    print(json.dumps({'files': results, 'errors': errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
