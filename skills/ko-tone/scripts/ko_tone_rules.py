#!/usr/bin/env python3
"""사용자 피드백을 규칙으로 쌓고 관리한다.

동작 원리
1. 피드백 한 건은 규칙 하나가 된다. 처음에는 '후보(candidate)'로 저장한다.
2. 같은 피드백이 다시 들어오면 횟수(count)가 오르고, 2회가 되면 '활성(active)'으로 올린다.
   사용자가 바로 적용하자고 하면 --activate로 처음부터 활성으로 저장한다.
3. 스킬은 작업 전에 활성 규칙을 읽어 기본 규칙보다 먼저 적용한다(사실 보존은 예외).
4. ko_tone_lint.py는 활성 'avoid' 규칙으로 글을 다시 점검한다.

저장 위치(스킬 폴더 밖이라 스킬을 업데이트해도 지워지지 않는다)
- 개인 규칙: $KO_TONE_HOME/rules.json
  KO_TONE_HOME이 없으면 Windows는 %APPDATA%\\ko-tone, 그 밖에는 $XDG_CONFIG_HOME/ko-tone 또는 ~/.config/ko-tone
- 팀 규칙: 현재 폴더의 .ko-tone/rules.json (--project). 팀 규칙이 개인 규칙보다 우선한다.

규칙 종류
- avoid: 쓰지 말 표현. --suggest로 대신 쓸 표현을 줄 수 있다. 패턴이 're:'로 시작하면 정규식.
- keep:  고치지 말 표현(팀 용어, 관용 표기 등).
- style: 자유 서술 규칙(예: "투자자 메일은 합쇼체").

쓰기는 임시 파일에 쓴 뒤 바꿔치기해서 중간에 끊겨도 파일이 깨지지 않게 하고, 모르는 필드는 지우지 않는다.
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

KINDS = ("avoid", "keep", "style")
SCOPES = ("all", "email", "chat", "blog", "translation", "talk", "sns", "intro", "ui")
SCOPE_NAMES = {"all": "모든 글", "email": "이메일", "chat": "메신저", "blog": "블로그·회고", "translation": "번역 글",
               "talk": "발표 대본", "sns": "SNS", "intro": "소개 문단", "ui": "화면 문구·에러 메시지"}
PROMOTE_AT = 2  # 같은 피드백이 이 횟수만큼 쌓이면 활성으로 올린다


# ── 저장 위치 ─────────────────────────────────────────────────────
def personal_path() -> Path:
    if os.environ.get("KO_TONE_HOME"):
        base = Path(os.environ["KO_TONE_HOME"])
    elif os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "ko-tone"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ko-tone"
    return base / "rules.json"


def project_path() -> Path:
    """팀 규칙 파일. 현재 폴더에서 위로 올라가며 .ko-tone 폴더를 찾고, 없으면 git 저장소 루트,
    그것도 없으면 현재 폴더 아래에 둔다. 그래서 저장소 안 어느 하위 폴더에서 실행해도 같은 파일을 쓴다."""
    here = Path.cwd().resolve()
    personal = personal_path().resolve()
    for marker in (".ko-tone", ".git"):
        for folder in (here, *here.parents):
            candidate = folder / ".ko-tone" / "rules.json"
            if (folder / marker).exists() and candidate.resolve() != personal:  # 개인 규칙 폴더를 팀 규칙으로 착각하지 않게
                return candidate
    return here / ".ko-tone" / "rules.json"


def load(path: Path) -> dict:
    if not path.is_file():
        return {"schema": 1, "rules": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("schema", 1)
    data.setdefault("rules", [])
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rules-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)  # 원자적 바꿔치기


def rule_id(kind: str, pattern: str, scope: str) -> str:
    return hashlib.sha1(f"{kind}\0{pattern.strip()}\0{scope}".encode("utf-8")).hexdigest()[:8]


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """'re:'로 시작하면 정규식, 아니면 글자 그대로 찾는다."""
    return re.compile(pattern[3:]) if pattern.startswith("re:") else re.compile(re.escape(pattern))


def bump(rule: dict, activate: bool = False) -> str:
    """같은 피드백이 다시 들어왔을 때 횟수를 올리고, 조건이 되면 활성으로 올린다.
    - 후보: PROMOTE_AT회가 되면 활성(promoted), 사용자가 바로 적용하자고 하면 활성(activated)
    - 보관(retired): 사용자가 일부러 끈 규칙이므로 횟수만 올리고, 직접 적용하자고 할 때만 다시 켠다"""
    rule["count"] = int(rule.get("count", 1)) + 1
    rule["updated"] = date.today().isoformat()
    if rule.get("status") == "active":
        return "count"
    if activate:
        rule["status"] = "active"
        return "activated"
    if rule.get("status") == "candidate" and rule["count"] >= PROMOTE_AT:
        rule["status"] = "active"
        return "promoted"
    return "count"


def locate(rid: str) -> Path:
    """규칙 id가 들어 있는 파일(팀 규칙 먼저)을 찾는다."""
    for path in (project_path(), personal_path()):
        if any(rule.get("id") == rid for rule in load(path)["rules"]):
            return path
    raise ValueError(f"규칙 {rid}을 찾지 못했습니다. list --status all로 id를 확인하세요.")


# ── 규칙 다루기 ───────────────────────────────────────────────────
def add_rule(path: Path, kind: str, pattern: str, scope: str = "all", suggest: str = "", note: str = "",
             example: str = "", activate: bool = False) -> tuple[dict, str]:
    """규칙을 추가하거나 같은 규칙의 횟수를 올린다. (규칙, 일어난 일)을 돌려준다."""
    if kind not in KINDS:
        raise ValueError(f"종류는 {', '.join(KINDS)} 중 하나여야 합니다.")
    if scope not in SCOPES:
        raise ValueError(f"범위는 {', '.join(SCOPES)} 중 하나여야 합니다.")
    if not pattern.strip():
        raise ValueError("패턴(표현이나 규칙 내용)이 비어 있습니다.")
    compile_pattern(pattern)  # 잘못된 정규식은 저장 전에 거른다
    data = load(path)
    rid = rule_id(kind, pattern, scope)
    today = date.today().isoformat()
    for rule in data["rules"]:
        if rule.get("id") == rid:
            if suggest:
                rule["suggest"] = suggest
            if note:
                rule["note"] = note
            if example and example not in rule.setdefault("examples", []):
                rule["examples"].append(example)
            event = bump(rule, activate)
            save(path, data)
            return rule, event
    rule = {"id": rid, "kind": kind, "pattern": pattern.strip(), "suggest": suggest, "scope": scope, "note": note,
            "examples": [example] if example else [], "count": 1,
            "status": "active" if activate else "candidate", "created": today, "updated": today}
    data["rules"].append(rule)
    save(path, data)
    return rule, "added-active" if activate else "added"


def hit_rule(rid: str, activate: bool = False) -> tuple[dict, str]:
    """이미 있는 규칙과 같은 피드백을 받았을 때 id로 횟수를 올린다."""
    path = locate(rid)
    data = load(path)
    for rule in data["rules"]:
        if rule.get("id") == rid:
            event = bump(rule, activate)
            save(path, data)
            return rule, event
    raise ValueError(f"규칙 {rid}을 찾지 못했습니다.")


def set_status(path: Path, rid: str, status: str) -> dict:
    data = load(path)
    for rule in data["rules"]:
        if rule.get("id") == rid:
            rule["status"] = status
            rule["updated"] = date.today().isoformat()
            save(path, data)
            return rule
    raise ValueError(f"규칙 {rid}을 찾지 못했습니다.")


def remove_rule(path: Path, rid: str) -> dict:
    data = load(path)
    for i, rule in enumerate(data["rules"]):
        if rule.get("id") == rid:
            data["rules"].pop(i)
            save(path, data)
            return rule
    raise ValueError(f"규칙 {rid}을 찾지 못했습니다.")


def all_rules(status: str = "active", scope: str | None = None) -> list[dict]:
    """팀 규칙과 개인 규칙을 합친다. 같은 id면 팀 규칙이 이긴다."""
    merged: dict[str, dict] = {}
    for origin, path in (("개인", personal_path()), ("팀", project_path())):
        for rule in load(path)["rules"]:
            merged[rule["id"]] = {**rule, "origin": origin}
    out = []
    for rule in merged.values():
        if status != "all" and rule.get("status") != status:
            continue
        if scope and rule.get("scope") not in ("all", scope):
            continue
        out.append(rule)
    return sorted(out, key=lambda r: (r.get("status") != "active", -int(r.get("count", 1)), r["id"]))


def describe(rule: dict) -> str:
    scope = SCOPE_NAMES.get(rule.get("scope", "all"), rule.get("scope"))
    kind = rule["kind"]
    if kind == "avoid":
        body = f"'{rule['pattern']}' 쓰지 않기" + (f" → '{rule['suggest']}'" if rule.get("suggest") else "")
    elif kind == "keep":
        body = f"'{rule['pattern']}'은(는) 고치지 않기"
    else:
        body = rule["pattern"]
    extra = f" ({rule['note']})" if rule.get("note") else ""
    return f"[{scope}] {body}{extra}"


def export_markdown(rules: list[dict]) -> str:
    lines = ["# ko-tone 사용자 규칙", "",
             "아래 규칙은 ko-tone의 기본 규칙보다 먼저 적용한다. 원문의 수치, 날짜, 이름, 코드는 규칙과 상관없이 바꾸지 않는다.", ""]
    lines += [f"- {describe(r)}" for r in rules] or ["- (활성 규칙 없음)"]
    return "\n".join(lines) + "\n"


def lint_patterns(scope: str | None = None) -> list[tuple[re.Pattern[str], str]]:
    """ko_tone_lint.py가 쓰는 활성 avoid 규칙 목록. scope를 주면 그 글 종류와 '모든 글' 규칙만."""
    out = []
    for rule in all_rules("active", scope):
        if rule["kind"] != "avoid":
            continue
        out.append((compile_pattern(rule["pattern"]), f"사용자 규칙 {rule['id']}: {describe(rule)}"))
    return out


def keep_patterns(scope: str | None = None) -> list[re.Pattern[str]]:
    """활성 keep 규칙. ko_tone_lint.py는 이 표현에만 걸린 기본 경고를 내지 않는다."""
    return [compile_pattern(rule["pattern"]) for rule in all_rules("active", scope) if rule["kind"] == "keep"]


# ── 자체 테스트 ──────────────────────────────────────────────────
def self_test() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as work:
        old_home, old_cwd = os.environ.get("KO_TONE_HOME"), os.getcwd()
        os.environ["KO_TONE_HOME"] = home
        os.chdir(work)
        try:
            p = personal_path()
            r, ev = add_rule(p, "avoid", "하는 것이 중요합니다", suggest="중요한 이유를 바로 쓰기")
            if ev != "added" or r["status"] != "candidate":
                failures.append("첫 피드백은 후보여야 함")
            r, ev = add_rule(p, "avoid", "하는 것이 중요합니다")
            if ev != "promoted" or r["status"] != "active" or r["count"] != 2:
                failures.append("두 번째 같은 피드백에서 활성으로 올라야 함")
            add_rule(p, "keep", "프론트엔드", scope="blog", activate=True)
            add_rule(p, "style", "투자자 메일은 합쇼체로 쓴다", scope="email")
            if [x["kind"] for x in all_rules("active")] != ["avoid", "keep"]:
                failures.append(f"활성 목록 이상: {[x['kind'] for x in all_rules('active')]}")
            if len(all_rules("all", scope="email")) != 2:  # all 범위 avoid + email 범위 style, blog 범위 keep은 제외
                failures.append("범위 필터 이상")
            add_rule(project_path(), "avoid", "re:되었습니다$", note="팀 규칙", activate=True)
            if not any(x["origin"] == "팀" for x in all_rules("active")):
                failures.append("팀 규칙이 합쳐지지 않음")
            if len(lint_patterns()) != 2 or not lint_patterns()[0][0].search("이건 꼭 하는 것이 중요합니다"):
                failures.append("lint 패턴 이상")
            if [k.pattern for k in keep_patterns("blog")] != ["프론트엔드"] or keep_patterns("email"):
                failures.append("keep 패턴 이상")
            cand, _ = add_rule(p, "avoid", "드리고자 합니다", scope="email")
            if hit_rule(cand["id"])[1] != "promoted":
                failures.append("hit으로 2회가 되면 활성으로 올라야 함")
            set_status(p, r["id"], "retired")
            if any(x["id"] == r["id"] for x in all_rules("active")):
                failures.append("보관한 규칙이 활성 목록에 남음")
            if hit_rule(r["id"])[1] != "count" or locate(r["id"]) != p:
                failures.append("보관한 규칙은 같은 피드백만으로 다시 켜지면 안 됨")
            os.mkdir("sub")
            os.chdir("sub")
            if project_path() != Path(work).resolve() / ".ko-tone" / "rules.json":
                failures.append("하위 폴더에서 팀 규칙 파일을 찾지 못함")
            os.chdir(work)
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw["custom"] = "keep-me"
            p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            add_rule(p, "avoid", "혁신적인")
            if json.loads(p.read_text(encoding="utf-8")).get("custom") != "keep-me":
                failures.append("모르는 필드를 지움")
            if "# ko-tone 사용자 규칙" not in export_markdown(all_rules("active")):
                failures.append("내보내기 이상")
            try:
                add_rule(p, "avoid", "re:(")
                failures.append("잘못된 정규식을 저장함")
            except re.error:
                pass
        finally:
            os.chdir(old_cwd)
            if old_home is None:
                os.environ.pop("KO_TONE_HOME", None)
            else:
                os.environ["KO_TONE_HOME"] = old_home
    if failures:
        print("FAIL  ko-tone rules self-test")
        for f in failures:
            print(f"      {f}")
        return 1
    print("PASS  ko-tone rules self-test")
    return 0


# ── 명령줄 ───────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="사용자 피드백을 ko-tone 규칙으로 쌓고 관리합니다.")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("add", help="피드백을 규칙으로 저장(같은 규칙이면 횟수 증가)")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("pattern")
    p.add_argument("--suggest", default="")
    p.add_argument("--scope", default="all", choices=SCOPES)
    p.add_argument("--note", default="")
    p.add_argument("--example", default="", help="'원문 => 고친 글' 형태의 예")
    p.add_argument("--activate", action="store_true", help="후보를 거치지 않고 바로 적용")
    p.add_argument("--project", action="store_true", help="팀 규칙(./.ko-tone/rules.json)에 저장")
    p = sub.add_parser("list", help="규칙 보기")
    p.add_argument("--status", default="active", choices=("active", "candidate", "retired", "all"))
    p.add_argument("--scope", choices=SCOPES)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("hit", help="이미 있는 규칙과 같은 피드백을 받았을 때 횟수 올리기")
    p.add_argument("id")
    p.add_argument("--activate", action="store_true")
    for name, helptext in (("activate", "후보를 활성으로"), ("retire", "규칙 보관(적용 중지)"), ("remove", "규칙 삭제")):
        sub.add_parser(name, help=helptext).add_argument("id")
    sub.add_parser("export", help="활성 규칙을 붙여 넣기용 마크다운으로")
    sub.add_parser("path", help="규칙 파일 위치")
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        if args.cmd in ("add", "hit"):
            if args.cmd == "add":
                path = project_path() if args.project else personal_path()
                rule, event = add_rule(path, args.kind, args.pattern, args.scope, args.suggest, args.note, args.example,
                                       args.activate)
            else:
                rule, event = hit_rule(args.id, args.activate)
            words = {"added": "후보로 저장", "added-active": "활성 규칙으로 저장",
                     "count": f"같은 피드백 {rule['count']}회째({rule['status']})",
                     "promoted": f"같은 피드백 {rule['count']}회째라 활성 규칙으로 올림",
                     "activated": "요청대로 활성 규칙으로 올림"}
            print(f"{words[event]}: {rule['id']} {describe(rule)}")
        elif args.cmd == "list":
            rules = all_rules(args.status, args.scope)
            if args.json:
                print(json.dumps(rules, ensure_ascii=False, indent=2))
            elif not rules:
                print("규칙 없음")
            else:
                for r in rules:
                    print(f"{r['id']}  {r['status']:<9} {r.get('count', 1)}회  {r['origin']}  {describe(r)}")
        elif args.cmd in ("activate", "retire", "remove"):
            path = locate(args.id)
            if args.cmd == "remove":
                rule = remove_rule(path, args.id)
                print(f"삭제: {rule['id']} {describe(rule)}")
            else:
                rule = set_status(path, args.id, "active" if args.cmd == "activate" else "retired")
                print(f"{'활성' if args.cmd == 'activate' else '보관'}: {rule['id']} {describe(rule)}")
        elif args.cmd == "export":
            print(export_markdown(all_rules("active")), end="")
        elif args.cmd == "path":
            print(f"개인: {personal_path()}\n팀:   {project_path()}")
        else:
            parser.print_help()
            return 2
    except (ValueError, re.error, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
