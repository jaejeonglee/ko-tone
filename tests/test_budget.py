"""스킬 문안의 예산·위생 검사(tools/skill_budget.py)를 테스트로 돌린다.

검사마다 테스트 하나라서, 실패하면 어느 검사를 어겼는지와 어긴 곳이 그대로 보인다.
실행: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "skill_budget.py"
_spec = importlib.util.spec_from_file_location("skill_budget", TOOL)
budget = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(budget)


class BudgetTest(unittest.TestCase):
    def assertNoProblems(self, problems: list) -> None:
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:30]))

    def test_1_sizes(self) -> None:
        self.assertNoProblems(budget.check_sizes())

    def test_2_no_web3_lines(self) -> None:
        self.assertNoProblems(budget.check_web3())

    def test_3_no_4gram_overlap_with_dev_material(self) -> None:
        self.assertNoProblems(budget.check_overlap())

    def test_4_no_quoted_examples_in_result_format(self) -> None:
        self.assertNoProblems(budget.check_result_format())

    def test_5_pattern_examples_add_no_values(self) -> None:
        self.assertNoProblems(budget.check_patterns_examples())

    def test_6_kind_lists_match(self) -> None:
        self.assertNoProblems(budget.check_kind_lists())


class BudgetToolTest(unittest.TestCase):
    """검사 도구 자체가 어긴 곳을 잡는지 확인한다(문안이 바뀌어도 도구가 헛돌지 않게)."""

    def test_frontmatter_and_sections(self) -> None:
        text = "---\nname: x\n---\n# 제목\n## 3. 셋\n가\n## 4. 넷\n나나\n```\n# 코드 속 제목\n```\n다\n## 5. 다섯\n라\n"
        body = budget.strip_frontmatter(text)
        self.assertTrue(body.startswith("# 제목"))
        self.assertNotIn("나나", budget.without_sections(body, (4,)))
        self.assertNotIn("코드 속", budget.without_sections(body, (4,)))  # 코드 블록 속 '#'은 제목이 아니다
        self.assertIn("라", budget.without_sections(body, (4,)))
        self.assertEqual(budget.section(body, "## 3.").strip(), "가")

    def test_web3_pattern(self) -> None:
        for line in ("지갑을 연결하세요", "EIP-4337 기반", "가스비가 오르면", "0x5aAe 주소"):
            self.assertTrue(budget.WEB3.search(line), line)
        for line in ("게임 체인저", "프랜차이즈 체인점", "ERCOT 아님", "Excel 파일"):
            self.assertFalse(budget.WEB3.search(line), line)

    def test_quoted_examples(self) -> None:
        self.assertEqual(budget.quoted_examples("'바꾼 점'과 '확인해 주세요'에 적는다"), [])
        self.assertEqual(budget.quoted_examples("\"규칙을 후보로 저장했습니다.\"처럼 쓴다"), ["규칙을 후보로 저장했습니다."])

    def test_grams_ignore_markdown_symbols(self) -> None:
        self.assertEqual(budget.tokens("| --- | --- | **굵게** `코드` https://a.b/c 끝"), ["굵게", "끝"])
        self.assertEqual(len(budget.grams(["가", "나", "다", "라", "마"])), 2)

    def test_tables(self) -> None:
        found = budget.tables("| 원문 | 고친 예 |\n| --- | --- |\n| 3건 | 5건 Zoom |\n")
        self.assertEqual(found, [(["원문", "고친 예"], [["3건", "5건 Zoom"]])])


if __name__ == "__main__":
    unittest.main()
