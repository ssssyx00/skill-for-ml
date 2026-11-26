#!/usr/bin/env python3
"""Local, atomic learning records. No scheduling, syncing or mastery inference."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def read_state(path):
    if not path.exists():
        return {'schema_version': 1, 'topics': {}, 'blockers': {}, 'history': []}
    state = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(state, dict) or state.get('schema_version') != 1 or not isinstance(state.get('topics'), dict) or not isinstance(state.get('blockers'), dict) or not isinstance(state.get('history'), list):
        raise ValueError('Invalid state; refusing to replace it.')
    return state


@contextmanager
def locked(path):
    lock = path.with_name(path.name + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink()


def write_state(path, state):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--file', required=True, type=Path)
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('show')
    rec = sub.add_parser('record')
    rec.add_argument('topic')
    rec.add_argument('--source')
    rec.add_argument('--coverage', choices=['uncovered', 'covered'])
    rec.add_argument('--evidence', choices=['unverified', 'self-reported', 'explained-back', 'basic-problem-passed'])
    rec.add_argument('--evidence-note')
    rec.add_argument('--next')
    park = sub.add_parser('park')
    park.add_argument('id')
    park.add_argument('--topic', required=True)
    park.add_argument('--source', required=True)
    park.add_argument('--gap', required=True)
    park.add_argument('--understood', required=True)
    park.add_argument('--reason', required=True)
    park.add_argument('--return-when', required=True)
    resolve = sub.add_parser('resolve')
    resolve.add_argument('id')
    resolve.add_argument('--evidence-note', required=True)
    args = ap.parse_args()
    path = args.file.expanduser().resolve()
    if args.command == 'show':
        if not path.exists():
            ap.error('No saved record exists at this path.')
        print(json.dumps(read_state(path), ensure_ascii=False, indent=2))
        return
    if args.command == 'record' and args.evidence and args.evidence != 'unverified' and not args.evidence_note:
        ap.error('Non-default evidence needs --evidence-note describing the actual user response, not an assistant demonstration.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path):
        state = read_state(path)
        stamp = datetime.now(timezone.utc).isoformat()
        if args.command == 'record':
            old = state['topics'].get(args.topic, {'coverage': 'uncovered', 'evidence': 'unverified'})
            new = dict(old)
            for key in ('source', 'coverage', 'evidence', 'evidence_note', 'next'):
                value = getattr(args, key)
                if value is not None:
                    new[key] = value
            if args.evidence == 'unverified':
                new.pop('evidence_note', None)
            new['updated_at'] = stamp
            state['topics'][args.topic] = new
            event = {'action': 'record', 'topic': args.topic, 'before': old, 'after': new}
        elif args.command == 'park':
            previous = state['blockers'].get(args.id)
            new = {k: getattr(args, k) for k in ('topic', 'source', 'gap', 'understood', 'reason', 'return_when')}
            new.update(status='open', updated_at=stamp)
            state['blockers'][args.id] = new
            event = {'action': 'park', 'id': args.id, 'before': previous, 'after': new}
        else:
            if args.id not in state['blockers']:
                ap.error('Unknown blocker ID.')
            old = dict(state['blockers'][args.id])
            state['blockers'][args.id].update(status='resolved', resolution=args.evidence_note, updated_at=stamp)
            event = {'action': 'resolve', 'id': args.id, 'before': old, 'after': dict(state['blockers'][args.id])}
        state['history'].append(dict(event, at=stamp))
        write_state(path, state)
    print(json.dumps({'saved': str(path), 'action': args.command}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
