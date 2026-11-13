import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import idle_stop

NOW = 1_800_000_000.0
MINUTE = 60


class CheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.pid_file = root / 'ha.pid'
        self.last_used_file = root / 'state/last-used'
        for name, value in (('HOSTAGENT_PID_FILE', self.pid_file), ('LAST_USED_FILE', self.last_used_file)):
            patcher = patch.object(idle_stop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def start_vm(self, minutes_ago):
        self.pid_file.write_text('1')
        started = NOW - minutes_ago * MINUTE
        os.utime(self.pid_file, (started, started))

    def record_last_use(self, minutes_ago):
        self.last_used_file.parent.mkdir(parents=True)
        self.last_used_file.write_text(str(NOW - minutes_ago * MINUTE))

    def run_stop_if_idle(self, running=True, in_use=False):
        with patch.object(idle_stop, 'is_vm_running', return_value=running), \
                patch.object(idle_stop, 'is_in_use', return_value=in_use), \
                patch.object(idle_stop, 'stop_rancher') as stop_rancher:
            idle_stop.stop_if_idle(NOW)
        return stop_rancher

    def test_stops_after_thirty_idle_minutes(self):
        """VM을 켠 지 두 시간이고 마지막 사용 뒤 31분 동안 쓰지 않았으면 Rancher Desktop을 끈다."""
        # given
        self.start_vm(minutes_ago=120)
        self.record_last_use(minutes_ago=31)
        # when
        stop_rancher = self.run_stop_if_idle()
        # then
        stop_rancher.assert_called_once_with()

    def test_keeps_running_within_thirty_idle_minutes(self):
        """마지막 사용 뒤 29분이면 아직 끄지 않는다."""
        # given
        self.start_vm(minutes_ago=120)
        self.record_last_use(minutes_ago=29)
        # when
        stop_rancher = self.run_stop_if_idle()
        # then
        stop_rancher.assert_not_called()

    def test_counts_idle_time_from_start_after_restart(self):
        """두 시간 전 기록이 남아 있어도 VM을 10분 전에 다시 켰으면 켠 시각부터 세어 끄지 않는다."""
        # given
        self.start_vm(minutes_ago=10)
        self.record_last_use(minutes_ago=120)
        # when
        stop_rancher = self.run_stop_if_idle()
        # then
        stop_rancher.assert_not_called()

    def test_records_use_while_in_use(self):
        """컨테이너나 docker 명령이 돌면 지금을 마지막 사용 시각으로 적고 끄지 않는다."""
        # given
        self.start_vm(minutes_ago=120)
        self.record_last_use(minutes_ago=120)
        # when
        stop_rancher = self.run_stop_if_idle(in_use=True)
        # then
        stop_rancher.assert_not_called()
        self.assertEqual(float(self.last_used_file.read_text()), NOW)

    def test_ignores_stopped_vm(self):
        """VM이 꺼져 있으면 기록도 끄기도 하지 않는다."""
        # given
        self.record_last_use(minutes_ago=120)
        # when
        stop_rancher = self.run_stop_if_idle(running=False)
        # then
        stop_rancher.assert_not_called()
        self.assertEqual(float(self.last_used_file.read_text()), NOW - 120 * MINUTE)


if __name__ == '__main__':
    unittest.main()
