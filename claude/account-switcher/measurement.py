"""Quota snapshots paired with local token-counter increments; no inference calls."""

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
import math
import os
from pathlib import Path
import time

from api import ApiError
from macos import KeychainError
from storage import SwitcherError, read_json


TOKEN_FIELDS = ('input_tokens', 'cache_creation_input_tokens',
                'cache_read_input_tokens', 'output_tokens')
MAX_LINE_BYTES = 1 << 20


class TokenTail:
    """Keep only counters and IDs in memory; never retain message content."""

    def __init__(self, projects, started_at=None):
        self.projects = Path(projects)
        self.started_at = time.time() if started_at is None else started_at
        self.last_scan = None
        self.files = {}
        self.seen = {}
        self.oldest_event = None
        self.directories = {}
        self.next_discovery = 0
        self.retry_files = set()
        self.cold = {}

    def discover(self, now):
        """Reuse unchanged directory listings, still stat files to detect resumed old sessions."""
        paths, visited, stack = [], set(), [self.projects]
        errors = 0
        while stack:
            directory = stack.pop()
            try:
                info = directory.stat()
                identity = (info.st_dev, info.st_ino, info.st_mtime_ns)
                cached = self.directories.get(directory)
                if cached is None or cached[0] != identity or now >= self.next_discovery:
                    children, files = [], []
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False):
                                children.append(Path(entry.path))
                            elif entry.name.endswith('.jsonl'):
                                files.append(Path(entry.path))
                    cached = (identity, children, files)
                    self.directories[directory] = cached
                visited.add(directory)
                stack.extend(cached[1])
                paths.extend(cached[2])
            except FileNotFoundError:
                continue
            except OSError:
                errors += 1
        self.directories = {path: value for path, value in self.directories.items() if path in visited}
        if now >= self.next_discovery:
            self.next_discovery = now + 600
        return paths, errors

    def reset(self, now):
        self.__init__(self.projects, now)

    def sample(self, now, *, prefixes=None):
        baseline = self.last_scan is None
        cutoff = max(self.started_at - 900, now - 7200)
        counts = defaultdict(lambda: dict.fromkeys(TOKEN_FIELDS + ('requests',), 0))
        paths, errors = self.discover(now)
        if not errors:
            present = set(paths)
            self.files = {path: value for path, value in self.files.items() if path in present}
            self.retry_files.intersection_update(present)
            self.cold = {path: value for path, value in self.cold.items() if path in present}
        scan_started = time.monotonic()
        for path in paths:
            cold = self.cold.get(path)
            if cold and now < cold[0]:
                continue
            try:
                info = path.stat()
                identity = (info.st_dev, info.st_ino)
                if prefixes is not None and identity not in prefixes:
                    continue
                if info.st_mtime < cutoff:
                    old = self.files.pop(path, None)
                    self.retry_files.discard(path)
                    if old:
                        checkpoint = old
                    elif cold and cold[1][0] == identity and cold[1][1] == info.st_size:
                        checkpoint = cold[1]
                    else:
                        with path.open('rb') as stream:
                            stream.seek(max(0, info.st_size - 64))
                            end = stream.read(64)
                            checkpoint = (identity, info.st_size, bool(end and not end.endswith(b'\n')),
                                          hashlib.sha256(end).digest())
                    newly_discovered = not baseline and cold is None
                    self.cold[path] = (now if old or newly_discovered else now + 120, checkpoint)
                    continue
                if (not cold and path not in self.retry_files
                        and info.st_mtime < (self.started_at - 900 if baseline else self.last_scan - 2)):
                    continue
                checkpoint = self.files.get(path) or (cold and cold[1]) or (None, 0, False, b'')
                old_identity, offset, discarding, anchor = checkpoint
                if old_identity != identity or info.st_size < offset:
                    offset, discarding = 0, False
                with path.open('rb') as stream:
                    limit = None
                    if prefixes is not None:
                        limit, expected_anchor = prefixes[identity]
                        stream.seek(max(0, limit - 64))
                        if (limit > info.st_size or
                                hashlib.sha256(stream.read(min(limit, 64))).hexdigest() != expected_anchor):
                            errors += 1
                            continue
                    verified_offset = None
                    if offset and anchor:
                        stream.seek(max(0, offset - 64))
                        if hashlib.sha256(stream.read(min(offset, 64))).digest() != anchor:
                            offset, discarding = 0, False
                        else:
                            verified_offset = offset
                    stream.seek(offset)
                    errors += int(discarding)
                    line = b''
                    while limit is None or stream.tell() < limit:
                        size = MAX_LINE_BYTES + 1 if limit is None else min(MAX_LINE_BYTES + 1, limit - stream.tell())
                        line = stream.readline(size)
                        if not line:
                            break
                        if discarding or len(line) > MAX_LINE_BYTES:
                            errors += int(not discarding)
                            discarding = not line.endswith(b'\n')
                            offset = stream.tell()
                            continue
                        if not line.endswith(b'\n'):
                            break
                        offset = stream.tell()
                        if b'"usage"' not in line or b'"assistant"' not in line:
                            continue
                        try:
                            row = json.loads(line)
                            msg = row.get('message', {})
                            if row.get('type') != 'assistant' or not isinstance(msg, dict):
                                continue
                            model, key, usage = msg.get('model'), msg.get('id'), msg.get('usage')
                            if (not isinstance(model, str) or not model.startswith('claude-')
                                    or not isinstance(key, str) or not isinstance(usage, dict)):
                                continue
                            stamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
                            if stamp < cutoff:
                                continue
                            if cold and self.last_scan is not None and stamp < self.last_scan - 2:
                                errors += 1
                            horizon = now + (time.monotonic() - scan_started) + 5
                            if stamp > horizon + 120:
                                errors += 1
                                continue
                            if stamp > horizon:
                                offset -= len(line)
                                self.retry_files.add(path)
                                break
                            values = tuple(usage.get(k, 0) or 0 for k in TOKEN_FIELDS)
                            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
                                errors += 1
                                continue
                        except (ValueError, KeyError, TypeError, AttributeError):
                            errors += 1
                            continue
                        prior = self.seen.get((model, key))
                        before = prior[1] if prior else (0,) * len(TOKEN_FIELDS)
                        after = tuple(max(a, b) for a, b in zip(before, values))
                        self.seen[(model, key)] = (max(stamp, prior[0] if prior else stamp), after)
                        if self.oldest_event is None or stamp < self.oldest_event:
                            self.oldest_event = stamp
                        for field, a, b in zip(TOKEN_FIELDS, before, after):
                            counts[model][field] += b - a
                        counts[model]['requests'] += int(prior is None)
                    if offset != verified_offset:
                        stream.seek(max(0, offset - 64))
                        anchor = hashlib.sha256(stream.read(min(offset, 64))).digest()
                self.files[path] = (identity, offset, discarding, anchor)
                self.cold.pop(path, None)
                if not line or not line.endswith(b'\n'):
                    self.retry_files.discard(path)
            except OSError:
                self.retry_files.add(path)
                errors += 1
        if self.oldest_event is not None and self.oldest_event < cutoff:
            self.seen = {key: value for key, value in self.seen.items() if value[0] >= cutoff}
            self.oldest_event = min((value[0] for value in self.seen.values()), default=None)
        self.last_scan = now
        return {'baseline': baseline, 'by_model': {} if baseline else dict(counts),
                'read_errors': errors, 'basis': 'newly_observed_cumulative_counter_increments'}


def observe(app):
    """Metadata-only fallback while the account writer's compatibility guard is closed."""
    started = time.time()
    readings, errors, retry = {}, {}, 0
    with app.state.lock():
        account = read_json(app.live.config).get('oauthAccount', {})
        email = account.get('emailAddress')
        if email not in app.accounts:
            raise SwitcherError('Current login is outside the measurement roster')
        try:
            blob = app.vault.read_active_for_measurement()
        except KeychainError:
            blob = None
        if read_json(app.live.config).get('oauthAccount') != account:
            raise SwitcherError('Login changed during measurement; retry later')
        active = ({'account': account, 'oauth': blob['claudeAiOauth']}
                  if isinstance(blob, dict) and isinstance(blob.get('claudeAiOauth'), dict) else None)
        settle_until = app.state.load('runtime').get('settle_until', 0)
        for candidate in app.accounts:
            try:
                bundle = active if candidate == email and active else app.vault.read(candidate)
                if bundle is None:
                    errors[candidate] = 'not_enrolled'
                    continue
                if bundle.get('account', {}).get('emailAddress') != candidate:
                    errors[candidate] = 'authentication_needs_attention'
                    continue
                if bundle['oauth'].get('expiresAt', 0) <= (time.time() + 120) * 1000:
                    if candidate == email:
                        errors[candidate] = 'active_token_needs_native_refresh'
                        continue
                    if time.time() < settle_until:
                        errors[candidate] = 'inactive_token_needs_refresh'
                        continue
                    if read_json(app.live.config).get('oauthAccount') != account:
                        raise SwitcherError('Login changed during measurement; retry later')
                    bundle = app.refresh_inactive(candidate, bundle, time.time())
                app.verify_identity(bundle)
                if (candidate == email and active and app.vault.read(email) != active
                        and not app.state.load('halt')):
                    current = app.vault.read_active_for_measurement()
                    if (current and current.get('claudeAiOauth') == active['oauth']
                            and read_json(app.live.config).get('oauthAccount') == account):
                        app.vault.write(email, active)
                reading = app.api.usage(bundle['oauth'], time.time())
                readings[candidate] = asdict(reading)
            except ApiError as exc:
                errors[candidate] = f'http_{exc.status}' if exc.status else 'metadata_unavailable'
                retry = max(retry, exc.retry_after)
            except (SwitcherError, KeychainError):
                errors[candidate] = 'authentication_needs_attention'
        changed = read_json(app.live.config).get('oauthAccount') != account
    return {'observed_at': started, 'active': email, 'switched': False,
            'usage': readings, 'errors': errors, 'identity_changed': changed,
            'retry_after_seconds': retry, 'source': 'measurement_only'}


def quota_deltas(previous, current):
    """Reject stale readings and changed reset windows, including fractional reset jitter."""
    result = []
    for email, reading in current['usage'].items():
        before = previous.get('usage', {}).get(email)
        if not before or reading.get('stale') or before.get('stale'):
            continue
        seconds = reading['checked_at'] - before['checked_at']
        if seconds <= 0:
            continue
        old = {w['name']: w for w in before['windows']}
        for window in reading['windows']:
            prior = old.get(window['name'])
            if prior is None:
                continue
            a, b = prior.get('percent'), window.get('percent')
            x, y = prior.get('resets_at'), window.get('resets_at')
            if any(v is None or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (a, b)):
                continue
            same_reset = (
                isinstance(x, (float, int)) and isinstance(y, (float, int))
                and abs(x - y) <= 2 and before['checked_at'] < min(x, y)
                and reading['checked_at'] < min(x, y))
            valid = same_reset and b >= a
            result.append({'account': email, 'window': window['name'],
                           'start_percent': a, 'end_percent': b, 'delta_pp': b - a,
                           'seconds': seconds, 'valid': valid,
                           'reason': ('same_window' if valid else 'unknown_reset'
                                      if x is None or y is None else 'reset_or_counter_decrease'),
                           'saturated': a >= 100 or b >= 100})
    return result


def latest_sample(state):
    try:
        latest = state.load('measurement_latest')
        return latest if isinstance(latest.get('captured_at'), (float, int)) else {}
    except (SwitcherError, OSError, ValueError):
        return {}


class Measurement:
    def __init__(self, state, projects):
        self.state = state
        self.tokens = TokenTail(projects)
        self.previous = latest_sample(state)
        self.pending = None
        self.appended = None
        self.pruned_day = None
        self.plan_start = self.previous.get('plan_start')

    def enabled(self, now=None):
        now = time.time() if now is None else now
        plan = self.state.load('monitoring')
        start = plan.get('starts_at')
        enabled = not plan or (plan.get('status') != 'complete' and now < plan['ends_at'])
        changed = (self.plan_start != start and
                   (self.tokens.last_scan is not None or self.plan_start is not None
                    or (start is not None and self.previous.get('captured_at', now) < start)))
        if changed or (not enabled and (self.tokens.last_scan is not None or self.appended)):
            self.recover_append()
            self.tokens.reset(now)
            self.previous = {}
            self.pending = None
        self.plan_start = start
        return enabled

    def recover_append(self):
        if self.appended is not None:
            path, start, raw, saved = self.appended
            try:
                stream = path.open('r+b')
            except FileNotFoundError:
                self.appended = None
                return
            with stream:
                stream.seek(start)
                tail = stream.read(len(raw) + 1)
                if tail == raw:
                    os.fsync(stream.fileno())
                    self.pending = None
                    self.previous = saved
                elif raw.startswith(tail):
                    stream.truncate(start)
                else:
                    raise SwitcherError('Measurement append changed during recovery')
            self.appended = None

    def resume_manual_interval(self, now):
        """Rebuild in-memory request counters from verified file prefixes of the last manual poll."""
        if not self.enabled(now) or not self.previous:
            return
        previous = self.previous['captured_at']
        if not 0 < now - previous <= 180:
            return
        try:
            saved = self.state.load('manual_measurement')
            if saved.get('captured_at') != previous:
                return
            prefixes = {(dev, ino): (offset, anchor) for dev, ino, offset, anchor in saved['files']
                        if isinstance(offset, int) and offset >= 0 and isinstance(anchor, str)}
            if len(prefixes) != len(saved['files']):
                return
            started = float(saved.get('started_at', previous))
        except (OSError, SwitcherError, KeyError, TypeError, ValueError):
            return
        self.tokens.reset(started)
        baseline = self.tokens.sample(previous, prefixes=prefixes)
        if baseline['read_errors'] or len(self.tokens.files) != len(prefixes):
            self.tokens.reset(now)

    def save_manual_interval(self, row):
        if row is not None:
            files = [[*identity, offset, anchor.hex()]
                     for identity, offset, _, anchor in self.tokens.files.values()]
            self.state.save('manual_measurement', {'captured_at': row['captured_at'],
                                                  'started_at': self.tokens.started_at, 'files': files})

    def record(self, report, now=None):
        now = time.time() if now is None else now
        self.prune(now)
        if not self.enabled(now):
            return None
        self.recover_append()
        # Whitelist data rather than serializing an arbitrary caller's payload.
        usage = {}
        for email, reading in report.get('usage', {}).items():
            if email in report.get('errors', {}) or reading.get('stale'):
                continue
            usage[email] = {'checked_at': reading['checked_at'], 'windows': [
                {k: w.get(k) for k in ('name', 'percent', 'resets_at', 'blocked')}
                for w in reading['windows']]}
        tokens = self.tokens.sample(now)
        changed = bool(report.get('switched') or report.get('identity_changed'))
        if self.pending:
            carried, prior_active, prior_changed = self.pending
            changed |= prior_changed or prior_active != report.get('active')
            for model, fields in carried['by_model'].items():
                values = tokens['by_model'].setdefault(model, {})
                for key, value in fields.items():
                    values[key] = values.get(key, 0) + value
            tokens['read_errors'] += carried['read_errors']
            tokens['baseline'] |= carried['baseline']
        self.pending = (tokens, report.get('active'), changed)
        previous = self.previous
        stable = bool(previous and previous.get('active') == report.get('active')
                      and not changed and not previous.get('switched')
                      and not report.get('identity_changed') and not previous.get('identity_changed')
                      and not tokens['baseline'] and not tokens['read_errors']
                      and not previous.get('tokens', {}).get('read_errors')
                      and 0 < now - previous['captured_at'] <= 180)
        row = {'schema': 1, 'captured_at': now, 'plan_start': self.plan_start,
               'poll_started_at': report['observed_at'],
               'source': report.get('source', 'switcher_poll'),
               'active': report.get('active'), 'switched': bool(report.get('switched')),
               'identity_changed': bool(report.get('identity_changed')),
               'usage': usage, 'errors': report.get('errors', {}), 'tokens': tokens,
               'token_interval_seconds': now - previous['captured_at'] if previous else None,
               'token_account_estimate': report.get('active') if stable else None,
               'quota_deltas': []}
        row['quota_deltas'] = quota_deltas(previous, row) if previous else []
        directory = self.state.root / 'measurements'
        if directory.is_symlink():
            raise SwitcherError('Measurement directory must not be a symlink')
        directory.mkdir(mode=0o700, exist_ok=True)
        day = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d')
        path = directory / f'{day}.jsonl'
        raw = (json.dumps(row, allow_nan=False, separators=(',', ':')) + '\n').encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab') as stream:
            os.fchmod(stream.fileno(), 0o600)
            self.appended = (path, os.fstat(fd).st_size, raw, row)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self.appended = None
        self.pending = None
        self.previous = row
        self.state.save('measurement_latest', row)
        return row

    def prune(self, now):
        day = int(now // 86400)
        if day == self.pruned_day:
            return
        directory = self.state.root / 'measurements'
        if directory.is_symlink():
            raise SwitcherError('Measurement directory must not be a symlink')
        plan = self.state.load('monitoring')
        cutoff = now - 30 * 86400
        if plan.get('status') == 'active':
            cutoff = min(cutoff, plan['starts_at'])
        for old in directory.glob('*.jsonl'):
            if old.is_symlink():
                continue
            try:
                written_day = datetime.strptime(old.stem, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if written_day.timestamp() + 86400 <= cutoff:
                old.unlink(missing_ok=True)
        self.pruned_day = day


def summarize(state, since=None, until=None):
    """Observed maxima only; rounded quota snapshots do not prove a future safety bound."""
    groups = {}
    count, paired, first, last = 0, 0, None, None
    failed, empty, token_read_errors, long_gaps, malformed = 0, 0, 0, 0, 0
    first_day = datetime.fromtimestamp(since, timezone.utc).date().isoformat() if since is not None else None
    last_day = datetime.fromtimestamp(until, timezone.utc).date().isoformat() if until is not None else None
    for path in sorted((state.root / 'measurements').glob('*.jsonl')):
        try:
            file_day = datetime.strptime(path.stem, '%Y-%m-%d').date().isoformat()
        except ValueError:
            file_day = None
        if file_day and ((first_day and file_day < first_day) or (last_day and file_day > last_day)):
            continue
        if path.is_symlink():
            continue
        with path.open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                if (not isinstance(row, dict) or not isinstance(row.get('captured_at'), (int, float))
                        or not math.isfinite(row['captured_at'])):
                    malformed += 1
                    continue
                at = row['captured_at']
                if (since is not None and at < since) or (until is not None and at >= until):
                    continue
                count += 1
                failed += bool(row.get('errors'))
                empty += not bool(row.get('usage'))
                token_read_errors += row.get('tokens', {}).get('read_errors', 0)
                long_gaps += (row.get('token_interval_seconds') or 0) > 180
                first = row['captured_at'] if first is None else min(first, row['captured_at'])
                last = max(last or 0, row['captured_at'])
                for d in row.get('quota_deltas', []):
                    if not d['valid'] or not 45 <= d['seconds'] <= 90:
                        continue
                    checked_at = row.get('usage', {}).get(d['account'], {}).get('checked_at', at)
                    if since is not None and checked_at - d['seconds'] < since:
                        continue
                    key = (d['account'], d['window'])
                    group = groups.setdefault(key, {'account': key[0], 'window': key[1],
                                                    'intervals': 0, 'saturated_intervals': 0,
                                                    'active_token_intervals': 0,
                                                    'positive_active_intervals': 0,
                                                    'opus55_only_intervals': 0,
                                                    'positive_opus55_intervals': 0,
                                                    'max_delta_pp': None, 'max_interval': None})
                    group['intervals'] += 1
                    group['saturated_intervals'] += int(d['saturated'])
                    if group['max_delta_pp'] is None or d['delta_pp'] > group['max_delta_pp']:
                        group['max_delta_pp'] = d['delta_pp']
                        group['max_interval'] = {'captured_at': row['captured_at'],
                                                 'seconds': d['seconds'],
                                                 'start_percent': d['start_percent'],
                                                 'end_percent': d['end_percent'],
                                                 'tokens': row['tokens']['by_model']
                                                 if row['token_account_estimate'] == d['account'] else None}
                    local = row['tokens']['by_model']
                    active_tokens = (row['token_account_estimate'] == d['account']
                                     and any(sum(v.get(f, 0) for f in TOKEN_FIELDS) > 0
                                             for v in local.values()))
                    if active_tokens:
                        paired += 1
                        group['active_token_intervals'] += 1
                        group['positive_active_intervals'] += int(d['delta_pp'] > 0 and not d['saturated'])
                        opus_only = all(name.startswith('claude-opus-5-5') for name, v in local.items()
                                        if sum(v.get(f, 0) for f in TOKEN_FIELDS) > 0)
                        group['opus55_only_intervals'] += int(opus_only)
                        group['positive_opus55_intervals'] += int(opus_only and d['delta_pp'] > 0
                                                                  and not d['saturated'])
    return {'samples': count, 'first_at': first, 'last_at': last,
            'paired_account_window_intervals': paired, 'windows': list(groups.values()),
            'quality': {'failed_samples': failed, 'empty_usage_samples': empty, 'malformed_rows': malformed,
                        'token_read_errors': token_read_errors, 'gaps_over_180_seconds': long_gaps},
            'latest': latest_sample(state),
            'error': state.load('measurement_error'),
            'note': 'Observed 45-90s quota deltas; not an exact rolling 60s maximum. '
                    'Token counts are local log-counter increments, account attribution is approximate.'}
