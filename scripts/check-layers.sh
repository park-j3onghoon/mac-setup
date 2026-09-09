#!/usr/bin/env bash
# 층위 규칙 검사: 하위 모듈(SKILL.md 가 아닌 .md)이 스킬을 호출하거나 소비자 목록을 갖지 않는지,
# 상위 스킬이 다른 스킬을 단계로 실행하지 않는지 본다. 위반이 있으면 exit 1.
exec python3 - "$@" <<'PY'
import re, sys
from pathlib import Path

HOME = Path.home()
SKILL_ROOTS = [HOME/"git/mac-setup/claude/skills", HOME/".claude/skills", HOME/"example/.claude/skills"]
LIB_ROOTS   = [HOME/"git/mac-setup/claude/lib", HOME/"example/.claude/lib"]

def frontmatter_name(p):
    try:
        head = p.read_text(encoding="utf-8").split("\n", 12)
    except Exception:
        return None
    for line in head[:12]:
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return None

skills = {}
for root in SKILL_ROOTS:
    for f in root.glob("*/SKILL.md"):
        n = frontmatter_name(f)
        if n:
            skills[n] = f
if not skills:
    print("no skills found"); sys.exit(1)

# 코드 스팬·펜스를 지운 산문만 본다 (경로 인용은 위반이 아니다)
FENCE = re.compile(r"```.*?```", re.S)
SPAN  = re.compile(r"`[^`]*`")
def prose(text):
    return SPAN.sub(" ", FENCE.sub(" ", text))

names = "|".join(sorted(map(re.escape, skills), key=len, reverse=True))
# 슬래시+스킬명. 뒤에 / 나 글자가 오면 경로의 일부이므로 제외한다.
CALL = re.compile(r"(?<![\w/])/(?:%s)(?![\w/.-])" % names)
RUN  = re.compile(r"(실행한다|호출한다|스킬을 실행|을 실행하고|를 실행하고)")

violations = []

def scan(path, is_skill, self_name=None):
    text = path.read_text(encoding="utf-8")
    body = prose(text)
    hits = [(i + 1, ln) for i, ln in enumerate(body.split("\n")) if CALL.search(ln)]
    if is_skill:
        for no, ln in hits:
            called = {m.group(0) for m in CALL.finditer(ln)} - {"/" + self_name}
            if called and RUN.search(ln):
                violations.append(("상위 스킬이 다른 스킬을 단계로 실행", path, no, ln.strip()))
    else:
        for no, ln in hits:
            violations.append(("하위 모듈이 스킬을 호출/언급", path, no, ln.strip()))
        first = text.split("\n", 1)[0]
        if first.startswith("#") and re.search(r"[(（][^)）]*·[^)）]*[)）]", first):
            violations.append(("하위 모듈 제목에 소비자 목록", path, 1, first.strip()))

for root in SKILL_ROOTS:
    for f in root.rglob("*.md"):
        if f.name == "SKILL.md":
            scan(f, True, frontmatter_name(f) or "")
        else:
            scan(f, False)
for root in LIB_ROOTS:
    for f in root.rglob("*.md"):
        scan(f, False)

for kind, path, no, line in violations:
    print(f"LAYER: {kind} — {path}:{no}")
    print(f"    {line[:160]}")

if violations:
    print(f"FAIL: 층위 위반 {len(violations)} 건"); sys.exit(1)
print(f"OK: 스킬 {len(skills)}개, 층위 위반 없음")
PY
