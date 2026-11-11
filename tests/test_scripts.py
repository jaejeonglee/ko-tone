"""검사 스크립트 회귀 테스트.

함수만 따로 부르지 않고 실제 사용과 같은 명령줄 입구(sys.executable + 스크립트 경로)로 실행해,
규칙이 전체 호출 흐름에서 동작하는지 확인한다.
실행: python3 -m unittest discover -s tests   (Windows: py -3 -m unittest discover -s tests)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "ko-tone" / "scripts"
LINT = SCRIPTS / "ko_tone_lint.py"
COMPARE = SCRIPTS / "ko_tone_compare.py"
FACTS = SCRIPTS / "ko_tone_facts.py"

AI_DRAFT = """## 계정 추상화: 지갑 경험의 새로운 패러다임

급변하는 Web3 생태계에서 사용자 경험의 중요성은 아무리 강조해도 지나치지 않습니다. 그렇다면 계정 추상화란 무엇일까요?

계정 추상화는 단순한 기술 업그레이드가 아니라 혁신적인 변화입니다. 지갑을 연결할 수 있습니다. 토큰을 스왑할 수 있습니다. 거래 내역을 확인할 수 있습니다.

저희 팀도 지난달 관련 검토를 진행했으며, 그 결과 온보딩 이탈률이 42%에서 18%로 감소되어졌습니다.

결론적으로, 계정 추상화는 대중화에 있어서 중요한 역할을 할 것으로 보입니다. 앞으로의 발전이 더욱 기대됩니다.
"""

NATURAL_DRAFT = """## EIP-4337 지갑을 붙여 보고 달라진 점

지난주에 사내 테스트넷에 EIP-4337 기반 지갑을 붙여 봤습니다. 가장 먼저 달라진 건 온보딩입니다. 시드 문구를 받아 적는 단계가 없어서, 처음 쓰는 사람도 이메일 인증만으로 지갑을 만들었습니다.

가스비는 Paymaster가 대신 내도록 설정했습니다. 그만큼 팀이 가스비 예산을 따로 관리해야 해서, 다음 달까지는 일일 한도를 0.5 ETH로 두고 지켜볼 생각입니다.

```bash
# 코드 블록 안은 검사하지 않는다: 에 있어서 — 혁신적인
cast send $ENTRYPOINT "handleOps(...)"
```
"""


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )


class TempFiles(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write(self, name: str, text: str) -> str:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)


class LintTest(TempFiles):
    def test_self_test(self) -> None:
        result = run(LINT, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_flags_ai_draft(self) -> None:
        result = run(LINT, self.write("ai.md", AI_DRAFT))
        self.assertEqual(result.returncode, 0)  # 경고만 내고 실패로 끝내지 않는다
        for expected in (
            "콜론으로 문구를 덧붙인 제목",
            "홍보 문구",
            "질문형 전환",
            "부정 병렬",
            "같은 종결 '…수 있습니다'",
            "'~를 진행/수행하다'",
            "이중 피동",
            "'~에 있어서'",
            "상투적인 결말",
        ):
            self.assertIn(expected, result.stdout)

    def test_natural_draft_and_code_block_pass(self) -> None:
        result = run(LINT, self.write("natural.md", NATURAL_DRAFT))
        self.assertEqual(result.returncode, 0)
        self.assertIn("PASS", result.stdout)
        self.assertNotIn("WARN", result.stdout)

    def test_mixed_speech_levels(self) -> None:
        text = "배포는 금요일입니다. 롤백 절차는 문서에 있다. 담당은 운영팀이다. 점검은 주말까지 이어집니다.\n"
        result = run(LINT, self.write("mixed.md", text))
        self.assertIn("높임 수준이 섞여 있습니다", result.stdout)

    def test_polite_requests_are_not_mixing(self) -> None:
        text = "배포는 금요일입니다. 롤백 절차는 문서를 참고해 주세요. 담당자는 운영팀입니다. 문제가 생기면 알려 주세요.\n"
        result = run(LINT, self.write("requests.md", text))
        self.assertNotIn("높임 수준이 섞여 있습니다", result.stdout)


class CompareTest(TempFiles):
    def test_self_test(self) -> None:
        result = run(COMPARE, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_facts_pass(self) -> None:
        original = self.write("a.md", "이탈률이 42%에서 18%로 줄었습니다. 자세한 내용은 https://example.com/aa 에 있습니다.\n")
        revised = self.write("b.md", "이탈률은 42%에서 18%로 줄었다. 자세한 내용: https://example.com/aa\n")
        result = run(COMPARE, original, revised)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_changed_and_invented_values_fail(self) -> None:
        original = self.write("a.md", "이탈률이 42%에서 18%로 줄었습니다. 주소는 0xAbC123def456이고 `forge test`로 확인했습니다.\n")
        revised = self.write("b.md", "이탈률이 크게 줄었고 사용자는 3배 늘었습니다. `forge test`로 확인했습니다.\n")
        result = run(COMPARE, original, revised)
        self.assertEqual(result.returncode, 1)
        self.assertIn("MISSING", result.stdout)
        self.assertIn("18, 42", result.stdout)
        self.assertIn("0xAbC123def456", result.stdout)
        self.assertIn("ADDED", result.stdout)
        self.assertIn("3", result.stdout)

    def test_usage_error(self) -> None:
        result = run(COMPARE)
        self.assertEqual(result.returncode, 2)



class FactsTest(TempFiles):
    def test_self_test(self) -> None:
        result = run(FACTS, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_weekday_and_timezone(self) -> None:
        self.assertEqual(run(FACTS, "weekday", "2026-12-02").stdout.strip(), "2026년 12월 2일(수)")
        out = run(FACTS, "tz", "2026-12-31 23:59", "--from", "UTC", "--to", "KST").stdout
        self.assertIn("2027년 1월 1일(금) 08:59 KST", out)

    def test_pct_and_numbers(self) -> None:
        self.assertTrue(run(FACTS, "pct", "1,240,000", "780,000").stdout.startswith("37.1% 감소"))
        self.assertIn("(1억 2,345만 6,789)", run(FACTS, "num", "123456789").stdout)
        self.assertEqual(run(FACTS, "units", "1500000000000000000", "--decimals", "18").stdout.strip(), "1.5")

    def test_address_checksum(self) -> None:
        good = run(FACTS, "addr", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")
        self.assertEqual(good.returncode, 0)
        bad = run(FACTS, "addr", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("체크섬이 맞지 않습니다", bad.stdout)
        lower = run(FACTS, "addr", "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed")
        self.assertEqual(lower.returncode, 0)
        self.assertIn("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", lower.stdout)

    def test_check_finds_wrong_weekday_and_bad_address(self) -> None:
        text = "2026년 공지\n- 일시: 12월 2일(목) 19:00 KST\n- 주소: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD\n- 다음 점검: 12월 9일(수)\n"
        result = run(FACTS, "check", self.write("notice.md", text))
        self.assertEqual(result.returncode, 1)
        self.assertIn("실제 요일은 (수)", result.stdout)
        self.assertIn("체크섬이 맞지 않습니다", result.stdout)
        self.assertIn("12월 9일(수): 2026년 기준 요일이 맞습니다", result.stdout)


if __name__ == "__main__":
    unittest.main()
