#!/usr/bin/env python3
"""Monitor saved plan limits and switch idle automatic Codex sessions."""

from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
import signal
import threading
import time

from policy import THRESHOLD, UsageUnavailable, choose
from profiles import PROFILES, Profile
from runtime import Runtime, prepare_home
from state import RUNTIME, load, poll_delay, record, save


def collect(profiles):
    snapshots, errors = {}, {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(profile.usage) for name, profile in profiles.items()}
        for name, future in futures.items():
            try:
                snapshots[name] = future.result()
            except Exception as error:
                errors[name] = type(error).__name__
    return snapshots, errors


def monitor(runtime, profiles, stop, state):
    next_poll = 0
    retry_switch_at = 0
    desired = None
    check_limited = False
    while not stop.is_set():
        if runtime.process.poll() is not None:
            raise UsageUnavailable("Automatic runtime exited")
        now = time.time()
        if now >= next_poll:
            fresh, errors = collect(profiles)
            state["errors"] = errors
            state["last_attempt_at"] = time.time()
            for name, value in fresh.items():
                state.setdefault("accounts", {})[name] = record(
                    state.get("accounts", {}).get(name), value,
                )
            try:
                desired = choose({name: value["used_percent"] for name, value in fresh.items()})
            except UsageUnavailable:
                desired = None
            next_poll = time.time() + poll_delay(state.get("accounts", {}))
            state["next_check_at"] = next_poll
            check_limited = True
        state["desired"] = desired
        if desired is not None and time.time() >= retry_switch_at:
            try:
                old = runtime.active
                changed = runtime.select(desired)
                if changed and old != runtime.active:
                    state["last_switch_at"] = time.time()
                    state["switch_count"] = state.get("switch_count", 0) + 1
                if (changed and check_limited
                        and state["accounts"][runtime.active]["used_percent"] < THRESHOLD):
                    runtime.continue_limited()
                    check_limited = False
                state["status"] = "ready" if changed else "waiting_for_idle"
                state.pop("runtime_error", None)
            except Exception as error:
                state["status"] = "degraded"
                state["runtime_error"] = type(error).__name__
                retry_switch_at = time.time() + 60
        else:
            state["status"] = "degraded"
        state.update(active=runtime.active, updated_at=time.time())
        save(state)
        stop.wait(2)


def main():
    prepare_home()
    with (RUNTIME / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = load()
        state.update(status="starting", active=None, pid=os.getpid(), updated_at=time.time())
        save(state)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        profiles, runtime = {}, None
        try:
            profiles = {name: Profile(name, home) for name, home in PROFILES.items()}
            if profiles["company"].account_id == profiles["personal"].account_id:
                raise UsageUnavailable("Two distinct workspaces are required")
            runtime = Runtime(profiles)
            runtime.start()
            state["runtime_pid"] = runtime.process.pid
            monitor(runtime, profiles, stop, state)
        except Exception as error:
            state.update(status="failed", runtime_error=type(error).__name__, updated_at=time.time())
            save(state)
        finally:
            if runtime:
                runtime.close()
            for profile in profiles.values():
                profile.close()
            if state.get("status") != "failed":
                state.update(status="stopped", updated_at=time.time())
                save(state)


if __name__ == "__main__":
    main()
