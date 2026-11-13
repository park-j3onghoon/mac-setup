from contextlib import contextmanager
import copy
from pathlib import Path

from policy import Usage, Window
from service import Switcher
from storage import LiveClaude, State, write_json


NOW = 2_000_000_000.0


def bundle(email, token):
    return {'oauth': {'accessToken': token, 'refreshToken': 'refresh-' + token,
                      'expiresAt': (NOW + 86400) * 1000},
            'account': {'emailAddress': email, 'accountUuid': 'uuid-' + email}}


class MemoryVault:
    def __init__(self):
        self.values = {'personal': bundle('personal', 'token-personal'),
                       'work': bundle('work', 'token-work')}
        self.active = {'claudeAiOauth': self.values['personal']['oauth'],
                       'mcpOAuth': {'keep': 'independent-connector-secret'}}
        self.crash_after_write = False
        self.active_writes = 0

    def read(self, name):
        return copy.deepcopy(self.values.get(name))

    def write(self, name, value):
        self.values[name] = copy.deepcopy(value)

    def delete(self, name):
        self.values.pop(name, None)

    def read_active(self):
        return copy.deepcopy(self.active)

    def write_active(self, value):
        self.active = copy.deepcopy(value)
        self.active_writes += 1
        if self.crash_after_write:
            self.crash_after_write = False
            raise KeyboardInterrupt('simulated process death')


class MetadataApi:
    def __init__(self):
        self.percent = {'token-personal': 95, 'token-work': 20}
        self.failed_tokens = set()
        self.profile_override = None
        self.profile_overrides = {}
        self.refreshes = 0
        self.before_usage = None

    def profile(self, oauth):
        if self.profile_override:
            return self.profile_override
        email = 'personal' if 'personal' in oauth['accessToken'] else 'work'
        return {'email': email, 'uuid': 'uuid-' + email}

    def usage(self, oauth, now):
        if self.before_usage:
            callback, self.before_usage = self.before_usage, None
            callback()
        if oauth['accessToken'] in self.failed_tokens:
            from api import ApiError
            raise ApiError('usage', 429, 300)
        return Usage(now, (Window('five_hour', self.percent[oauth['accessToken']], now + 600),
                           Window('seven_day', 10, now + 86400)))

    def refresh(self, oauth, now):
        self.refreshes += 1
        updated = dict(oauth, accessToken=oauth['accessToken'] + '-new',
                       refreshToken='rotated-refresh-token', expiresAt=(now + 86400) * 1000)
        self.percent[updated['accessToken']] = 20
        return updated


class TestSwitcher(Switcher):
    def check_version(self):
        pass


class FaultyLive(LiveClaude):
    fail_next_config_write = False

    def write_account(self, account):
        if self.fail_next_config_write:
            self.fail_next_config_write = False
            raise OSError('injected disk failure')
        super().write_account(account)


def make_app(directory):
    home = Path(directory) / '.claude'
    home.mkdir()
    state = State(Path(directory) / 'state')
    vault = MemoryVault()
    path = Path(directory) / '.claude.json'
    write_json(path, {'oauthAccount': vault.read('personal')['account'],
                      'mcpServers': {'existing': {'command': 'keep-me'}}})
    config = {'primary': 'personal@example.com', 'fallback': 'work@example.com',
              'threshold': 95, 'poll_seconds': 60, 'settle_seconds': 45,
              'config_home': str(home), 'config_path': str(path),
              'claude_executable': '/unused/claude', 'supported_version': '2.1.322'}
    # Short test identities are swapped for realistic email-form identities here.
    for role in ('personal', 'work'):
        entry = vault.values.pop(role)
        entry['account']['emailAddress'] = role + '@example.com'
        entry['account']['accountUuid'] = 'uuid-' + role + '@example.com'
        vault.write(role + '@example.com', entry)
    vault.active['claudeAiOauth'] = vault.read('personal@example.com')['oauth']
    write_json(path, {'oauthAccount': vault.read('personal@example.com')['account'],
                      'mcpServers': {'existing': {'command': 'keep-me'}}})
    api = MetadataApi()
    original_profile = api.profile

    def profile(oauth):
        override = api.profile_overrides.get(oauth['accessToken'])
        if override is not None:
            return override
        result = original_profile(oauth)
        if not api.profile_override:
            result = {k: v + '@example.com' for k, v in result.items()}
        return result

    api.profile = profile
    live = FaultyLive(home, path, vault)
    state.save('roster', {e: {'registered': True} for e in
                          ('personal@example.com', 'work@example.com')})
    return TestSwitcher(config, state, live, vault, api)
