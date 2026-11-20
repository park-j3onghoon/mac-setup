"""Enrollment, polling, and a recoverable swap of only Claude's account fields."""

from dataclasses import asdict
import hashlib
import json
import math
import time

from api import ApiError
from compatibility import check as check_compatibility
from macos import KeychainError
from policy import Decision, choose_account, poll_seconds
from refresh import record_switch
from storage import LockBusy, SwitcherError, email_key, fingerprint, read_json


def matches_identity(account, actual):
    return (email_key(actual.get('email')) == email_key(account.get('emailAddress'))
            and actual.get('uuid') == account.get('accountUuid')
            and (account.get('organizationUuid') is None
                 or actual.get('organizationUuid') == account['organizationUuid']))


def oauth_generation(oauth):
    return hashlib.sha256(json.dumps(oauth, sort_keys=True).encode()).hexdigest()


def refresh_generation(bundle):
    token = bundle['oauth'].get('refreshToken')
    generation = hashlib.sha256(token.encode()).hexdigest() if isinstance(token, str) and token else None
    if generation and generation == bundle.get('rotation_pending'):
        raise ApiError('token refresh', 400, 0, 'rotation_uncertain')
    if generation and generation == bundle.get('rejected_refresh'):
        raise ApiError('token refresh', 400, 0, 'invalid_grant')
    return generation


def validate_config(config):
    required = ('primary', 'fallback', 'config_home', 'config_path',
                'claude_executable', 'supported_version')
    if any(not isinstance(config.get(k), str) or not config[k] for k in required):
        raise SwitcherError('Run init to create a complete configuration')
    if email_key(config['primary']) == email_key(config['fallback']):
        raise SwitcherError('Primary and fallback must be different accounts')
    for email in (config['primary'], config['fallback']):
        if '@' not in email or any(c.isspace() for c in email):
            raise SwitcherError('Invalid configured account email')
    for key, low, high in (('threshold', 1, 100), ('poll_seconds', 30, 300),
                           ('settle_seconds', 45, 300)):
        value = config.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not low <= value <= high):
            raise SwitcherError(f'Invalid switcher setting: {key}')


class Switcher:
    def __init__(self, config, state, live, vault, api):
        validate_config(config)
        self.config, self.state, self.live = config, state, live
        self.vault, self.api = vault, api
        self.accounts = (config['primary'], config['fallback'])

        self._last_preference = None

    def account_key(self, email):
        return next((e for e in self.accounts if email_key(email) == email_key(e)), email)

    def preference(self):
        try:
            value = self.state.load('preference')
            if value and self.account_key(value.get('preferred')) not in self.accounts:
                raise SwitcherError('Preferred account is not configured')
        except (OSError, ValueError, SwitcherError):
            if self._last_preference is None:
                saved = self.state.load('runtime').get('last_preference')
                if saved == {} or (isinstance(saved, dict) and self.account_key(saved.get('preferred')) in self.accounts):
                    self._last_preference = saved
            if self._last_preference is not None:
                return self._last_preference
            raise SwitcherError('Account preference is temporarily unreadable') from None
        self._last_preference = value
        return value

    def request_metadata(self, email, operation, now, call, *args):
        now = time.time() if now is None else now
        limits = self.state.load('api_backoff')
        deadline = limits.get(email, {}).get(operation, 0)
        if deadline > now:
            raise ApiError(operation, 429, deadline - now)
        started = time.monotonic()
        try:
            return call(*args)
        except ApiError as exc:
            if exc.retry_after and exc.status != 401:
                deadline = now + (time.monotonic() - started) + exc.retry_after
                with self.state.lock('api-backoff', blocking=True):
                    limits = self.state.load('api_backoff')
                    account_limits = limits.setdefault(email, {})
                    account_limits[operation] = max(deadline, account_limits.get(operation, 0))
                    self.state.save('api_backoff', limits)
            raise

    def read_usage(self, email, oauth, now):
        return self.request_metadata(email, 'usage', now, self.api.usage, oauth, now)

    def verify_identity(self, bundle, now=None):
        account = bundle['account']
        cache = getattr(self, '_verified_identities', {})
        identity = (fingerprint(bundle['oauth']), account.get('emailAddress'),
                    account.get('accountUuid'), account.get('organizationUuid'))
        if cache.get(account.get('emailAddress')) == identity:
            return
        actual = self.request_metadata(self.account_key(account.get('emailAddress')),
                                       'profile', now, self.api.profile, bundle['oauth'])
        if not matches_identity(account, actual):
            raise SwitcherError('OAuth token ownership does not match the saved account')
        cache[account['emailAddress']] = identity
        self._verified_identities = cache

    def capture(self, expected_email):
        with self.state.lock():
            return self.capture_locked(expected_email)

    def capture_locked(self, expected_email):
        expected_email = self.account_key(expected_email)
        if expected_email not in self.accounts:
            raise SwitcherError('Account is not in the configured two-account roster')
        with self.live.locked():
            blob, account = self.live.read()
        if self.account_key(account['emailAddress']) != expected_email:
            raise SwitcherError(f'Log into the expected account first: {expected_email}')
        bundle = {'oauth': blob['claudeAiOauth'], 'account': account}
        self.verify_identity(bundle)
        with self.live.locked():
            current, current_account = self.live.read()
            if current['claudeAiOauth'] != bundle['oauth'] or current_account != account:
                raise SwitcherError('Claude login changed during enrollment; retry capture')
            self.vault.write(expected_email, bundle)
        roster = self.state.load('roster')
        roster[expected_email] = {'registered': True, 'captured_at': time.time()}
        self.state.save('roster', roster)
        runtime = self.state.load('runtime')
        last_verified = runtime.get('verified_active', runtime.get('active'))
        if last_verified in self.accounts and last_verified != expected_email:
            record_switch(self.state, time.time())
        runtime.update(active=expected_email, verified_active=expected_email,
                       settle_until=time.time() + self.config['settle_seconds'])
        self.state.save('runtime', runtime)
        return bundle

    def restore_enrollment(self, previous, unexpected):
        # Journal only the generation hash of the unexpected account, never its credentials.
        with self.live.locked():
            blob, account = self.live.read()
            if account != unexpected:
                raise SwitcherError('Login changed after enrollment; restore using the official login')
            journal = {'restore': previous, 'unexpected_account': account, 'switched_at': time.time(),
                       'unexpected_generation': oauth_generation(blob['claudeAiOauth'])}
            self.vault.write('__transaction__', journal)
            self.finish_enrollment_restore(journal, blob, account)

    def finish_enrollment_intent(self, journal, *, restore=False):
        with self.live.locked():
            blob, account = self.live.read()
        email = self.account_key(account['emailAddress'])
        expected, previous = journal['enrollment'], journal['previous']
        if email in (expected, self.account_key(previous['account']['emailAddress'])):
            self.capture_locked(email)
            self.vault.delete('__transaction__')
            return email
        # auth login provides no receipt linking an arbitrary third login to its child.
        # Keep it untouched unless the operator explicitly chooses the saved login.
        if restore:
            with self.live.locked():
                latest, current = self.live.read()
                if current != account or latest['claudeAiOauth'] != blob['claudeAiOauth']:
                    raise SwitcherError('Login changed during enrollment recovery; retry later')
                restore_journal = {'restore': previous, 'unexpected_account': account,
                                   'unexpected_generation': oauth_generation(blob['claudeAiOauth']),
                                   'switched_at': time.time()}
                self.vault.write('__transaction__', restore_journal)
                self.finish_enrollment_restore(restore_journal, latest, current)
            return self.account_key(previous['account']['emailAddress'])
        raise SwitcherError('A different account is signed in. Use restore-enrollment to restore '
                            'the saved login, or log into the expected account.')

    def finish_enrollment_restore(self, journal, blob, account):
        self.ensure_writer_enabled()
        target = journal['restore']
        if account not in (journal['unexpected_account'], target['account']):
            raise SwitcherError('Login changed during enrollment recovery; manual recovery required')
        if blob['claudeAiOauth'] != target['oauth']:
            if (account != journal['unexpected_account'] or
                    oauth_generation(blob['claudeAiOauth']) != journal['unexpected_generation']):
                raise SwitcherError('Login changed during enrollment recovery; manual recovery required')
            self.vault.write_active(dict(blob, claudeAiOauth=target['oauth']))
        if account != target['account']:
            self.live.write_account(target['account'])
        if 'switched_at' not in journal:
            journal['switched_at'] = time.time()
            self.vault.write('__transaction__', journal)
        if self.state.load('session_refresh').get('since', 0) < journal['switched_at']:
            record_switch(self.state, journal['switched_at'])
        self.vault.delete('__transaction__')

    def refresh_inactive(self, email, bundle, now, *, measurement=False):
        # The native login can change independently of the switcher's operation lock.
        # Reading metadata under Claude's locks also works for the no-UI measurement path.
        with self.live.locked():
            actual = read_json(self.live.config).get('oauthAccount', {})
            current_email = self.account_key(actual.get('emailAddress'))
            if current_email not in self.accounts or current_email == email:
                raise SwitcherError('Login changed before inactive refresh; retry later')
            live = (self.vault.read_active_for_measurement() if measurement else self.vault.read_active())
            known = self.vault.read(current_email)
            if (not isinstance(live, dict) or not isinstance(live.get('claudeAiOauth'), dict)
                    or not known or fingerprint(live['claudeAiOauth']) != fingerprint(known['oauth'])):
                raise SwitcherError('Live token generation changed before inactive refresh; retry later')
            current = self.vault.read(email)
            if current is None or current['oauth'] != bundle['oauth']:
                raise SwitcherError('Saved token changed before inactive refresh; retry later')
            return self._rotate(email, current, now)

    def _rotate(self, email, bundle, now):
        generation = refresh_generation(bundle)
        if not generation:
            raise SwitcherError('Inactive account needs a new Claude login: no refresh token')
        self.vault.write(email, dict(bundle, rotation_pending=generation))
        try:
            oauth = self.request_metadata(email, 'token refresh', now, self.api.refresh, bundle['oauth'], now)
        except ApiError as error:
            if generation and error.oauth_error == 'invalid_grant':
                self.vault.write(email, dict(bundle, rejected_refresh=generation))
            elif error.status and 400 <= error.status < 500 and error.status != 408:
                self.vault.write(email, bundle)
            raise
        renewed = {'oauth': oauth, 'account': bundle['account']}
        for attempt in range(3):
            try:
                self.vault.write(email, renewed)
                break
            except (KeychainError, OSError):
                if attempt == 2:
                    raise
                time.sleep(0.1 * (attempt + 1))
        return renewed

    def check_version(self, *, recovery_email=None):
        accounts = self.accounts + (recovery_email,) if recovery_email else self.accounts
        self.compatibility = check_compatibility(
            self.config['claude_executable'], self.config['config_home'], accounts,
            getattr(self, 'compatibility', None))

    def prepare_write(self, journal, *, allow_network=True):
        self.ensure_writer_enabled()
        if hasattr(self.vault, 'require_unlocked'):
            self.vault.require_unlocked()
        # A browser may already have selected the journaled third account when a new
        # process starts. Validate the native layout before completing just that recovery.
        email = (journal or {}).get('unexpected_account', {}).get('emailAddress')
        if journal and 'enrollment' in journal:
            current = read_json(self.live.config).get('oauthAccount', {})
            email = current.get('emailAddress')
        self.check_version(recovery_email=email)
        if journal is not None:
            self.recover_journal(journal, allow_network=allow_network)

    def recover(self, *, allow_network=True):
        journal = self.vault.read('__transaction__')
        if journal is not None:
            self.recover_journal(journal, allow_network=allow_network)

    def recover_journal(self, journal, *, allow_network=True):
        if 'enrollment' in journal:
            if not allow_network:
                return
            self.finish_enrollment_intent(journal)
            return
        with self.live.locked():
            blob, account = self.live.read()
            if 'restore' in journal:
                self.finish_enrollment_restore(journal, blob, account)
                return
        oauth = blob['claudeAiOauth']
        before, after = journal['before'], journal['after']
        allowed = (after['account'], before['account'])
        if self.account_key(account['emailAddress']) not in {self.account_key(entry['emailAddress']) for entry in allowed}:
            raise SwitcherError('Pending swap found a different login; manual recovery required')
        recovered = next((entry['account'] for entry in (after, before)
                          if fingerprint(oauth) == fingerprint(entry['oauth'])), None)
        identity_changed = (recovered is not None
                            and self.account_key(account['emailAddress']) == self.account_key(recovered['emailAddress'])
                            and (account.get('accountUuid'), account.get('organizationUuid')) !=
                            (recovered.get('accountUuid'), recovered.get('organizationUuid')))
        if recovered is None or identity_changed:
            if not allow_network:
                return
            # A native refresh can replace the token between the credential and metadata writes.
            actual = self.api.profile(oauth)
            recovered = next((entry for entry in (account, *allowed) if matches_identity(entry, actual)), None)
            if recovered is None:
                raise SwitcherError('Pending swap found a renewed login; manual recovery required')
        with self.live.locked():
            latest, latest_account = self.live.read()
            if latest['claudeAiOauth'] != oauth or latest_account != account:
                raise SwitcherError('Claude login changed during recovery; retry later')
            if (self.account_key(account['emailAddress']) == self.account_key(recovered['emailAddress'])
                    and account.get('accountUuid') == recovered.get('accountUuid')
                    and account.get('organizationUuid') == recovered.get('organizationUuid')):
                recovered = account
            recovered_email = self.account_key(recovered['emailAddress'])
            self.vault.write(recovered_email, {'oauth': oauth, 'account': recovered})
            if account != recovered:
                self.live.write_account(recovered)
            runtime = self.state.load('runtime')
            runtime.update(active=recovered_email, verified_active=recovered_email,
                           settle_until=time.time() + self.config['settle_seconds'])
            if recovered_email == self.account_key(after['account']['emailAddress']):
                runtime['switched_at'] = journal.get('switched_at', time.time())
            self.state.save('runtime', runtime)
            if recovered_email == self.account_key(after['account']['emailAddress']):
                record_switch(self.state, runtime['switched_at'])
            self.vault.delete('__transaction__')

    def switch_to(self, expected, target_email, now, reading=None, token_id=None, *, clock=None,
                  preference=None):
        """Preflight outside Claude's locks, then commit a recoverable local swap."""
        self.ensure_writer_enabled()
        clock = clock or (lambda: now)
        if target_email not in self.accounts:
            raise SwitcherError('Target account is not configured')
        target = self.vault.read(target_email)
        if target is None:
            raise SwitcherError(f'Account is not enrolled: {target_email}')
        if self.account_key(target['account'].get('emailAddress')) != target_email:
            raise SwitcherError('Saved account identity is inconsistent')
        refresh_generation(target)
        self.verify_identity(target, now)
        if reading is None:
            reading = self.read_usage(target_email, target['oauth'], now)
        elif fingerprint(target['oauth']) != token_id:
            raise SwitcherError('Target credential changed after the quota reading; retry later')
        if not reading.available(clock(), self.config['threshold'], 90):
            raise SwitcherError('Target account no longer has verified capacity')
        with self.state.lock('preference', blocking=True), self.live.locked():
            blob, account = self.live.read()
            if (account['emailAddress'] != expected['account']['emailAddress']
                    or fingerprint(blob['claudeAiOauth']) != fingerprint(expected['oauth'])):
                raise SwitcherError('Live login changed during preflight; retry on the next poll')
            before = {'oauth': blob['claudeAiOauth'], 'account': account}
            outgoing = self.account_key(account['emailAddress'])
            if self.vault.read(outgoing) != before:
                self.vault.write(outgoing, before)
            committed_at = clock()
            if not reading.available(committed_at, self.config['threshold'], 90):
                raise SwitcherError('Target account no longer has verified capacity')
            if preference is not None and self.preference() != preference:
                return False
            self.vault.write('__transaction__', {'before': before, 'after': target,
                                                'switched_at': committed_at})
            patched = dict(blob)
            patched['claudeAiOauth'] = target['oauth']
            try:
                self.vault.write_active(patched)
                self.live.write_account(target['account'])
            except Exception as original:
                try:
                    self.rollback_swap(before, target)
                except (KeychainError, SwitcherError, OSError, ValueError) as rollback:
                    if isinstance(original, KeychainError):
                        raise original from rollback
                    raise
                if isinstance(original, KeychainError):
                    raise
                raise SwitcherError('Account swap failed; recovery journal retained if needed') from original
            runtime = self.state.load('runtime')
            runtime.update(active=target_email, verified_active=target_email, switched_at=committed_at,
                           settle_until=clock() + self.config['settle_seconds'])
            self.state.save('runtime', runtime)
            record_switch(self.state, committed_at)
            self.vault.delete('__transaction__')
            return True

    def rollback_swap(self, before, target):
        current_blob, current_account = self.live.read()
        current_fp = fingerprint(current_blob['claudeAiOauth'])
        if (current_fp == fingerprint(target['oauth'])
                and self.account_key(current_account['emailAddress']) in self.accounts):
            self.vault.write_active(dict(current_blob, claudeAiOauth=before['oauth']))
            self.live.write_account(before['account'])
            self.vault.delete('__transaction__')
        elif current_fp == fingerprint(before['oauth']) and current_account == before['account']:
            self.vault.delete('__transaction__')

    def ensure_writer_enabled(self):
        if self.state.load('halt'):
            raise SwitcherError('Account writer halted; resolve the cause before resume')

    def tick(self, apply=False, now=None):
        clock = time.time if now is None else (lambda: now)
        try:
            with self.state.lock():
                if apply:
                    self.ensure_writer_enabled()
                return self._tick_locked(apply, clock)
        except LockBusy:
            return {'observed_at': clock(), 'active': self.state.load('runtime').get('active'),
                    'target': None, 'switched': False, 'apply': apply, 'errors': {}, 'usage': {},
                    'switch_threshold': self.config['threshold'],
                    'reason': 'waiting_for_operation'}

    def _tick_locked(self, apply, clock):
        now = clock()
        runtime = self.state.load('runtime')
        if now < runtime.get('retry_after', 0):
            if apply:
                journal = self.vault.read('__transaction__')
                if journal is not None:
                    self.prepare_write(journal, allow_network=False)
                    runtime = self.state.load('runtime')
            return {'observed_at': now, 'active': runtime.get('active'), 'target': None,
                    'switched': False, 'apply': apply, 'errors': {}, 'usage': {},
                    'switch_threshold': self.config['threshold'],
                    'reason': 'waiting_for_retry_after'}
        if apply:
            self.prepare_write(self.vault.read('__transaction__'))
            runtime = self.state.load('runtime')
        elif self.vault.read('__transaction__') is not None:
            raise SwitcherError('A pending swap needs recovery; run once --apply')
        with self.live.locked():
            blob, account = self.live.read()
        email = self.account_key(account['emailAddress'])
        if email not in self.accounts:
            raise SwitcherError('Current Claude login is outside the configured account roster')
        roster = self.state.load('roster')
        if apply and any(not roster.get(e, {}).get('registered') for e in self.accounts):
            raise SwitcherError('Enroll both accounts before enabling automatic switching')
        active = {'oauth': blob['claudeAiOauth'], 'account': account}
        active_error = None
        try:
            self.verify_identity(active, now)
        except ApiError as error:
            active_error = error
        if apply and active_error is None:
            # Capture Claude's latest token generation, never a startup-time copy.
            with self.live.locked():
                latest, identity = self.live.read()
                if identity != account or latest['claudeAiOauth'] != active['oauth']:
                    raise SwitcherError('Claude renewed its login; retry on the next poll')
                if self.vault.read(email) != active:
                    self.vault.write(email, active)
        settle_until = runtime.get('settle_until', 0)
        preference = self.preference()
        immediate = (preference.get('immediate') is True
                     and preference.get('requested_at') != runtime.get('preference_at'))
        readings, errors, reading_tokens, stages, oauth_errors = {}, {}, {}, {}, {}
        for candidate in self.accounts:
            try:
                if candidate == email and active_error:
                    raise active_error
                bundle = active if candidate == email else self.vault.read(candidate)
                if bundle is None:
                    errors[candidate] = 'not_enrolled'
                    continue
                if self.account_key(bundle.get('account', {}).get('emailAddress')) != candidate:
                    raise SwitcherError('Saved account identity is inconsistent')
                if candidate != email:
                    refresh_generation(bundle)
                expiry = bundle['oauth'].get('expiresAt')
                if (candidate != email and isinstance(expiry, (int, float))
                        and expiry <= (now + 120) * 1000):
                    if not apply or (now < settle_until and not immediate):
                        errors[candidate] = 'inactive_token_needs_refresh'
                        continue
                    bundle = self.refresh_inactive(candidate, bundle, now)
                try:
                    if candidate != email:
                        self.verify_identity(bundle, now)
                    readings[candidate] = self.read_usage(candidate, bundle['oauth'], now)
                except ApiError as error:
                    if not (error.status == 401 and candidate != email and apply
                            and (now >= settle_until or immediate)
                            and not isinstance(expiry, (int, float)) and bundle['oauth'].get('refreshToken')):
                        raise
                    bundle = self.refresh_inactive(candidate, bundle, now)
                    self.verify_identity(bundle, now)
                    readings[candidate] = self.read_usage(candidate, bundle['oauth'], now)
                reading_tokens[candidate] = fingerprint(bundle['oauth'])
            except ApiError as exc:
                stages[candidate] = exc.operation
                if exc.oauth_error:
                    oauth_errors[candidate] = exc.oauth_error
                errors[candidate] = f'http_{exc.status}' if exc.status else 'metadata_unavailable'
            except SwitcherError:
                errors[candidate] = 'authentication_needs_attention'
            except KeychainError:
                # Only the switcher's saved bundle is accessed in this per-candidate block.
                errors[candidate] = 'saved_credential_unavailable'
        preferred = self.account_key(preference.get('preferred', self.config['primary']))
        if preferred not in self.accounts:
            raise SwitcherError('Preferred account is not configured')
        fallback = next(candidate for candidate in self.accounts if candidate != preferred)
        now = clock()
        decision = choose_account(email, preferred, fallback, readings, now,
                                  self.config['threshold'], 90)
        if active_error is not None:
            other = next(key for key in self.accounts if key != email)
            if (active_error.status == 401 and self.vault.read(email) == active and other in readings
                    and readings[other].available(now, self.config['threshold'], 90)):
                decision = Decision(other, 'active_reauthentication_required')
            else:
                decision = Decision(None, 'active_authentication_unverified')
        if apply and decision.target is None and errors.get(fallback) == 'authentication_needs_attention':
            raise SwitcherError('Fallback account ownership could not be verified')
        report = {'observed_at': now, 'active': email, 'target': decision.target,
                  'reason': decision.reason, 'apply': apply, 'switched': False, 'error_stages': stages,
                  'switch_threshold': self.config['threshold'],
                  'oauth_errors': oauth_errors,
                  'usage': {e: asdict(u) for e, u in readings.items()}, 'errors': errors}
        previous = runtime.get('usage', {})
        for candidate in self.accounts:
            if candidate not in report['usage'] and candidate in previous:
                report['usage'][candidate] = dict(previous[candidate], stale=True)
        if not apply:
            self.state.save('last_observation', report)
            return report
        last_verified = runtime.get('verified_active', runtime.get('active'))
        if active_error is None:
            if last_verified in self.accounts and last_verified != email:
                record_switch(self.state, now)
                report['identity_changed'] = True
            runtime['verified_active'] = email
        runtime.update(active=email, sampled_at=now, usage=report['usage'], errors=errors,
                       preferred=preferred, last_preference=preference, target=decision.target,
                       error_stages=stages, oauth_errors=oauth_errors)
        if getattr(self, 'writer_daemon', False):
            runtime['observed_at'] = now
        if email == preferred and decision.target == email:
            runtime['preference_at'] = preference.get('requested_at')
        self.state.save('runtime', runtime)
        if decision.target and decision.target != email:
            if now < settle_until and not immediate:
                report['reason'] = 'waiting_for_credential_cache'
            else:
                report['switched'] = self.switch_to(active, decision.target, now, readings[decision.target],
                                                    reading_tokens[decision.target], clock=clock,
                                                    preference=preference)
                if not report['switched']:
                    report['reason'] = 'preference_replaced'
        self.state.save('last_report', report)
        if report['switched'] and decision.target == preferred:
            runtime = self.state.load('runtime')
            runtime['preference_at'] = preference.get('requested_at')
            self.state.save('runtime', runtime)
        return report

    def next_delay(self, now):
        runtime = self.state.load('runtime')
        # A failed lookup keeps the last windows (marked stale); they still tell how close the
        # account is, so 429 answers do not shrink the interval.
        active = runtime.get('usage', {}).get(runtime.get('active'), {})
        percents = [w['percent'] for w in active.get('windows', [])
                    if isinstance(w.get('percent'), (int, float))]
        wake = now + poll_seconds(max(percents, default=None), self.config['threshold'],
                                  self.config['poll_seconds'])
        if 'saved_credential_unavailable' in runtime.get('errors', {}).values():
            wake = min(wake, now + 60)
        if (runtime.get('target') and runtime['target'] != runtime.get('active')
                and runtime.get('settle_until', 0) > now):
            wake = min(wake, runtime['settle_until'])
        for usage in runtime.get('usage', {}).values():
            for window in usage.get('windows', []):
                reset = window.get('resets_at')
                if isinstance(reset, (int, float)) and reset > now:
                    wake = min(wake, reset + 2)
                elif isinstance(reset, (int, float)) and usage.get('checked_at', reset) <= reset:
                    wake = min(wake, now + self.config['poll_seconds'])
        limits = self.state.load('api_backoff')
        deadlines = [min((t for t in limits.get(key, {}).values() if t > now), default=0)
                     for key in self.accounts]
        if all(deadlines):
            wake = max(wake, min(deadlines))
        elif any(deadlines):
            wake = min(wake, min(t for t in deadlines if t))
        # Metadata 429/network failures must not become a tight polling loop.
        wake = max(wake, runtime.get('retry_after', 0))
        return max(2, wake - now)
