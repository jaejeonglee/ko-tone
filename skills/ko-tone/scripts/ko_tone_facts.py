#!/usr/bin/env python3
"""글에 덧붙일 값을 계산하고, 완성된 글의 날짜·요일을 확인한다.

모델이 눈대중으로 쓰기 쉬운 값(요일, 시간대 변환, 증감률, 단위)을 계산으로 만들고,
틀리면 사고가 나는 값(날짜와 요일의 짝, 덧붙인 증감률)을 확인한다.
0x 주소의 EIP-55 체크섬은 ko_tone_facts_web3.py에 있고, 주소를 만났을 때만 불러온다.
표준 라이브러리만 쓴다.

하위 명령
  weekday  2026-12-02                     → 2026년 12월 2일(수)
  tz       "2026-12-01 오후 7시" --from KST --to UTC
  pct      820 310                        → 62.2% 감소   (42% 18%처럼 퍼센트끼리면 %p 차이도)
  num      1240000                        → 1,240,000 (124만)
  units    1500000000000000000 --decimals 18 → 1.5
  addr     0x...                          → EIP-55 체크섬 확인과 올바른 표기
  check    <파일> [--year 2026]            → 글 속 '날짜 + 요일'과 0x 주소를 모두 확인
  verify   <원문 파일> <고친 글 파일>        → 고친 글에만 있는 퍼센트를 원문의 'A에서 B로' 짝으로 검산
  --self-test

check는 "11월 18일(화)", "11월 18일 화요일", "(화요일)", "11/18(화)", 범위의 둘째 날("1일(화)~3일(수)")을 읽는다.
연도는 같은 문장에 있는 'YYYY년'만 쓰고, 없으면 --year, 그것도 없으면 맞는 해 후보를 알려 준다.
걸려도 종료 코드는 0이다(--strict일 때만 1). 사용법·입력 오류는 2.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import importlib.util
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

WEEKDAYS = "월화수목금토일"  # date.weekday(): 월요일 = 0
HERE = Path(__file__).resolve().parent


def _setup_stdout() -> None:
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


# ── web3 모듈(0x 주소가 있을 때만) ──────────────────────────────────
_WEB3 = None


def web3():
    global _WEB3
    if _WEB3 is None:
        spec = importlib.util.spec_from_file_location("ko_tone_facts_web3", HERE / "ko_tone_facts_web3.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _WEB3 = module
    return _WEB3


HEX40 = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")


# ── 날짜·시간 ────────────────────────────────────────────────────
DATE_FORMS = [
    re.compile(r"(?P<y>\d{4})\s*[-./]\s*(?P<m>\d{1,2})\s*[-./]\s*(?P<d>\d{1,2})"),
    re.compile(r"(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일"),
]
FIXED_TZ = {"UTC": 0, "GMT": 0, "Z": 0, "KST": 9, "JST": 9, "SGT": 8, "HKT": 8, "CET": 1, "CEST": 2,
            "BST": 1, "EST": -5, "EDT": -4, "PST": -8, "PDT": -7, "IST": 5.5}


def _date(y: int, m: int, d: int, raw: str) -> date:
    try:
        return date(y, m, d)
    except ValueError:
        raise ValueError(f"없는 날짜입니다: {raw}") from None


def parse_date(text: str) -> date:
    for pattern in DATE_FORMS:
        m = pattern.search(text)
        if m:
            return _date(int(m["y"]), int(m["m"]), int(m["d"]), m.group(0))
    raise ValueError(f"날짜를 읽을 수 없습니다: {text!r} (예: 2026-12-02, 2026년 12월 2일)")


def korean_date(d: date, with_year: bool = True) -> str:
    head = f"{d.year}년 " if with_year else ""
    return f"{head}{d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})"


def _zone(name: str):
    key = name.upper()
    if key in FIXED_TZ:
        return timezone(timedelta(hours=FIXED_TZ[key]), key)
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # zoneinfo가 없거나(Windows에 tzdata 미설치) 이름이 틀린 경우
        raise ValueError(f"시간대를 찾을 수 없습니다: {name} (UTC, KST, JST, PST 또는 Asia/Seoul 같은 IANA 이름)") from None


TIME_FORMS = (
    re.compile(r"(?P<h>\d{1,2}):(?P<mi>\d{2})"),
    re.compile(r"(?P<ap>오전|오후|낮|밤|저녁|새벽)?\s*(?P<h>\d{1,2})시(?!간|대|각|점)(?:\s*(?P<mi>\d{1,2})분|\s*(?P<half>반))?"),
)


def parse_time(text: str) -> tuple:
    """'14:00', '오후 7시', '오전 9시 30분', '7시 반' → (시, 분)."""
    for pattern in TIME_FORMS:
        m = pattern.search(text)
        if not m:
            continue
        h = int(m["h"])
        groups = m.groupdict()
        mi = int(groups.get("mi") or 0) if not groups.get("half") else 30
        ap = groups.get("ap")
        if ap in ("오후", "저녁", "밤") and h < 12:
            h += 12
        elif ap == "낮" and h < 6:
            h += 12
        elif ap in ("오전", "새벽") and h == 12:
            h = 0
        if not (0 <= h <= 24 and 0 <= mi < 60):
            raise ValueError(f"없는 시각입니다: {m.group(0)}")
        return h, mi
    raise ValueError(f"시각을 읽을 수 없습니다: {text!r} (예: 2026-12-01 10:00, 2026-12-01 오후 7시)")


def convert_tz(stamp: str, src: str, dst: str) -> tuple:
    d = parse_date(stamp)
    rest = stamp
    for pattern in DATE_FORMS:
        rest = pattern.sub(" ", rest, count=1)
    h, mi = parse_time(rest)
    start = datetime(d.year, d.month, d.day, tzinfo=_zone(src)) + timedelta(hours=h, minutes=mi)
    return start, start.astimezone(_zone(dst))


def tz_label(dt: datetime, name: str) -> str:
    return f"{korean_date(dt.date())} {dt:%H:%M} {name.upper() if name.upper() in FIXED_TZ else name}"


# ── 숫자 ─────────────────────────────────────────────────────────
def _dec(text: str) -> Decimal:
    cleaned = text.replace(",", "").strip().rstrip("%")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"숫자를 읽을 수 없습니다: {text!r} (예: 1240000, 1,240,000, 42%)") from None


def pct_change(before: str, after: str, digits: int = 1) -> str:
    b, a = _dec(before), _dec(after)
    if b == 0:
        raise ValueError("기준값이 0이면 증감률을 계산할 수 없습니다.")
    rate = (a - b) / b * 100
    q = Decimal(1).scaleb(-digits)
    word = "증가" if rate > 0 else "감소" if rate < 0 else "변화 없음"
    out = f"{abs(rate).quantize(q, ROUND_HALF_UP)}% {word} ({before} → {after}, 차이 {a - b:+,})"
    if before.strip().endswith("%") and after.strip().endswith("%"):
        out += f". 퍼센트끼리의 차이는 {a - b:+}%p"
    return out


def korean_number(text: str) -> str:
    n = _dec(text)
    whole = int(n)
    units = [(10**12, "조"), (10**8, "억"), (10**4, "만")]
    parts, rest = [], abs(whole)
    for size, name in units:
        if rest >= size:
            parts.append(f"{rest // size:,}{name}")
            rest %= size
    if rest or not parts:
        parts.append(f"{rest:,}")
    sign = "-" if whole < 0 else ""
    return f"{n:,} ({sign}{' '.join(parts)})"


def from_units(raw: str, decimals: int) -> str:
    value = _dec(raw).scaleb(-decimals)
    return format(value.normalize(), "f")


# ── 완성된 글 검사: 날짜와 요일 ──────────────────────────────────
WD = r"(?:\s*\(\s*(?P<w1>[월화수목금토일])(?:요일)?\s*\)|,?\s+(?P<w2>[월화수목금토일])요일)"
WEEKDAY_ANNOTATED = [
    re.compile(r"(?P<y>\d{4})\s*[-./]\s*(?P<m>\d{1,2})\s*[-./]\s*(?P<d>\d{1,2})\.?" + WD),
    re.compile(r"(?:(?P<y>\d{4})년\s*)?(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일" + WD),
    re.compile(r"(?<![\d/])(?P<m>\d{1,2})/(?P<d>\d{1,2})(?![\d/])" + WD),
]
# 범위의 둘째 날: "12월 1일(화)~3일(수)", "12월 31일(목)~1월 2일(토)", "11/18(화)~11/20(목)"
RANGE_TAIL = re.compile(r"\s*(?:~|∼|-|–|부터)\s*(?:(?P<m>\d{1,2})(?:월\s*|/))?(?P<d>\d{1,2})일?" + WD)
YEAR_WORD = re.compile(r"(?<!\d)(\d{4})년")
SENTENCE_END = re.compile(r"(?<=[가-힣)][.!?])\s+|(?<=[.!?。])\s+(?=[^\d\s])|\n")


def _sentence(text: str, start: int, end: int) -> str:
    left = max((m.end() for m in SENTENCE_END.finditer(text, 0, start)), default=0)
    right_match = SENTENCE_END.search(text, end)
    return text[left:right_match.start() if right_match else len(text)]


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _judge(raw: str, line: int, y, m: int, d: int, w: str, default_year, base_year: int) -> tuple:
    """(수준, 행, 설명). 수준: OK | WARN | NOTE"""
    if y:
        try:
            actual = WEEKDAYS[date(int(y), m, d).weekday()]
        except ValueError:
            return "WARN", line, f"{raw}: 없는 날짜입니다({y}년 기준)."
        if actual == w:
            return "OK", line, f"{raw}: {y}년 기준 요일이 맞습니다."
        return "WARN", line, f"{raw}: {y}년 기준 실제 요일은 ({actual})입니다."
    # 연도를 모르면 맞는 해 후보를 알려 준다
    years = [base_year - 1, base_year, base_year + 1]
    fits, others = [], []
    for year in years:
        try:
            actual = WEEKDAYS[date(year, m, d).weekday()]
        except ValueError:
            continue
        (fits if actual == w else others).append((year, actual))
    if not fits and not others:
        return "WARN", line, f"{raw}: 없는 날짜입니다."
    wrong = ", ".join(f"{year}년이면 ({actual})" for year, actual in others)
    if fits:
        right = "·".join(f"{year}년" for year, _ in fits) + "이면 맞"
        msg = f"{right}고 {wrong}" if wrong else f"{right}습니다"
    else:
        msg = wrong
    level = "OK" if any(year == base_year for year, _ in fits) else "WARN"
    return level, line, f"{raw}: 연도가 없습니다. {msg}. 연도를 알면 --year로 주세요."


def check_dates(text: str, default_year=None, base_year=None) -> list:
    """'날짜 + 요일' 짝을 모두 확인한다. [(수준, 행, 설명)]"""
    base_year = base_year or default_year or date.today().year
    findings, taken = [], []

    def overlaps(span):
        return any(span[0] < e and s < span[1] for s, e in taken)

    for pattern in WEEKDAY_ANNOTATED:
        for m in pattern.finditer(text):
            if overlaps(m.span()):
                continue
            taken.append(m.span())
            year = m.groupdict().get("y")
            if not year:
                in_sentence = set(YEAR_WORD.findall(_sentence(text, m.start(), m.end())))
                if len(in_sentence) == 1:
                    year = in_sentence.pop()
                elif default_year:
                    year = str(default_year)
            month, day = int(m["m"]), int(m["d"])
            w = m["w1"] or m["w2"]
            line = _line_no(text, m.start())
            findings.append((m.start(), _judge(m.group(0).strip(), line, year, month, day, w, default_year, base_year)))
            tail = RANGE_TAIL.match(text, m.end())
            if tail and not overlaps(tail.span()):
                taken.append(tail.span())
                month2 = int(tail["m"]) if tail["m"] else month
                year2 = year
                if year and month2 < month:  # 12월 31일 ~ 1월 2일: 해가 바뀐다
                    year2 = str(int(year) + 1)
                raw2 = tail.group(0).strip().lstrip("~∼-–").strip()
                if raw2.startswith("부터"):
                    raw2 = raw2[2:].strip()
                findings.append((tail.start(), _judge(f"{raw2}(범위의 둘째 날)", line, year2, month2,
                                                      int(tail["d"]), tail["w1"] or tail["w2"], default_year, base_year)))
    return [f for _, f in sorted(findings, key=lambda item: item[0])]


def check_addresses(text: str) -> list:
    if "0x" not in text:
        return []
    found = []
    module = web3()
    for address in sorted(set(HEX40.findall(text))):
        status, note = module.address_status(address)
        level = "OK" if status == "ok" else "WARN" if status == "mismatch" else "NOTE"
        found.append((level, _line_no(text, text.find(address)), f"{address}: {note}"))
    return found


def check_text(text: str, default_year=None, base_year=None) -> list:
    """[(수준, 행, 설명)]"""
    return check_addresses(text) + check_dates(text, default_year, base_year)


# ── 덧붙인 증감률 검산(verify) ──────────────────────────────────
_NUM = r"[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+−]?\d+(?:\.\d+)?"
_MAG = r"(?:\s*[천만억조])?"
PAIR = re.compile(rf"[$₩€£¥]?(?P<a>{_NUM}){_MAG}\s*(?P<ua>%|[^\s\d,.()]{{0,3}}?)\s*(?:에서|→|->|=>|⇒)\s*"
                  rf"(?:약\s*)?[$₩€£¥]?(?P<b>{_NUM}){_MAG}\s*(?P<ub>%|[^\s\d,.()]{{0,3}}?)(?=\s|으로|로|까지|[,.)]|$)")
PERCENT = re.compile(r"(?<![\d.,])(?P<v>[-+−]?\d+(?:\.\d+)?)\s*(?P<p>%p|%포인트|퍼센트포인트|%|퍼센트)")
RATIO = re.compile(r"(?<![\d.,])(?P<v>\d+(?:\.\d+)?)\s*배")


def _plain(value: str) -> Decimal:
    return Decimal(value.replace(",", "").replace("−", "-"))


def _pairs(text: str) -> list:
    out = []
    for m in PAIR.finditer(text):
        try:
            out.append((m.group(0).strip(), _plain(m["a"]), _plain(m["b"]), m["ua"] == "%" and m["ub"] == "%"))
        except InvalidOperation:
            continue
    return out


def _close(value: Decimal, target: Decimal, shown: str) -> bool:
    decimals = len(shown.split(".", 1)[1]) if "." in shown else 0
    step = Decimal(1).scaleb(-decimals)
    return abs(abs(value) - abs(target)) <= step / 2 + Decimal("0.0000001") or \
        abs(target).quantize(step, ROUND_HALF_UP) == abs(value)


def explain_added_values(original: str, revised: str) -> list:
    """고친 글에만 있는 퍼센트(와 'N배')를 원문 짝으로 다시 계산한다.
    [(값 표기, 설명됨 여부, 설명)]"""
    orig_pcts = {_plain(m["v"]).copy_abs() for m in PERCENT.finditer(original)}
    orig_ratios = {_plain(m["v"]) for m in RATIO.finditer(original)}
    pairs = _pairs(original)
    results, seen = [], set()
    candidates = [(m.group(0), _plain(m["v"]), m["p"]) for m in PERCENT.finditer(revised)]
    candidates += [(m.group(0), _plain(m["v"]), "배") for m in RATIO.finditer(revised)]
    for shown, value, kind in candidates:
        if shown in seen:
            continue
        seen.add(shown)
        if kind == "배":
            if value in orig_ratios:
                continue
        elif value.copy_abs() in orig_pcts and kind in ("%", "퍼센트"):
            continue
        number = shown.split("%")[0].split("퍼")[0].split("배")[0].strip()
        why = None
        for label, a, b, both_pct in pairs:
            if a == 0:
                continue
            if kind in ("%", "퍼센트") and _close(value, (b - a) / a * 100, number):
                why = f"원문 '{label}'의 증감률({'증가' if b > a else '감소'})"
            elif kind in ("%p", "%포인트", "퍼센트포인트") and both_pct and _close(value, b - a, number):
                why = f"원문 '{label}'의 차이"
            elif kind in ("%", "퍼센트") and both_pct and _close(value, b - a, number):
                why = f"원문 '{label}'의 차이(%p로 쓰는 편이 정확합니다)"
            elif kind == "배" and _close(value, b / a, number):
                why = f"원문 '{label}'의 비율"
            if why:
                break
        results.append((shown.strip(), bool(why), why or "원문의 'A에서 B로', 'A → B' 짝으로 설명되지 않습니다"))
    return results


TZ_VALUE = re.compile(r"(?:(?:오전|오후|낮|밤|저녁|새벽)\s*\d{1,2}시(?:\s*\d{1,2}분)?|\d{1,2}:\d{2})\s*\(?\s*"
                      r"(?P<tz>UTC|GMT|KST|JST|SGT|HKT|CET|CEST|BST|EST|EDT|PST|PDT|IST)(?![A-Za-z])")


def missing_timezones(original: str, revised: str) -> list:
    """원문에 '시각 + 시간대'로 적힌 값이 고친 글에서 사라졌으면 그 값 목록."""
    def keys(text):
        out = {}
        for m in TZ_VALUE.finditer(text):
            try:
                h, mi = parse_time(m.group(0))
            except ValueError:
                continue
            shown = re.sub(r"\s*\(\s*", " ", m.group(0).strip())
            out.setdefault((f"{h:02d}:{mi:02d}", m["tz"]), shown)
        return out
    before, after = keys(original), keys(revised)
    revised_times = set()
    for pattern in TIME_FORMS:
        for m in pattern.finditer(revised):
            try:
                h, mi = parse_time(m.group(0))
            except ValueError:
                continue
            revised_times.add(f"{h:02d}:{mi:02d}")
    missing = []
    for (hm, tz), shown in before.items():
        if (hm, tz) in after:
            continue
        # '기간(UTC): 10:00 ~ 23:59'처럼 시간대를 머리말로 옮긴 경우는 남은 것으로 본다
        if hm in revised_times and re.search(rf"(?<![A-Za-z]){tz}(?![A-Za-z])", revised):
            continue
        missing.append(shown)
    return missing


# ── 자체 테스트 ──────────────────────────────────────────────────
def self_test() -> int:
    failures = []
    if korean_date(parse_date("2026-12-02")) != "2026년 12월 2일(수)":
        failures.append("요일 계산 오류")
    start, end = convert_tz("2026-12-31 23:59", "UTC", "KST")
    if (end.year, end.month, end.day, end.hour, end.minute) != (2027, 1, 1, 8, 59):
        failures.append("UTC→KST 날짜 넘김 오류")
    _, end = convert_tz("2026-12-01 오후 7시", "KST", "UTC")
    if (end.day, end.hour) != (1, 10):
        failures.append("'오후 7시' 변환 오류")
    if not pct_change("820", "310").startswith("62.2% 감소"):
        failures.append("증감률 오류")
    if "-24%p" not in pct_change("42%", "18%"):
        failures.append("퍼센트끼리 %p 안내 없음")
    if korean_number("1240000") != "1,240,000 (124만)" or korean_number("123456789") != "123,456,789 (1억 2,345만 6,789)":
        failures.append("한국어 단위 오류")
    if from_units("1500000000000000000", 18) != "1.5":
        failures.append("단위 환산 오류")
    cases = {
        "2026년 11월 18일 화요일에 배포합니다.": "WARN",
        "2026년 11월 18일(수요일)에 배포합니다.": "OK",
        "2026년 공지. 11/18(화) 배포": None,  # 다른 문장의 연도는 쓰지 않는다
    }
    for text, want in cases.items():
        got = check_dates(text, base_year=2026)
        if want and (not got or got[0][0] != want):
            failures.append(f"요일 검사 이상: {text} → {got}")
    rng = check_dates("2026년 12월 1일(화)~3일(수) 행사", base_year=2026)
    if len(rng) != 2 or rng[1][0] != "WARN":
        failures.append(f"범위 둘째 날 검사 이상: {rng}")
    other_year = check_dates("2025년 실적을 정리했습니다. 다음 회의는 1월 6일(화)입니다.", base_year=2026)
    if not other_year or other_year[0][0] != "OK" or "2026년이면 맞" not in other_year[0][2]:
        failures.append(f"다른 문장의 연도를 썼음: {other_year}")
    explained = explain_added_values("이탈률이 1,240,000에서 780,000으로", "37.1% 줄었다")
    if not explained or not explained[0][1]:
        failures.append(f"증감률 검산 이상: {explained}")
    try:
        failures.extend(web3().self_test())
    except Exception as exc:  # web3 모듈이 없어도 나머지는 동작해야 한다
        failures.append(f"web3 모듈을 불러오지 못함: {exc}")
    if failures:
        print("자체 테스트 실패: ko-tone facts")
        for f in failures:
            print(f"      {f}")
        return 1
    print("자체 테스트 통과: ko-tone facts (요일, 범위, 연도 후보, 시간대, 증감률, 검산, 단위, EIP-55)")
    return 0


LEVEL_WORD = {"OK": "맞음", "WARN": "확인", "NOTE": "참고"}


def main() -> int:
    _setup_stdout()
    parser = argparse.ArgumentParser(description="글의 보강 값을 계산하고 날짜·요일·주소를 확인합니다.")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("weekday"); p.add_argument("date")
    p = sub.add_parser("tz"); p.add_argument("stamp"); p.add_argument("--from", dest="src", default="UTC"); p.add_argument("--to", dest="dst", default="KST")
    p = sub.add_parser("pct"); p.add_argument("before"); p.add_argument("after"); p.add_argument("--digits", type=int, default=1)
    p = sub.add_parser("num"); p.add_argument("value")
    p = sub.add_parser("units"); p.add_argument("raw"); p.add_argument("--decimals", type=int, required=True)
    p = sub.add_parser("addr"); p.add_argument("address")
    p = sub.add_parser("check"); p.add_argument("file"); p.add_argument("--year", type=int); p.add_argument("--strict", action="store_true")
    p = sub.add_parser("verify"); p.add_argument("original"); p.add_argument("revised"); p.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        if args.cmd == "weekday":
            print(korean_date(parse_date(args.date)))
        elif args.cmd == "tz":
            start, end = convert_tz(args.stamp, args.src, args.dst)
            print(f"{tz_label(end, args.dst)}  ←  {tz_label(start, args.src)}")
        elif args.cmd == "pct":
            print(pct_change(args.before, args.after, args.digits))
        elif args.cmd == "num":
            print(korean_number(args.value))
        elif args.cmd == "units":
            print(from_units(args.raw, args.decimals))
        elif args.cmd == "addr":
            if not HEX40.fullmatch(args.address):
                print("확인  0x로 시작하는 40자리 16진수 주소가 아닙니다.")
                return 1
            status, note = web3().address_status(args.address)
            print(f"{LEVEL_WORD['OK' if status == 'ok' else 'WARN' if status == 'mismatch' else 'NOTE']}  {note}")
            return 1 if status == "mismatch" else 0
        elif args.cmd == "check":
            findings = check_text(read_text(args.file), args.year)
            for level, line, note in findings:
                print(f"{LEVEL_WORD[level]}  {line}행 {note}")
            if not findings:
                print("확인할 '날짜 + 요일' 표기나 0x 주소가 없습니다.")
            return 1 if args.strict and any(level == "WARN" for level, _, _ in findings) else 0
        elif args.cmd == "verify":
            original, revised = read_text(args.original), read_text(args.revised)
            results = explain_added_values(original, revised)
            for shown, ok, why in results:
                print(f"{'설명됨' if ok else '설명 안 됨'}  {shown}: {why}")
            for shown in missing_timezones(original, revised):
                print(f"확인  원문의 시간대 값 '{shown}'이 고친 글에 없습니다.")
            if not results:
                print("고친 글에만 있는 퍼센트나 배수가 없습니다.")
            return 1 if args.strict and any(not ok for _, ok, _ in results) else 0
        else:
            parser.print_help()
            return 2
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"오류: 파일을 읽지 못했습니다 ({exc.strerror or exc})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
