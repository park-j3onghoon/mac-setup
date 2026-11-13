#!/bin/bash
# /pr-create 5단계가 부른다. PR의 CodeRabbit 리뷰를 부르고 끝날 때까지 5분마다 확인하며 기다린다.
# 상태는 coderabbitai[bot]의 PR 대화 코멘트(요약 코멘트와 답글)와 head 커밋에 단 리뷰로 판정한다.
# 사람이 단 마지막 `@coderabbitai review` 코멘트가 있으면, 그 뒤에 쓰이거나 고쳐진 CodeRabbit 코멘트만 지금 상태로 본다.
# 사용:
#   coderabbit-review.sh <owner/repo> <PR 번호> request
#     상태를 보고 none이면 5분 뒤 한 번 더 본다. 상태가 none·draft_skipped·paused·rate_limited면
#     `@coderabbitai review` 코멘트를 달고 "requested"를, 아니면 지금 상태를 출력한다.
#   coderabbit-review.sh <owner/repo> <PR 번호> wait [<분>]
#     reviewed·rate_limited·skipped 가운데 하나가 되거나 <분>(기본 30)이 지날 때까지 5분마다 다시 보고,
#     마지막 상태를 출력한다. 읽기에 실패한 회차는 건너뛰고 다음 회차에 다시 본다.
#     코멘트를 달지 않으니 끊겼으면 다시 불러도 된다.
# 상태:
#   reviewed <지적 수>  CodeRabbit 코멘트의 coveredCommitId나 coderabbitai[bot] 리뷰가 head 커밋을 가리킨다.
#                       지적 수는 head 커밋 리뷰들의 "Actionable comments posted: N" 합이다(리뷰가 없으면 0).
#   rate_limited <분>   리뷰 한도에 걸렸다. <분>은 "Next included review available in N minutes"의 N이고, 없으면 ?다.
#   skipped            Review skipped가 있다(리뷰할 변경이 없는 PR 등).
#   draft_skipped      Draft라 자동 리뷰를 건너뛰었다("Draft PR not reviewed").
#   paused             이 PR의 자동 리뷰가 멈춰 있다(review paused).
#   in_progress        CodeRabbit 코멘트는 있고 head 커밋은 아직 보지 않았다. 마지막 호출 뒤 CodeRabbit 코멘트가 없을 때도 이 상태다.
#   none               CodeRabbit 코멘트가 없다.
# 시험할 때는 PR_REVIEW_POLL_SECONDS로 확인 간격(초, 기본 300)을 줄인다.
set -uo pipefail

repo=${1:?owner/repo}
num=${2:?PR 번호}
mode=${3:?request 또는 wait}
minutes=${4:-30}
interval=${PR_REVIEW_POLL_SECONDS:-300}

state() {
  local head comments reviews trigger all fresh actionable available
  head=$(gh pr view "$num" -R "$repo" --json headRefOid --jq .headRefOid) || return 1
  [ -n "$head" ] || return 1
  comments=$(gh api "repos/$repo/issues/$num/comments" --paginate | jq -s 'add // []') || return 1
  reviews=$(gh api "repos/$repo/pulls/$num/reviews" --paginate \
    --jq ".[] | select(.user.login == \"coderabbitai[bot]\" and .commit_id == \"$head\") | .body + \"\n\"") || return 1
  trigger=$(jq -r '[.[] | select(.user.login != "coderabbitai[bot]"
      and (.body | test("^\\s*@coderabbitai (full )?review")))] | last | .created_at // ""' <<<"$comments")
  all=$(jq -r '.[] | select(.user.login == "coderabbitai[bot]") | .body' <<<"$comments")
  fresh=$(jq -r --arg t "$trigger" \
    '.[] | select(.user.login == "coderabbitai[bot]" and .updated_at >= $t) | .body' <<<"$comments")
  if grep -qF "\"coveredCommitId\":\"$head\"" <<<"$all" || [ -n "$reviews" ]; then
    actionable=$(grep -o 'Actionable comments posted: [0-9]*' <<<"$reviews" | awk '{s += $4} END {print s + 0}')
    echo "reviewed $actionable"
  elif [ -z "$all" ]; then
    echo none
  elif [ -z "$fresh" ]; then
    echo in_progress
  elif grep -qF 'rate limited by coderabbit.ai' <<<"$fresh"; then
    available=$(grep -o 'available in [0-9]* minute' <<<"$fresh" | head -1 | awk '{print $3}')
    echo "rate_limited ${available:-?}"
  elif grep -qF 'Draft PR not reviewed' <<<"$fresh"; then
    echo draft_skipped
  elif grep -qF 'review paused by coderabbit.ai' <<<"$fresh"; then
    echo paused
  elif grep -qF 'skip review by coderabbit.ai' <<<"$fresh"; then
    echo skipped
  else
    echo in_progress
  fi
}

read_failed() {
  echo "error: $repo#$num 상태를 읽지 못했다(gh 인증·네트워크 확인)" >&2
}

case $mode in
  request)
    s=$(state) || { read_failed; exit 1; }
    if [ "$s" = none ]; then
      sleep "$interval"
      s=$(state) || { read_failed; exit 1; }
    fi
    case $s in
      none | draft_skipped | paused | rate_limited*)
        gh pr comment "$num" -R "$repo" --body "@coderabbitai review" >/dev/null || exit 1
        echo "requested (이전 상태: $s)"
        ;;
      *) echo "$s" ;;
    esac
    ;;
  wait)
    deadline=$(($(date +%s) + minutes * 60))
    s=""
    while :; do
      if next=$(state); then
        s=$next
        case $s in
          reviewed* | rate_limited* | skipped) break ;;
        esac
      else
        read_failed
      fi
      [ $(($(date +%s) + interval)) -le "$deadline" ] || break
      sleep "$interval"
    done
    [ -n "$s" ] || exit 1
    echo "$s"
    ;;
  *)
    echo "모드는 request 또는 wait다: $mode" >&2
    exit 2
    ;;
esac
