import unittest

from policy import Decision, Usage, Window, choose_account


NOW = 2_000_000_000.0


def usage(percent=10, *, reset=NOW + 300, checked=NOW, weekly=10):
    return Usage(checked, (Window('five_hour', percent, reset),
                           Window('seven_day', weekly, NOW + 86400)))


class PolicyTests(unittest.TestCase):
    def test_prefers_primary_even_when_fallback_has_more_quota(self):
        """회사 계정에 여유가 더 있어도 개인 계정을 우선한다."""
        # given
        readings = {'personal': usage(90), 'work': usage(1)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result, Decision('personal', 'primary_available'))

    def test_switches_at_exactly_95_percent(self):
        """개인 계정이 95%에 닿으면 회사 계정으로 전환한다."""
        # given
        readings = {'personal': usage(95), 'work': usage(20)}
        # when
        result = choose_account('personal', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'work')

    def test_keeps_primary_below_threshold(self):
        """94.9%에서는 개인 계정을 계속 사용한다."""
        # given
        readings = {'personal': usage(94.9), 'work': usage(20)}
        # when
        result = choose_account('personal', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'personal')

    def test_reset_clock_alone_does_not_prove_quota_available(self):
        """초기화 시간이 지났어도 갱신 전 데이터로 복귀하지 않는다."""
        # given
        readings = {'personal': usage(95, reset=NOW - 1), 'work': usage(20)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'work')

    def test_returns_after_fresh_reset_reading(self):
        """초기화된 사용량을 새로 확인하면 개인 계정으로 복귀한다."""
        # given
        readings = {'personal': usage(0), 'work': usage(20)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'personal')

    def test_weekly_limit_prevents_return(self):
        """5시간 한도가 초기화돼도 주간 한도가 남아 있으면 복귀하지 않는다."""
        # given
        readings = {'personal': usage(0, weekly=99), 'work': usage(20)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'work')

    def test_exhausted_accounts_do_not_ping_pong(self):
        """두 계정 모두 한도에 닿으면 계속 교체하지 않는다."""
        # given
        readings = {'personal': usage(100), 'work': usage(100)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result, Decision(None, 'no_verified_capacity'))

    def test_stale_primary_is_not_selected(self):
        """오래된 사용량으로 개인 계정이 비어 있다고 판단하지 않는다."""
        # given
        readings = {'personal': usage(0, checked=NOW - 91), 'work': usage(20)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'work')

    def test_unknown_usage_is_not_zero(self):
        """사용률 누락을 0%로 해석하지 않는다."""
        # given
        readings = {'personal': Usage(NOW, (Window('seven_day', None, NOW + 60),)),
                    'work': usage(20)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'work')

    def test_failed_primary_read_does_not_switch_back(self):
        """개인 계정 조회 실패 시 회사 계정을 유지한다."""
        # given
        readings = {'work': usage(20)}
        # when
        result = choose_account('work', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'work')

    def test_failed_primary_read_does_not_leave_the_primary(self):
        """개인 계정을 쓰는 중 개인 조회가 실패(HTTP 429)해도 한도 도달로 보지 않고 개인 계정을 유지한다."""
        # given
        readings = {'work': usage(20)}
        # when
        result = choose_account('personal', 'personal', 'work', readings, NOW, 95, 90)
        # then
        self.assertEqual(result.target, 'personal')


if __name__ == '__main__':
    unittest.main()
