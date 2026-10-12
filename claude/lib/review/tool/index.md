diff가 아래 도구를 쓰면 그 모듈을 Read해 기준에 더한다.

- Sentry 호출(`sentry_sdk`, `@sentry/`, `Sentry.capture*`)이 있으면 `~/.claude/lib/review/tool/sentry.md`
- `.github/workflows/` 파일이나 `CODEOWNERS`가 있으면 `~/.claude/lib/review/tool/github-actions.md`
- DynamoDB 호출(`dynamodb`, `TransactWriteItems`, `Query`·`Scan` 요청)이 있으면 `~/.claude/lib/review/tool/dynamodb.md`
- Kafka producer·consumer 코드나 설정(`linger.ms`, `group.id`)이 있으면 `~/.claude/lib/review/tool/kafka.md`
- Redis 호출이 있으면 `~/.claude/lib/review/tool/redis.md`
- Kubernetes·Helm 파일(`charts/`, `values*.yaml`, `kind:`가 있는 매니페스트, Istio 설정)이 있으면 `~/.claude/lib/review/tool/kubernetes.md`
- Terraform 파일(`.tf`)이나 Atlantis plan이 있으면 `~/.claude/lib/review/tool/terraform.md`
- Athena·Trino로 실행하는 SQL(dbt 모델, 배치의 쿼리 문자열)이 있으면 `~/.claude/lib/review/tool/athena.md`
