#!/usr/bin/env python3
"""0x 주소의 EIP-55 체크섬을 확인한다(ko_tone_facts.py와 ko_tone_check.py가 0x 주소를 만났을 때만 불러온다).

Keccak-256은 표준 라이브러리에 없어서(hashlib.sha3_256은 패딩이 다름) 직접 구현했다.
따로 실행하면 자체 테스트를 돌린다: python3 ko_tone_facts_web3.py --self-test
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import re
import sys

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


def _keccak_f(a: list) -> list:
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


def address_status(address: str) -> tuple:
    """(상태, 설명). 상태: ok | no-checksum | mismatch"""
    body = address[2:]
    correct = to_checksum(address)
    if body == body.lower() or body == body.upper():
        return "no-checksum", f"대소문자 체크섬이 없는 표기입니다(주소 자체는 유효). 체크섬 표기: {correct}"
    if address == correct:
        return "ok", "EIP-55 체크섬이 맞습니다."
    return "mismatch", (f"EIP-55 체크섬이 맞지 않습니다. 글자가 틀렸을 수 있으니 원본과 대조하세요. "
                        f"이 표기가 맞다면 체크섬 표기는 {correct} 입니다.")


def self_test() -> list:
    """실패 설명 목록을 돌려준다(비었으면 통과)."""
    failures = []
    if keccak256(b"").hex() != "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470":
        failures.append("keccak256('') 값이 다름")
    # EIP-55 명세의 예시 주소: 소문자에서 계산한 체크섬 표기가 예시와 같아야 한다
    for addr in ("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
                 "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB", "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb"):
        if to_checksum(addr.lower()) != addr or address_status(addr)[0] != "ok":
            failures.append(f"EIP-55 예시 불일치: {addr}")
    if address_status("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD")[0] != "mismatch":  # 마지막 글자만 바꿈
        failures.append("체크섬 불일치를 놓침")
    return failures


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        problems = self_test()
        for problem in problems:
            print(f"실패  {problem}")
        print("자체 테스트 실패" if problems else "자체 테스트 통과 (keccak, EIP-55 예시 4개)")
        raise SystemExit(1 if problems else 0)
    print("이 파일은 ko_tone_facts.py addr 또는 ko_tone_check.py가 불러 씁니다. 자체 테스트: --self-test")
    raise SystemExit(2)
