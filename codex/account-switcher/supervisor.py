#!/usr/bin/env python3
"""Monitor saved plan limits and switch idle automatic Codex sessions."""

from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
import signal
import threading
import time

from policy import THRESHOLD, UsageUnavailable, choose
from profiles import PROFILES, Profile, RegistrationMismatch
from runtime import Runtime, prepare_home, server_package_cache
from service import process_start
from state import RUNTIME, STATE_FILE, changed_file, load, poll_delay, preference, record, save


def collect(profiles):
    snapshots, errors = {}, {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(profile.usage) for name, profile in profiles.items()}
        for name, future in futures.items():
            try:
                snapshots[name] = future.result()
            except Exception as error:
                errors[name] = type(error).__name__
    identities = [profile.account_id for profile in profiles.values() if profile.account_id is not None]
    if len(identities) != len(set(identities)):
        return {}, {name: 'DuplicateWorkspace' for name in profiles}
    return snapshots, errors


def check_upgrade(runtime, state):
    installed = runtime.binary.resolve(strict=True)
    if server_package_cache(installed, runtime.home) and installed.parent.parent.name != state["runtime_version"]:
        state["upgrade_target"] = installed.parent.parent.name
        state["upgrade_status"] = "draining" if runtime.drain_for_upgrade(installed) else "waiting_for_idle"
    else:
        state.pop("upgrade_target", None)
        state.pop("upgrade_status", None)


def monitor(runtime, profiles, stop, state):
    state.setdefault("preferred", "company")
    next_poll = 0
    next_release = 0
    next_upgrade = 0
    retry_switch_at = 0
    idle_retry_delay = 2
    desired = None
    check_limited = False
    saved_content = None
    saved_at = 0
    previous_wall = 0
    retry_registration = {}
    next_limit_check = 0
    while not stop.is_set():
        if not runtime.running():
            if state.get("upgrade_status") == "draining":
                return True
            raise UsageUnavailable("Automatic runtime exited")
        now = time.time()
        if now < previous_wall:
            next_poll = next_release = next_upgrade = retry_switch_at = saved_at = next_limit_check = 0
            retry_registration.clear()
            saved_content = None
        previous_wall = now
        if state.get("runtime_version") and state.get("upgrade_status") != "draining" and now >= next_upgrade:
            try:
                check_upgrade(runtime, state)
                state.pop("upgrade_error", None)
            except (OSError, KeyError, ValueError) as error:
                state["upgrade_error"] = type(error).__name__
                state['upgrade_checked_at'] = now
            next_upgrade = time.time() + 15
        if state.get("upgrade_status") == "draining":
            if state.get('active') or state.get('restore_account') != runtime.active or now - saved_at >= 30:
                state.update(updated_at=now, active=None, restore_account=runtime.active)
                save(state)
                saved_at = now
            stop.wait(2)
            continue
        requested = preference()
        manual = changed_file(RUNTIME / 'usage-request.json').get('requested_at', 0)
        if manual > state.get('usage_request_at', 0):
            next_poll = 0
        legacy = changed_file(RUNTIME / 'profile-registration.json')
        for name, profile in profiles.items():
            binding = changed_file(RUNTIME / f'profile-registration-{name}.json')
            if (legacy.get('profile') == name and
                    (not binding or legacy.get('requested_at', 0) > binding.get('requested_at', 0))):
                binding = legacy
                if binding.get('requested_at', 0) <= state.get('registration_at', 0):
                    continue
            if not binding or binding.get('profile') != name:
                continue
            request = binding.get('requested_at')
            if state.get('registration_requests', {}).get(name) == request:
                continue
            last, retry_at = retry_registration.get(name, (None, 0))
            if last == request and now < retry_at:
                continue
            errors = state.setdefault('registration_errors', {})
            try:
                profile.register(binding.get('account_id'))
            except RegistrationMismatch as error:
                errors[name] = str(error)
            except UsageUnavailable as error:
                errors[name] = str(error)
                retry_registration[name] = (request, now + 5)
                state['registration_error'] = '; '.join(f'{key}: {value}' for key, value in errors.items())
                continue
            else:
                errors.pop(name, None)
                state['accounts'] = {key: value for key, value in state.get('accounts', {}).items() if key != name}
            if errors:
                state['registration_error'] = '; '.join(f'{key}: {value}' for key, value in errors.items())
            else:
                state.pop('registration_error', None)
            state.setdefault('registration_requests', {})[name] = request
            state['registration_at'] = max(state.get('registration_at', 0), request)
            next_poll = 0
        if requested and requested.get("requested_at") != state.get("preference_at"):
            state.update(preferred=requested["preferred"], preference_at=requested.get("requested_at"),
                         preference_immediate=requested.get('immediate') is True)
            next_poll = retry_switch_at = 0
            idle_retry_delay = 2
        if now >= next_release:
            complete = True
            try:
                complete = runtime.release_subscriptions()
                state.pop("release_error", None)
            except Exception as error:
                state["release_error"] = type(error).__name__
                complete = not (runtime.release_ids or runtime.release_cursor)
            next_release = time.time() + (2 if complete is False else 60)
        if now >= next_limit_check and runtime.take_limit_failure() is True:
            next_poll = 0
            next_limit_check = now + 15
        if now >= next_poll:
            previous_desired = desired
            fresh, errors = collect(profiles)
            state["errors"] = errors
            state["last_attempt_at"] = time.time()
            existing = state.get('accounts', {})
            state['accounts'] = {**existing, **{name: record(existing.get(name), value)
                                                for name, value in fresh.items()}}
            if manual > state.get('usage_request_at', 0):
                state['usage_request_at'] = manual
                state['updated_at'] = time.time()
                save(state)
            try:
                desired = choose({name: value["used_percent"] for name, value in fresh.items()},
                                 preferred=state["preferred"])
            except UsageUnavailable:
                desired = None
            try:
                previous = state.setdefault('last_observed_active', state.get('active', runtime.active))
                runtime.observe_account()
                state['last_observed_active'] = runtime.active
                state["account_observed_at"] = time.time()
                state.pop("account_error", None)
                if previous is not None and previous != runtime.active:
                    state["last_external_change"] = {
                        "from": previous, "to": runtime.active,
                        "observed_at": state["account_observed_at"],
                    }
            except Exception as error:
                state["account_error"] = type(error).__name__
            if runtime.active and len(fresh) == 2 and all(v['used_percent'] >= THRESHOLD for v in fresh.values()):
                desired = runtime.active
            if desired != previous_desired:
                retry_switch_at, idle_retry_delay = 0, 2
            next_poll = time.time() + poll_delay(fresh, runtime.active, history=state.get('accounts', {}))
            state["next_check_at"] = next_poll
            runtime.quota_periods = {name: max((window.get('last_reset_confirmed_at', 0)
                                      for window in value.get('windows', {}).values()), default=0)
                                     for name, value in state['accounts'].items()}
            check_limited = True
        state["desired"] = desired
        if (desired is not None and time.time() >= retry_switch_at
                and "account_error" not in state):
            try:
                old = runtime.active
                changed = runtime.select(desired, force=state.get('preference_immediate', False)
                                         and desired == state["preferred"])
                if changed and runtime.active == state['preferred']:
                    state.pop('preference_immediate', None)
                if changed and old != runtime.active:
                    next_poll = time.time() + poll_delay(state['accounts'], runtime.active)
                    state['next_check_at'] = next_poll
                    state['last_observed_active'] = runtime.active
                    state["last_switch_at"] = time.time()
                    state["switch_count"] = state.get("switch_count", 0) + 1
                if (changed and check_limited
                        and state["accounts"][runtime.active]["used_percent"] < THRESHOLD):
                    check_limited = runtime.continue_limited() is False
                state["status"] = "ready" if changed else "waiting_for_idle"
                if changed:
                    retry_switch_at, idle_retry_delay = 0, 2
                else:
                    retry_switch_at = time.time() + idle_retry_delay
                    idle_retry_delay = (2 if runtime.idle_pending is True
                                        else min(idle_retry_delay * 2, 30))
                state.pop("runtime_error", None)
            except Exception as error:
                state["status"] = "degraded"
                state["runtime_error"] = type(error).__name__
                retry_switch_at = time.time() + 60
        elif desired is None or 'account_error' in state:
            state["status"] = "degraded"
        state['active'] = runtime.active
        uncertain = getattr(runtime, 'uncertain_continuations', {})
        if isinstance(uncertain, dict) and uncertain:
            state['uncertain_continuation_count'] = len(uncertain)
        else:
            state.pop('uncertain_continuation_count', None)
        content = {key: value for key, value in state.items() if key != 'updated_at'}
        if content != saved_content or time.time() - saved_at >= 30:
            state['updated_at'] = time.time()
            save(state)
            saved_content, saved_at = content, state['updated_at']
        stop.wait(2)


def run_runtimes(profiles, stop, state):
    while not stop.is_set():
        runtime = Runtime(profiles)
        try:
            runtime.start(restore_account=state.get("restore_account"))
            same_runtime = (runtime.pid, runtime.pid_start) == (state.get("runtime_pid"), state.get("runtime_pid_start"))
            if not same_runtime or state.get("upgrade_status") != "draining":
                state.pop("upgrade_status", None)
                state.pop("upgrade_target", None)
                state.pop("restore_account", None)
            state.update(runtime_pid=runtime.pid, runtime_pid_start=runtime.pid_start,
                         runtime_version=runtime.client.version)
            if not monitor(runtime, profiles, stop, state):
                return
        finally:
            runtime.close()
        state.update(status="starting", active=None, runtime_pid=None, runtime_pid_start=None, updated_at=time.time())
        save(state)


def main():
    prepare_home()
    with (RUNTIME / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for prefix in (f'.{STATE_FILE.name}-', '.continuation-receipts.json-', '.usage-request.json-',
                       '.profile-registration.json-', '.profile-registration-company.json-',
                       '.profile-registration-personal.json-', '.continuation-followups.json-', '.usage-'):
            for orphan in STATE_FILE.parent.glob(prefix + '*'):
                try:
                    if not orphan.is_file() or orphan.is_symlink():
                        continue
                    pid, _, _ = orphan.name[len(prefix):].partition('-')
                    if pid.isdecimal():
                        try:
                            os.kill(int(pid), 0)
                            continue
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            continue
                    elif prefix not in (f'.{STATE_FILE.name}-', '.continuation-receipts.json-') and time.time() - orphan.stat().st_mtime < 86400:
                        continue
                    orphan.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
        state = load()
        if 'active' in state:
            state.setdefault('last_observed_active', state['active'])
        state.update(status="starting", active=None, pid=os.getpid(),
                     pid_start=process_start(os.getpid()), updated_at=time.time())
        save(state)
        stop = threading.Event()
        heartbeat_path = RUNTIME / 'supervisor-heartbeat'
        heartbeat_path.touch(mode=0o600)
        def heartbeat():
            while not stop.wait(25):
                try:
                    heartbeat_path.touch(mode=0o600)
                except OSError:
                    pass
        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        profiles = {}
        try:
            profiles = {name: Profile(name, home) for name, home in PROFILES.items()}
            run_runtimes(profiles, stop, state)
        except Exception as error:
            state.update(status="failed", runtime_error=type(error).__name__, updated_at=time.time())
            save(state)
        finally:
            stop.set()
            pulse.join()
            for profile in profiles.values():
                profile.close()
            if state.get("status") != "failed":
                state.update(status="stopped", updated_at=time.time())
                save(state)


if __name__ == "__main__":
    main()
