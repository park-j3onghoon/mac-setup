#!/usr/bin/env python3
"""Keep final agent completions; silence nested completions and pending work."""

import json
from pathlib import Path
import sys
import time


SILENT_EFFECTS = dict.fromkeys(
    ('record', 'markUnread', 'reorderWorkspace', 'desktop', 'sound', 'command', 'paneFlash'), False)
TURN_EVENTS = {'task_started', 'task_complete', 'turn_complete', 'turn_aborted'}


def load_record(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def find_user_transcript(record, user_home):
    session_id = record.get('sessionId', '')
    if not session_id or any(char not in '0123456789abcdef-' for char in session_id.lower()):
        return None
    hint = Path(record.get('transcriptPath', '/nonexistent'))
    pattern = f'rollout-*-{session_id}.jsonl'
    candidates = list(hint.parent.glob(pattern))
    if not candidates:
        candidates = list((user_home / '.codex/sessions').glob(f'*/*/*/{pattern}'))
    for path in candidates:
        try:
            with path.open() as stream:
                first = json.loads(stream.readline())
        except (OSError, ValueError):
            continue
        payload = first.get('payload', {})
        if (first.get('type') == 'session_meta' and payload.get('id') == session_id
                and payload.get('thread_source') == 'user'):
            return path, payload.get('timestamp', '')
    return None


def latest_turn_state(path):
    # Read backwards: a long answer can put task_started megabytes before EOF.
    with path.open('rb') as stream:
        stream.seek(0, 2)
        cursor = stream.tell()
        remaining = 16 * 1024 * 1024
        fragment = b''
        discard_tail = True
        while cursor and remaining:
            size = min(cursor, remaining, 1024 * 1024)
            cursor -= size
            remaining -= size
            stream.seek(cursor)
            data = stream.read(size) + fragment
            if discard_tail:
                complete, separator, tail = data.rpartition(b'\n')
                if not separator:
                    fragment = b''
                    continue
                data = complete + separator
                discard_tail = False
            lines = data.split(b'\n')
            fragment = lines.pop(0) if cursor else b''
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or not isinstance(event.get('payload'), dict):
                    continue
                kind = event.get('payload', {}).get('type')
                if event.get('type') == 'event_msg' and kind in TURN_EVENTS:
                    return kind
    return None


def legacy_codex_complete(envelope, user_home):
    notification = envelope.get('notification', {})
    surface_id = notification.get('surfaceId', '').lower()
    registry = load_record(user_home / '.cmuxterm/codex-hook-sessions.json')
    candidates = []
    for record in registry.get('sessions', {}).values():
        if record.get('surfaceId', '').lower() != surface_id:
            continue
        candidate = find_user_transcript(record, user_home)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return False
    path, timestamp = max(candidates, key=lambda pair: pair[1])
    try:
        for attempt in range(3):
            if latest_turn_state(path) in ('task_complete', 'turn_complete', 'turn_aborted'):
                return True
            if attempt < 2:
                time.sleep(0.1)
        return False
    except OSError:
        return False


def filter_notification(envelope, user_home=None):
    agent = envelope.get('agent', {})
    intermediate = agent.get('pending') is True or agent.get('isSubagent') is True
    if agent.get('category') == 'turn-complete' and intermediate:
        return {'effects': SILENT_EFFECTS}
    notification = envelope.get('notification', {})
    legacy = notification.get('title') == 'Codex' and notification.get('subtitle', '').startswith('Completed')
    codex_complete = agent.get('kind') == 'codex' and agent.get('category') == 'turn-complete'
    if legacy or codex_complete:
        if not legacy_codex_complete(envelope, user_home or Path.home()):
            return {'effects': SILENT_EFFECTS}
        return {'effects': {'markUnread': False}}
    if agent.get('category') == 'turn-complete':
        return {'effects': {'markUnread': False}}
    return {}


if __name__ == '__main__':
    print(json.dumps(filter_notification(json.load(sys.stdin))))
