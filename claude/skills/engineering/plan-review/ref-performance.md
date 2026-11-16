계획이 Python 코드를 바꾸면 `~/.claude/skills/plan-review/ref-performance-python.md`도 Read해 이 기준에 더한다.

## 쿼리·외부 호출
- 루프 안에서 항목마다 DB를 읽거나 쓰는 곳(N+1 포함)에 측정된 병목이 있을 때 루프 밖 한 번의 조회나 일괄 쓰기로 바꾼다.
- N+1을 막을 때 JPA는 관계를 `JOIN FETCH`나 `@EntityGraph`로 함께 읽는다.
- 항목마다 외부 시스템을 부르면 그 시스템의 일괄 API를 쓰고, 일괄 API가 없고 호출끼리 서로 기다릴 필요가 없으면 동시에 보낸다.
- Kotlin에서 서로 기다릴 필요 없는 호출은 `coroutineScope` 안에서 `async`로 띄우고 `awaitAll()`로 모은다.
- 한 요청 안에서 같은 행을 두 번 이상 읽으면 한 번 읽어 넘긴다.

## 메모리·CPU
- 상수배 최적화(타입 변환·복사 횟수 줄이기)는 측정된 병목에만 한다.
- 행 수 상한이 없는 조회는 한 번에 메모리에 올리는 대신 페이지 단위나 스트리밍으로 읽는다.
- 데이터가 늘수록 커지는 목록 안에서 다른 목록의 원소를 찾을 때는 순회 대신 집합·맵으로 찾는다.

## 캐싱
- 요청마다 다시 읽는 값이 설정·코드 테이블처럼 배포나 관리자 수정 때만 바뀌고 그 읽기에 측정된 병목이 있을 때 캐시한다.
- 캐시를 쓰는 계획이면 어떤 쓰기가 어떤 캐시 키를 지우는지와, 지우기 전까지 옛 값을 허용하는 시간을 계획에 적는다.
- TanStack Query의 queryKey에 배열 값을 넣을 때는 이어 붙인 문자열 대신 배열 그대로 넣는다(`[path, ...primitives, array]`).
- TanStack Query에서 `staleTime`을 둔 쿼리의 `refetchOnMount`는 `true`로 둔다.
- TanStack Query에서 목록을 바꾸는 편집 경로마다(다른 훅, 다른 탭, 외부 경로) 그 목록 쿼리를 invalidate하고, 목록 페이지가 이동의 중심이면 `refetchOnWindowFocus`도 켠다.

## 동시성
- 여러 요청이 같은 행을 동시에 고칠 수 있으면 unique 제약·compare-and-set(버전 컬럼)·멱등 키로 동시 실행을 무해하게 만드는 방법을 적고, 락은 `~/.claude/lib/coding/db.md` Transactions and locks를 따른다.
- JPA에서 낙관적 락은 `@Version` 필드로, 비관적 락은 `@Lock(LockModeType.PESSIMISTIC_WRITE)`로 건다.
- 한 트랜잭션이 여러 행을 잠그면 모든 경로가 같은 순서(예: PK 오름차순)로 잠근다.
- 격리 수준을 바꾸거나 거기에 기대는 계획이면 막으려는 이상 현상(non-repeatable read, phantom read)을 계획에 적는다.
- 동시에 도는 작업(스레드, 코루틴, async 태스크)이 같은 메모리 상태를 고치면 그 상태를 호출 안으로 옮기거나 멱등하게 만드는 방법을 적고, 락(Kotlin `kotlinx.coroutines.sync.Mutex` 포함)은 `~/.claude/lib/coding/db.md` Transactions and locks를 따른다.
- 쓰기 직후 그 결과로 분기하는데 읽기가 복제본·결과적 일관성 저장소·외부 시스템으로 가면, 쓰기 응답값으로 판정하고 뒤따르는 읽기는 확인용으로만 쓴다.
- 쓰기 API가 리소스를 통째로 바꾸는데 호출자가 한 필드만 고치려고 읽고-고치고-쓰면, 소유 서비스에 부분 수정 API(field mask, PATCH)를 둔다.

## 멱등성·중복 제거
- 받는 쪽이 본문 문자열을 그대로 비교해 중복을 거르면, 보내는 쪽은 같은 내용에 늘 같은 문자열을 낸다: 목록은 안정 키로 정렬하고 숫자는 정해진 형식으로 쓰며, 상위 행 순서를 섞어도 같은 문자열이 나오는지 테스트로 고정한다.
