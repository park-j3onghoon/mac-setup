# billingsvc 레포 작업 규칙 (개인)

`~/buzzvil/billingsvc` 작업 시 적용하는 **개인** 규칙. 팀 공유 규칙은 레포 `AGENTS.md` 참조. 상세 도메인 지형도는 메모리 `project_billingsvc_*`.

## 날짜 타입 — 신규 코드 LocalDate 금지, date 사용

레거시 `LocalDate`(`src/billing/domain/values.py`, `str` 하위 클래스)를 **새/수정 코드에서 쓰지 않는다.** stdlib `datetime.date`만 사용하고 `LocalDate(...)`·`LocalDate.parse_date(...)` 등 LocalDate 토큰을 새로 추가하지 않는다. 시그니처도 `date`로 받고 `date`로 흘린다.

레거시 LocalDate 경계는 stdlib로 우회한다:
- 엔티티(`Payout.local_date: LocalDate`) 시드/주입 → `d.isoformat()`(str)을 넘긴다. `date` 직접 주입은 pydantic v1이 `"str type expected"`로 거부한다.
- `LocalDate`(str) → `date` 변환 → `date.fromisoformat(localdate)`.
- UTC 자정 앵커(옛 `LocalDate.to_utc_datetime()` 대체) → `datetime.combine(d, time.min, tzinfo=timezone.utc)`.

레거시 시그니처(generate 경로 `data_at: LocalDate` 등)는 외부 호출자가 아직 LocalDate를 넘기면 시그니처는 두되, 내부에서 즉시 `date`로 변환해 신규 헬퍼(`_active_contracts_qs(data_at: date)`)에 넘긴다. generate까지 한 번에 갈아엎지 않고 점진 분리.

상세 타입 지형도(레이어별 LocalDate vs date 현황, 출처 PR #945): 메모리 `project_billingsvc_localdate_to_date`.
