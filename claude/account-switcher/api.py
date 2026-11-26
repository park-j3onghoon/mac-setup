"""Metadata-only requests to Anthropic. No model calls, redirects, or proxies."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import json
import math
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import (Request, HTTPSHandler, HTTPRedirectHandler,
                            ProxyHandler, build_opener)

from storage import SwitcherError
from switchcore.quota import Usage, Window


class ApiError(SwitcherError):
    def __init__(self, operation, status=None, retry_after=60, oauth_error=None):
        super().__init__(f'Anthropic {operation} failed: status={status or "unavailable"}')
        self.operation = operation
        self.oauth_error = oauth_error
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def epoch(value):
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Invalid timestamp')
    return float(value)


def parse_usage(data, now):
    windows = []
    for name in ('five_hour', 'seven_day'):
        window = data.get(name)
        if window is None:
            continue
        if not isinstance(window, dict) or 'utilization' not in window:
            raise ApiError('usage schema')
        windows.append(Window(name, window['utilization'], epoch(window.get('resets_at')),
                              window.get('locked_reason') not in (None, '')))
    # Legacy model limits and the newer scoped weekly windows are both binding.
    for name in ('seven_day_opus', 'seven_day_sonnet', 'seven_day_oauth_apps',
                 'seven_day_cowork', 'seven_day_omelette'):
        window = data.get(name)
        if window is not None:
            if not isinstance(window, dict) or 'utilization' not in window:
                raise ApiError('model quota schema')
            windows.append(Window(name, window['utilization'], epoch(window.get('resets_at')),
                                  window.get('locked_reason') not in (None, '')))
    limits = data.get('limits', [])
    if not isinstance(limits, list):
        raise ApiError('scoped quota schema')
    for limit in limits:
        if not isinstance(limit, dict):
            raise ApiError('scoped quota schema')
        kind = limit.get('kind')
        if kind in ('session', 'weekly_all', 'weekly_scoped'):
            if 'percent' not in limit:
                raise ApiError('scoped quota schema')
            name = {'session': 'five_hour', 'weekly_all': 'seven_day'}.get(kind)
            if name is None:
                name = json.dumps(limit.get('scope', {}), sort_keys=True)
            windows.append(Window(name, limit['percent'], epoch(limit.get('resets_at')),
                                  limit.get('locked_reason') not in (None, '')))
    if not windows:
        raise ApiError('usage schema: no quota windows')
    combined = {}
    for window in windows:
        previous = combined.get(window.name)
        if previous is not None:
            percents = (previous.percent, window.percent)
            resets = (r for r in (previous.resets_at, window.resets_at) if r is not None)
            window = Window(window.name, None if None in percents else max(percents),
                            min(resets, default=None), previous.blocked or window.blocked)
        combined[window.name] = window
    return Usage(now, tuple(combined.values()))


class Anthropic:
    ORIGINS = ('https://api.anthropic.com/', 'https://platform.claude.com/')
    CLIENT_ID = '9d1c250a-e61b-44d9-88ed-5944d1962f5e'

    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), NoRedirect(),
                                   HTTPSHandler(context=ssl.create_default_context()))

    def request(self, path, token=None, payload=None, operation='request'):
        if not path.startswith(self.ORIGINS):
            raise SwitcherError('Anthropic request origin is not allowed')
        headers = {'User-Agent': 'local-claude-account-switcher/1',
                   'Content-Type': 'application/json', 'anthropic-beta': 'oauth-2025-04-20'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(path, data=None if payload is None else json.dumps(payload).encode(),
                          headers=headers)
        try:
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(262145)
                if len(raw) > 262144:
                    raise ApiError(operation + ' response too large')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ApiError(operation + ' response schema')
                return data
        except HTTPError as exc:
            value = exc.headers.get('Retry-After', '60')
            try:
                retry = int(value)
            except (ValueError, TypeError):
                try:
                    retry = math.ceil(parsedate_to_datetime(value).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError, OSError):
                    retry = 60
            retry = max(30, retry)
            oauth_error = None
            if operation == 'token refresh' and exc.code == 400:
                try:
                    body = json.loads(exc.read(8192))
                    code = body.get('error') if isinstance(body, dict) else None
                    if isinstance(code, dict):
                        code = code.get('type')
                    if isinstance(code, str) and code in (
                            'invalid_grant', 'invalid_client', 'invalid_request', 'invalid_scope',
                            'unsupported_grant_type', 'unauthorized_client'):
                        oauth_error = code
                except (OSError, ValueError, HTTPException):
                    pass
            exc.close()
            raise ApiError(operation, exc.code, retry, oauth_error) from None
        except (URLError, TimeoutError, OSError, ValueError, HTTPException):
            raise ApiError(operation) from None

    def profile(self, oauth):
        data = self.request('https://api.anthropic.com/api/oauth/profile',
                            oauth['accessToken'], operation='profile')
        account = data.get('account', {})
        if not isinstance(account, dict) or not account.get('email') or not account.get('uuid'):
            raise ApiError('profile schema')
        organization = data.get('organization')
        return dict(account, organizationUuid=(organization.get('uuid')
                    if isinstance(organization, dict) else None))

    def usage(self, oauth, now):
        data = self.request('https://api.anthropic.com/api/oauth/usage',
                            oauth['accessToken'], operation='usage')
        try:
            return parse_usage(data, now)
        except (TypeError, ValueError, OverflowError):
            raise ApiError('usage schema') from None

    def refresh(self, oauth, now):
        refresh_token = oauth.get('refreshToken')
        if not refresh_token:
            raise SwitcherError('Inactive account needs a new Claude login: no refresh token')
        data = self.request('https://platform.claude.com/v1/oauth/token', payload={
            'grant_type': 'refresh_token', 'refresh_token': refresh_token,
            'client_id': self.CLIENT_ID}, operation='token refresh')
        ttl = data.get('expires_in')
        if (not isinstance(data.get('access_token'), str) or not data['access_token']
                or isinstance(ttl, bool) or not isinstance(ttl, (int, float))
                or not math.isfinite(ttl) or ttl <= 0):
            raise ApiError('token refresh schema')
        result = dict(oauth)
        result.update(accessToken=data['access_token'], expiresAt=(now + ttl) * 1000)
        if data.get('refresh_token'):
            result['refreshToken'] = data['refresh_token']
        if data.get('scope'):
            result['scopes'] = data['scope'].split()
        return result
