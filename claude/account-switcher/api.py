"""Metadata-only requests to Anthropic. No model calls, redirects, or proxies."""

from datetime import datetime
import json
import math
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import (Request, HTTPSHandler, HTTPRedirectHandler,
                            ProxyHandler, build_opener)

from policy import Usage, Window
from storage import SwitcherError


class ApiError(SwitcherError):
    def __init__(self, operation, status=None, retry_after=60):
        super().__init__(f'Anthropic {operation} failed: status={status or "unavailable"}')
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
        if limit.get('kind') == 'weekly_scoped':
            if 'percent' not in limit:
                raise ApiError('scoped quota schema')
            name = json.dumps(limit.get('scope', {}), sort_keys=True)
            windows.append(Window(name, limit['percent'], epoch(limit.get('resets_at')),
                                  limit.get('locked_reason') not in (None, '')))
    if not windows:
        raise ApiError('usage schema: no quota windows')
    return Usage(now, tuple(windows))


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
            retry = 60
            try:
                retry = max(30, min(3600, int(exc.headers.get('Retry-After', '60'))))
            except (ValueError, TypeError):
                pass
            raise ApiError(operation, exc.code, retry) from None
        except (URLError, TimeoutError, OSError, ValueError):
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
