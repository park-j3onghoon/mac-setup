"""Framework-backed private vault and Claude's login item through /usr/bin/security."""

import ctypes as C
import getpass
import json
import subprocess
import sys

CLAUDE_SERVICE = 'Claude Code-credentials'
SECURITY = '/usr/bin/security'
# Claude Code 2.1.323 passes the command to `security -i` on stdin up to this length,
# and passes it as arguments beyond it ("exceeds security -i stdin limit; using argv").
SECURITY_STDIN_LIMIT = 4032
MAX_CREDENTIAL_BYTES = 262144


class KeychainError(RuntimeError):
    pass


def system_awake(runner=subprocess.run):
    """False in a dark wake: a lid-closed maintenance wake runs without graphics."""
    try:
        result = runner(['/usr/bin/pmset', '-g', 'systemstate'], capture_output=True, text=True,
                        timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return True
    prefix = 'Current System Capabilities are:'
    for line in result.stdout.splitlines() if result.returncode == 0 else ():
        if line.strip().startswith(prefix):
            capabilities = line.split(':', 1)[1].split()
            return not capabilities or 'Graphics' in capabilities
    return True


class DictionaryKeyCallbacks(C.Structure):
    _fields_ = [('version', C.c_long), ('retain', C.c_void_p),
                ('release', C.c_void_p), ('describe', C.c_void_p),
                ('equal', C.c_void_p), ('hash', C.c_void_p)]


class DictionaryValueCallbacks(C.Structure):
    _fields_ = [('version', C.c_long), ('retain', C.c_void_p),
                ('release', C.c_void_p), ('describe', C.c_void_p),
                ('equal', C.c_void_p)]


class Keychain:
    def __init__(self, allow_interaction=False):
        if sys.platform != 'darwin':
            raise KeychainError('macOS is required')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.sec = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.declare_core_foundation()
        self.declare_security()
        self.allow_interaction = allow_interaction
        status = self.sec.SecKeychainSetUserInteractionAllowed(allow_interaction)
        if status:
            raise KeychainError(f'Could not disable Keychain UI: status={status}')

    def declare_core_foundation(self):
        self.cf.CFStringCreateWithCString.argtypes = [C.c_void_p, C.c_char_p, C.c_uint32]
        self.cf.CFStringCreateWithCString.restype = C.c_void_p
        self.cf.CFDataCreate.argtypes = [C.c_void_p, C.c_void_p, C.c_long]
        self.cf.CFDataCreate.restype = C.c_void_p
        self.cf.CFDictionaryCreate.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p,
                                             C.c_long, C.c_void_p, C.c_void_p]
        self.cf.CFDictionaryCreate.restype = C.c_void_p
        self.key_callbacks = DictionaryKeyCallbacks.in_dll(
            self.cf, 'kCFTypeDictionaryKeyCallBacks')
        self.value_callbacks = DictionaryValueCallbacks.in_dll(
            self.cf, 'kCFTypeDictionaryValueCallBacks')
        self.cf.CFDataGetLength.argtypes = [C.c_void_p]
        self.cf.CFDataGetLength.restype = C.c_long
        self.cf.CFDataGetBytePtr.argtypes = [C.c_void_p]
        self.cf.CFDataGetBytePtr.restype = C.c_void_p
        self.cf.CFRelease.argtypes = [C.c_void_p]

    def declare_security(self):
        self.sec.SecItemCopyMatching.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
        self.sec.SecItemCopyMatching.restype = C.c_int32
        self.sec.SecItemUpdate.argtypes = [C.c_void_p, C.c_void_p]
        self.sec.SecItemUpdate.restype = C.c_int32
        self.sec.SecItemAdd.argtypes = [C.c_void_p, C.c_void_p]
        self.sec.SecItemAdd.restype = C.c_int32
        self.sec.SecItemDelete.argtypes = [C.c_void_p]
        self.sec.SecItemDelete.restype = C.c_int32
        self.sec.SecKeychainFindGenericPassword.argtypes = [
            C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p,
            C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)]
        self.sec.SecKeychainFindGenericPassword.restype = C.c_int32
        self.sec.SecKeychainItemModifyAttributesAndData.argtypes = [
            C.c_void_p, C.c_void_p, C.c_uint32, C.c_void_p]
        self.sec.SecKeychainItemModifyAttributesAndData.restype = C.c_int32
        self.sec.SecKeychainItemFreeContent.argtypes = [C.c_void_p, C.c_void_p]
        self.sec.SecKeychainItemFreeContent.restype = C.c_int32
        self.sec.SecKeychainSetUserInteractionAllowed.argtypes = [C.c_bool]

    def constant(self, name):
        library = self.cf if name.startswith('kCF') else self.sec
        return C.c_void_p.in_dll(library, name).value

    def dictionary(self, values):
        owned = []
        keys, vals = [], []
        for key, value in values.items():
            keys.append(self.constant(key))
            if isinstance(value, str):
                ptr = self.cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
                owned.append(ptr)
            elif isinstance(value, bytes):
                ptr = self.cf.CFDataCreate(None, value, len(value))
                owned.append(ptr)
            else:
                ptr = value
            vals.append(ptr)
        array = C.c_void_p * len(keys)
        result = self.cf.CFDictionaryCreate(None, array(*keys), array(*vals),
                                             len(keys), C.byref(self.key_callbacks),
                                             C.byref(self.value_callbacks))
        return result, owned

    def query(self, service, account):
        return {'kSecClass': self.constant('kSecClassGenericPassword'),
                'kSecAttrService': service, 'kSecAttrAccount': account,
                'kSecUseAuthenticationUI': self.constant(
                    'kSecUseAuthenticationUIAllow' if self.allow_interaction
                    else 'kSecUseAuthenticationUIFail')}

    def release(self, dictionary, owned):
        self.cf.CFRelease(dictionary)
        for item in owned:
            self.cf.CFRelease(item)

    def read(self, service, account):
        values = self.query(service, account)
        values['kSecReturnData'] = self.constant('kCFBooleanTrue')
        values['kSecMatchLimit'] = self.constant('kSecMatchLimitOne')
        query, owned = self.dictionary(values)
        result = C.c_void_p()
        try:
            status = self.sec.SecItemCopyMatching(query, C.byref(result))
            if status == -25300:
                return None
            if status:
                raise KeychainError(f'Keychain read denied or unavailable: status={status}')
            try:
                raw = C.string_at(self.cf.CFDataGetBytePtr(result),
                                  self.cf.CFDataGetLength(result))
                return json.loads(raw)
            finally:
                self.cf.CFRelease(result)
        finally:
            self.release(query, owned)

    def write(self, service, account, value):
        raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
        query, owned = self.dictionary(self.query(service, account))
        attrs, attr_owned = self.dictionary({'kSecValueData': raw})
        try:
            status = self.sec.SecItemUpdate(query, attrs)
            if status == -25300:
                values = self.query(service, account)
                values['kSecValueData'] = raw
                added, added_owned = self.dictionary(values)
                try:
                    status = self.sec.SecItemAdd(added, None)
                finally:
                    self.release(added, added_owned)
            if status:
                raise KeychainError(f'Keychain write denied or unavailable: status={status}')
        finally:
            self.release(query, owned)
            self.release(attrs, attr_owned)
        if self.read(service, account) != value:
            raise KeychainError('Keychain read-back verification failed')

    def delete(self, service, account):
        query, owned = self.dictionary(self.query(service, account))
        try:
            status = self.sec.SecItemDelete(query)
            if status not in (0, -25300):
                raise KeychainError(f'Keychain delete failed: status={status}')
        finally:
            self.release(query, owned)

    def replace_existing(self, service, account, value):
        """Read, update and verify the existing login through the owning Apple CLI."""
        native = NativeKeychain(self, account, service=service)
        native.read()
        native.write_item(value)

    def read_existing(self, service, account):
        """Read a legacy item using the same Keychain API family as security."""
        service_bytes, account_bytes = service.encode(), account.encode()
        size, data, item = C.c_uint32(), C.c_void_p(), C.c_void_p()
        status = self.sec.SecKeychainFindGenericPassword(
            None, len(service_bytes), service_bytes, len(account_bytes), account_bytes,
            C.byref(size), C.byref(data), C.byref(item))
        if status == -25300:
            return None
        if status:
            raise KeychainError(f'Native Keychain read denied or unavailable: status={status}')
        try:
            return json.loads(C.string_at(data, size.value))
        finally:
            self.sec.SecKeychainItemFreeContent(None, data)
            self.cf.CFRelease(item)



class Vault:
    SERVICE = 'local.mac-setup.claude-account-switcher'

    def __init__(self, keychain, namespace):
        self.keychain = keychain
        self.namespace = namespace
        self.username = getpass.getuser()
        self.native = NativeKeychain(keychain, self.username)

    def read_active(self):
        return self.native.read()

    def write_active(self, value):
        self.native.write(value)

    def read_active_for_measurement(self):
        """Use SecItemCopyMatching with kSecUseAuthenticationUIFail; never launch a CLI."""
        return self.keychain.read(CLAUDE_SERVICE, self.username)

    def read(self, name):
        return self.keychain.read(self.SERVICE, f'{self.namespace}:{name}')

    def write(self, name, value):
        self.keychain.write(self.SERVICE, f'{self.namespace}:{name}', value)

    def delete(self, name):
        self.keychain.delete(self.SERVICE, f'{self.namespace}:{name}')


class NativeKeychain:
    """Read and write Claude's login item with /usr/bin/security, as Claude Code does.

    Claude Code reads the item with /usr/bin/security, whose Keychain partition is
    "apple-tool:". A write from any other binary replaces the item's partition list
    with that binary's partition, and every Claude session then asks for the login
    password on each read. On 2026-11-13 11:23 a /usr/bin/ruby writer left only
    "apple:" (securityd: "ACL partition mismatch: client apple-tool:"), which caused
    a prompt storm. Writing through /usr/bin/security keeps "apple-tool:".
    """

    def __init__(self, keychain, username, runner=None, *, service=None):
        self.service = CLAUDE_SERVICE if service is None else service
        for name in (self.service, username):
            if not name or not name.isprintable() or any(c in name for c in ('"', '\\')):
                raise KeychainError('Unsupported name for the Keychain command')
        self.keychain, self.username = keychain, username
        self.runner = subprocess.run if runner is None else runner

    def read(self):
        try:
            result = self.runner([SECURITY, 'find-generic-password',
                                  '-s', self.service, '-a', self.username, '-w'],
                                 stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                                 check=False)
            if result.returncode:
                raise KeychainError(f'Native Claude credential read failed: status={result.returncode}')
            if len(result.stdout) > MAX_CREDENTIAL_BYTES:
                raise KeychainError('Native Claude credential data exceeds the reader limit')
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise KeychainError('Native Claude credential schema changed')
            return value
        except (OSError, ValueError, subprocess.SubprocessError):
            raise KeychainError('Native Claude credential read failed') from None

    def write(self, value):
        if not isinstance(value, dict) or not isinstance(value.get('claudeAiOauth'), dict):
            raise KeychainError('Native Claude credential schema changed')
        self.write_item(value)

    def write_item(self, value):
        try:
            raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
            if len(raw) > MAX_CREDENTIAL_BYTES:
                raise KeychainError('Native Claude credential data exceeds the writer limit')
            data = raw.hex()
            command = (f'add-generic-password -U -a "{self.username}" '
                       f'-s "{self.service}" -X "{data}"\n')
            if len(command) <= SECURITY_STDIN_LIMIT:
                result = self.runner([SECURITY, '-i'], input=command.encode(),
                                     capture_output=True, timeout=5, check=False)
            else:
                # Same fallback as Claude Code: `security -i` cannot read a longer line.
                result = self.runner([SECURITY, 'add-generic-password', '-U', '-a', self.username,
                                      '-s', self.service, '-X', data],
                                     stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                                     check=False)
            if result.returncode:
                raise KeychainError('Native Claude credential update failed')
            if self.read() != value:
                raise KeychainError('Native Claude credential read-back verification failed')
        except (OSError, ValueError, subprocess.SubprocessError):
            raise KeychainError('Native Claude credential update failed') from None
