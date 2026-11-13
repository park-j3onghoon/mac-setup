# cmux notification policy

`notification-filter.py` is registered as a global notification hook in
`~/.config/cmux/cmux.json`. It suppresses completion effects when cmux reports
`agent.pending=true` or `agent.isSubagent=true`, and preserves the final parent
completion and requests that require a human decision.
Final completions keep their banner/history, but do not mark the surface as
requiring input. This prevents a previous completion from showing `Needs input`
while the next request is running.

cmux 0.64.22 does not pass `agent` metadata. For Codex, the hook resolves the
surface's user session by its exact rollout filename and first session metadata,
then scans backwards for the last top-level turn event. It ignores child/fork
metadata and corrupted registry transcript paths. Unknown or active turns stay
silent; terminal events are retried briefly to allow the JSONL append to flush.

The study room also removes cmux targeting variables from its background CLI
environment and opts out of wrapper hooks, so grading is not reported as a
separate terminal conversation.

Reference: https://github.com/manaflow-ai/cmux/blob/main/docs/notifications.md#agent-event-context
