"""검사 스크립트 회귀 테스트.

함수만 따로 부르지 않고 실제 사용과 같은 명령줄 입구(sys.executable + 스크립트 경로)로 실행해,
규칙이 전체 호출 흐름에서 동작하는지 확인한다.
실행: python3 -m unittest discover -s tests   (Windows: py -3 -m unittest discover -s tests)
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "ko-tone" / "scripts"
DATA = Path(__file__).resolve().parent / "data"
CHECK = SCRIPTS / "ko_tone_check.py"
LINT = SCRIPTS / "ko_tone_lint.py"
COMPARE = SCRIPTS / "ko_tone_compare.py"
FACTS = SCRIPTS / "ko_tone_facts.py"
WEB3 = SCRIPTS / "ko_tone_facts_web3.py"
RULES = SCRIPTS / "ko_tone_rules.py"

TEMP_WARNING = "이 위치는 대화가 끝나면 지워질 수 있습니다. 목록을 프로젝트 지침에 붙여 넣으세요."
NOT_SEEN = "보지 않은 것:"

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


# 실제 사용자 규칙(~/.config/ko-tone, 저장소의 .ko-tone)이 테스트 결과를 바꾸지 않도록
# 모든 실행을 빈 임시 폴더(KO_TONE_HOME, 작업 폴더)에 가둔다.
_SANDBOX = tempfile.TemporaryDirectory()
SANDBOX = Path(_SANDBOX.name)


def tearDownModule() -> None:
    _SANDBOX.cleanup()


def run(script: Path, *args: str, home: Path | None = None, cwd: Path | None = None,
        stdin: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "KO_TONE_HOME": str(home or SANDBOX / "home"), "PYTHONDONTWRITEBYTECODE": "1",
                **(env or {})}
    return subprocess.run(
        [sys.executable, str(script), *args], input=stdin,
        capture_output=True, text=True, encoding="utf-8", check=False, env=full_env, cwd=str(cwd or SANDBOX),
    )


def load_module(path: Path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def assertOneLineError(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)


# ── lint ────────────────────────────────────────────────────────
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
        self.assertNotIn("PASS", result.stdout)

    def test_strict_exit_code(self) -> None:
        self.assertEqual(run(LINT, "--strict", self.write("ai.md", AI_DRAFT)).returncode, 1)
        self.assertEqual(run(LINT, "--strict", self.write("ok.md", "점검은 금요일입니다.\n")).returncode, 0)

    def test_output_shows_only_nearby_text(self) -> None:
        long_line = "가" * 120 + " 오후에 팀 회의를 가졌습니다. " + "나" * 120 + "\n"
        out = run(LINT, self.write("long.md", long_line)).stdout
        first = out.splitlines()[0]
        self.assertLess(len(first), 90, first)
        self.assertIn("회의를 가졌", first)

    def test_natural_draft_and_code_block_pass(self) -> None:
        result = run(LINT, self.write("natural.md", NATURAL_DRAFT))
        self.assertEqual(result.returncode, 0)
        self.assertIn("표현 후보 없음. 구성, 사실, 빈칸, 덜어낸 것은 보지 않습니다.", result.stdout)
        self.assertNotIn("PASS", result.stdout)

    def test_mixed_speech_levels(self) -> None:
        text = "배포는 금요일입니다. 롤백 절차는 문서에 있다. 담당은 운영팀이다. 점검은 주말까지 이어집니다.\n"
        result = run(LINT, self.write("mixed.md", text))
        self.assertIn("높임 수준이 섞여 있습니다", result.stdout)

    def test_polite_requests_are_not_mixing(self) -> None:
        text = "배포는 금요일입니다. 롤백 절차는 문서를 참고해 주세요. 담당자는 운영팀입니다. 문제가 생기면 알려 주세요.\n"
        result = run(LINT, self.write("requests.md", text))
        self.assertNotIn("높임 수준이 섞여 있습니다", result.stdout)

    def test_particle_pairs(self) -> None:
        hit = run(LINT, self.write("p1.md", "회원 등급(으)로 나뉩니다.\n")).stdout
        self.assertIn("조사를 함께 적었습니다", hit)
        for text in ("{name}(으)로 바꿀까요?\n", "{name}을(를) 삭제할까요?\n", "`{token}`을(를) 받았어요.\n"):
            self.assertNotIn("조사를 함께 적었습니다", run(LINT, self.write("p2.md", text)).stdout, text)

    def test_closing_inquiry_is_not_chatbot(self) -> None:
        text = "점검은 금요일 밤입니다. 궁금한 점이 있으시면 고객센터(1588-0000)로 문의해 주세요.\n"
        self.assertNotIn("챗봇", run(LINT, self.write("notice.md", text)).stdout)

    def test_quotes_and_blockquotes_are_skipped(self) -> None:
        text = "\"검토를 진행했습니다\"는 고칠 예입니다.\n> 혁신적인 게임 체인저라는 말은 남의 글이다.\n"
        self.assertNotIn("확인  ", run(LINT, self.write("q.md", text)).stdout)

    def test_scope_turns_off_rules_for_formal_documents(self) -> None:
        path = self.write("doc.md", "## 부록: 설치 방법\n\n설치는 아래 순서로 합니다.\n")
        self.assertIn("콜론으로", run(LINT, path).stdout)
        self.assertNotIn("콜론으로", run(LINT, "--scope", "개발 문서", path).stdout)

    def test_no_user_rules_option_is_accepted(self) -> None:
        self.assertEqual(run(LINT, "--no-user-rules", self.write("a.md", "점검합니다.\n")).returncode, 0)

    def test_diagnose(self) -> None:
        text = ("먼저 매출을 정리했습니다. 다음으로 비용을 보았습니다. 또한 인력을 검토하였습니다. "
                "마지막으로 계획을 수립하였습니다. 금일 중으로 공유드리고자 합니다.\n")
        out = run(LINT, "--diagnose", self.write("orig.md", text)).stdout
        for expected in ("접속 부사 사다리", "'하였습니다' 반복", "한자 공문투", "고자 합니다"):
            self.assertIn(expected, out)

    def test_missing_file(self) -> None:
        self.assertOneLineError(run(LINT, str(self.dir / "nope.md")))

    def test_probe_sentences(self) -> None:
        """감사 때 지은 자연스러운 문장 오탐 회귀(tests/data/lint_probes.json)."""
        lint = load_module(LINT)
        probes = json.loads((DATA / "lint_probes.json").read_text(encoding="utf-8"))["probes"]
        scope_of = {"doc": "doc", "release": "release", "sns": "sns", "메신저": "chat"}
        for probe in probes:
            hints = lint.find_line_hints(lint.visible_lines(probe["text"]), scope=scope_of.get(probe["scope"]))
            levels = {h[3] for h in hints}
            with self.subTest(probe["text"]):
                if probe["expect"] == "pass":
                    self.assertEqual(hints, [])
                elif probe["expect"] == "info":
                    self.assertEqual(levels, {"참고"})
                else:
                    self.assertIn("확인", levels)

    def test_human_baseline_record(self) -> None:
        record = json.loads((DATA / "human_baseline.json").read_text(encoding="utf-8"))
        self.assertLessEqual(record["after_1_0_rc"]["per_1000_warn"], record["before_1_0"]["per_1000"])


# ── compare ─────────────────────────────────────────────────────
class CompareTest(TempFiles):
    def compare(self, original: str, revised: str, *args: str) -> subprocess.CompletedProcess:
        return run(COMPARE, self.write("a.md", original), self.write("b.md", revised), *args)

    def test_self_test(self) -> None:
        result = run(COMPARE, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_facts(self) -> None:
        result = self.compare("이탈률이 42%에서 18%로 줄었습니다. 자세한 내용은 https://example.com/aa 에 있습니다.\n",
                              "이탈률은 42%에서 18%로 줄었다. 자세한 내용: https://example.com/aa\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout.startswith("차이 없음. 보지 않은 것:"), result.stdout)
        self.assertNotIn("PASS", result.stdout)

    def test_changed_and_invented_values(self) -> None:
        result = self.compare("이탈률이 42%에서 18%로 줄었습니다. 주소는 0xAbC123def456이고 `forge test`로 확인했습니다.\n",
                              "이탈률이 크게 줄었고 사용자는 3배 늘었습니다. `forge test`로 확인했습니다.\n")
        self.assertEqual(result.returncode, 0)  # 차이가 있어도 0
        self.assertIn("원문에만 있음  수치: 42%, 18%", result.stdout)
        self.assertIn("0xAbC123def456", result.stdout)
        self.assertIn("고친 글에만 있음  수치: 3배", result.stdout)
        self.assertIn("'덜어낸 것'이나 '바꾼 점'에 적었는지 확인하고, 실수면 되돌리세요.", result.stdout)
        self.assertNotIn("원문 값으로 되돌리세요", result.stdout)
        self.assertTrue(result.stdout.strip().splitlines()[-1].startswith(NOT_SEEN))

    def test_strict(self) -> None:
        self.assertEqual(self.compare("3건", "4건", "--strict").returncode, 1)
        self.assertEqual(self.compare("3건", "3건", "--strict").returncode, 0)

    def test_json(self) -> None:
        result = self.compare("EIP-4337 기반", "ERC-4337 기반", "--json")
        data = json.loads(result.stdout)
        self.assertEqual(data["missing"], [{"category": "식별자", "value": "EIP-4337", "line": 1}])
        self.assertEqual(data["added"][0]["value"], "ERC-4337")

    def test_usage_error(self) -> None:
        self.assertEqual(run(COMPARE).returncode, 2)
        self.assertOneLineError(run(COMPARE, str(self.dir / "nope.md"), str(self.dir / "nope2.md")))

    # tooling-audit 6.1 표의 회귀 짝
    def assertCaught(self, original: str, revised: str, *expected: str) -> None:
        out = self.compare(original, revised).stdout
        self.assertNotIn("차이 없음", out)
        for text in expected:
            self.assertIn(text, out)

    def assertSame(self, original: str, revised: str) -> None:
        out = self.compare(original, revised).stdout
        self.assertTrue(out.startswith("차이 없음"), out)

    def test_regression_identifier(self) -> None:
        self.assertCaught("EIP-4337 기반 지갑", "ERC-4337 기반 지갑", "원문에만 있음  식별자: EIP-4337",
                          "고친 글에만 있음  식별자: ERC-4337")

    def test_regression_weekday(self) -> None:
        self.assertCaught("배포는 11월 18일(화) 오후 2시", "배포는 11월 18일(수) 오후 2시", "11월 18일(화)", "11월 18일(수)")

    def test_regression_direction(self) -> None:
        self.assertCaught("이탈률이 42%에서 18%로 줄었습니다.", "이탈률이 18%에서 42%로 늘었습니다.",
                          "방향이 바뀜  42%에서 18%로 → 18%에서 42%로")

    def test_regression_units(self) -> None:
        self.assertCaught("응답 820ms, 실패 30건", "응답 820초, 실패 30%", "820ms", "820초", "30건", "30%")

    def test_regression_sign(self) -> None:
        self.assertCaught("전월 대비 -5%", "전월 대비 +5%", "-5%", "+5%")

    def test_regression_names_and_email(self) -> None:
        self.assertCaught("지민 님, Arbitrum, help@example.com", "지현 님, Optimism, support@example.com",
                          "help@example.com", "support@example.com", "Arbitrum", "Optimism")

    def test_regression_quote(self) -> None:
        self.assertCaught("대표는 \"올해 안에 출시하겠다\"고 말했다.", "대표는 \"내년에 출시하겠다\"고 말했다.",
                          "올해 안에 출시하겠다")

    def test_regression_year_at_line_start(self) -> None:
        self.assertCaught("2026. 11. 18. 배포", "2027. 11. 18. 배포", "2026. 11. 18.", "2027. 11. 18.")

    def test_regression_same_value_other_notation(self) -> None:
        self.assertSame("참가자 1,000,000명", "참가자 100만 명")
        self.assertSame("오후 2시, 0.30%, 11월 05일", "14:00, 0.3%, 11월 5일")
        self.assertSame("총 1억 2,345만 6,789원", "총 123,456,789원")

    def test_regression_url_particle(self) -> None:
        self.assertSame("https://example.com/docs를 참고하세요.", "자세한 내용: https://example.com/docs")

    def test_regression_backticks_only(self) -> None:
        self.assertSame("주소는 0xAbC123def456이고 경로는 /v1/quote입니다.", "주소는 `0xAbC123def456`이고 경로는 `/v1/quote`입니다.")
        self.assertSame("`forge test --gas 30`으로 확인합니다.", "아래로 확인합니다.\n\n```bash\nforge test --gas 30\n```\n")
        self.assertSame("v2.3.1 배포", "`v2.3.1` 배포")

    def test_words_with_one_digit_are_not_numbers(self) -> None:
        self.assertSame("Web3 대중화와 L2 확장", "대중화와 확장")


# ── facts ───────────────────────────────────────────────────────
class FactsTest(TempFiles):
    def test_self_test(self) -> None:
        result = run(FACTS, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(run(WEB3, "--self-test").returncode, 0)

    def test_weekday_and_timezone(self) -> None:
        self.assertEqual(run(FACTS, "weekday", "2026-12-02").stdout.strip(), "2026년 12월 2일(수)")
        out = run(FACTS, "tz", "2026-12-31 23:59", "--from", "UTC", "--to", "KST").stdout
        self.assertIn("2027년 1월 1일(금) 08:59 KST", out)
        out = run(FACTS, "tz", "2026-12-01 오후 7시", "--from", "KST", "--to", "UTC").stdout
        self.assertIn("2026년 12월 1일(화) 10:00 UTC", out)

    def test_pct_and_numbers(self) -> None:
        self.assertTrue(run(FACTS, "pct", "1,240,000", "780,000").stdout.startswith("37.1% 감소"))
        self.assertIn("-24%p", run(FACTS, "pct", "42%", "18%").stdout)
        self.assertIn("(1억 2,345만 6,789)", run(FACTS, "num", "123456789").stdout)
        self.assertEqual(run(FACTS, "units", "1500000000000000000", "--decimals", "18").stdout.strip(), "1.5")

    def test_errors_are_one_line(self) -> None:
        self.assertOneLineError(run(FACTS, "num", "abc"))
        self.assertOneLineError(run(FACTS, "pct", "abc", "3"))
        self.assertOneLineError(run(FACTS, "weekday", "2026-13-45"))
        self.assertOneLineError(run(FACTS, "check", str(self.dir / "nope.md")))

    def test_address_checksum(self) -> None:
        good = run(FACTS, "addr", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")
        self.assertEqual(good.returncode, 0)
        bad = run(FACTS, "addr", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD")
        self.assertEqual(bad.returncode, 1)  # 주소 하나를 묻는 명령은 틀리면 1
        self.assertIn("체크섬이 맞지 않습니다", bad.stdout)
        lower = run(FACTS, "addr", "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed")
        self.assertEqual(lower.returncode, 0)
        self.assertIn("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", lower.stdout)

    def test_check_finds_wrong_weekday_and_bad_address(self) -> None:
        text = "2026년 공지\n- 일시: 12월 2일(목) 19:00 KST\n- 주소: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD\n- 다음 점검: 12월 9일(수)\n"
        path = self.write("notice.md", text)
        result = run(FACTS, "check", path, "--year", "2026")
        self.assertEqual(result.returncode, 0)  # 걸려도 0
        self.assertIn("실제 요일은 (수)", result.stdout)
        self.assertIn("체크섬이 맞지 않습니다", result.stdout)
        self.assertIn("12월 9일(수): 2026년 기준 요일이 맞습니다", result.stdout)
        self.assertNotIn("PASS", result.stdout)
        self.assertEqual(run(FACTS, "check", path, "--year", "2026", "--strict").returncode, 1)

    def check(self, text: str, *args: str) -> str:
        return run(FACTS, "check", self.write("t.md", text), *args).stdout

    def test_check_reads_more_weekday_forms(self) -> None:
        self.assertIn("실제 요일은 (수)", self.check("배포는 2026년 11월 18일 화요일 오후 2시입니다.\n"))
        self.assertIn("실제 요일은 (수)", self.check("배포는 2026년 11월 18일(화요일) 오후 2시입니다.\n"))
        self.assertIn("11/18(화): 2026년 기준 실제 요일은 (수)", self.check("배포 11/18(화)\n", "--year", "2026"))
        both = self.check("행사: 2026년 12월 1일(화)~3일(수)\n")
        self.assertIn("12월 1일(화): 2026년 기준 요일이 맞습니다", both)
        self.assertIn("3일(수)(범위의 둘째 날): 2026년 기준 실제 요일은 (목)", both)

    def test_check_uses_only_the_same_sentence_year(self) -> None:
        out = self.check("2025년 실적을 정리했습니다. 다음 회의는 1월 6일(화)입니다.\n", "--year", "2026")
        self.assertIn("1월 6일(화): 2026년 기준 요일이 맞습니다", out)

    def test_check_offers_year_candidates(self) -> None:
        out = self.check("다음 회의는 11월 18일(화)입니다.\n")
        self.assertIn("연도가 없습니다", out)
        this_year = datetime.date.today().year
        fits = [y for y in (this_year - 1, this_year, this_year + 1) if datetime.date(y, 11, 18).weekday() == 1]
        for year in fits:
            self.assertIn(f"{year}년", out)
        self.assertIn("--year", out)

    def test_verify_added_percentages(self) -> None:
        original = self.write("o.md", "가스 사용량이 약 1,240,000에서 약 780,000으로 줄었습니다. 마감은 23:59(UTC)입니다.\n")
        revised = self.write("r.md", "가스 사용량이 37.1% 줄었고 처리량은 50% 늘었습니다. 마감은 한국 시간 오전 8시 59분입니다.\n")
        out = run(FACTS, "verify", original, revised).stdout
        self.assertIn("설명됨  37.1%", out)
        self.assertIn("설명 안 됨  50%", out)
        self.assertIn("23:59 UTC", out)


# ── rules ───────────────────────────────────────────────────────
class RulesTest(TempFiles):
    """피드백 → 후보 → 활성 승격 → rules check 적용 → 보관 흐름을 명령줄로 확인한다."""

    def rules(self, *args: str, cwd: Path | None = None, stdin: str | None = None,
              home: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        return run(RULES, *args, home=home or self.dir / "home", cwd=cwd or self.dir, stdin=stdin, env=env)

    def lint(self, *args: str) -> str:
        return run(LINT, *args, home=self.dir / "home", cwd=self.dir).stdout

    def test_self_test(self) -> None:
        result = run(RULES, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_feedback_becomes_active_on_repeat(self) -> None:
        first = self.rules("add", "avoid", "말씀드리겠습니다", "--suggest", "말씀드릴게요", "--scope", "chat")
        self.assertIn("후보로 저장", first.stdout)
        draft = self.write("chat.md", "내일 다시 말씀드리겠습니다.\n다음 주에 말씀 드리겠습니다.\n")
        self.assertIn("활성 avoid 규칙이 없습니다", self.rules("check", draft).stdout)  # 후보는 아직 적용하지 않는다
        rid = first.stdout.split(": ", 1)[1].split()[0]
        second = self.rules("hit", rid)
        self.assertIn("활성 규칙으로 올림", second.stdout)
        out = self.rules("check", draft, "--scope", "메신저").stdout
        self.assertIn(f"사용자 규칙 {rid}  1행", out)
        self.assertIn(f"사용자 규칙 {rid}  2행", out)  # 띄어쓰기가 달라도 잡는다
        self.assertNotIn("사용자 규칙", self.rules("check", draft, "--scope", "email").stdout)  # 다른 글 종류에는 적용하지 않는다
        self.assertEqual(self.rules("check", draft, "--scope", "chat").returncode, 0)
        self.assertEqual(self.rules("check", draft, "--scope", "chat", "--strict").returncode, 1)
        self.assertNotIn("사용자 규칙", self.lint(draft))  # lint는 사용자 규칙 점검을 rules check에 맡긴다
        self.rules("retire", rid)
        self.assertNotIn("사용자 규칙", self.rules("check", draft).stdout)

    def test_keep_rule_silences_only_its_own_span(self) -> None:
        self.rules("add", "keep", "혁신적인", "--note", "회사 슬로건", "--activate")
        draft = self.write("intro.md", "혁신적인 지갑을 소개합니다.\n혁신적인 게임 체인저 지갑입니다.\n")
        out = self.lint(draft)
        self.assertNotIn("intro.md:1", out)
        self.assertIn("intro.md:2", out)  # '게임 체인저'는 keep 규칙에 없으므로 그대로 경고한다

    def test_team_rules_found_from_subfolder(self) -> None:
        repo = self.dir / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "docs").mkdir()
        self.rules("add", "keep", "온체인", "--project", "--activate", cwd=repo / "docs")
        saved = json.loads((repo / ".ko-tone" / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["rules"][0]["pattern"], "온체인")
        listed = self.rules("list", cwd=repo).stdout
        self.assertIn("팀", listed)
        self.assertIn("온체인", listed)

    def test_errors(self) -> None:
        self.assertEqual(self.rules("retire", "nope").returncode, 2)
        self.assertEqual(self.rules("add", "avoid", "re:(").returncode, 2)
        self.assertEqual(self.rules("add", "avoid", "x", "--scope", "[깨진]").returncode, 2)

    def test_free_and_korean_scope_names(self) -> None:
        for scope, key in (("report", "report"), ("회의록", "minutes"), ("슬랙", "chat"), ("사내 위키", "사내 위키")):
            result = self.rules("add", "style", f"{scope} 규칙", "--scope", scope)
            self.assertEqual(result.returncode, 0, result.stderr)
        scopes = {r["pattern"]: r["scope"] for r in json.loads(self.rules("list", "--status", "all", "--json").stdout)}
        self.assertEqual(scopes, {"report 규칙": "report", "회의록 규칙": "minutes", "슬랙 규칙": "chat",
                                  "사내 위키 규칙": "사내 위키"})
        listed = self.rules("list", "--status", "all", "--scope", "회의록").stdout
        self.assertIn("[회의록] 회의록 규칙", listed)
        self.assertNotIn("슬랙 규칙", listed)

    def test_export_matches_skill_block_and_round_trips(self) -> None:
        self.rules("add", "avoid", "말씀드리겠습니다", "--suggest", "말씀드릴게요", "--scope", "chat")
        self.rules("add", "keep", "온체인", "--activate", "--note", "팀 용어")
        self.rules("add", "style", "투자자 메일은 합쇼체로", "--scope", "email", "--note", "대표 요청", "--activate")
        self.rules("add", "avoid", "금일", "--scope", "사내 위키")
        first = json.loads(self.rules("list", "--status", "all", "--json").stdout)[0]["id"]
        self.rules("hit", first)  # 횟수 2가 export --all에 실려 되살아나는지 본다
        plain = self.rules("export").stdout
        lines = plain.splitlines()
        self.assertEqual(lines[0], "# ko-tone 사용자 규칙")
        self.assertEqual(lines[1], "아래 규칙은 ko-tone의 기본 규칙보다 먼저 적용한다. "
                                   "원문의 수치, 날짜, 이름, 코드는 규칙과 상관없이 바꾸지 않는다.")
        self.assertTrue(all(line.startswith("- [") for line in lines[2:]), plain)
        self.assertNotIn("(후보)", plain)  # 활성 규칙만
        full = self.rules("export", "--all").stdout
        self.assertIn("- [메신저] '말씀드리겠습니다' 쓰지 않기 → '말씀드릴게요' (후보) <!-- id:", full)
        self.assertIn("- [사내 위키] '금일' 쓰지 않기 (후보)", full)
        other = self.dir / "other-home"
        imported = self.rules("import", "-", stdin=full, home=other)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertNotIn("읽지 못한 줄", imported.stdout)
        self.assertEqual(self.rules("export", "--all", home=other).stdout, full)  # 횟수와 상태까지 되살린다

    def test_import_hand_written_list(self) -> None:
        text = ("# ko-tone 사용자 규칙\n아래 규칙은 …\n"
                "- [메일] '말씀 드리겠습니다' 쓰지 않기 → '말씀드릴게요'\n"
                "- [슬랙] 해요체로 쓴다 (후보)\n"
                "- [회고] 'Web3'은(는) 고치지 않기\n"
                "- [사내 위키] 문단은 세 문장 이하 (후보)\n"
                "- [깨진 줄\n")
        result = self.rules("import", self.write("list.md", text))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("읽지 못한 줄: - [깨진 줄", result.stdout)
        rules = {r["pattern"]: r for r in json.loads(self.rules("list", "--status", "all", "--json").stdout)}
        self.assertEqual((rules["말씀 드리겠습니다"]["kind"], rules["말씀 드리겠습니다"]["scope"],
                          rules["말씀 드리겠습니다"]["status"], rules["말씀 드리겠습니다"]["suggest"]),
                         ("avoid", "email", "active", "말씀드릴게요"))
        self.assertEqual((rules["해요체로 쓴다"]["kind"], rules["해요체로 쓴다"]["scope"], rules["해요체로 쓴다"]["status"]),
                         ("style", "chat", "candidate"))
        self.assertEqual((rules["Web3"]["kind"], rules["Web3"]["scope"]), ("keep", "blog"))
        self.assertEqual(rules["문단은 세 문장 이하"]["scope"], "사내 위키")
        again = self.rules("import", "-", stdin="- [슬랙] 해요체로 쓴다\n")  # 같은 규칙이면 횟수를 올린다
        self.assertIn("이미 있어 횟수 올림", again.stdout)
        rules = {r["pattern"]: r for r in json.loads(self.rules("list", "--status", "all", "--json").stdout)}
        self.assertEqual((rules["해요체로 쓴다"]["count"], rules["해요체로 쓴다"]["status"]), (2, "active"))

    def test_avoid_keep_conflict_warning(self) -> None:
        self.rules("add", "keep", "혁신적인", "--activate")
        result = self.rules("add", "avoid", "혁신적인")
        self.assertIn("경고: 같은 표현이 keep 규칙", result.stdout)
        self.assertNotIn("경고", self.rules("add", "avoid", "획기적인").stdout)

    def test_temporary_location_warning(self) -> None:
        # 테스트 폴더는 임시 폴더 아래이므로 add, list, path가 알린다
        for args in (("add", "avoid", "금일"), ("list",), ("path",)):
            self.assertIn(TEMP_WARNING, self.rules(*args).stdout, args)
        # 임시 폴더가 다른 곳이면 알리지 않는다
        tmp = self.dir / "elsewhere"
        tmp.mkdir()
        env = {"TMPDIR": str(tmp), "TEMP": str(tmp), "TMP": str(tmp)}
        self.assertNotIn(TEMP_WARNING, self.rules("list", env=env).stdout)

    def test_broken_rules_file(self) -> None:
        home = self.dir / "home"
        home.mkdir()
        (home / "rules.json").write_text("{깨진", encoding="utf-8")
        result = self.rules("list")
        self.assertOneLineError(result)
        self.assertIn("규칙 파일이 깨졌습니다", result.stderr)
        self.assertIn("옮긴 뒤 다시 실행하세요", result.stderr)


# ── check ───────────────────────────────────────────────────────
ORIGINAL = """사내 배포 안내드립니다. 배포는 2026년 11월 18일 화요일 오후 2시부터 약 1시간 동안 진행합니다.
가스 사용량이 1,240,000에서 780,000으로 줄었고, 대상 표준은 EIP-4337입니다.
오늘날 이 변화는 혁신적인 변화입니다.
"""
REVISED = """배포 안내

- 일시: 2026년 11월 18일(수) 오후 2시부터 약 1시간
- 가스 사용량: 37.1% 감소(1,240,000 → 780,000)
- 표준: ERC-4337
- 문의: [문의 채널]

이 변화는 혁신적인 게임 체인저입니다.
"""


class CheckTest(TempFiles):
    def check(self, *args: str, original: str = ORIGINAL, revised: str = REVISED,
              home: Path | None = None) -> subprocess.CompletedProcess:
        return run(CHECK, self.write("o.md", original), self.write("r.md", revised), *args,
                   home=home or self.dir / "home", cwd=self.dir)

    def test_default_output(self) -> None:
        result = self.check()
        out = result.stdout
        self.assertEqual(result.returncode, 0, result.stderr)  # 걸려도 0
        lines = out.strip().splitlines()
        self.assertTrue(lines[0].startswith("참고: 길이 "))
        self.assertTrue(lines[-1].startswith("보지 않은 것: 관계, 확정·예정 표시"))
        self.assertLessEqual(len(lines), 20)
        self.assertNotIn("PASS", out)
        self.assertIn("[값] 원문에만 있음  식별자 EIP-4337", out)
        self.assertIn("[값] 고친 글에만 있음  식별자 ERC-4337", out)
        self.assertIn("[환산] 설명됨  37.1%", out)
        self.assertIn("[원문의 오류] 원문 1행 2026년 11월 18일 화요일: 2026년 기준 실제 요일은 (수)", out)
        for absent in ("[표현]", "[빈칸]", "[틀]", "[겹침]", "높임", "홍보 문구"):
            self.assertNotIn(absent, out)  # 문체 경고와 실험 항목은 기본 출력에 없다

    def test_strict_and_usage(self) -> None:
        self.assertEqual(self.check("--strict").returncode, 1)
        self.assertEqual(self.check("--strict", original="3건입니다.\n", revised="3건입니다.\n").returncode, 0)
        clean = self.check(original="3건입니다.\n", revised="3건입니다.\n").stdout
        self.assertIn("걸린 곳 없음.", clean)
        self.assertEqual(run(CHECK).returncode, 2)
        self.assertEqual(run(CHECK, str(self.dir / "nope.md"), str(self.dir / "nope2.md")).returncode, 2)

    def test_style_and_experimental(self) -> None:
        out = self.check("--style").stdout
        self.assertIn("[표현]", out)
        exp = self.check("--experimental",
                         original="하는 일은 세 가지입니다.\n- 가\n- 나\n- 다\n",
                         revised="하는 일은 세 가지입니다.\n- 가\n- 나\n- 다\n- 문의: [문의 채널]\n\n"
                                 "앞에서 \"검토를 진행하였습니다\"라고 썼고, 뒤에서 \"검토를 진행했습니다\"라고 썼다.\n"
                                 "다시 보면\n\"검토를 진행하였습니다\" 대신\n\"검토를 진행했습니다\"로 적었다.\n").stdout
        self.assertIn("[틀]", exp)
        self.assertIn("[빈칸] 5행", exp)
        self.assertIn("[겹침]", exp)

    def test_output_is_capped(self) -> None:
        original = "\n".join(f"항목 {i}: {i * 7}건, 코드 AB-{1000 + i}" for i in range(1, 30)) + "\n"
        revised = "항목은 모두 정리했습니다.\n"
        lines = self.check(original=original, revised=revised).stdout.strip().splitlines()
        self.assertLessEqual(len(lines), 20)
        self.assertTrue(any("--json으로 전체" in line for line in lines))
        data = json.loads(self.check("--json", original=original, revised=revised).stdout)
        self.assertGreater(len(data["values"]), 20)

    def test_user_rules_and_keep(self) -> None:
        home = self.dir / "home"
        run(RULES, "add", "avoid", "게임 체인저", "--activate", home=home, cwd=self.dir)
        out = self.check(home=home).stdout
        self.assertIn("[사용자 규칙]", out)
        self.assertIn("게임 체인저", out)
        # keep 규칙에 걸린 표현은 [값]이 고칠 것으로 내지 않는다
        run(RULES, "add", "keep", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD", "--activate", home=home, cwd=self.dir)
        text = "보낼 곳: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD\n"
        kept = self.check(original=text, revised=text, home=home).stdout
        self.assertNotIn("체크섬", kept)
        fresh = self.check(original=text, revised=text, home=self.dir / "fresh").stdout
        self.assertIn("[값] 원문 체크섬  주소 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD", fresh)
        run(RULES, "add", "keep", "EIP-4337", "--activate", home=home, cwd=self.dir)
        same = self.check(original="EIP-4337 기반입니다.\n", revised="EIP-4337 기반이에요.\n", home=home).stdout
        self.assertNotIn("[값]", same)
        changed = self.check(original="EIP-4337 기반입니다.\n", revised="ERC-4337 기반이에요.\n", home=home).stdout
        self.assertIn("EIP-4337 (keep 규칙: 고치지 말 표현)", changed)


if __name__ == "__main__":
    unittest.main()
