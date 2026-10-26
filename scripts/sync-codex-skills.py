#!/usr/bin/env python3
"""Share repository-managed Claude skills with Codex without copying SKILL.md."""

import argparse
from datetime import datetime
from pathlib import Path
import re


def shared_skills(repo):
    skills = {}
    for pattern in ("claude/skills/*/*/SKILL.md", "private/claude/skills/*/SKILL.md"):
        for manifest in sorted(repo.glob(pattern)):
            skills[manifest.parent.name] = manifest.parent
    if not skills:
        raise ValueError(f"No shared skills found in {repo}")
    return skills


def invocation_policy(metadata, automatic):
    value = "true" if automatic else "false"
    text = metadata.read_text() if metadata.exists() else ""
    policy = re.search(r"^policy:[ \t]*(?:#[^\n]*)?(?:\n|$)", text, re.MULTILINE)
    if policy is None:
        if re.search(r"^policy:", text, re.MULTILINE) or text.lstrip().startswith("{"):
            raise ValueError(f"Use a block-style policy mapping in {metadata}")
        return text.rstrip() + ("\n" if text.strip() else "") + f"policy:\n  allow_implicit_invocation: {value}\n"
    following = re.search(r"^\S", text[policy.end():], re.MULTILINE)
    end = policy.end() + following.start() if following else len(text)
    body = text[policy.end():end]
    setting = re.search(r"^([ \t]+allow_implicit_invocation:[ \t]*)(true|false)([ \t]*(?:#[^\n]*)?)$", body, re.MULTILINE)
    if setting:
        body = body[:setting.start(2)] + value + body[setting.end(2):]
    elif "allow_implicit_invocation" in body:
        raise ValueError(f"Use a boolean allow_implicit_invocation value in {metadata}")
    else:
        body = f"  allow_implicit_invocation: {value}\n" + body
    return text[:policy.end()] + body + text[end:]


def sync(repo, task_home, projects=(), *, dry_run=False, check=False):
    skills = shared_skills(repo)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    changes = 0
    policies = {}
    for source in skills.values():
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", (source / "SKILL.md").read_text(), re.DOTALL)
        if match is None:
            raise ValueError(f"Missing frontmatter in {source / 'SKILL.md'}")
        explicit = bool(re.search(r"^disable-model-invocation:\s*true\s*$", match.group(1), re.MULTILINE))
        metadata = source / "agents/openai.yaml"
        policies[metadata] = invocation_policy(metadata, automatic=not explicit)

    def backup(path, root):
        destination = root / "skill-backups" / stamp / path.parent.name / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        path.rename(destination)
        print(f"BACKUP {path} -> {destination}")

    def link(source, destination, backup_root):
        nonlocal changes
        if destination.is_symlink() and destination.resolve() == source.resolve():
            return
        changes += 1
        print(f"LINK {destination} -> {source}")
        if check or dry_run:
            return
        if destination.exists() or destination.is_symlink():
            backup(destination, backup_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source)

    for name, source in sorted(skills.items()):
        metadata = source / "agents/openai.yaml"
        if metadata in policies and (not metadata.exists() or metadata.read_text() != policies[metadata]):
            changes += 1
            print(f"POLICY {metadata}: match Claude invocation policy")
            if not (check or dry_run):
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_text(policies[metadata])
        link(source, task_home / ".claude/skills" / name, task_home / ".claude")
        link(source, task_home / ".codex/skills" / name, task_home / ".codex")

    # Shared modules keep their ~/.claude paths in both harnesses. Private wins.
    modules = {}
    for directory in (repo / "claude/lib", repo / "private/claude/lib"):
        if directory.is_dir():
            modules.update({p.name: p for p in directory.iterdir() if not p.name.startswith(".")})
    for name, source in sorted(modules.items()):
        link(source, task_home / ".claude/lib" / name, task_home / ".claude")
    link(repo / "codex/AGENTS.md", task_home / ".codex/AGENTS.md", task_home / ".codex")

    # An older project copy otherwise competes with the shared user skill.
    # Keep project-only skills, and move collisions outside discovery roots.
    for project in projects:
        for directory in (project / ".codex/skills", project / ".agents/skills"):
            for name in sorted(skills):
                path = directory / name
                if not (path.exists() or path.is_symlink()):
                    continue
                changes += 1
                print(f"ARCHIVE project skill {path}")
                if not (check or dry_run):
                    backup(path, project / directory.parent.name)

    print(f"{len(skills)} shared skills; {changes} {'pending' if check or dry_run else 'applied'} changes")
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    mode.add_argument("--check", action="store_true", help="Exit 1 if synchronization is needed")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Installation directory")
    parser.add_argument("--project", type=Path, action="append", default=[], help="Back up project copies with shared names")
    args = parser.parse_args()
    changes = sync(
        Path(__file__).resolve().parent.parent,
        args.home.expanduser().resolve(),
        [p.expanduser().resolve() for p in args.project],
        dry_run=args.dry_run,
        check=args.check,
    )
    return int(args.check and changes > 0)


if __name__ == "__main__":
    raise SystemExit(main())
