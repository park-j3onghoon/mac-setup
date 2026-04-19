# 프론트엔드 공통 코딩 규칙 (React / Vue)

`coding-rules.md` 코어와 함께 적용한다.
Vue + Buzzvil 메인 프로젝트는 `coding-rules-vue.md` 도 함께 읽는다.

---

## 테스트 연동

- **테스트 전용 속성(`data-testid` 등)은 실제 참조하는 테스트와 같은 PR에 묶는다**. 추가만 하고 테스트에서 쿼리하지 않으면 YAGNI 위반. 해당 PR에서 최소 한 곳이라도 `getByTestId` 등으로 사용해 정당화하거나, 추가 자체를 미룬다.
