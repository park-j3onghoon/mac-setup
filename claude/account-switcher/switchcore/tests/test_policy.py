import unittest

from switchcore.choices import pick
from switchcore.policy import Decision, PriorityPolicy
from switchcore.quota import Usage, Window


NOW = 2_000_000_000.0


def usage(percent=10, *, reset=NOW + 300, checked=NOW, weekly=10):
    return Usage(checked, (Window('five_hour', percent, reset),
                           Window('seven_day', weekly, NOW + 86400)))


def choose(active, readings):
    return PriorityPolicy(95, 60).choose(('personal', 'work'), active, readings, NOW)


class PolicyTests(unittest.TestCase):
    def test_prefers_primary_even_when_fallback_has_more_quota(self):
        """회사 계정에 여유가 더 있어도 개인 계정을 우선한다."""
        # given
        readings = {'personal': usage(90), 'work': usage(1)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result, Decision('personal', 'primary_available'))

    def test_switches_at_exactly_95_percent(self):
        """개인 계정이 95%에 닿으면 회사 계정으로 전환한다."""
        # given
        readings = {'personal': usage(95), 'work': usage(20)}
        # when
        result = choose('personal', readings)
        # then
        self.assertEqual(result.target, 'work')

    def test_keeps_primary_below_threshold(self):
        """94.9%에서는 개인 계정을 계속 사용한다."""
        # given
        readings = {'personal': usage(94.9), 'work': usage(20)}
        # when
        result = choose('personal', readings)
        # then
        self.assertEqual(result.target, 'personal')

    def test_reset_clock_alone_does_not_prove_quota_available(self):
        """초기화 시간이 지났어도 갱신 전 데이터로 복귀하지 않는다."""
        # given
        readings = {'personal': usage(95, reset=NOW - 1), 'work': usage(20)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result.target, 'work')

    def test_returns_after_fresh_reset_reading(self):
        """초기화된 사용량을 새로 확인하면 개인 계정으로 복귀한다."""
        # given
        readings = {'personal': usage(0), 'work': usage(20)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result.target, 'personal')

    def test_weekly_limit_prevents_return(self):
        """5시간 한도가 초기화돼도 주간 한도가 남아 있으면 복귀하지 않는다."""
        # given
        readings = {'personal': usage(0, weekly=99), 'work': usage(20)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result.target, 'work')

    def test_exhausted_accounts_do_not_ping_pong(self):
        """두 계정 모두 한도에 닿으면 계속 교체하지 않는다."""
        # given
        readings = {'personal': usage(100), 'work': usage(100)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result, Decision(None, 'no_verified_capacity'))

    def test_stale_primary_is_not_selected(self):
        """오래된 사용량으로 개인 계정이 비어 있다고 판단하지 않는다."""
        # given
        readings = {'personal': usage(0, checked=NOW - 91), 'work': usage(20)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result.target, 'work')

    def test_unknown_usage_is_not_zero(self):
        """사용률 누락을 0%로 해석하지 않는다."""
        # given
        readings = {'personal': Usage(NOW, (Window('seven_day', None, NOW + 60),)),
                    'work': usage(20)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result.target, 'work')

    def test_failed_primary_read_does_not_switch_back(self):
        """개인 계정 조회 실패 시 회사 계정을 유지한다."""
        # given
        readings = {'work': usage(20)}
        # when
        result = choose('work', readings)
        # then
        self.assertEqual(result.target, 'work')

    def test_poll_interval_follows_headroom(self):
        """기준까지 여유가 클수록 사용량 조회 간격을 늘리고, 기준에 가까우면 가장 짧은 간격으로 조회한다."""
        # given
        cases = ((20, 540), (60, 540), (61, 300), (75, 300), (76, 120), (85, 120), (86, 60), (None, 60))
        for percent, seconds in cases:
            with self.subTest(percent=percent):
                reading = Usage(NOW, (Window('five_hour', percent, None),))
                # when
                result = PriorityPolicy(90, 60).poll_seconds(reading)
                # then
                self.assertEqual(result, seconds)

    def test_poll_interval_without_a_reading_is_the_shortest(self):
        """아직 사용량을 한 번도 읽지 못했으면 가장 짧은 간격으로 다시 본다."""
        # when
        result = PriorityPolicy(90, 60).poll_seconds(None)
        # then
        self.assertEqual(result, 60)

    def test_failed_primary_read_does_not_leave_the_primary(self):
        """개인 계정을 쓰는 중 개인 조회가 실패(HTTP 429)해도 한도 도달로 보지 않고 개인 계정을 유지한다."""
        # given
        readings = {'work': usage(20)}
        # when
        result = choose('personal', readings)
        # then
        self.assertEqual(result.target, 'personal')

    def test_availability_needs_a_fresh_reading_below_the_threshold(self):
        """전환 직전 다시 묻는 판단도 같은 규칙이다: 90초 안에 읽은 사용량이 모든 창에서 기준 미만이어야 한다."""
        # given
        policy = PriorityPolicy(95, 60)
        # when
        results = [policy.available(usage(20), NOW), policy.available(usage(95), NOW),
                   policy.available(usage(20, checked=NOW - 91), NOW)]
        # then
        self.assertEqual(results, [True, False, False])


class ChoicesTests(unittest.TestCase):
    def test_a_setting_names_only_a_built_in_policy(self):
        """설정은 repo 안 규칙의 이름만 고를 수 있고, 모르는 이름은 쓸 수 있는 이름을 알려 주며 거부한다."""
        # when
        chosen = pick('policy', 'priority')
        with self.assertRaises(ValueError) as raised:
            pick('policy', 'my_rules:Custom')
        # then
        self.assertIs(chosen, PriorityPolicy)
        self.assertEqual(str(raised.exception),
                         'Invalid switcher setting: policy=my_rules:Custom '
                         '(choose from: priority, strict-priority)')


if __name__ == '__main__':
    unittest.main()
