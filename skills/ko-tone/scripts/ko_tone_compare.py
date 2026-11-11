#!/usr/bin/env python3
"""원문과 고친 글을 비교해 바뀌면 안 되는 값이 빠졌거나 새로 생겼는지 알려 준다.

동작 원리
1. 두 글에서 '보존 대상'을 같은 순서로 뽑는다. 앞에서 뽑은 것은 본문에서 지워 중복 집계를 막는다.
   코드 블록(```) → 인라인 코드(`...`) → URL → 16진수 주소·해시(0x...) → 숫자
2. 숫자는 쉼표와 %를 떼고 값만 비교한다(1,000 = 1000). 마크다운 번호 목록(1.)과
   번호 붙은 제목(## 1.)의 번호는 글 구조라서 비교하지 않는다.
3. 원문에만 있는 값은 MISSING(사실이 빠졌을 수 있음),
   고친 글에만 있는 값은 ADDED(근거 없이 생겼을 수 있음)로 출력한다.

종료 코드: 0 = 차이 없음, 1 = 확인할 차이 있음, 2 = 사용법 오류.
차이가 의도한 변경(예: 발표 대본에서 1,000,000 → 백만)이면 그대로 두면 된다.
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):  # 아래 타입 표기(tuple[...])가 3.9부터 동작한다
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import re
from pathlib import Path

FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
# \b는 한글도 글자로 보기 때문에 "0x12ab이고"를 놓친다. 그래서 ASCII 기준 앞뒤 조건을 직접 쓴다.
HEX = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{4,}(?![0-9a-fA-F])")
LIST_OR_HEADING_NUMBER = re.compile(r"^\s*(?:#{1,6}\s+)?\d+[.)]\s", re.MULTILINE)
# 앞이 숫자·점·쉼표가 아닌 곳에서 시작하는 숫자. 1,000 / 3.5 / 1.2.3 / 30% 형태를 한 덩어리로 본다.
NUMBER = re.compile(r"(?<![0-9.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![0-9.,])\d+(?:\.\d+)*%?")

CATEGORIES = ("코드 블록", "인라인 코드", "URL", "주소·해시", "숫자")


def extract(text: str) -> dict[str, set[str]]:
    """보존 대상 값을 종류별 집합으로 돌려준다."""
    found: dict[str, set[str]] = {name: set() for name in CATEGORIES}

    def take(pattern: re.Pattern[str], name: str, source: str, group: int = 0) -> str:
        for match in pattern.finditer(source):
            found[name].add(match.group(group).strip())
        return pattern.sub(" ", source)  # 뽑은 부분을 지워 다음 단계에서 다시 세지 않는다

    rest = take(FENCE, "코드 블록", text, 1)
    rest = take(INLINE_CODE, "인라인 코드", rest, 1)
    # URL 끝에 붙은 문장부호는 링크가 아니다
    for match in URL.finditer(rest):
        found["URL"].add(match.group().rstrip(".,;:!?。"))
    rest = URL.sub(" ", rest)
    rest = take(HEX, "주소·해시", rest)
    rest = LIST_OR_HEADING_NUMBER.sub(" ", rest)
    for match in NUMBER.finditer(rest):
        found["숫자"].add(match.group().replace(",", "").rstrip("%"))
    return found


def compare(original: str, revised: str) -> list[tuple[str, str, list[str]]]:
    """(MISSING|ADDED, 종류, 값 목록)을 돌려준다."""
    before, after = extract(original), extract(revised)
    diffs: list[tuple[str, str, list[str]]] = []
    for name in CATEGORIES:
        missing = sorted(before[name] - after[name])
        added = sorted(after[name] - before[name])
        if missing:
            diffs.append(("MISSING", name, missing))
        if added:
            diffs.append(("ADDED", name, added))
    return diffs


def read_text(name: str) -> str:
    return sys.stdin.read() if name == "-" else Path(name).read_text(encoding="utf-8")


def self_test() -> int:
    original = (
        "## 1. 배포 안내\n"
        "1. 수수료가 약 30% 줄었고, 처리량은 1,000건에서 2500건으로 늘었다.\n"
        "컨트랙트 주소는 0xAbC123def456이고 `cast send`로 호출한다.\n"
        "자세한 내용은 https://example.com/docs. 를 보라. 버전은 v1.2.3이다.\n"
        "```bash\nforge test\n```\n"
    )
    same_facts = (
        "## 배포 안내\n"
        "- 수수료는 약 30% 줄었고 처리량은 1000건에서 2500건으로 늘었습니다.\n"
        "`cast send`로 0xAbC123def456 컨트랙트를 호출합니다. 버전은 v1.2.3입니다.\n"
        "자세한 내용: https://example.com/docs\n"
        "```bash\nforge test\n```\n"
    )
    changed = (
        "수수료가 크게 줄었고 처리량은 1000건에서 3000건으로 늘었습니다.\n"
        "`cast send`로 0xAbC123def456 컨트랙트를 호출합니다. 버전은 v1.2.3입니다.\n"
        "```bash\nforge test\n```\n"
    )
    failures = []
    if compare(original, same_facts):
        failures.append(f"오탐: 같은 사실인데 차이 보고 {compare(original, same_facts)}")
    got = {(kind, name, tuple(values)) for kind, name, values in compare(original, changed)}
    want = {
        ("MISSING", "URL", ("https://example.com/docs",)),
        ("MISSING", "숫자", ("2500", "30")),
        ("ADDED", "숫자", ("3000",)),
    }
    if got != want:
        failures.append(f"기대와 다름: {sorted(got)}")
    if failures:
        print("FAIL  ko-tone compare self-test")
        for failure in failures:
            print(f"      {failure}")
        return 1
    print("PASS  ko-tone compare self-test")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="원문과 고친 글의 수치·링크·코드·주소를 비교합니다.")
    parser.add_argument("original", nargs="?", help="원문 UTF-8 파일, 표준 입력은 -")
    parser.add_argument("revised", nargs="?", help="고친 글 UTF-8 파일")
    parser.add_argument("--self-test", action="store_true", help="자체 테스트 실행")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.original or not args.revised:
        parser.print_usage(sys.stderr)
        print("원문 파일과 고친 글 파일을 차례로 주세요.", file=sys.stderr)
        return 2
    diffs = compare(read_text(args.original), read_text(args.revised))
    if not diffs:
        print("PASS  원문의 수치, 링크, 코드, 주소가 고친 글에 모두 그대로 있습니다.")
        return 0
    for kind, name, values in diffs:
        label = "원문에만 있음" if kind == "MISSING" else "고친 글에만 있음"
        print(f"{kind:<8}{name} ({label}): " + ", ".join(values))
    print("\n다음 단계: 각 항목이 의도한 변경인지 확인하세요. 아니면 원문 값으로 되돌리세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
