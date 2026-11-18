"""Enrollment, polling, and a recoverable swap of only Claude's account fields."""

from dataclasses import asdict
import math
import time

from api import ApiError
from compatibility import check as check_compatibility
from policy import choose_account, poll_seconds
from storage import SwitcherError, fingerprint


def validate_config(config):
    required = ('primary', 'fallback', 'config_home', 'config_path',
                'claude_executable', 'supported_version')
    if any(not isinstance(config.get(k), str) or not config[k] for k in required):
        raise SwitcherError('Run init to create a complete configuration')
    if config['primary'] == config['fallback']:
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

    def verify_identity(self, bundle):
        account = bundle['account']
        cache = getattr(self, '_verified_identities', set())
        identity = (fingerprint(bundle['oauth']), account.get('emailAddress'),
                    account.get('accountUuid'), account.get('organizationUuid'))
        if identity in cache:
            return
        actual = self.api.profile(bundle['oauth'])
        if (actual.get('email') != account.get('emailAddress')
                or actual.get('uuid') != account.get('accountUuid')
                or (account.get('organizationUuid') is not None
                    and actual.get('organizationUuid') != account['organizationUuid'])):
            raise SwitcherError('OAuth token ownership does not match the saved account')
        cache.add(identity)
        self._verified_identities = cache

    def capture(self, expected_email):
        if expected_email not in self.accounts:
            raise SwitcherError('Account is not in the configured two-account roster')
        with self.state.lock():
            with self.live.locked():
                blob, account = self.live.read()
            if account['emailAddress'] != expected_email:
                raise SwitcherError(f'Log into the expected account first: {expected_email}')
            bundle = {'oauth': blob['claudeAiOauth'], 'account': account}
            self.verify_identity(bundle)
            with self.live.locked():
                current, current_account = self.live.read()
                if (fingerprint(current['claudeAiOauth']) != fingerprint(bundle['oauth'])
                        or current_account != account):
                    raise SwitcherError('Claude login changed during enrollment; retry capture')
                self.vault.write(expected_email, bundle)
            roster = self.state.load('roster')
            roster[expected_email] = {'registered': True, 'captured_at': time.time()}
            self.state.save('roster', roster)
            runtime = self.state.load('runtime')
            runtime.update(active=expected_email,
                           settle_until=time.time() + self.config['settle_seconds'])
            self.state.save('runtime', runtime)

    def check_version(self):
        self.compatibility = check_compatibility(
            self.config['claude_executable'], self.config['config_home'], self.accounts,
            getattr(self, 'compatibility', None))

    def recover(self):
        journal = self.vault.read('__transaction__')
        if journal is None:
            return
        with self.live.locked():
            blob, account = self.live.read()
            current = fingerprint(blob['claudeAiOauth'])
            before = journal['before']
            after = journal['after']
            allowed_emails = {before['account']['emailAddress'], after['account']['emailAddress']}
            if account['emailAddress'] not in allowed_emails:
                raise SwitcherError('Pending swap found a different login; manual recovery required')
            if current == fingerprint(after['oauth']):
                self.live.write_account(after['account'])
                recovered_email = after['account']['emailAddress']
            elif current == fingerprint(before['oauth']):
                self.live.write_account(before['account'])
                recovered_email = before['account']['emailAddress']
            else:
                raise SwitcherError('Pending swap found a renewed login; manual recovery required')
            runtime = self.state.load('runtime')
            runtime.update(active=recovered_email,
                           settle_until=time.time() + self.config['settle_seconds'])
            if recovered_email == after['account']['emailAddress']:
                runtime['switched_at'] = time.time()
            self.state.save('runtime', runtime)
            self.vault.delete('__transaction__')

    def switch_to(self, expected, target_email, now, reading=None, token_id=None):
        """Preflight outside Claude's locks, then commit a recoverable local swap."""
        if target_email not in self.accounts:
            raise SwitcherError('Target account is not configured')
        target = self.vault.read(target_email)
        if target is None:
            raise SwitcherError(f'Account is not enrolled: {target_email}')
        if target['account'].get('emailAddress') != target_email:
            raise SwitcherError('Saved account identity is inconsistent')
        self.verify_identity(target)
        if reading is None:
            reading = self.api.usage(target['oauth'], now)
        elif fingerprint(target['oauth']) != token_id:
            raise SwitcherError('Target credential changed after the quota reading; retry later')
        if not reading.available(now, self.config['threshold'], 90):
            raise SwitcherError('Target account no longer has verified capacity')
        with self.live.locked():
            blob, account = self.live.read()
            if (account['emailAddress'] != expected['account']['emailAddress']
                    or fingerprint(blob['claudeAiOauth']) != fingerprint(expected['oauth'])):
                raise SwitcherError('Live login changed during preflight; retry on the next poll')
            before = {'oauth': blob['claudeAiOauth'], 'account': account}
            self.vault.write(account['emailAddress'], before)
            self.vault.write('__transaction__', {'before': before, 'after': target})
            patched = dict(blob)
            patched['claudeAiOauth'] = target['oauth']
            try:
                self.vault.write_active(patched)
                self.live.write_account(target['account'])
            except Exception:
                # No network or output here: preserve unrelated live MCP credentials.
                current_blob, current_account = self.live.read()
                current_fp = fingerprint(current_blob['claudeAiOauth'])
                if (current_fp == fingerprint(target['oauth'])
                        and current_account['emailAddress'] in self.accounts):
                    restored = dict(current_blob)
                    restored['claudeAiOauth'] = before['oauth']
                    self.vault.write_active(restored)
                    self.live.write_account(before['account'])
                    self.vault.delete('__transaction__')
                elif (current_fp == fingerprint(before['oauth'])
                      and current_account == before['account']):
                    self.vault.delete('__transaction__')
                raise SwitcherError('Account swap failed; recovery journal retained if needed') from None
            self.vault.delete('__transaction__')
        runtime = self.state.load('runtime')
        runtime.update(active=target_email, switched_at=now,
                       settle_until=now + self.config['settle_seconds'])
        self.state.save('runtime', runtime)

    def tick(self, apply=False, now=None):
        now = time.time() if now is None else now
        with self.state.lock():
            if apply:
                self.check_version()
                self.recover()
            elif self.vault.read('__transaction__') is not None:
                raise SwitcherError('A pending swap needs recovery; run once --apply')
            with self.live.locked():
                blob, account = self.live.read()
            email = account['emailAddress']
            if email not in self.accounts:
                raise SwitcherError('Current Claude login is outside the configured account roster')
            roster = self.state.load('roster')
            if apply and any(not roster.get(e, {}).get('registered') for e in self.accounts):
                raise SwitcherError('Enroll both accounts before enabling automatic switching')
            active = {'oauth': blob['claudeAiOauth'], 'account': account}
            self.verify_identity(active)
            if apply:
                # Capture Claude's latest token generation, never a startup-time copy.
                with self.live.locked():
                    latest, identity = self.live.read()
                    if (identity != account or fingerprint(latest['claudeAiOauth'])
                            != fingerprint(active['oauth'])):
                        raise SwitcherError('Claude renewed its login; retry on the next poll')
                    self.vault.write(email, active)
            runtime = self.state.load('runtime')
            settle_until = runtime.get('settle_until', 0)
            readings, errors, reading_tokens = {}, {}, {}
            for candidate in self.accounts:
                bundle = active if candidate == email else self.vault.read(candidate)
                if bundle is None:
                    errors[candidate] = 'not_enrolled'
                    continue
                try:
                    expiry = bundle['oauth'].get('expiresAt')
                    if (candidate != email and isinstance(expiry, (int, float))
                            and expiry <= (now + 120) * 1000):
                        if not apply or now < settle_until:
                            errors[candidate] = 'inactive_token_needs_refresh'
                            continue
                        bundle['oauth'] = self.api.refresh(bundle['oauth'], now)
                        # Persist the successor before any further network request.
                        self.vault.write(candidate, bundle)
                        self.verify_identity(bundle)
                    readings[candidate] = self.api.usage(bundle['oauth'], now)
                    reading_tokens[candidate] = fingerprint(bundle['oauth'])
                except ApiError as exc:
                    errors[candidate] = f'http_{exc.status}' if exc.status else 'metadata_unavailable'
                    runtime['retry_after'] = max(runtime.get('retry_after', 0), now + exc.retry_after)
                except SwitcherError:
                    errors[candidate] = 'authentication_needs_attention'
            preference = self.state.load('preference')
            preferred = preference.get('preferred', self.config['primary'])
            if preferred not in self.accounts:
                raise SwitcherError('Preferred account is not configured')
            fallback = next(candidate for candidate in self.accounts if candidate != preferred)
            decision = choose_account(email, preferred, fallback, readings, now,
                                      self.config['threshold'], 90)
            report = {'observed_at': now, 'active': email, 'target': decision.target,
                      'reason': decision.reason, 'apply': apply, 'switched': False,
                      'usage': {e: asdict(u) for e, u in readings.items()}, 'errors': errors}
            previous = runtime.get('usage', {})
            for candidate in self.accounts:
                if candidate not in report['usage'] and candidate in previous:
                    report['usage'][candidate] = dict(previous[candidate], stale=True)
            runtime.update(active=email, observed_at=now, usage=report['usage'], errors=errors,
                           preferred=preferred, preference_at=preference.get('requested_at'), target=decision.target)
            self.state.save('runtime', runtime)
            if apply and decision.target and decision.target != email:
                if now < settle_until:
                    report['reason'] = 'waiting_for_credential_cache'
                else:
                    self.switch_to(active, decision.target, now, readings[decision.target],
                                   reading_tokens[decision.target])
                    report['switched'] = True
            self.state.save('last_report', report)
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
        for usage in runtime.get('usage', {}).values():
            for window in usage.get('windows', []):
                reset = window.get('resets_at')
                if isinstance(reset, (int, float)) and reset > now:
                    wake = min(wake, reset + 2)
        # Metadata 429/network failures must not become a tight polling loop.
        wake = max(wake, runtime.get('retry_after', 0))
        return max(2, wake - now)
