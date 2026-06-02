# 변경 설명 문서 양식 (review Step 7 상세)

리뷰 완료 후, **이 PR이 왜 필요하고 어떻게 동작하는지** 설명하는 문서를 생성한다.

## 7a: 엔드유저 시나리오 → 함수 호출 체인

엔드유저(또는 외부 시스템)가 이 코드를 트리거하는 시점부터 최종 결과까지, **함수 호출을 하나하나 빠짐없이** 보여준다. 수정된 함수는 `← 수정` 표시.

```
예시:
1. 캠페인 매니저가 Dash 리포트 페이지를 연다
2. GET /api/ba/ads/{id}/reports
3. ServiceLineitemReportDetail.get()
   → get_full_lineitem_report()
     → get_lineitem_report()
       → StatsProvider.list_unit_creative()
         → statssvc gRPC ListUnitCreatives
           → views.list_unit_creative()  ← 수정
             → DjangoJobRepository.list_unit_creative()
               → _list_unit_creative_query_new2()  ← 수정: Sum(alternative_conversion) 추가
```

## 7b: 파일별 수정 이유

diff의 각 파일에 대해:
1. **상대 경로** (레포 루트 기준, 전체 표기)
2. **이 파일의 역할** 1줄
3. **왜 수정했는가**: 이 변경이 없으면 어떤 문제가 생기는지
4. **구체적 변경 내용**: 어떤 라인에서 무엇을 추가/변경했는지
5. **설계 결정**: 비자명한 결정이 있으면 설명 (default 값, nullable 등)

## 7c: 문서 저장

생성한 문서를 사용자에게 보여주고, 저장 여부를 묻는다.
