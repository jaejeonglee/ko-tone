#!/usr/bin/env python3
"""사용자 피드백을 규칙으로 쌓고 관리한다.

동작 원리
1. 피드백 한 건은 규칙 하나가 된다. 처음에는 '후보(candidate)'로 저장한다.
2. 같은 피드백이 다시 들어오면 횟수(count)가 오르고, 2회가 되면 '활성(active)'으로 올린다.
   사용자가 바로 적용하자고 하면 --activate로 처음부터 활성으로 저장한다.
3. 스킬은 작업 전에 활성 규칙을 읽어 기본 규칙보다 먼저 적용한다(사실 보존은 예외).
4. check <파일>은 활성 'avoid' 규칙에 걸린 곳을 보여 준다. export / import로 목록을 주고받는다.

저장 위치(스킬 폴더 밖이라 스킬을 업데이트해도 지워지지 않는다)
- 개인 규칙: $KO_TONE_HOME/rules.json
  KO_TONE_HOME이 없으면 Windows는 %APPDATA%\\ko-tone, 그 밖에는 $XDG_CONFIG_HOME/ko-tone 또는 ~/.config/ko-tone
- 팀 규칙: 현재 폴더의 .ko-tone/rules.json (--project). 팀 규칙이 개인 규칙보다 우선한다.
저장 위치가 임시 폴더 아래이거나 쓴 뒤 다시 읽지 못하면 add, list, path가 한 줄로 알린다.

규칙 종류
- avoid: 쓰지 말 표현. --suggest로 대신 쓸 표현을 줄 수 있다. 패턴이 're:'로 시작하면 정규식,
  아니면 글자 그대로 찾되 한글 사이 띄어쓰기는 너그럽게 본다("말씀드리겠습니다"가 "말씀 드리겠습니다"도 잡는다).
- keep:  고치지 말 표현(팀 용어, 슬로건 등).
- style: 자유 서술 규칙(예: "투자자 메일은 합쇼체").

범위(--scope)는 알려진 이름(email, chat, blog, translation, talk, sns, intro, ui, notice, report, minutes,
release, doc, letter, reply), 한국어 이름(메일, 메신저, 공지, 회의록 …), 그 밖의 자유 꼬리표를 받는다.

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
PROMOTE_AT = 2  # 같은 피드백이 이 횟수만큼 쌓이면 활성으로 올린다

# 알려진 범위 이름과 한국어 표시 이름
SCOPE_NAMES = {
    "all": "모든 글", "email": "이메일", "chat": "메신저", "blog": "블로그·회고", "translation": "번역 글",
    "talk": "발표 대본", "sns": "SNS·커뮤니티", "intro": "소개 글", "ui": "화면 문구", "notice": "공지·안내문",
    "report": "보고", "minutes": "회의록", "release": "릴리스 노트", "doc": "개발 문서",
    "letter": "자기소개서·지원서", "reply": "고객 응대",
}
SCOPES = tuple(SCOPE_NAMES)  # 예전 이름. 이제 이 밖의 이름도 자유 꼬리표로 받는다.
SCOPE_SYNONYMS = {
    "전체": "all", "모든 글": "all", "모두": "all",
    "메일": "email", "이메일": "email", "전자 우편": "email",
    "메신저": "chat", "슬랙": "chat", "slack": "chat", "카톡": "chat", "디스코드 대화": "chat",
    "블로그": "blog", "회고": "blog", "블로그·회고": "blog",
    "번역": "translation", "번역 글": "translation",
    "발표": "talk", "발표 대본": "talk",
    "sns": "sns", "커뮤니티": "sns", "sns·커뮤니티": "sns",
    "소개": "intro", "소개 글": "intro", "소개 문단": "intro",
    "화면 문구": "ui", "화면 문구·에러 메시지": "ui", "에러 메시지": "ui",
    "공지": "notice", "안내문": "notice", "공지·안내문": "notice",
    "보고": "report", "보고서": "report",
    "회의록": "minutes",
    "릴리스 노트": "release", "릴리즈 노트": "release",
    "개발 문서": "doc",
    "자기소개서": "letter", "지원서": "letter", "자기소개서·지원서": "letter",
    "고객 응대": "reply", "고객 응대 답변": "reply",
}
TEMP_WARNING = "이 위치는 대화가 끝나면 지워질 수 있습니다. 목록을 프로젝트 지침에 붙여 넣으세요."
EXPORT_HEAD = ("# ko-tone 사용자 규칙\n"
               "아래 규칙은 ko-tone의 기본 규칙보다 먼저 적용한다. 원문의 수치, 날짜, 이름, 코드는 규칙과 상관없이 바꾸지 않는다.")
NOTICES: list = []  # 명령이 끝날 때 한 번씩 보여 줄 알림


def notice(message: str) -> None:
    if message not in NOTICES:
        NOTICES.append(message)


def normalize_scope(name) -> str:
    """알려진 이름·한국어 동의어는 키로, 그 밖은 자유 꼬리표로 둔다."""
    if name is None:
        return "all"
    text = re.sub(r"\s+", " ", str(name)).strip()
    if not text:
        return "all"
    lowered = text.lower()
    if lowered in SCOPE_NAMES:
        return lowered
    if lowered in SCOPE_SYNONYMS:
        return SCOPE_SYNONYMS[lowered]
    if re.search(r"[\[\]\n<>]", text) or len(text) > 30:
        raise ValueError(f"범위 이름으로 쓸 수 없습니다: {text!r} (대괄호·꺾쇠 없이 30자 이내)")
    return text


def scope_label(scope: str) -> str:
    return SCOPE_NAMES.get(scope, scope)


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


def is_temporary(path: Path) -> bool:
    try:
        tmp = Path(tempfile.gettempdir()).resolve()
        target = path.resolve()
    except OSError:
        return False
    return target == tmp or tmp in target.parents


def warn_if_temporary(path: Path) -> None:
    if is_temporary(path):
        notice(TEMP_WARNING)


def load(path: Path) -> dict:
    if not path.is_file():
        return {"schema": 1, "rules": []}
    def broken(reason: str = "") -> ValueError:
        why = f" ({reason})" if reason else ""
        return ValueError(f"규칙 파일이 깨졌습니다: {path}{why}. 파일을 고치거나 다른 이름으로 옮긴 뒤 다시 실행하세요"
                          "(옮기면 빈 규칙으로 시작합니다).")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise broken(getattr(exc, "msg", exc.__class__.__name__)) from None
    if not isinstance(data, dict) or not isinstance(data.get("rules", []), list):
        raise broken()
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
    try:
        if json.loads(path.read_text(encoding="utf-8")) != data:
            notice(TEMP_WARNING)
    except (OSError, ValueError):
        notice(TEMP_WARNING)
    warn_if_temporary(path)


def rule_id(kind: str, pattern: str, scope: str) -> str:
    return hashlib.sha1(f"{kind}\0{pattern.strip()}\0{scope}".encode("utf-8")).hexdigest()[:8]


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def compile_pattern(pattern: str) -> re.Pattern:
    """'re:'로 시작하면 정규식. 아니면 글자 그대로 찾되, 띄어쓰기 차이는 너그럽게 본다
    ('말씀드리겠습니다'가 '말씀 드리겠습니다'도 잡는다. 영문·숫자끼리는 붙인 그대로만)."""
    if pattern.startswith("re:"):
        return re.compile(pattern[3:])
    chars = [ch for ch in re.sub(r"\s+", " ", pattern.strip())]
    parts = []
    for i, ch in enumerate(chars):
        if ch == " ":
            parts.append(r"[ \t]*")
            continue
        parts.append(re.escape(ch))
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if nxt and nxt != " " and not (ch.isascii() and ch.isalnum() and nxt.isascii() and nxt.isalnum()):
            parts.append(r"[ \t]*")
    return re.compile("".join(parts))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


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
def conflicts(kind: str, pattern: str) -> list:
    """avoid와 keep에 같은 표현이 함께 있으면 그 반대쪽 규칙 목록."""
    if kind not in ("avoid", "keep"):
        return []
    other = "keep" if kind == "avoid" else "avoid"
    target = _squash(pattern)
    return [r for r in all_rules("all") if r.get("kind") == other and r.get("status") != "retired"
            and _squash(r.get("pattern", "")) == target]


def add_rule(path: Path, kind: str, pattern: str, scope: str = "all", suggest: str = "", note: str = "",
             example: str = "", activate: bool = False) -> tuple:
    """규칙을 추가하거나 같은 규칙의 횟수를 올린다. (규칙, 일어난 일)을 돌려준다."""
    if kind not in KINDS:
        raise ValueError(f"종류는 {', '.join(KINDS)} 중 하나여야 합니다.")
    scope = normalize_scope(scope)
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


def hit_rule(rid: str, activate: bool = False) -> tuple:
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


def all_rules(status: str = "active", scope=None) -> list:
    """팀 규칙과 개인 규칙을 합친다. 같은 id면 팀 규칙이 이긴다."""
    wanted = normalize_scope(scope) if scope else None
    merged: dict = {}
    for origin, path in (("개인", personal_path()), ("팀", project_path())):
        for rule in load(path)["rules"]:
            if isinstance(rule, dict) and rule.get("id"):
                merged[rule["id"]] = {**rule, "origin": origin}
    out = []
    for rule in merged.values():
        if status != "all" and rule.get("status") != status:
            continue
        if wanted and wanted != "all" and rule.get("scope", "all") not in ("all", wanted):
            continue
        out.append(rule)
    return sorted(out, key=lambda r: (r.get("status") != "active", -int(r.get("count", 1)), r["id"]))


def body_text(rule: dict) -> str:
    kind = rule["kind"]
    if kind == "avoid":
        body = f"'{rule['pattern']}' 쓰지 않기" + (f" → '{rule['suggest']}'" if rule.get("suggest") else "")
    elif kind == "keep":
        body = f"'{rule['pattern']}'은(는) 고치지 않기"
    else:
        body = rule["pattern"]
    return body + (f" ({rule['note']})" if rule.get("note") else "")


def describe(rule: dict) -> str:
    return f"[{scope_label(rule.get('scope', 'all'))}] {body_text(rule)}"


def export_markdown(rules: list, with_meta: bool = False) -> str:
    """SKILL.md 6절 블록과 같은 꼴. with_meta면 후보에 (후보)를, 줄 끝에 id와 횟수를 붙인다."""
    lines = [EXPORT_HEAD]
    for r in rules:
        if r.get("status") not in ("active", "candidate"):
            continue
        line = f"- {describe(r)}"
        if r.get("status") == "candidate":
            line += " (후보)"
        if with_meta:
            line += f" <!-- id:{r['id']} n:{int(r.get('count', 1))} -->"
        lines.append(line)
    if len(lines) == 1:
        lines.append("- (규칙 없음)")
    return "\n".join(lines) + "\n"


# ── 들여오기 ─────────────────────────────────────────────────────
LINE = re.compile(r"^\s*[-*]\s+(?:\[(?P<scope>[^\]]*)\]\s*)?(?P<body>.+?)\s*$")
META = re.compile(r"\s*<!--\s*id:(?P<id>[0-9a-f]{8})(?:\s+n:(?P<n>\d+))?\s*-->\s*$")
AVOID = re.compile(r"^'(?P<p>.+?)'\s*(?:을|를)?\s*쓰지\s*않기"
                   r"(?:\s*\(?\s*(?:→|->)\s*'?(?P<s>[^']*?)'?\s*\)?)?(?:\s+\((?P<n>[^()]*)\))?$")
KEEP = re.compile(r"^'(?P<p>.+?)'\s*(?:은\(는\)|은|는|을|를)?\s*고치지\s*않기(?:\s+\((?P<n>[^()]*)\))?$")


def parse_line(line: str):
    """목록 한 줄 → (규칙 사전, id, 횟수) 또는 None. 형식: '- [범위 이름] 내용 (후보)? <!-- id:… n:… -->?'"""
    m = LINE.match(line)
    if not m:
        return None
    body = m["body"]
    rid, count = None, None
    meta = META.search(body)
    if meta:
        rid, count = meta["id"], int(meta["n"] or 1)
        body = body[:meta.start()].rstrip()
    candidate = False
    if body.endswith("(후보)"):
        candidate, body = True, body[:-len("(후보)")].rstrip()
    if not body or re.fullmatch(r"\(.*없음\)", body) or body.startswith("["):
        return None
    scope = normalize_scope(m["scope"])
    rule = {"scope": scope, "suggest": "", "note": ""}
    avoid, keep = AVOID.match(body), KEEP.match(body)
    if avoid:
        rule.update(kind="avoid", pattern=avoid["p"], suggest=(avoid["s"] or "").strip(), note=avoid["n"] or "")
    elif keep:
        rule.update(kind="keep", pattern=keep["p"], note=keep["n"] or "")
    else:
        rule.update(kind="style", pattern=body)
        tail = re.match(r"^(?P<p>.+?)\s+\((?P<n>[^()]*)\)$", body)
        if tail and rid and rule_id("style", tail["p"], scope) == rid:  # export한 style 규칙의 메모
            rule.update(pattern=tail["p"], note=tail["n"])
    rule["status"] = "candidate" if candidate else "active"
    return rule, rid, count


def import_rules(path: Path, text: str) -> tuple:
    """붙여 넣은 목록을 되읽는다. (결과 줄 목록, 읽지 못한 줄 목록)"""
    data = load(path)
    by_id = {r.get("id"): r for r in data["rules"]}
    today = date.today().isoformat()
    report, skipped = [], []
    for raw in text.splitlines():
        if not re.match(r"^\s*[-*]\s+", raw):
            continue
        try:
            parsed = parse_line(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            if re.search(r"\S", re.sub(r"^\s*[-*]\s+|\(.*없음\)", "", raw)):
                skipped.append(raw.strip())
            continue
        rule, _, count = parsed
        try:
            compile_pattern(rule["pattern"])
        except re.error:
            skipped.append(raw.strip())
            continue
        rid = rule_id(rule["kind"], rule["pattern"], rule["scope"])
        if rid in by_id:
            event = bump(by_id[rid], activate=rule["status"] == "active" and by_id[rid].get("status") == "candidate"
                         and count is None)
            report.append(f"이미 있어 횟수 올림({by_id[rid]['status']}): {rid} {describe(by_id[rid])}"
                          + (" — 활성으로 올림" if event in ("promoted", "activated") else ""))
            continue
        new = {"id": rid, "kind": rule["kind"], "pattern": rule["pattern"].strip(), "suggest": rule["suggest"],
               "scope": rule["scope"], "note": rule["note"], "examples": [], "count": count or 1,
               "status": rule["status"], "created": today, "updated": today}
        data["rules"].append(new)
        by_id[rid] = new
        report.append(f"가져옴({'후보' if new['status'] == 'candidate' else '활성'}): {rid} {describe(new)}")
    if report:
        save(path, data)
    return report, skipped


# ── 점검 ─────────────────────────────────────────────────────────
FENCE_MARK = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
LIST_START = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s")


def visible_lines(text: str) -> list:
    """코드 블록(``` · ~~~ · 들여쓴 코드)과 인라인 코드를 뺀 (줄 번호, 글) 목록. 위치는 원래 줄과 같게 둔다."""
    out, fence, prev_blank, in_list = [], None, True, False
    for number, raw in enumerate(text.splitlines(), start=1):
        mark = FENCE_MARK.match(raw)
        if fence:
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence):
                fence = None
            continue
        if mark:
            fence = mark.group(1)
            continue
        if not raw.strip():
            prev_blank = True
            continue
        if LIST_START.match(raw) and not raw.startswith(("    ", "\t")):
            in_list = True
        elif not raw.startswith((" ", "\t")):
            in_list = False
        if raw.startswith(("    ", "\t")) and prev_blank and not in_list and not LIST_START.match(raw):
            continue  # 들여쓴 코드
        prev_blank = False
        out.append((number, re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), raw)))
    return out


def snippet(line: str, start: int, end: int, width: int = 20) -> str:
    head = "…" if start > width else ""
    tail = "…" if len(line) - end > width else ""
    return head + line[max(0, start - width):end + width].strip() + tail


def check_text(text: str, scope=None) -> list:
    """활성 avoid 규칙에 걸린 곳. [(줄 번호, 앞뒤 20자, 규칙)] — 활성 keep 표현과 겹친 곳은 뺀다."""
    rules = all_rules("active", scope)
    avoid = [(compile_pattern(r["pattern"]), r) for r in rules if r["kind"] == "avoid"]
    keep = [compile_pattern(r["pattern"]) for r in rules if r["kind"] == "keep"]
    found = []
    for number, line in visible_lines(text):
        kept = [m.span() for k in keep for m in k.finditer(line)]
        for pattern, rule in avoid:
            for m in pattern.finditer(line):
                if m.start() == m.end():
                    continue
                if any(s <= m.start() and m.end() <= e for s, e in kept):
                    continue
                found.append((number, snippet(line, m.start(), m.end()), rule))
    return found


def lint_patterns(scope=None) -> list:
    """활성 avoid 규칙 목록(예전 ko_tone_lint.py 연동용). scope를 주면 그 글 종류와 '모든 글' 규칙만."""
    return [(compile_pattern(r["pattern"]), f"사용자 규칙 {r['id']}: {describe(r)}")
            for r in all_rules("active", scope) if r["kind"] == "avoid"]


def keep_patterns(scope=None) -> list:
    """활성 keep 규칙. ko_tone_lint.py는 이 표현에만 걸린 기본 경고를 내지 않는다."""
    return [compile_pattern(r["pattern"]) for r in all_rules("active", scope) if r["kind"] == "keep"]


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
            add_rule(p, "keep", "프론트엔드", scope="블로그", activate=True)
            add_rule(p, "style", "투자자 메일은 합쇼체로 쓴다", scope="메일")
            if [x["kind"] for x in all_rules("active")] != ["avoid", "keep"]:
                failures.append(f"활성 목록 이상: {[x['kind'] for x in all_rules('active')]}")
            if len(all_rules("all", scope="email")) != 2:
                failures.append("범위 필터 이상")
            add_rule(project_path(), "avoid", "re:되었습니다$", note="팀 규칙", activate=True)
            if not any(x["origin"] == "팀" for x in all_rules("active")):
                failures.append("팀 규칙이 합쳐지지 않음")
            if not compile_pattern("말씀드리겠습니다").search("다시 말씀 드리겠습니다"):
                failures.append("띄어쓰기에 너그러운 찾기 실패")
            if [k.pattern for k in keep_patterns("blog")] != [compile_pattern("프론트엔드").pattern] or keep_patterns("email"):
                failures.append("keep 패턴 이상")
            cand, _ = add_rule(p, "avoid", "드리고자 합니다", scope="email")
            if hit_rule(cand["id"])[1] != "promoted":
                failures.append("hit으로 2회가 되면 활성으로 올라야 함")
            set_status(p, r["id"], "retired")
            if any(x["id"] == r["id"] for x in all_rules("active")):
                failures.append("보관한 규칙이 활성 목록에 남음")
            if hit_rule(r["id"])[1] != "count" or locate(r["id"]) != p:
                failures.append("보관한 규칙은 같은 피드백만으로 다시 켜지면 안 됨")
            if normalize_scope("회의록") != "minutes" or normalize_scope("사내 위키") != "사내 위키":
                failures.append("범위 이름 정규화 이상")
            exported = export_markdown(all_rules("all"), with_meta=True)
            with tempfile.TemporaryDirectory() as other:
                os.environ["KO_TONE_HOME"] = other
                _, skipped = import_rules(personal_path(), exported)
                again = export_markdown(all_rules("all"), with_meta=True)
                os.environ["KO_TONE_HOME"] = home
            if skipped or exported != again:
                failures.append(f"export → import 왕복 이상: {skipped}")
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
    NOTICES.clear()
    if failures:
        print("자체 테스트 실패: ko-tone rules")
        for f in failures:
            print(f"      {f}")
        return 1
    print("자체 테스트 통과: ko-tone rules")
    return 0


# ── 명령줄 ───────────────────────────────────────────────────────
def _read(name: str) -> str:
    if name == "-":
        return sys.stdin.read()
    path = Path(name)
    if not path.is_file():
        raise ValueError(f"파일을 찾을 수 없습니다: {name}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"UTF-8로 읽을 수 없습니다: {name} (UTF-8로 저장한 뒤 다시 실행하세요)") from None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="사용자 피드백을 ko-tone 규칙으로 쌓고 관리합니다.")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("add", help="피드백을 규칙으로 저장(같은 규칙이면 횟수 증가)")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("pattern")
    p.add_argument("--suggest", default="")
    p.add_argument("--scope", default="all", help="글 종류: email, chat, notice … 또는 한국어 이름, 자유 꼬리표")
    p.add_argument("--note", default="")
    p.add_argument("--example", default="", help="'원문 => 고친 글' 형태의 예")
    p.add_argument("--activate", action="store_true", help="후보를 거치지 않고 바로 적용")
    p.add_argument("--project", action="store_true", help="팀 규칙(./.ko-tone/rules.json)에 저장")
    p = sub.add_parser("list", help="규칙 보기")
    p.add_argument("--status", default="active", choices=("active", "candidate", "retired", "all"))
    p.add_argument("--scope")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("hit", help="이미 있는 규칙과 같은 피드백을 받았을 때 횟수 올리기")
    p.add_argument("id")
    p.add_argument("--activate", action="store_true")
    for name, helptext in (("activate", "후보를 활성으로"), ("retire", "규칙 보관(적용 중지)"), ("remove", "규칙 삭제")):
        sub.add_parser(name, help=helptext).add_argument("id")
    p = sub.add_parser("export", help="규칙을 붙여 넣기용 목록으로(SKILL.md 6절 형식)")
    p.add_argument("--all", action="store_true", help="후보까지, id와 횟수를 붙여서")
    p = sub.add_parser("import", help="붙여 넣은 목록을 되읽기(파일 또는 -)")
    p.add_argument("file")
    p.add_argument("--project", action="store_true")
    p = sub.add_parser("check", help="활성 avoid 규칙에 걸린 곳 보기")
    p.add_argument("file")
    p.add_argument("--scope")
    p.add_argument("--strict", action="store_true", help="걸린 곳이 있으면 종료 코드 1")
    sub.add_parser("path", help="규칙 파일 위치")
    args = parser.parse_args()
    code = 0
    try:
        if args.self_test:
            return self_test()
        if args.cmd in ("add", "hit"):
            if args.cmd == "add":
                path = project_path() if args.project else personal_path()
                clash = conflicts(args.kind, args.pattern)
                rule, event = add_rule(path, args.kind, args.pattern, args.scope, args.suggest, args.note,
                                       args.example, args.activate)
            else:
                clash = []
                rule, event = hit_rule(args.id, args.activate)
            words = {"added": "후보로 저장", "added-active": "활성 규칙으로 저장",
                     "count": f"같은 피드백 {rule['count']}회째({rule['status']})",
                     "promoted": f"같은 피드백 {rule['count']}회째라 활성 규칙으로 올림",
                     "activated": "요청대로 활성 규칙으로 올림"}
            print(f"{words[event]}: {rule['id']} {describe(rule)}")
            for other in clash:
                print(f"경고: 같은 표현이 {other['kind']} 규칙 {other['id']}에도 있습니다({describe(other)}). "
                      "어느 쪽이 맞는지 사용자에게 물어보세요.")
        elif args.cmd == "list":
            warn_if_temporary(personal_path())
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
            rules = all_rules("all") if args.all else all_rules("active")
            print(export_markdown(rules, with_meta=args.all), end="")
        elif args.cmd == "import":
            path = project_path() if args.project else personal_path()
            report, skipped = import_rules(path, _read(args.file))
            for line in report:
                print(line)
            for line in skipped:
                print(f"읽지 못한 줄: {line}")
            if not report and not skipped:
                print("가져올 규칙 줄이 없습니다. '- [범위 이름] 내용' 꼴의 줄을 주세요.")
        elif args.cmd == "check":
            text = _read(args.file)
            found = check_text(text, args.scope)
            active_avoid = [r for r in all_rules("active", args.scope) if r["kind"] == "avoid"]
            for number, part, rule in found[:20]:
                print(f"사용자 규칙 {rule['id']}  {number}행: {part}  ← {describe(rule)}")
            if len(found) > 20:
                print(f"… 외 {len(found) - 20}건")
            if not active_avoid:
                print("활성 avoid 규칙이 없습니다.")
            elif not found:
                print(f"활성 avoid 규칙 {len(active_avoid)}개에 걸린 곳 없음.")
            code = 1 if args.strict and found else 0
        elif args.cmd == "path":
            warn_if_temporary(personal_path())
            print(f"개인: {personal_path()}\n팀:   {project_path()}")
        else:
            parser.print_help()
            return 2
    except (ValueError, re.error) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"오류: 규칙 파일을 읽거나 쓰지 못했습니다 ({exc.strerror or exc})", file=sys.stderr)
        return 2
    for message in NOTICES:  # JSON 출력을 깨지 않게 --json이면 표준 오류로
        print(message, file=sys.stderr if getattr(args, "json", False) else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
