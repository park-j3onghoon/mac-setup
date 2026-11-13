"""Rancher Desktop을 쉬는 동안 끈다. 끄는 조건과 설치 방법은 README.md에 있다."""
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

LABEL = 'local.rancher-idle-stop'
CHECK_INTERVAL_SECONDS = 10 * 60
IDLE_LIMIT_SECONDS = 30 * 60
COMMAND_TIMEOUT_SECONDS = 180
RD_BIN = Path.home() / '.rd/bin'
LIMACTL = Path('/Applications/Rancher Desktop.app/Contents/Resources/resources/darwin/lima/bin/limactl')
LIMA_HOME = Path.home() / 'Library/Application Support/rancher-desktop/lima'
LIMA_ENV = {**os.environ, 'LIMA_HOME': str(LIMA_HOME)}
# hostagent가 VM을 켤 때 쓰는 파일이라 수정 시각이 VM을 켠 시각이다.
HOSTAGENT_PID_FILE = LIMA_HOME / '0/ha.pid'
LAST_USED_FILE = Path.home() / 'Library/Application Support/rancher-idle-stop/last-used'
LOG_FILE = Path.home() / 'Library/Logs/rancher-idle-stop.log'
CLIENT_PROCESS_NAMES = 'docker|docker-compose|rdctl'


def stop_if_idle(now):
    if not is_vm_running():
        return
    if is_in_use():
        LAST_USED_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_USED_FILE.write_text(str(now))
        return
    last_used = float(LAST_USED_FILE.read_text()) if LAST_USED_FILE.exists() else 0
    # 지난번 VM 때 남은 기록이면 이번에 켠 시각부터 센다.
    if now - max(HOSTAGENT_PID_FILE.stat().st_mtime, last_used) >= IDLE_LIMIT_SECONDS:
        stop_rancher()


def is_vm_running():
    result = subprocess.run([LIMACTL, 'list', '--format', '{{.Status}}', '0'], capture_output=True, text=True,
                            env=LIMA_ENV, timeout=COMMAND_TIMEOUT_SECONDS)
    return result.stdout.strip() == 'Running'


def is_in_use():
    if subprocess.run(['/usr/bin/pgrep', '-xq', CLIENT_PROCESS_NAMES]).returncode == 0:
        return True
    # docker 기본 context는 없는 /var/run/docker.sock을 가리켜서 Rancher 소켓을 직접 준다.
    docker_env = {**os.environ, 'DOCKER_HOST': f'unix://{Path.home()}/.rd/docker.sock'}
    containers = subprocess.run([RD_BIN / 'docker', 'ps', '-q'], capture_output=True, text=True,
                                env=docker_env, timeout=COMMAND_TIMEOUT_SECONDS)
    return bool(containers.stdout.strip())


def stop_rancher():
    app = subprocess.run([RD_BIN / 'rdctl', 'list-settings'], capture_output=True,
                         timeout=COMMAND_TIMEOUT_SECONDS)
    # 앱이 죽고 VM만 남으면 rdctl이 앱에 닿지 못해 limactl로 VM만 끈다.
    command = [RD_BIN / 'rdctl', 'shutdown'] if app.returncode == 0 else [LIMACTL, 'stop', '0']
    subprocess.run(command, env=LIMA_ENV, check=True, timeout=COMMAND_TIMEOUT_SECONDS)
    print(time.strftime('%Y-%m-%d %H:%M:%S'), 'stopped idle Rancher Desktop with', command[0].name)


def install_service():
    destination = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'
    destination.write_bytes(plistlib.dumps({
        'Label': LABEL, 'ProgramArguments': [sys.executable, str(Path(__file__).resolve()), 'run'],
        'StartInterval': CHECK_INTERVAL_SECONDS, 'ProcessType': 'Background',
        'StandardOutPath': str(LOG_FILE), 'StandardErrorPath': str(LOG_FILE)}))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['/bin/launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True, timeout=10)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(destination)], check=True, timeout=10)


if __name__ == '__main__':
    {'run': lambda: stop_if_idle(time.time()), 'install': install_service}[sys.argv[1]]()
