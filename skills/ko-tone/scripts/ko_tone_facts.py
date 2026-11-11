#!/usr/bin/env python3
"""업무 글에 덧붙일 값을 계산하고, 완성된 글의 날짜·주소를 검증한다.

모델이 눈대중으로 쓰기 쉬운 값(요일, 시간대 변환, 증감률, 단위)을 계산으로 만들고,
틀리면 사고가 나는 값(컨트랙트 주소 체크섬, 날짜와 요일의 짝)을 확인한다.
표준 라이브러리만 쓴다. Keccak-256은 표준 라이브러리에 없어서(hashlib.sha3_256은 패딩이 다름) 직접 구현했다.

하위 명령
  weekday  2026-12-02              → 2026-12-02 (수)
  tz       "2026-12-01 10:00" --from UTC --to KST
  pct      820 310                 → 62.2% 감소
  num      1240000                 → 1,240,000 (124만)
  units    1500000000000000000 --decimals 18 → 1.5
  addr     0x...                   → EIP-55 체크섬 확인과 올바른 표기
  check    <파일> [--year 2026]     → 글 속 주소 체크섬, '날짜(요일)' 짝을 모두 검사(문제 있으면 종료 코드 1)
  --self-test                      → Keccak·EIP-55 공식 테스트 값과 계산 함수 검사
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

WEEKDAYS = "월화수목금토일"  # date.weekday(): 월요일 = 0

# ── Keccak-256 (Ethereum이 쓰는 원래 Keccak, 패딩 0x01) ──────────────
_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [  # _ROT[x][y]: rho 단계 회전량
    [0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rol(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & _MASK if n else v


def _keccak_f(a: list[list[int]]) -> list[list[int]]:
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]       # theta
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]                                                # rho + pi
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]  # chi
        a[0][0] ^= rc                                                                  # iota
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136  # 1088비트
    pad = bytearray(rate - len(data) % rate)
    pad[0] |= 0x01
    pad[-1] |= 0x80
    msg = data + bytes(pad)
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        a = _keccak_f(a)
    return b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


# ── EIP-55 주소 체크섬 ────────────────────────────────────────────
ADDR_RE = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")


def to_checksum(address: str) -> str:
    body = address[2:].lower()
    digest = keccak256(body.encode("ascii")).hex()
    return "0x" + "".join(ch.upper() if ch.isalpha() and int(digest[i], 16) >= 8 else ch for i, ch in enumerate(body))


def address_status(address: str) -> tuple[str, str]:
    """(상태, 설명). 상태: ok | no-checksum | mismatch"""
    body = address[2:]
    correct = to_checksum(address)
    if body == body.lower() or body == body.upper():
        return "no-checksum", f"대소문자 체크섬이 없는 표기입니다(주소 자체는 유효). 체크섬 표기: {correct}"
    if address == correct:
        return "ok", "EIP-55 체크섬이 맞습니다."
    return "mismatch", f"EIP-55 체크섬이 맞지 않습니다. 글자가 틀렸을 수 있으니 원본과 대조하세요. 이 표기가 맞다면 체크섬 표기는 {correct} 입니다."


# ── 날짜·시간 ────────────────────────────────────────────────────
DATE_FORMS = [
    re.compile(r"(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일"),
]
FIXED_TZ = {"UTC": 0, "GMT": 0, "Z": 0, "KST": 9, "JST": 9}


def parse_date(text: str) -> date:
    for pattern in DATE_FORMS:
        m = pattern.search(text)
        if m:
            return date(int(m["y"]), int(m["m"]), int(m["d"]))
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
    except Exception as exc:  # zoneinfo가 없거나(Windows에 tzdata 미설치) 이름이 틀린 경우
        raise ValueError(f"시간대를 찾을 수 없습니다: {name} (UTC, KST, JST 또는 Asia/Seoul 같은 IANA 이름)") from exc


def convert_tz(stamp: str, src: str, dst: str) -> tuple[datetime, datetime]:
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})[ T](\d{1,2}):(\d{2})", stamp)
    if not m:
        raise ValueError(f"일시를 읽을 수 없습니다: {stamp!r} (예: 2026-12-01 10:00)")
    y, mo, d, h, mi = map(int, m.groups())
    start = datetime(y, mo, d, h, mi, tzinfo=_zone(src))
    return start, start.astimezone(_zone(dst))


def tz_label(dt: datetime, name: str) -> str:
    return f"{korean_date(dt.date())} {dt:%H:%M} {name.upper() if name.upper() in FIXED_TZ else name}"


# ── 숫자 ─────────────────────────────────────────────────────────
def _dec(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def pct_change(before: str, after: str, digits: int = 1) -> str:
    b, a = _dec(before), _dec(after)
    if b == 0:
        raise ValueError("기준값이 0이면 증감률을 계산할 수 없습니다.")
    rate = (a - b) / b * 100
    q = Decimal(1).scaleb(-digits)
    word = "증가" if rate > 0 else "감소" if rate < 0 else "변화 없음"
    return f"{abs(rate).quantize(q, ROUND_HALF_UP)}% {word} ({before} → {after}, 차이 {a - b:+,})"


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
    text = format(value.normalize(), "f")
    return text


# ── 완성된 글 검사 ────────────────────────────────────────────────
WEEKDAY_ANNOTATED = [
    re.compile(r"(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})\s*\((?P<w>[월화수목금토일])\)"),
    re.compile(r"(?:(?P<y>\d{4})년\s*)?(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일\s*\((?P<w>[월화수목금토일])\)"),
]
YEAR_MENTION = re.compile(r"(\d{4})년")


def check_text(text: str, default_year: int | None) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for address in sorted(set(ADDR_RE.findall(text))):
        status, note = address_status(address)
        findings.append(("OK" if status == "ok" else "WARN" if status == "mismatch" else "NOTE", f"{address}: {note}"))
    seen = set()
    for pattern in WEEKDAY_ANNOTATED:
        for m in pattern.finditer(text):
            if m.span() in seen:
                continue
            seen.add(m.span())
            year = m["y"]
            if not year:  # 앞쪽 가장 가까운 'YYYY년'을 쓰고, 없으면 --year
                before = YEAR_MENTION.findall(text[:m.start()])
                year = before[-1] if before else default_year
            if not year:
                findings.append(("NOTE", f"{m.group(0)}: 연도를 알 수 없어 요일을 확인하지 못했습니다. --year를 주세요."))
                continue
            try:
                actual = WEEKDAYS[date(int(year), int(m["m"]), int(m["d"])).weekday()]
            except ValueError:
                findings.append(("WARN", f"{m.group(0)}: 존재하지 않는 날짜입니다({year}년 기준)."))
                continue
            if actual == m["w"]:
                findings.append(("OK", f"{m.group(0)}: {year}년 기준 요일이 맞습니다."))
            else:
                findings.append(("WARN", f"{m.group(0)}: {year}년 기준 실제 요일은 ({actual})입니다."))
    return findings


# ── 자체 테스트 ──────────────────────────────────────────────────
def self_test() -> int:
    failures = []
    if keccak256(b"").hex() != "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470":
        failures.append("keccak256('') 값이 다름")
    # EIP-55 명세의 예시 주소: 소문자에서 계산한 체크섬 표기가 예시와 같아야 한다
    for addr in ("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
                 "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB", "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb"):
        if to_checksum(addr.lower()) != addr or address_status(addr)[0] != "ok":
            failures.append(f"EIP-55 예시 불일치: {addr}")
    broken = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD"  # 마지막 글자 대소문자만 바꿈
    if address_status(broken)[0] != "mismatch":
        failures.append("체크섬 불일치를 놓침")
    if korean_date(parse_date("2026-12-02")) != "2026년 12월 2일(수)":
        failures.append("요일 계산 오류")
    start, end = convert_tz("2026-12-31 23:59", "UTC", "KST")
    if (end.year, end.month, end.day, end.hour, end.minute) != (2027, 1, 1, 8, 59):
        failures.append("UTC→KST 날짜 넘김 오류")
    if not pct_change("820", "310").startswith("62.2% 감소"):
        failures.append("증감률 오류")
    if korean_number("1240000") != "1,240,000 (124만)" or korean_number("123456789") != "123,456,789 (1억 2,345만 6,789)":
        failures.append("한국어 단위 오류")
    if from_units("1500000000000000000", 18) != "1.5":
        failures.append("토큰 단위 환산 오류")
    found = check_text("배포는 2026년 12월 2일(목)입니다. 주소: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD", None)
    if sum(1 for level, _ in found if level == "WARN") != 2:
        failures.append(f"검사 결과 이상: {found}")
    if failures:
        print("FAIL  ko-tone facts self-test")
        for f in failures:
            print(f"      {f}")
        return 1
    print("PASS  ko-tone facts self-test (keccak, EIP-55 예시 4개, 요일, 시간대, 증감률, 단위, 검사)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="업무 글의 보강 값을 계산하고 날짜·주소를 검증합니다.")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("weekday"); p.add_argument("date")
    p = sub.add_parser("tz"); p.add_argument("stamp"); p.add_argument("--from", dest="src", default="UTC"); p.add_argument("--to", dest="dst", default="KST")
    p = sub.add_parser("pct"); p.add_argument("before"); p.add_argument("after"); p.add_argument("--digits", type=int, default=1)
    p = sub.add_parser("num"); p.add_argument("value")
    p = sub.add_parser("units"); p.add_argument("raw"); p.add_argument("--decimals", type=int, required=True)
    p = sub.add_parser("addr"); p.add_argument("address")
    p = sub.add_parser("check"); p.add_argument("file"); p.add_argument("--year", type=int)
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
            if not ADDR_RE.fullmatch(args.address):
                print("WARN  0x로 시작하는 40자리 16진수 주소가 아닙니다."); return 1
            status, note = address_status(args.address)
            print(("OK    " if status == "ok" else "WARN  " if status == "mismatch" else "NOTE  ") + note)
            return 1 if status == "mismatch" else 0
        elif args.cmd == "check":
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            findings = check_text(text, args.year)
            for level, note in findings:
                print(f"{level:<6}{note}")
            if not findings:
                print("PASS  검사할 주소나 '날짜(요일)' 표기가 없습니다.")
            return 1 if any(level == "WARN" for level, _ in findings) else 0
        else:
            parser.print_help(); return 2
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
