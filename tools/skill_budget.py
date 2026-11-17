#!/usr/bin/env python3
"""ko-tone 스킬 문안의 예산과 위생을 검사한다(tests/test_budget.py가 부른다).

1. 글자 상한(파이썬 len): SKILL.md 본문(frontmatter 제외) 6,300자, 4절을 뺀 C 5,500자,
   4·6절을 뺀 핵심 4,800자, patterns.md 6,000자, style-principles.md 6,000자,
   user-rules.md 3,500자, reader-questions.md 2,200자.
2. web3 낱말이 든 줄: 스킬 문안(SKILL.md와 references/*.md) 0줄. 스크립트와 테스트는 세지 않는다.
3. 어절 4-그램 겹침: 스킬 문안 대 저장소의 dev 자료(evals/ko-tone/dev/) 0건.
   마크다운 기호만으로 된 어절은 어절에서 빠진다(표 구분선 등). 봉인 사례는 보지 않는다.
4. 결과 형식(SKILL.md 7절, user-rules.md '알리기')에 따옴표로 묶은 예문이 없다.
5. patterns.md 표의 '고친 예' 칸에 원문 칸에 없는 숫자나 영문 고유명사가 없다.
6. SKILL.md 3절 끝의 종류 목록과 reader-questions.md 표들의 '종류' 칸이 같다.

실행: python3 tools/skill_budget.py   (하나라도 어기면 종료 코드 1)
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills" / "ko-tone"
SKILL = SKILL_DIR / "SKILL.md"
REFS = SKILL_DIR / "references"
DEV = REPO / "evals" / "ko-tone" / "dev"

# rc2에서 '덜 고침'을 막는 문장(1절 둘째 항목, 5절 4번)을, rc3에서 높임 유지와 1:1 메일 문단 유지
# 문장을 더하며 SKILL.md 상한을 올렸다(사람 블라인드 판정 18승 10패 1무 뒤 진 사례에서 나온 문장).
# rc5에서 상황 읽기 단계와 상황별 기본값 표(사용자 요청)를 더하며 다시 올렸다.
LIMITS = {
    "SKILL.md 본문": 8400,
    "SKILL.md C(4절 제외)": 7600,
    "SKILL.md 핵심(4·6절 제외)": 6900,
    "patterns.md": 6000,
    "style-principles.md": 6000,
    "user-rules.md": 3500,
    "reader-questions.md": 2200,
}
WEB3 = re.compile(
    r"블록체인|토큰|지갑|컨트랙트|체인(?![저점])|온체인|오프체인|가스|이더리움|비트코인|코인|에어드롭|스테이킹|메인넷|테스트넷"
    r"|트랜잭션|스왑|민팅|롤업|시드 ?문구|니모닉|슬리피지|디파이|가상자산|암호화폐|웹3"
    r"|(?<![A-Za-z])(?:EIP|ERC|dApp|DApp|NFT|DeFi|DAO|Ethereum|Solidity|[Ww]eb3)(?![A-Za-z])"
    r"|(?<![0-9A-Za-z])0x[0-9a-fA-F]")
QUOTED_EXAMPLE = re.compile(r"\"([^\"\n]+)\"|“([^”\n]+)”|‘([^’\n]+)’|'([^'\n]+)'|「([^」\n]+)」")
TERMS = {"맨 위", "바꾼 점", "덜어낸 것", "확인해 주세요", "이어 읽는 글", "훑어보는 글", "후보", "(후보)", "고친 글"}
SENTENCE_END = re.compile(r"(?:다|요|죠|까|니다|세요|어|야)[.!?]?$|[.!?]$")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def strip_frontmatter(text: str) -> str:
    m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    return text[m.end():] if m else text


def section(text: str, heading_prefix: str) -> str:
    """'## 7.'처럼 시작하는 절의 본문(다음 같은 수준 제목 전까지)."""
    lines = text.splitlines(keepends=True)
    out, inside = [], False
    level = len(heading_prefix) - len(heading_prefix.lstrip("#"))
    for line, in_code in _with_fences(lines):
        is_heading = None if in_code else re.match(r"^(#{1,6}) ", line)
        if inside and is_heading and len(is_heading.group(1)) <= level:
            break
        if not in_code and line.startswith(heading_prefix):
            inside = True
            continue
        if inside:
            out.append(line)
    return "".join(out)


def _with_fences(lines: list) -> list:
    """[(줄, 코드 블록 안인가)] — 코드 블록 안의 '# …'를 제목으로 보지 않으려고."""
    out, fence = [], None
    for line in lines:
        mark = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            out.append((line, True))
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence):
                fence = None
            continue
        if mark:
            fence = mark.group(1)
            out.append((line, True))
            continue
        out.append((line, False))
    return out


def without_sections(body: str, numbers) -> str:
    out, skipping = [], False
    for line, in_code in _with_fences(body.splitlines(keepends=True)):
        if not in_code and re.match(r"^#{1,2} ", line):
            skipping = any(line.startswith(f"## {n}.") for n in numbers)
        if not skipping:
            out.append(line)
    return "".join(out)


def skill_texts() -> dict:
    texts = {"SKILL.md": read(SKILL)}
    for path in sorted(REFS.glob("*.md")):
        texts[f"references/{path.name}"] = read(path)
    return texts


# ── 1. 글자 상한 ─────────────────────────────────────────────────
def sizes() -> dict:
    body = strip_frontmatter(read(SKILL))
    return {
        "SKILL.md 본문": len(body),
        "SKILL.md C(4절 제외)": len(without_sections(body, (4,))),
        "SKILL.md 핵심(4·6절 제외)": len(without_sections(body, (4, 6))),
        "patterns.md": len(read(REFS / "patterns.md")),
        "style-principles.md": len(read(REFS / "style-principles.md")),
        "user-rules.md": len(read(REFS / "user-rules.md")),
        "reader-questions.md": len(read(REFS / "reader-questions.md")),
    }


def check_sizes() -> list:
    problems = []
    if not SKILL.is_file():
        return ["SKILL.md가 없습니다"]
    measured = sizes()
    for name, limit in LIMITS.items():
        if name.endswith(".md") and not (REFS / name).is_file():
            problems.append(f"{name}: 파일이 없습니다")
        elif measured[name] > limit:
            problems.append(f"{name}: {measured[name]:,}자 > 상한 {limit:,}자")
    return problems


# ── 2. web3 낱말 ─────────────────────────────────────────────────
def check_web3() -> list:
    problems = []
    for name, text in skill_texts().items():
        for number, line in enumerate(text.splitlines(), start=1):
            m = WEB3.search(line)
            if m:
                problems.append(f"{name}:{number} '{m.group(0)}': {line.strip()[:60]}")
    return problems


# ── 3. 4-그램 겹침 ──────────────────────────────────────────────
def tokens(text: str) -> list:
    text = re.sub(r"`[^`]*`", " ", text)  # 인라인 코드
    text = re.sub(r"https?://\S+", " ", text)
    out = []
    for word in text.split():
        word = re.sub(r"^[\W_]+|[\W_]+$", "", word)  # 마크다운 기호만으로 된 어절은 여기서 빠진다
        if word:
            out.append(word)
    return out


def grams(words: list, n: int = 4) -> set:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _strings(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def dev_texts() -> dict:
    out = {}
    if not DEV.is_dir():
        return out
    for path in sorted(p for p in DEV.rglob("*") if p.is_file()):
        rel = str(path.relative_to(REPO))
        if path.suffix == ".json":
            try:
                out[rel] = "\n".join(_strings(json.loads(read(path))))
            except json.JSONDecodeError:
                out[rel] = read(path)
        elif path.suffix in (".md", ".txt", ""):
            out[rel] = read(path)
    return out


def overlaps() -> list:
    """[(스킬 파일, 겹친 4-그램, dev 파일)]"""
    dev = {name: grams(tokens(text)) for name, text in dev_texts().items()}
    found = []
    for name, text in skill_texts().items():
        mine = grams(tokens(strip_frontmatter(text) if name == "SKILL.md" else text))
        mine |= grams(tokens(text))  # description도 스킬 문안이다
        for dev_name, theirs in dev.items():
            for gram in sorted(mine & theirs):
                found.append((name, " ".join(gram), dev_name))
    return found


def check_overlap() -> list:
    if not DEV.is_dir():
        return [f"dev 자료 폴더가 없습니다: {DEV.relative_to(REPO)}"]
    return [f"{name}: '{gram}' ({dev})" for name, gram, dev in overlaps()]


# ── 4. 결과 형식에 따옴표 예문이 없다 ────────────────────────────
def quoted_examples(text: str) -> list:
    out = []
    for m in QUOTED_EXAMPLE.finditer(text):
        content = next(g for g in m.groups() if g is not None).strip()
        if content in TERMS:
            continue
        if SENTENCE_END.search(content) or content.count(" ") >= 2:
            out.append(content)
    return out


def check_result_format() -> list:
    problems = []
    seventh = section(strip_frontmatter(read(SKILL)), "## 7.")
    if not seventh.strip():
        problems.append("SKILL.md 7절을 찾지 못했습니다")
    problems += [f"SKILL.md 7절: \"{q}\"" for q in quoted_examples(seventh)]
    user_rules = REFS / "user-rules.md"
    if not user_rules.is_file():
        problems.append("user-rules.md: 파일이 없습니다")
    else:
        notify = section(read(user_rules), "## 알리기")
        if not notify.strip():
            problems.append("user-rules.md: '## 알리기' 절을 찾지 못했습니다")
        problems += [f"user-rules.md 알리기: \"{q}\"" for q in quoted_examples(notify)]
    return problems


# ── 5. patterns.md '고친 예'에 새 숫자·고유명사가 없다 ──────────
def tables(text: str) -> list:
    """[(머리 칸 목록, [행 칸 목록])]"""
    out, current = [], None
    for line in text.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if current is None:
                current = (cells, [])
            elif all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
                continue
            else:
                current[1].append(cells)
        else:
            if current:
                out.append(current)
            current = None
    if current:
        out.append(current)
    return out


def check_patterns_examples() -> list:
    path = REFS / "patterns.md"
    if not path.is_file():
        return ["patterns.md: 파일이 없습니다"]
    problems = []
    for header, rows in tables(read(path)):
        src = next((i for i, h in enumerate(header) if "원문" in h), None)
        fix = next((i for i, h in enumerate(header) if "고친" in h), None)
        if src is None or fix is None:
            continue
        for row in rows:
            if len(row) <= max(src, fix):
                continue
            before, after = row[src], row[fix]
            new_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", after)) - set(re.findall(r"\d+(?:[.,]\d+)*", before))
            new_names = set(re.findall(r"(?<![A-Za-z])[A-Z][A-Za-z0-9]+", after)) - \
                set(re.findall(r"(?<![A-Za-z])[A-Z][A-Za-z0-9]+", before))
            if new_numbers or new_names:
                problems.append(f"'{after[:40]}': 원문 칸에 없는 {', '.join(sorted(new_numbers | new_names))}")
    return problems


# ── 6. SKILL.md 3절 종류 목록 = reader-questions.md '종류' 칸 ────
SKILL_KINDS = re.compile(r"요청이나 제목에 (?P<list>.+?)(?:이|가) 있으면")


def skill_kinds() -> list:
    third = section(strip_frontmatter(read(SKILL)), "## 3.")
    m = SKILL_KINDS.search(third)
    return [k.strip() for k in m["list"].split(",")] if m else []


def reader_kinds() -> list:
    out = []
    for header, rows in tables(read(REFS / "reader-questions.md")):
        col = next((i for i, h in enumerate(header) if h == "종류"), None)
        if col is None:
            continue
        out += [row[col] for row in rows if len(row) > col and row[col]]
    return out


def check_kind_lists() -> list:
    if not (REFS / "reader-questions.md").is_file():
        return ["reader-questions.md: 파일이 없습니다"]
    mine, theirs = skill_kinds(), reader_kinds()
    if not mine:
        return ["SKILL.md 3절 끝에서 '요청이나 제목에 … 있으면' 종류 목록을 찾지 못했습니다"]
    if not theirs:
        return ["reader-questions.md에서 '종류' 칸이 있는 표를 찾지 못했습니다"]
    problems = []
    only_skill = sorted(set(mine) - set(theirs))
    only_ref = sorted(set(theirs) - set(mine))
    if only_skill:
        problems.append("SKILL.md 3절에만 있음: " + ", ".join(only_skill))
    if only_ref:
        problems.append("reader-questions.md 표에만 있음: " + ", ".join(only_ref))
    return problems


CHECKS = (
    ("1. 글자 상한", check_sizes),
    ("2. web3 낱말 줄", check_web3),
    ("3. dev 자료와 4-그램 겹침", check_overlap),
    ("4. 결과 형식의 따옴표 예문", check_result_format),
    ("5. patterns.md 고친 예의 새 값", check_patterns_examples),
    ("6. 종류 목록 일치", check_kind_lists),
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    failed = False
    if SKILL.is_file():
        print("크기: " + ", ".join(f"{k} {v:,}" for k, v in sizes().items()))
    for title, check in CHECKS:
        problems = check()
        failed |= bool(problems)
        print(f"{title}: {'어김 ' + str(len(problems)) + '건' if problems else '지킴'}")
        for problem in problems[:20]:
            print(f"    {problem}")
        if len(problems) > 20:
            print(f"    … 외 {len(problems) - 20}건")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
