"""Bounded local daily reviews and a final archive. No UI, network, or model calls."""

from datetime import datetime, timezone, timedelta
import time

from measurement import summarize
from storage import SwitcherError, write_json, write_text


DAY = 86400
KST = timezone(timedelta(hours=9))


def stamp(value):
    return datetime.fromtimestamp(value, KST).strftime('%Y-%m-%d %H:%M:%S KST')


def start(state, days=14, now=None):
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise SwitcherError('Monitoring days must be between 1 and 30')
    now = time.time() if now is None else now
    with state.lock('monitoring'):
        existing = state.load('monitoring')
        if existing.get('status') == 'active' and existing['ends_at'] > now:
            return existing
        plan = {'schema': 1, 'status': 'active', 'starts_at': now, 'ends_at': now + days * DAY,
                'days': days, 'review_seconds': DAY, 'next_review_at': now,
                'last_review_at': None, 'last_report': None}
        state.save('monitoring', plan)
    return review_if_due(state, now)


def review_if_due(state, now=None):
    now = time.time() if now is None else now
    with state.lock('monitoring'):
        plan = state.load('monitoring')
        if not plan or plan.get('status') != 'active':
            return plan
        if now < min(plan['next_review_at'], plan['ends_at']):
            return plan
        final = now >= plan['ends_at']
        until = min(now, plan['ends_at'])
        summary = summarize(state, since=plan['starts_at'], until=until)
        summary.pop('latest', None)
        config = state.load('config')
        primary = config.get('primary')
        threshold = config.get('threshold', 90)
        primary_window = next((w for w in summary['windows']
                               if w['account'] == primary and w['window'] == 'five_hour'), None)
        enough_to_compare = bool(primary_window and primary_window['positive_opus55_intervals'])
        finding = ('observed_margin_exceeded' if enough_to_compare
                   and primary_window['max_delta_pp'] >= 100 - threshold else
                   'no_exceedance_observed' if enough_to_compare else 'insufficient_active_primary_data')
        report = {'schema': 1, 'generated_at': now, 'period_start': plan['starts_at'],
                  'period_end': until, 'planned_end': plan['ends_at'], 'final': final,
                  'switch_threshold': threshold, 'margin_pp': 100 - threshold,
                  'finding': finding, 'primary_five_hour': primary_window,
                  'switcher_health': state.load('switcher_health'),
                  'summary': summary,
                  'limitation': 'Observed 45-90s intervals and approximate token pairing; '
                                'no future safety guarantee and no automatic threshold change.'}
        name = datetime.fromtimestamp(plan['starts_at'], timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        root = state.root / 'monitoring'
        if root.is_symlink():
            raise SwitcherError('Monitoring directory must not be a symlink')
        root.mkdir(mode=0o700, exist_ok=True)
        directory = root / name
        if directory.is_symlink():
            raise SwitcherError('Monitoring report directory must not be a symlink')
        directory.mkdir(mode=0o700, exist_ok=True)
        basename = 'final' if final else datetime.fromtimestamp(now, KST).strftime('%Y-%m-%d')
        json_path = directory / f'{basename}.json'
        write_json(json_path, report)
        text_path = directory / f'{basename}.md'
        text = render(report)
        write_text(text_path, text)
        write_json(directory / 'latest.json', report)
        write_text(directory / 'latest.md', text)
        plan.update(last_review_at=now, last_report=str(text_path),
                    next_review_at=min(plan['ends_at'], plan['starts_at'] +
                                       (int((now - plan['starts_at']) // DAY) + 1) * DAY))
        if final:
            plan['status'] = 'complete'
        state.save('monitoring', plan)
        return plan


def render(report):
    finding = {'insufficient_active_primary_data': '개인 계정의 실제 사용 구간이 부족해 여유 한도 판정은 미확인이다.',
               'observed_margin_exceeded': '관측 구간에서 남겨 둔 여유 이상의 사용률 증가가 있었다.',
               'no_exceedance_observed': '관측 구간에서 현재 여유를 넘는 증가는 찾지 못했다. 향후 안전을 보장하지는 않는다.'}[report['finding']]
    s = report['summary']
    lines = ['# Claude 사용률 관측' if not report['final'] else '# Claude 사용률 최종 관측',
             '', finding, '', f"- 관측 범위: {stamp(report['period_start'])} ~ {stamp(report['period_end'])}",
             f"- 예정 종료: {stamp(report['planned_end'])}",
             f"- 생성 시각: {stamp(report['generated_at'])}",
             f"- 전환 설정: {report['switch_threshold']:g}% (여유 {report['margin_pp']:g}%포인트)",
             f"- 수집 스냅샷: {s['samples']}개",
             f"- 자동 전환 상태: {report['switcher_health'].get('state', '미확인')}",
             f"- 조회 실패가 포함된 스냅샷: {s['quality']['failed_samples']}개",
             f"- 사용률이 전부 누락된 스냅샷: {s['quality']['empty_usage_samples']}개",
             f"- 180초 초과 관측 공백: {s['quality']['gaps_over_180_seconds']}개", '', '## 한도별 관측', '']
    for window in s['windows']:
        if window['window'] not in ('five_hour', 'seven_day'):
            continue
        w = window['max_interval']
        lines.append(f"- {window['account']} / {window['window']}: 유효 구간 {window['intervals']}개, "
                     f"토큰 대응 구간 {window['active_token_intervals']}개, "
                     f"Opus 5.5만 관측된 대응 구간 {window['opus55_only_intervals']}개, "
                     f"최대 증가 {window['max_delta_pp']:g}%포인트 / {w['seconds']:.2f}초.")
    lines += ['', '## 해석 범위', '',
              '- 사용률 최대치는 실제 관측 간격 45~90초에서의 증가폭이다. 정확히 연속 60초의 서버 차감 최대치가 아니다.',
              '- 토큰은 입력·출력·캐시 생성·캐시 읽기를 나누어 저장한다. 스트리밍·서버 집계 지연과 다른 기기·웹 사용으로 대응에는 오차가 있다.',
              '- 조회 실패·초기화·계정 전환·긴 관측 공백은 유효한 대응 구간에서 제외한다. 0%포인트 변화가 소모 0을 뜻하지는 않는다.',
              '- 이 보고서는 측정 이력을 검토한다. 자동 계정 교체의 실행 여부는 별도의 버전·인증 검사를 따른다.',
              '- Mac이 꺼져 있거나 잠자기 중인 시간은 측정할 수 없다. 종료 시각에 잠자기 중이면 다음 실행에서 최종 보고서를 만든다.',
              '- 한도를 자동 변경하거나 외부 메시지를 보내지 않는다.', '']
    return '\n'.join(lines)
