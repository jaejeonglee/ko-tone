#!/usr/bin/env python3
"""원문과 고친 글을 한 번에 맞대는 점검 명령(SKILL.md 2절).

    python3 ko_tone_check.py <원문 파일> <고친 글 파일> [--year 2026] [--scope 글 종류]
                             [--json] [--style] [--experimental] [--strict]

기본 출력(항목 이름은 SKILL.md 2절과 같다)
  첫 줄          참고 수치: 길이 비율, 덩어리 수, 원문과 글자까지 같은 줄의 비율(판정 없음)
  [값]           수치(부호·단위), 날짜·요일·시각, 식별자, 링크, 코드, 인용이 빠지거나 생기거나 방향이 바뀐 곳.
                 0x 주소가 있으면 EIP-55 체크섬(ko_tone_facts_web3.py를 이때만 불러온다)
  [환산]         고친 글에만 있는 퍼센트·배수를 원문의 'A에서 B로', 'A → B' 짝으로 다시 계산.
                 원문의 '시각 + 시간대' 값이 사라졌는지
  [원문의 오류]  원문과 고친 글 둘 다에서 날짜와 요일의 짝
  [사용자 규칙]  활성 avoid 규칙에 걸린 곳(ko_tone_rules.py check). 활성 keep 표현은 [값]에서 고칠 것으로 내지 않는다
  --experimental [빈칸] 새로 생긴 '이름표 + 빈칸' 줄, [틀] 'N가지' 예고 + 목록이 원문에서 그대로 남음,
                 [겹침] 같은 인용문의 표기 불일치. 오탐을 재기 전이라 기본 출력에 넣지 않는다
  --style        [표현] ko_tone_lint.py 규칙표
  끝 줄          보지 않은 것

출력은 20줄 이하이고 걸린 곳 앞뒤 20자만 보인다. 넘치면 '… 외 n건(--json으로 전체)'.
걸려도 종료 코드는 0이다(--strict일 때만 1). 사용법·입력 오류는 2.
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import difflib
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_LINES = 20
NOT_SEEN = "보지 않은 것: 관계, 확정·예정 표시, 덜어낸 것이 결과에 적혔는지, 짜임, 말맛. 직접 보세요."
SKIMMED = {"notice", "report", "minutes", "release", "doc", "ui", "reply"}  # 훑어보는 글: [틀]을 보지 않는다
_MODULES: dict = {}


def module(name: str):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


def snippet(text: str, pos: int, length: int, width: int = 20) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    line_end = len(text) if line_end < 0 else line_end
    start, end = max(line_start, pos - width), min(line_end, pos + length + width)
    return ("…" if start > line_start else "") + text[start:end].strip() + ("…" if end < line_end else "")


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ── 참고 수치 ────────────────────────────────────────────────────
def blocks(text: str) -> int:
    return len([b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()])


def stats(original: str, revised: str) -> dict:
    a, b = len(re.sub(r"\s", "", original)), len(re.sub(r"\s", "", revised))
    orig_lines = {line.strip() for line in original.splitlines() if line.strip()}
    rev_lines = [line.strip() for line in revised.splitlines() if line.strip()]
    same = sum(1 for line in rev_lines if line in orig_lines)
    return {"length_original": a, "length_revised": b, "length_ratio": round(b / a, 2) if a else None,
            "blocks_original": blocks(original), "blocks_revised": blocks(revised),
            "same_lines": same, "revised_lines": len(rev_lines)}


def stats_line(s: dict) -> str:
    ratio = f"{s['length_ratio']}배" if s["length_ratio"] is not None else "-"
    return (f"참고: 길이 {ratio}({s['length_original']:,} → {s['length_revised']:,}자), "
            f"덩어리 {s['blocks_original']} → {s['blocks_revised']}, 원문과 같은 줄 {s['same_lines']}/{s['revised_lines']}")


# ── 사용자 규칙 ──────────────────────────────────────────────────
def user_rules(revised: str, scope) -> tuple:
    """([항목], [keep 패턴], 오류 문구)"""
    try:
        rules = module("ko_tone_rules")
        keep = rules.keep_patterns(scope)
        active_avoid = [r for r in rules.all_rules("active", scope) if r["kind"] == "avoid"]
        items = []
        if active_avoid:
            for number, part, rule in rules.check_text(revised, scope):
                items.append({"line": number, "text": part, "rule": rule["id"], "description": rules.describe(rule)})
        return items, keep, None
    except Exception as exc:  # 규칙 파일 문제로 나머지 점검이 멈추지 않게 한다
        return [], [], str(exc)


def kept(value: str, keep: list) -> bool:
    return any(k.search(value) for k in keep)


# ── 실험 항목 ────────────────────────────────────────────────────
PLACEHOLDER = (r"(?:\[(?![ xX]\])[^\]\n]{1,30}\](?!\()|O{3,}|○{2,}|X{3,}|TBD|\{[가-힣][^}\n]{0,20}\}"
               r"|<[가-힣][^>\n]{0,20}>)")
BLANK_LINE = re.compile(r"^\s*(?:[-*+•]\s+|\d{1,3}[.)]\s+)?(?:\*\*)?(?:[^:：\[\]{}<>\n]{1,20}?(?:\*\*)?\s*[:：]\s*"
                        r"(?:\*\*)?\s*)?" + PLACEHOLDER + r"(?:\s*[,/·]\s*" + PLACEHOLDER + r")*\s*(?:\*\*)?\s*$")
PREVIEW = re.compile(r"(?P<n>두|세|네|다섯|여섯|일곱|여덟|아홉|열|\d{1,2})\s?가지")
LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+\S")
KOREAN_COUNT = {"두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
QUOTE = re.compile(r"\"([^\"\n]{8,})\"|“([^”\n]{8,})”|'([^'\n]{8,})'|‘([^’\n]{8,})’")


def new_blanks(original: str, revised: str, scope=None) -> list:
    """원문에 없던 '이름표 + 빈칸' 줄. 화면 문구({변수})는 빈칸이 아니다."""
    before = {line.strip() for line in original.splitlines()}
    out = []
    for number, line in enumerate(revised.splitlines(), start=1):
        if scope == "ui" and re.search(r"\{[^}]+\}", line):
            continue
        if line.strip() and line.strip() not in before and BLANK_LINE.match(line):
            out.append({"line": number, "text": line.strip()[:60]})
    return out


def frames(text: str) -> list:
    """'N가지' 예고 뒤 3줄 안에 목록이 오는 곳. [(줄 번호, 예고 수, 항목 수, 예고 줄)]"""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = PREVIEW.search(line)
        if not m or LIST_ITEM.match(line) or len(line.strip()) - m.end() > 15:
            continue
        start = next((j for j in range(i + 1, min(i + 4, len(lines))) if LIST_ITEM.match(lines[j])), None)
        if start is None:
            continue
        count = 0
        for j in range(start, len(lines)):
            if LIST_ITEM.match(lines[j]):
                count += 1
            elif lines[j].strip() and not lines[j].startswith((" ", "\t")):
                break
        n = KOREAN_COUNT.get(m["n"]) or (int(m["n"]) if m["n"].isdigit() else 0)
        out.append((i + 1, n, count, line.strip()))
    return out


def kept_frames(original: str, revised: str, scope) -> list:
    if scope in SKIMMED:
        return []
    out = []
    before = frames(original)
    for number, n, count, line in frames(revised):
        note = []
        if before:
            note.append("원문의 'N가지' 예고와 목록이 그대로 남았습니다")
        if n and count and n != count:
            note.append(f"예고 {n} ≠ 항목 {count}")
        if note:
            out.append({"line": number, "text": line[:40], "note": ", ".join(note)})
    return out


def quote_mismatches(text: str) -> list:
    quotes = []
    for number, line in enumerate(text.splitlines(), start=1):
        for m in QUOTE.finditer(line):
            content = next(g for g in m.groups() if g).strip()
            if " " in content and re.search(r"(?:다|요|죠|니다|까|음)[.!?]?$", content):
                quotes.append((number, content))
    out = []
    for i, (n1, q1) in enumerate(quotes):
        for n2, q2 in quotes[i + 1:]:
            if n1 == n2 or q1 == q2:
                continue
            ratio = difflib.SequenceMatcher(None, q1, q2).ratio()
            if 0.72 <= ratio < 1:
                out.append({"line": n1, "other_line": n2, "text": f"\"{q1[:24]}\" / {n2}행 \"{q2[:24]}\""})
    return out


# ── 모으기 ───────────────────────────────────────────────────────
def run_checks(original: str, revised: str, year=None, scope=None, style=False, experimental=False) -> dict:
    compare, facts = module("ko_tone_compare"), module("ko_tone_facts")
    rule_items, keep, rule_error = user_rules(revised, scope)
    result = {"stats": stats(original, revised), "values": [], "conversions": [], "source_errors": [],
              "user_rules": rule_items, "not_seen": NOT_SEEN}
    if rule_error:
        result["user_rules_error"] = rule_error

    # [환산]
    conversions = facts.explain_added_values(original, revised)
    explained_shown = {re.sub(r"\s", "", shown) for shown, _, _ in conversions}
    for shown, ok, why in conversions:
        result["conversions"].append({"value": shown, "explained": ok, "note": why})
    for shown in facts.missing_timezones(original, revised):
        result["conversions"].append({"value": shown, "explained": False, "note": "원문의 시간대 값이 고친 글에 없습니다"})

    # [값]
    diff = compare.compare(original, revised)
    for kind, text, values in (("원문에만 있음", original, diff["missing"]), ("고친 글에만 있음", revised, diff["added"])):
        for v in values:
            if v.category == "수치" and re.sub(r"\s", "", v.shown) in explained_shown:
                continue  # [환산]에서 다룬다
            item = {"kind": kind, "category": v.category, "value": v.shown, "line": line_of(text, v.pos),
                    "text": snippet(text, v.pos, len(v.shown))}
            if kind == "원문에만 있음" and kept(v.shown, keep):
                item["keep"] = True  # 고치지 말 표현이 바뀌었다
            result["values"].append(item)
    for before, after, pos_a, pos_b in diff["reversed"]:
        result["values"].append({"kind": "방향이 바뀜", "category": "수치", "value": f"{before} → {after}",
                                 "line": line_of(revised, pos_b), "text": ""})
    for label, text in (("원문", original), ("고친 글", revised)):
        for level, number, note in facts.check_addresses(text):
            address = note.split(":", 1)[0]
            if level == "WARN" and not kept(address, keep):
                result["values"].append({"kind": f"{label} 체크섬", "category": "주소", "value": address,
                                         "line": number, "text": note.split(": ", 1)[1].split(".")[0]})

    # [원문의 오류]
    for label, text in (("원문", original), ("고친 글", revised)):
        for level, number, note in facts.check_dates(text, year):
            if level == "WARN":
                result["source_errors"].append({"where": label, "line": number, "note": note})

    if experimental:
        result["blanks"] = new_blanks(original, revised, scope)
        result["frames"] = kept_frames(original, revised, scope)
        result["overlaps"] = quote_mismatches(revised)
    if style:
        lint = module("ko_tone_lint")
        result["style"] = [{"line": n, "text": part, "note": msg.split(". ")[0].rstrip(".") + ".", "level": level}
                           for n, part, msg, level in lint.find_hints(revised, keep=tuple(keep), scope=scope)]
    return result


def finding_lines(result: dict) -> list:
    lines = []
    for item in result["values"]:
        keep = " (keep 규칙: 고치지 말 표현)" if item.get("keep") else ""
        where = f" ({item['line']}행: {item['text']})" if item.get("text") else ""
        lines.append(f"[값] {item['kind']}  {item['category']} {item['value']}{keep}{where}")
    for item in result["conversions"]:
        lines.append(f"[환산] {'설명됨' if item['explained'] else '설명 안 됨'}  {item['value']}: {item['note']}")
    for item in result["source_errors"]:
        lines.append(f"[원문의 오류] {item['where']} {item['line']}행 {item['note']}")
    if result.get("user_rules_error"):
        lines.append(f"[사용자 규칙] 규칙을 읽지 못했습니다: {result['user_rules_error']}")
    for item in result["user_rules"]:
        lines.append(f"[사용자 규칙] {item['rule']} {item['line']}행: {item['text']} ← {item['description']}")
    for item in result.get("blanks", []):
        lines.append(f"[빈칸] {item['line']}행 새 빈칸 줄: {item['text']}")
    for item in result.get("frames", []):
        lines.append(f"[틀] {item['line']}행 {item['note']}: {item['text']}")
    for item in result.get("overlaps", []):
        lines.append(f"[겹침] {item['line']}행 같은 인용의 표기가 다릅니다: {item['text']}")
    for item in result.get("style", []):
        lines.append(f"[표현] {item['line']}행 {item['text']} — {item['note']}")
    return lines


def has_findings(result: dict) -> bool:
    return bool(result["values"] or any(not c["explained"] for c in result["conversions"]) or result["source_errors"]
                or result["user_rules"] or result.get("blanks") or result.get("frames") or result.get("overlaps")
                or result.get("style"))


def render(result: dict) -> list:
    out = [stats_line(result["stats"])]
    findings = finding_lines(result)
    advice = []
    if result["values"]:
        advice.append("[값]이 일부러 덜어내거나 바꾼 것이면 결과의 '덜어낸 것'이나 '바꾼 점'에 적고, 실수면 되돌리세요.")
    room = MAX_LINES - len(out) - len(advice) - 1
    if not findings:
        out.append("걸린 곳 없음.")
    elif len(findings) <= room:
        out += findings
    else:
        out += findings[:room - 1]
        out.append(f"… 외 {len(findings) - (room - 1)}건(--json으로 전체)")
    out += advice
    out.append(NOT_SEEN)
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="원문과 고친 글을 한 번에 맞댑니다(SKILL.md 2절).")
    parser.add_argument("original", help="원문 UTF-8 파일")
    parser.add_argument("revised", help="고친 글 UTF-8 파일")
    parser.add_argument("--year", type=int, help="연도 없는 날짜의 요일을 이 해로 확인")
    parser.add_argument("--scope", help="글 종류(사용자 규칙 범위, 훑어보는 글이면 [틀]을 보지 않음)")
    parser.add_argument("--json", action="store_true", help="모든 항목을 JSON으로")
    parser.add_argument("--style", action="store_true", help="[표현] ko_tone_lint.py 규칙표도 돌린다")
    parser.add_argument("--experimental", action="store_true", help="[빈칸] [틀] [겹침]도 돌린다(오탐을 재기 전)")
    parser.add_argument("--strict", action="store_true", help="걸린 곳이 있으면 종료 코드 1")
    args = parser.parse_args()
    if args.original == "-" and args.revised == "-":
        print("오류: 표준 입력(-)은 둘 중 하나에만 쓸 수 있습니다.", file=sys.stderr)
        return 2
    compare = module("ko_tone_compare")
    try:
        original, revised = compare.read_text(args.original), compare.read_text(args.revised)
        scope = None
        if args.scope:
            scope = module("ko_tone_rules").normalize_scope(args.scope)
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    result = run_checks(original, revised, args.year, scope, args.style, args.experimental)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for line in render(result):
            print(line)
    return 1 if args.strict and has_findings(result) else 0


if __name__ == "__main__":
    raise SystemExit(main())
