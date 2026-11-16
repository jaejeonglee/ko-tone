#!/usr/bin/env python3
"""원문과 고친 글을 맞대어 바뀌면 안 되는 값이 빠졌거나 새로 생겼는지 알려 준다(ko_tone_check.py의 [값]).

동작 원리
1. 두 글에서 '값'을 같은 순서로 뽑는다. 앞에서 뽑은 자리는 지워 두 번 세지 않는다.
   코드(``` · ~~~ 블록, 들여쓴 코드, `인라인`) → 링크 → 이메일·@계정·0x 값 → 날짜(+요일) → 시각
   → 전화번호·버전·영문 식별자(EIP-4337, v3.2.0, ethers.js) → 수치(부호·단위 포함) → 따로 쓴 요일
   따옴표 안 인용문(띄어쓰기가 있는 4자 이상)은 따로 뽑는다.
2. 같은 값의 다른 표기는 같게 본다: 05와 5, 0.30과 0.3, 1,000,000명과 100만 명, 오후 2시와 14:00,
   820밀리초와 820ms, 백틱으로 감쌌는지 여부, URL 뒤에 붙은 조사, 연도를 뺀 날짜.
3. 부호(-5%와 +5%)와 단위(820ms와 820초)가 다르면 다른 값이다. 'A에서 B로' 짝의 방향이 뒤집혀도 알린다.
4. 'Web3', 'L2'처럼 낱말 속 숫자 하나는 수치로 세지 않는다. 한글 이름과 관계, 확정·예정 표시는 보지 않는다.

종료 코드: 차이가 있어도 0(--strict일 때만 1), 사용법·입력 오류는 2.
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

NOT_SEEN = "보지 않은 것: 관계, 확정·예정 표시, 한글 이름, 덜어낸 것이 결과에 적혔는지. 직접 보세요."
ADVICE = ("일부러 덜어내거나 바꾼 값이면 결과의 '덜어낸 것'이나 '바꾼 점'에 적었는지 확인하고, "
          "실수면 되돌리세요.")


def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def read_text(name: str) -> str:
    """UTF-8(BOM 허용)로 읽는다. 문제가 있으면 한 줄 안내를 담은 ValueError."""
    if name == "-":
        return sys.stdin.read()
    path = Path(name)
    if not path.is_file():
        raise ValueError(f"파일을 찾을 수 없습니다: {name}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"UTF-8로 읽을 수 없습니다: {name} (UTF-8로 저장한 뒤 다시 실행하세요)") from None


# ── 값 하나 ──────────────────────────────────────────────────────
class Value:
    __slots__ = ("category", "shown", "pos", "keys", "accept", "content")

    def __init__(self, category: str, shown: str, pos: int, keys, accept=None, content: str = ""):
        self.category = category
        self.shown = shown
        self.pos = pos
        self.keys = set(keys)
        self.accept = set(accept) if accept is not None else set(self.keys)
        self.content = content  # 코드·인용의 글자(백틱을 벗긴 값으로 맞출 때 쓴다)

    def as_dict(self, text: str) -> dict:
        return {"category": self.category, "value": self.shown, "line": text.count("\n", 0, self.pos) + 1}


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


# ── 코드 ─────────────────────────────────────────────────────────
FENCE = re.compile(r"^[ \t]{0,3}(?P<mark>`{3,}|~{3,})[^\n]*\n(?P<body>.*?)^[ \t]{0,3}(?P=mark)[ \t]*$",
                   re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
LIST_START = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s")


def code_spans(text: str) -> list:
    """(시작, 끝, 내용 줄 목록) — 펜스 블록과 들여쓴 코드 블록."""
    spans = []
    for m in FENCE.finditer(text):
        spans.append((m.start(), m.end(), [line.strip() for line in m["body"].splitlines() if line.strip()]))
    taken = [(s, e) for s, e, _ in spans]
    pos, prev_blank, in_indent, in_list = 0, True, False, False
    for line in text.splitlines(keepends=True):
        start, end = pos, pos + len(line)
        pos = end
        if any(s <= start < e for s, e in taken):
            prev_blank, in_indent = False, False
            continue
        body = line.rstrip("\n")
        if not body.strip():
            prev_blank = True
            continue
        if LIST_START.match(body) and not body.startswith(("    ", "\t")):
            in_list = True
        elif not body.startswith((" ", "\t")):
            in_list = False
        indented = body.startswith(("    ", "\t"))
        if indented and not in_list and (prev_blank or in_indent) and not LIST_START.match(body):
            spans.append((start, end, [body.strip()]))
            in_indent = True
        else:
            in_indent = False
        prev_blank = False
    return spans


# ── 날짜·시각·요일 ───────────────────────────────────────────────
WD = r"(?:\s*\(\s*(?P<w1>[월화수목금토일])(?:요일)?\s*\)|,?\s+(?P<w2>[월화수목금토일])요일)?"
DATES = [
    re.compile(r"(?<!\d)(?P<y>\d{4})\s*[-./]\s*(?P<m>\d{1,2})\s*[-./]\s*(?P<d>\d{1,2})(?!\d)\.?" + WD),
    re.compile(r"(?:(?P<y>\d{4})년\s*)?(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일" + WD),
    # '11/18'. '3/4분기' 같은 분기 표기는 빼고, 범위는 1~12월, 1~31일만 받는다
    re.compile(r"(?<![\d/.])(?P<m>\d{1,2})/(?P<d>\d{1,2})(?![\d/]|\s*분기)" + WD),
]
YEAR_MONTH = re.compile(r"(?P<y>\d{4})년\s*(?P<m>\d{1,2})월")
TIME_AP = re.compile(r"(?P<ap>오전|오후|낮|밤|저녁|새벽)\s*(?P<h>\d{1,2})시(?:\s*(?P<mi>\d{1,2})분|\s*(?P<half>반))?")
TIME_COLON = re.compile(r"(?<![\d:])(?P<h>\d{1,2}):(?P<mi>\d{2})(?![\d:])")
TIME_BARE = re.compile(r"(?<![\d.,])(?P<h>\d{1,2})시(?:\s*(?P<mi>\d{1,2})분|\s*(?P<half>반))?(?![가-힣])"
                       r"|(?<![\d.,])(?P<h2>\d{1,2})시(?=[에부까쯤경가는도이반,.\s)]|$)")
WEEKDAY_ALONE = re.compile(r"\(\s*(?P<w>[월화수목금토일])(?:요일)?\s*\)|(?<![가-힣])(?P<w2>[월화수목금토일])요일")


def _hm(h: int, mi: int) -> str:
    return f"{h:02d}:{mi:02d}"


# ── 식별자와 수치 ───────────────────────────────────────────────
URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'*+,;=%]+")
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
HANDLE = re.compile(r"(?<![A-Za-z0-9._%+-])@[A-Za-z0-9_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?")
HEX = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{4,}(?![0-9a-fA-F])")
PHONE = re.compile(r"(?<![\d-])(?:\d{2,4}-\d{3,4}-\d{4}|1\d{3}-\d{4})(?![\d-])")
VERSION = re.compile(r"(?<![A-Za-z0-9_.])v?\d+(?:\.\d+){2,}(?:-[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)?(?![A-Za-z0-9_]|\.\d)")
WORD = re.compile(r"(?<![A-Za-z0-9_$])[A-Za-z][A-Za-z0-9_.\-/+#]*")
LIST_NUMBER = re.compile(r"^(\s*(?:#{1,6}\s+)?(?:\*\*|__)?)(\d{1,3})([.)])(?=\s)", re.MULTILINE)
QUOTES = re.compile(r"\"([^\"\n]{4,}?)\"|“([^”\n]{4,}?)”|「([^」\n]{2,}?)」|『([^』\n]{2,}?)』")

HANGUL_UNITS = sorted("""밀리초 마이크로초 시간 개월 퍼센트포인트 퍼센트 달러 유로 엔 위안 원 명 건 개 배 회 번 차 초 분 일 주 년 월
세 살 점 위 등 층 호 장 권 대 곳 쪽 줄 글자 자 단계 가지 종 인분 미터 킬로미터 킬로그램 그램 리터 도 평 박 표 석""".split(),
                      key=len, reverse=True)
ASCII_UNITS = sorted("""%p % ‰ ms sec min hrs hr h s KB MB GB TB PB kB Kbps Mbps Gbps km cm mm m kg mg g mL ml L
K M B k x px pt em rem fps Hz kHz MHz GHz ℃ °C USD KRW EUR JPY""".split(), key=len, reverse=True)
UNIT_CANON = {"밀리초": "ms", "초": "s", "sec": "s", "분": "min", "시간": "h", "hr": "h", "hrs": "h", "퍼센트": "%",
              "퍼센트포인트": "%p", "달러": "USD", "$": "USD", "원": "KRW", "₩": "KRW", "유로": "EUR", "€": "EUR",
              "엔": "JPY", "¥": "JPY", "킬로미터": "km", "킬로그램": "kg", "그램": "g", "미터": "m", "리터": "L",
              "ml": "mL", "°C": "℃", "개월": "개월"}
MAGNITUDE = {"천": 10**3, "만": 10**4, "억": 10**8, "조": 10**12}
NUMBER = re.compile(r"(?P<cur>[$₩€£¥])?(?P<n>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<mag>\s?[천만억조](?![가-힣]))?")
ASCII_UNIT_RE = re.compile(r"(?P<sp>\s?)(?P<u>" + "|".join(re.escape(u) for u in ASCII_UNITS) + r")(?![A-Za-z0-9])")


def _canon_number(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _fmt(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _read_unit(rest: str, pos: int, has_mag: bool) -> tuple:
    """pos 뒤의 단위를 읽는다. (단위, 끝 위치)"""
    m = ASCII_UNIT_RE.match(rest, pos)
    if m and (not m["sp"] or len(m["u"]) >= 2 or m["u"] in "%‰"):
        return m["u"], m.end()
    start = pos
    if has_mag and rest[pos:pos + 1] == " ":
        start = pos + 1
    for unit in HANGUL_UNITS:
        if rest.startswith(unit, start):
            return unit, start + len(unit)
    return "", pos


def _sign_before(rest: str, start: int) -> tuple:
    if start > 0 and rest[start - 1] in "-+−±":
        before = rest[start - 2] if start >= 2 else " "
        if not (before.isalnum() or before in ".,_"):
            sign = rest[start - 1]
            return ("-" if sign in "-−" else "±" if sign == "±" else ""), start - 1
    return "", start


def extract(text: str, include_quotes: bool = True) -> list:
    """글에서 값 목록을 뽑는다."""
    values: list = []
    rest = text.replace("\r\n", "\n")

    # 1. 코드: 블록은 줄마다, 인라인은 통째로. 코드 안 값도 키로 달아 백틱을 벗긴 값과 맞춘다.
    def code_value(content: str, pos: int) -> Value:
        inner = extract(content, include_quotes=False)
        keys = {"K:" + content} | {k for v in inner for k in v.keys}
        return Value("코드", content, pos, keys, accept={"K:" + content}, content=content)

    for start, end, lines in code_spans(rest):
        for line in lines:
            values.append(code_value(line, start))
        rest = _blank(rest, start, end)
    for m in INLINE_CODE.finditer(rest):
        content = m.group(1).strip()
        if content:
            values.append(code_value(content, m.start()))
    rest = INLINE_CODE.sub(lambda m: " " * len(m.group(0)), rest)

    # 인용문은 겹쳐 뽑는다(안의 값도 따로 센다)
    if include_quotes:
        for m in QUOTES.finditer(rest):
            content = re.sub(r"\s+", " ", next(g for g in m.groups() if g)).strip().rstrip(".,!?")
            if " " in content and len(content) >= 4:
                values.append(Value("인용", f"\"{content}\"", m.start(), {"Q:" + content}, content=content))

    # 2. 링크(뒤에 붙은 조사·문장부호는 뗀다)
    for m in URL.finditer(rest):
        url = m.group(0).rstrip(".,;:!?'")
        values.append(Value("링크", url, m.start(), {"U:" + url.rstrip("/")}))
        rest = _blank(rest, m.start(), m.end())

    # 3. 이메일, @계정, 0x 값
    for pattern in (EMAIL, HANDLE, HEX):
        for m in pattern.finditer(rest):
            values.append(Value("식별자", m.group(0), m.start(), {"I:" + m.group(0)}))
            rest = _blank(rest, m.start(), m.end())

    # 4. 날짜(+요일)
    for pattern in DATES:
        for m in pattern.finditer(rest):
            month, day = int(m["m"]), int(m["d"])
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            year = m.groupdict().get("y")
            md = f"{month}-{day}"
            if year:
                keys, accept = {f"D:{year}-{md}", f"D*:{md}"}, {f"D:{year}-{md}", f"D:{md}"}
            else:
                keys, accept = {f"D:{md}"}, {f"D:{md}", f"D*:{md}"}
            date_shown = re.sub(r"\s*\(.*$|,?\s+[월화수목금토일]요일$", "", m.group(0).strip())
            values.append(Value("날짜", date_shown, m.start(), keys, accept))
            w = m["w1"] or m["w2"]
            if w:
                values.append(Value("요일", m.group(0).strip(), m.start(), {f"W:{md}:{w}"}))
            rest = _blank(rest, m.start(), m.end())
    for m in YEAR_MONTH.finditer(rest):
        values.append(Value("날짜", m.group(0), m.start(), {f"YM:{m['y']}-{int(m['m'])}"}))
        rest = _blank(rest, m.start(), m.end())

    # 5. 시각
    for m in TIME_AP.finditer(rest):
        h, mi = int(m["h"]), 30 if m["half"] else int(m["mi"] or 0)
        if m["ap"] in ("오후", "저녁", "밤") and h < 12:
            h += 12
        elif m["ap"] == "낮" and h < 6:
            h += 12
        elif m["ap"] in ("오전", "새벽") and h == 12:
            h = 0
        values.append(Value("시각", m.group(0), m.start(), {"T:" + _hm(h, mi)}))
        rest = _blank(rest, m.start(), m.end())
    for m in TIME_COLON.finditer(rest):
        h, mi = int(m["h"]), int(m["mi"])
        if h <= 24 and mi < 60:
            values.append(Value("시각", m.group(0), m.start(), {"T:" + _hm(h, mi)}))
            rest = _blank(rest, m.start(), m.end())
    for m in TIME_BARE.finditer(rest):
        h = int(m["h"] or m["h2"])
        mi = 30 if m["half"] else int(m["mi"] or 0)
        if h > 24:
            continue
        keys = {"T:" + _hm(h, mi)} | ({"T:" + _hm(h + 12, mi)} if h < 12 else set())
        values.append(Value("시각", m.group(0), m.start(), keys))
        rest = _blank(rest, m.start(), m.end())

    # 6. 전화번호, 버전, 영문 식별자
    for pattern in (PHONE, VERSION):
        for m in pattern.finditer(rest):
            values.append(Value("식별자", m.group(0), m.start(), {"I:" + m.group(0).lstrip("v")}))
            rest = _blank(rest, m.start(), m.end())
    for m in WORD.finditer(rest):
        token = m.group(0).rstrip("._-/+")
        if not token:
            continue
        digits = sum(ch.isdigit() for ch in token)
        has_sep = bool(re.search(r"[A-Za-z0-9][-_./][A-Za-z0-9]", token))
        if digits:
            if has_sep or digits >= 2:
                values.append(Value("식별자", token, m.start(), {"I:" + token}))
            # 'Web3', 'L2'처럼 낱말 속 숫자 하나는 수치로 세지 않는다
        elif has_sep and len(token) >= 4:
            values.append(Value("식별자", token, m.start(), {"I:" + token}))
        elif len(token) >= 2 and any(ch.isupper() for ch in token):
            values.append(Value("영문", token, m.start(), {"E:" + token}))
        rest = _blank(rest, m.start(), m.start() + len(m.group(0)))

    # 7. 수치(부호, 단위, 만·억 단위 포함). 목록 번호와 번호 붙은 제목의 번호는 글 구조라서 뺀다.
    rest = LIST_NUMBER.sub(lambda m: m.group(1) + " " * (len(m.group(2)) + 1), rest)
    found = []
    for m in NUMBER.finditer(rest):
        start = m.start()
        if start > 0 and (rest[start - 1].isalnum() and rest[start - 1].isascii() or rest[start - 1] in ".,_"):
            continue
        try:
            value = _canon_number(m["n"])
        except InvalidOperation:
            continue
        mag = (m["mag"] or "").strip()
        if mag:
            value *= MAGNITUDE[mag]
        unit, end = _read_unit(rest, m.end(), bool(mag))
        sign, start = _sign_before(rest, start)
        if m["cur"]:
            unit = m["cur"]
        found.append([start, end, sign, value, unit, bool(mag), mag])
    # '1억 2,345만 6,789명'처럼 이어진 큰 수를 하나로 합친다
    merged = []
    for item in found:
        if merged:
            prev = merged[-1]
            gap = rest[prev[1]:item[0]]
            if prev[5] and not prev[4] and gap.strip() == "" and len(gap) <= 1 and \
                    (not item[6] or MAGNITUDE[item[6]] < MAGNITUDE[prev[6]]):
                prev[1], prev[3], prev[4] = item[1], prev[3] + item[3], item[4]
                prev[5], prev[6] = bool(item[6]), item[6] or prev[6]
                continue
        merged.append(item)
    for start, end, sign, value, unit, _, _ in merged:
        canon = UNIT_CANON.get(unit, unit)
        key = f"N:{sign}{_fmt(value)}{canon}"
        values.append(Value("수치", text[start:end].strip() if text[start:end].strip() else f"{sign}{value}{unit}",
                            start, {key}))
        rest = _blank(rest, start, end)

    # 8. 날짜에 붙지 않은 요일
    for m in WEEKDAY_ALONE.finditer(rest):
        w = m["w"] or m["w2"]
        values.append(Value("요일", m.group(0), m.start(), {"W:" + w}))
    return values


# ── 방향이 뒤집힌 'A에서 B로' ─────────────────────────────────────
_NUM = r"[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+−]?\d+(?:\.\d+)?"
PAIR = re.compile(rf"(?P<a>{_NUM})(?P<ua>[^\s\d,]{{0,3}}?)\s*(?:에서|→|->|=>|⇒)\s*(?P<b>{_NUM})(?P<ub>[^\s\d,]{{0,3}}?)"
                  r"(?:으로|로|까지)?(?=\s|[,.)]|$)")


def pairs(text: str) -> list:
    out = []
    for m in PAIR.finditer(text):
        a, b = m["a"].replace(",", ""), m["b"].replace(",", "")
        try:
            out.append((m.group(0).strip(), _fmt(Decimal(a)) + m["ua"], _fmt(Decimal(b)) + m["ub"], m.start()))
        except InvalidOperation:
            continue
    return out


# ── 비교 ─────────────────────────────────────────────────────────
def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("`", ""))


def compare(original: str, revised: str) -> dict:
    """{'missing': [Value], 'added': [Value], 'reversed': [(원문 표기, 고친 글 표기, 원문 위치, 고친 글 위치)]}"""
    before, after = extract(original), extract(revised)
    keys_before = {k for v in before for k in v.keys}
    keys_after = {k for v in after for k in v.keys}
    plain_before, plain_after = _squash(original), _squash(revised)
    code_before = [v.content for v in before if v.category == "코드"]
    code_after = [v.content for v in after if v.category == "코드"]

    def leftovers(values, other_keys, other_plain, other_code):
        out, seen = [], set()
        for v in values:
            if v.accept & other_keys:
                continue
            if v.content and _squash(v.content) in other_plain:  # 백틱·따옴표만 바뀐 것
                continue
            if v.category != "코드" and any(v.shown in code for code in other_code):  # 상대 글에서는 코드 안에 있다
                continue
            primary = sorted(v.keys)[0]
            if primary in seen:
                continue
            seen.add(primary)
            out.append(v)
        return out

    missing = leftovers(before, keys_after, plain_after, code_after)
    added = leftovers(after, keys_before, plain_before, code_before)
    reversed_pairs = []
    after_pairs = pairs(revised)
    after_set = {(a, b) for _, a, b, _ in after_pairs}
    for shown, a, b, pos in pairs(original):
        if a != b and (b, a) in after_set and (a, b) not in after_set:
            other = next(p for p in after_pairs if (p[1], p[2]) == (b, a))
            reversed_pairs.append((shown, other[0], pos, other[3]))
    return {"missing": missing, "added": added, "reversed": reversed_pairs}


ORDER = ("수치", "날짜", "요일", "시각", "식별자", "영문", "링크", "코드", "인용")


def grouped(values: list) -> list:
    groups: dict = {}
    for v in values:
        groups.setdefault(v.category, []).append(v.shown)
    return [(name, groups[name]) for name in ORDER if name in groups]


def report_lines(result: dict) -> list:
    lines = []
    for label, key in (("원문에만 있음", "missing"), ("고친 글에만 있음", "added")):
        for name, shown in grouped(result[key]):
            lines.append(f"{label}  {name}: " + ", ".join(shown))
    for before, after, _, _ in result["reversed"]:
        lines.append(f"방향이 바뀜  {before} → {after}")
    return lines


def as_json(result: dict, original: str, revised: str) -> dict:
    return {
        "missing": [v.as_dict(original) for v in result["missing"]],
        "added": [v.as_dict(revised) for v in result["added"]],
        "reversed": [{"original": a, "revised": b} for a, b, _, _ in result["reversed"]],
    }


# ── 자체 테스트 ──────────────────────────────────────────────────
def self_test() -> int:
    failures = []

    def diff(a: str, b: str) -> set:
        r = compare(a, b)
        return {("M", v.category, v.shown) for v in r["missing"]} | {("A", v.category, v.shown) for v in r["added"]} | \
            {("R", x, y) for x, y, _, _ in r["reversed"]}

    same = [
        ("## 1. 배포 안내\n1. 수수료가 약 30% 줄었고, 처리량은 1,000건에서 2500건으로 늘었다.\n"
         "주소는 0xAbC123def456이고 `cast send`로 호출한다. 버전은 v1.2.3이다.\n"
         "자세한 내용은 https://example.com/docs를 보라.\n```bash\nforge test\n```\n",
         "## 배포 안내\n- 수수료는 약 30% 줄었고 처리량은 1000건에서 2500건으로 늘었습니다.\n"
         "`cast send`로 `0xAbC123def456`을 호출합니다. 버전은 v1.2.3입니다.\n"
         "자세한 내용: https://example.com/docs\n`forge test`\n"),
        ("1,000,000명, 오후 2시, 0.30%, 11월 05일", "100만 명, 14:00, 0.3%, 11월 5일"),
        ("Web3 대중화와 L2", "대중화"),
    ]
    for a, b in same:
        if diff(a, b):
            failures.append(f"오탐: {diff(a, b)}")
    changed = {
        ("EIP-4337 기반 지갑", "ERC-4337 기반 지갑"): {("M", "식별자", "EIP-4337"), ("A", "식별자", "ERC-4337")},
        ("배포는 11월 18일(화)", "배포는 11월 18일(수)"): {("M", "요일", "11월 18일(화)"), ("A", "요일", "11월 18일(수)")},
        ("-5%", "+5%"): {("M", "수치", "-5%"), ("A", "수치", "+5%")},
        ("820ms", "820초"): {("M", "수치", "820ms"), ("A", "수치", "820초")},
        ("42%에서 18%로 줄었다", "18%에서 42%로 늘었다"): {("R", "42%에서 18%로", "18%에서 42%로")},
    }
    for (a, b), want in changed.items():
        if diff(a, b) != want:
            failures.append(f"기대와 다름: {a} → {b}: {sorted(diff(a, b))}")
    if failures:
        print("자체 테스트 실패: ko-tone compare")
        for failure in failures:
            print(f"      {failure}")
        return 1
    print("자체 테스트 통과: ko-tone compare")
    return 0


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="원문과 고친 글의 수치·날짜·요일·식별자·링크·코드·인용을 맞댑니다.")
    parser.add_argument("original", nargs="?", help="원문 UTF-8 파일, 표준 입력은 -")
    parser.add_argument("revised", nargs="?", help="고친 글 UTF-8 파일")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로")
    parser.add_argument("--strict", action="store_true", help="차이가 있으면 종료 코드 1")
    parser.add_argument("--self-test", action="store_true", help="자체 테스트 실행")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.original or not args.revised:
        parser.print_usage(sys.stderr)
        print("원문 파일과 고친 글 파일을 차례로 주세요.", file=sys.stderr)
        return 2
    if args.original == "-" and args.revised == "-":
        print("표준 입력(-)은 둘 중 하나에만 쓸 수 있습니다.", file=sys.stderr)
        return 2
    try:
        original, revised = read_text(args.original), read_text(args.revised)
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    result = compare(original, revised)
    found = bool(result["missing"] or result["added"] or result["reversed"])
    if args.json:
        print(json.dumps(as_json(result, original, revised), ensure_ascii=False, indent=2))
    elif not found:
        print("차이 없음. " + NOT_SEEN)
    else:
        for line in report_lines(result):
            print(line)
        print(ADVICE)
        print(NOT_SEEN)
    return 1 if args.strict and found else 0


if __name__ == "__main__":
    raise SystemExit(main())
