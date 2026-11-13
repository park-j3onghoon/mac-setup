#!/usr/bin/env python3
"""Shared local learning records with atomic, revision-checked checkpoints."""

import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

# Claude 세션 안에서 띄운 Codex는 두 변수를 모두 가질 수 있어 Codex 대화를 먼저 본다.
HOLDER_VARIABLES = (('codex', 'CODEX_THREAD_ID'), ('claude', 'CLAUDE_CODE_SESSION_ID'))
LIST_KEYS = ('id', 'title', 'topic', 'aliases', 'status', 'revision', 'saved_at')


class StoreError(Exception):
    pass


def current_holder():
    holders = (f'{agent}:{os.environ[name]}' for agent, name in HOLDER_VARIABLES if os.environ.get(name))
    return next(holders, None)


class Store:
    def __init__(self, root=None, holder=None):
        configured = root or os.environ.get('MASTERY_TUTOR_HOME')
        self.root = Path(configured).expanduser() if configured else Path.home() / '.local/share/mastery-tutor'
        self.holder = holder or current_holder()

    @staticmethod
    def valid_id(record_id):
        if not isinstance(record_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', record_id):
            raise StoreError('Record ID must contain lowercase letters, digits and hyphens, at most 96 characters.')
        return record_id

    @staticmethod
    def read_json(path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def atomic_text(path, content):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def atomic_json(self, path, value):
        self.atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / '.write.lock').open('a', encoding='utf-8') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                self.ensure_layout()
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def ensure_layout(self):
        manifest = self.root / 'store.json'
        if manifest.exists():
            value = self.read_json(manifest)
            if not value or value.get('schema_version') != 1:
                raise StoreError('Unsupported or damaged store.json; existing records were not replaced.')
        else:
            self.atomic_json(manifest, {'schema_version': 1})
        for name in ('concepts', 'sessions'):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)

    def init(self):
        with self.locked():
            pass
        return {'root': str(self.root), 'schema_version': 1}

    def read(self, kind, record_id):
        self.valid_id(record_id)
        if kind == 'concepts':
            path = self.root / kind / f'{record_id}.json'
            if not path.exists():
                return None
            value = self.read_json(path)
            if not self.valid_record(value, record_id):
                raise StoreError(f'Damaged concept record: {path}')
            return value
        if kind != 'sessions':
            raise StoreError('Unknown record kind.')
        directory = self.root / kind / record_id
        candidates = [directory / 'state.json', *sorted((directory / 'history').glob('*.json'))]
        valid = [value for path in candidates if self.valid_record(value := self.read_json(path), record_id)]
        if not valid:
            if any(path.exists() for path in candidates):
                raise StoreError(f'No valid checkpoint for session {record_id}.')
            return None
        return max(valid, key=lambda value: value['revision'])

    @staticmethod
    def valid_record(value, record_id):
        return (isinstance(value, dict) and value.get('id') == record_id
                and value.get('schema_version') == 1
                and type(value.get('revision')) is int and value['revision'] > 0)

    def is_active_elsewhere(self, record):
        return record.get('status') == 'active' and record.get('holder') not in (None, self.holder)

    def write(self, kind, payload, take_over=False):
        if kind not in ('concepts', 'sessions') or not isinstance(payload, dict):
            raise StoreError('A concept or session JSON object is required.')
        record_id = self.valid_id(payload.get('id'))
        expected = payload.get('revision', 0)
        if type(expected) is not int or expected < 0:
            raise StoreError('revision must be the last loaded nonnegative integer.')
        if payload.get('schema_version', 1) != 1:
            raise StoreError('Unsupported record schema_version.')
        label = payload.get('title' if kind == 'concepts' else 'topic')
        if not isinstance(label, str) or not label.strip():
            raise StoreError('A nonempty concept title or session topic is required.')
        if kind == 'sessions' and payload.get('status') not in ('active', 'paused', 'complete'):
            raise StoreError('Session status must be active, paused or complete.')
        if kind == 'sessions' and not isinstance(payload.get('state'), dict):
            raise StoreError('A session requires its full state object, not only a summary.')
        if not isinstance(payload.get('summary_markdown', ''), str):
            raise StoreError('summary_markdown must be a string.')
        with self.locked():
            current = self.read(kind, record_id)
            if kind == 'sessions' and current and not take_over and self.is_active_elsewhere(current):
                raise StoreError(f'Session {record_id} is active in another conversation: '
                                 f'holder={current["holder"]}, saved_at={current.get("saved_at")}. '
                                 'Ask the user, then reload it and write with --take-over.')
            actual = current['revision'] if current else 0
            if expected != actual:
                raise StoreError(f'Revision conflict for {record_id}: expected {expected}, stored {actual}. Reload and merge.')
            saved = copy.deepcopy(payload)
            saved.update(schema_version=1, revision=actual + 1,
                         saved_at=datetime.now(timezone.utc).isoformat())
            if kind == 'sessions':
                saved['holder'] = self.holder
                directory = self.root / kind / record_id
                self.atomic_json(directory / 'history' / f'{saved["revision"]:08d}.json', saved)
                self.atomic_json(directory / 'state.json', saved)
                self.atomic_text(directory / 'notes.md', saved.get('summary_markdown', ''))
            else:
                directory = self.root / kind
                self.atomic_json(directory / f'{record_id}.json', saved)
                self.atomic_text(directory / f'{record_id}.md', saved.get('summary_markdown', ''))
            return saved

    def records(self, kind, query=''):
        if kind not in ('concepts', 'sessions'):
            raise StoreError('Unknown record kind.')
        directory = self.root / kind
        ids = ([path.stem for path in directory.glob('*.json')] if kind == 'concepts'
               else [path.name for path in directory.iterdir() if path.is_dir()] if directory.exists() else [])
        results = []
        for record_id in ids:
            record = self.read(kind, record_id)
            if record and (not query or query.casefold() in json.dumps(record, ensure_ascii=False).casefold()):
                results.append(record)
        return sorted(results, key=lambda value: value.get('saved_at', ''), reverse=True)

    def resume(self, record_id=None):
        if record_id:
            return self.read('sessions', record_id)
        unfinished = [value for value in self.records('sessions') if value.get('status') != 'complete']
        held_here = [value for value in unfinished if self.holder and value.get('holder') == self.holder]
        if held_here:
            return held_here[0]
        if len(unfinished) > 1:
            raise StoreError(f'{len(unfinished)} unfinished sessions and none is held by this conversation. '
                             'Choose one from list sessions and pass --id.')
        return unfinished[0] if unfinished else None


def summarize(store, kind, record):
    summary = {key: record[key] for key in LIST_KEYS if key in record}
    if kind == 'sessions':
        summary['active_elsewhere'] = store.is_active_elsewhere(record)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='Override the shared data directory (also MASTERY_TUTOR_HOME).')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    listing = commands.add_parser('list')
    listing.add_argument('kind', choices=['concepts', 'sessions'])
    listing.add_argument('--query', default='')
    reading = commands.add_parser('read')
    reading.add_argument('kind', choices=['concepts', 'sessions'])
    reading.add_argument('id')
    writing = commands.add_parser('write')
    writing.add_argument('kind', choices=['concepts', 'sessions'])
    writing.add_argument('--file', required=True, help='JSON input path, or - for stdin.')
    writing.add_argument('--take-over', action='store_true',
                         help='Save a session another conversation holds as active, after the user agrees.')
    resuming = commands.add_parser('resume')
    resuming.add_argument('--id')
    args = parser.parse_args()
    store = Store(args.root)
    try:
        if args.command == 'init':
            result = store.init()
        elif args.command == 'read':
            result = store.read(args.kind, args.id)
        elif args.command == 'write':
            raw = sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8')
            saved = store.write(args.kind, json.loads(raw), take_over=args.take_over)
            result = {key: saved[key] for key in ('id', 'revision', 'saved_at')}
        elif args.command == 'resume':
            result = store.resume(args.id)
        else:
            result = [summarize(store, args.kind, value) for value in store.records(args.kind, args.query)]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (StoreError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
