#!/usr/bin/env python3
"""한국어 원고에서 문맥을 보고 다시 판단할 표현 후보를 찾는다.

oil-tone(https://github.com/oil-oil/oil-tone, MIT)의 tone_lint.py 구조
(코드 블록 제외 → 줄 단위 정규식 경고 → 자체 테스트)를 바탕으로,
한국어 패턴과 문서 단위 점검(높임 수준 혼용, 같은 종결 반복)을 새로 작성했다.

동작 원리
1. visible_lines(): 코드 블록(```), <script>/<style>, HTML 태그, 인라인 코드(`...`)를
   지우고 사람이 읽는 텍스트 줄만 (줄 번호, 텍스트)로 남긴다.
2. LINE_RULES: 줄마다 정규식 규칙을 대조해 걸리면 안내 문구와 함께 경고한다.
3. 문서 단위 점검: 제목·목록·표·인용을 뺀 본문 문장만 모아
   - 문장 끝 어미로 높임 수준(합쇼체/해요체/평어체)을 분류해 두 가지 이상이 섞였는지,
   - 같은 종결(끝 6글자)이 3문장 이상 연달아 나오는지 본다.
4. 사용자 규칙(ko_tone_rules.py): 활성 avoid 규칙에 걸리는 줄을 경고하고,
   활성 keep 규칙으로 정한 표현에만 걸린 기본 경고는 내지 않는다. --no-user-rules로 끌 수 있다.

경고는 '다시 볼 후보'일 뿐이며 고칠지는 문맥을 보고 정한다.
그래서 종료 코드는 항상 0이다(--self-test 실패 시에만 1).
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import Counter
from pathlib import Path

if sys.version_info < (3, 9):  # 아래 타입 표기(tuple[...])가 3.9부터 동작한다
    sys.exit("Python 3.9 이상이 필요합니다.")

Rule = tuple[re.Pattern[str], str]
Hint = tuple[int, str, str]  # (줄 번호, 해당 텍스트, 안내 문구)


# ── 줄 단위 규칙 ─────────────────────────────────────────────
# 정밀도를 우선한다. 흔히 정상적으로 쓰이는 표현은 넣지 않거나,
# 안내 문구에 "유지해도 되는 경우"를 함께 적는다.
LINE_RULES: tuple[Rule, ...] = (
    # 1. 번역투
    (re.compile(r"에 있어서|(?:함|기|것)에 있어"),
     "'~에 있어서'는 영어 직역투입니다. '~에서', '~할 때'로 바꿀 수 있는지 확인하세요."),
    (re.compile(r"에 의해서?"),
     "행위자가 분명하면 능동문('A가 B를 ~한다')으로 바꿀 수 있는지 확인하세요."),
    (re.compile(r"[을를] 통(?:해|하여)서?"),
     "수단·경로가 분명하면 유지해도 됩니다. '~로', '~해서'로 더 짧게 쓸 수 있는지 확인하세요."),
    (re.compile(r"하는 중에 있"),
     "'~하는 중에 있다'는 '~하고 있다'로 줄일 수 있습니다."),
    # '~적인/~적으로'가 한 줄에 3번 이상: 게으른 매칭(*?)과 고정 반복{2}로 역추적 폭주를 막는다.
    (re.compile(r"[가-힣]적(?:인|으로|이고|이며)(?:[^.!?]*?[가-힣]적(?:인|으로|이고|이며)){2}"),
     "'~적' 수식이 몰려 있습니다. 실제 방법이나 결과로 바꿀 수 있는지 확인하세요."),

    # 2. 돌려 말하는 동사·이중 피동
    (re.compile(r"(?:되어|보여|쓰여|잊혀)(?:지|진|져|졌|짐|집)"),
     "이중 피동입니다. '되다', '보이다', '쓰이다', '잊히다'로 고치세요."),
    (re.compile(r"(?:검토|논의|회의|미팅|테스트|배포|업데이트|개발|분석|점검|작업|조사|확인|교육|인터뷰|리뷰|검증|구현)"
                r"[을를] (?:진행|수행)"),
     "'~를 진행/수행하다' 대신 '~하다'로 바로 쓸 수 있는지 확인하세요."),
    (re.compile(r"(?:회의|미팅|시간|자리|간담회|논의|대화)[을를] 가(?:졌|지|진|집|질|져)"),
     "영어 have 직역입니다. '회의했다', '이야기했다'처럼 동사로 쓰세요."),
    (re.compile(r"[이가] 이루어(?:졌|지|집|질|져|진)"),
     "누가 무엇을 했는지 능동으로 쓸 수 있는지 확인하세요."),

    # 3. 빈말
    (re.compile(r"급변하는|빠르게 변화하는|급속도로 발전하는|빠르게 발전하는|디지털 전환 시대|4차 산업혁명|(?:^|[.!?] )오늘날"),
     "정보 없는 시대 배경인지 확인하세요. 아니면 바로 본론으로 들어갑니다."),
    (re.compile(r"[이가] (?:가속화|본격화|대두)되(?:면서|고 있)"),
     "배경 설명이 뒤 내용과 구체적으로 이어지는지 확인하세요."),
    (re.compile(r"전문가들?(?:은|이|에 따르면)|업계에서는|업계 관계자|입을 모"),
     "자료에 출처가 있으면 이름을 쓰고, 없으면 모호한 출처를 지우세요."),
    (re.compile(r"(?:많은|다수의|상당수의?|일부) (?:사용자|이용자|사람|개발자|고객)들?[이가은는] [^.!?]{0,20}"
                r"(?:평가|반응|호평|만족|말한|말합|이야기)"),
     "사용자 반응에 근거 자료가 있는지 확인하세요."),
    (re.compile(r"연구(?:에 따르면|결과에 따르면|들에서)"),
     "연구 출처를 자료에서 찾아 밝히세요. 없으면 출처를 지어내지 말고 문장을 지우세요."),
    (re.compile(r"중요한 역할을|핵심적인 역할|아무리 강조해도 지나치지 않|(?:것이|게) (?:매우 )?중요(?:합니다|하다|해요)|의 중요성"),
     "중요하다는 주장 대신 무엇이 어떻게 달라지는지 쓸 수 있는지 확인하세요."),
    (re.compile(r"혁신적|획기적|게임 ?체인저|패러다임|시너지|새로운 지평|차원이 다른|판도를 바꾸|압도적인|독보적인"),
     "홍보 문구입니다. 기능, 조건, 수치로 바꿀 수 있는지 확인하세요."),
    (re.compile(r"앞으로(?:가|의 [가-힣]{1,6}[이가])? (?:더욱 |더 )?기대(?:됩|된|되|합)|미래가 (?:더욱 )?(?:기대|밝)|새로운 장을 (?:열|여)"
                r"|첫걸음을 (?:내딛|뗐|떼)|무한한 가능성|가능성을 (?:보여|열어|제시)|한 단계 도약|귀추가 주목"),
     "상투적인 결말입니다. 지우거나 실제 결과·다음 일정으로 바꾸세요."),

    # 4. AI 수사 습관
    (re.compile(r"단순(?:히|한)[^.!?]{0,30}아니(?:라|다)|선택이 아닌 필수"),
     "'단순한 X가 아니라 Y' 꼴의 부정 병렬입니다. Y를 근거와 함께 바로 쓰세요."),
    (re.compile(r"(?:^|[.!?] )(?:결론적으로|요약하자면|요약하면|종합하자면|종합하면|정리하자면|이처럼|이와 같이|이렇듯)"),
     "새 정보 없는 요약 문단인지 확인하세요."),
    (re.compile(r"(?:^|[.!?] )(?:그렇다면|그럼|과연)[^.!?]{0,40}(?:까요|가요)\?"),
     "질문형 전환 대신 답을 바로 쓸 수 있는지 확인하세요."),
    (re.compile(r"[—―]"),
     "줄표는 한국어 글에서 드뭅니다. 쉼표, 괄호, 문장 나누기로 바꿀 수 있는지 확인하세요."),
    (re.compile(r"^#{1,6} [^:：]+[:：] \S"),
     "콜론으로 문구를 덧붙인 제목입니다. 제목이 내용을 바로 말하는지 확인하세요."),
    (re.compile(r"^(?:[-*+] |\d+\. )?\s*(?:✅|🚀|💡|👉|✨|🔥|📌|🎯|⚡|🌟|📈|🛠|🔑|💪|🙌)"),
     "이모지 불릿입니다. 글의 성격(문서·보고·공지)에 맞는지 확인하세요."),

    # 5. 완충 표현·과잉 겸양
    (re.compile(r"수 있을 (?:것|듯)|(?:라고|다고) (?:할|볼) 수 있|것으로 (?:보입니다|보인다|보여요|사료|판단됩니다|예상됩니다)"),
     "완충 표현이 겹쳤는지 확인하세요. 사실 상태에 맞는 하나만 남깁니다."),
    (re.compile(r"(?:하도록|드리도록|할 수 있도록|드릴 수 있도록) 하겠습니다"),
     "'~하겠습니다'로 줄일 수 있습니다."),

    # 6. 챗봇 말투
    (re.compile(r"좋은 질문|훌륭한 질문|(?:^|[.!?] )물론(?:입니다|이죠)|도움이 (?:되었|되셨|됐|되)(?:으면|길) (?:좋겠|바랍)"
                r"|궁금한 (?:점|사항)이 (?:있으시면|있다면|있으면)|언제든(?:지)? (?:말씀|문의|물어)"),
     "독자에게 가는 글에 남은 챗봇 말투입니다. 지우세요."),

    # 8. 표기
    (re.compile(r"을\(를\)|를\(을\)|이\(가\)|가\(이\)|은\(는\)|는\(은\)|과\(와\)|와\(과\)|으로\(로\)|로\(으로\)"),
     "조사를 함께 적었습니다. 앞말 발음의 받침에 맞는 조사 하나만 쓰세요."),
)


# ── 텍스트 추출 ──────────────────────────────────────────────
def read_text(name: str) -> str:
    return sys.stdin.read() if name == "-" else Path(name).read_text(encoding="utf-8")


def visible_lines(text: str) -> list[tuple[int, str]]:
    """사람이 읽는 텍스트 줄만 (줄 번호, 텍스트)로 돌려준다."""
    lines: list[tuple[int, str]] = []
    in_fence = False
    in_script = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.strip().startswith("```"):  # 코드 블록 경계: 안쪽은 검사하지 않는다
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if re.search(r"<(script|style)\b", raw, flags=re.IGNORECASE):
            in_script = True
        if in_script:
            if re.search(r"</(script|style)>", raw, flags=re.IGNORECASE):
                in_script = False
            continue
        without_tags = re.sub(r"<[^>]+>", " ", raw)
        without_code = re.sub(r"`[^`]*`", " ", without_tags)  # 인라인 코드 제거
        visible = html.unescape(re.sub(r"\s+", " ", without_code)).strip()
        if visible:
            lines.append((number, visible))
    return lines


# ── 줄 단위 점검 ─────────────────────────────────────────────
def find_line_hints(lines: list[tuple[int, str]], keep: tuple[re.Pattern[str], ...] = ()) -> list[Hint]:
    hints: list[Hint] = []
    for line_number, line in lines:
        # 사용자가 '고치지 말 표현(keep)'으로 정한 구간. 기본 규칙이 이 구간에만 걸렸다면 경고하지 않는다.
        kept = [m.span() for k in keep for m in k.finditer(line)]
        for pattern, fix in LINE_RULES:
            spans = [m.span() for m in pattern.finditer(line)]
            if spans and not all(any(start < k_end and k_start < end for k_start, k_end in kept) for start, end in spans):
                hints.append((line_number, line, fix))
    return hints


# ── 문서 단위 점검 ───────────────────────────────────────────
# 제목(#), 목록(-, *, +, 1.), 표(|), 인용(>)은 관행상 종결이 달라도 되므로 본문에서 뺀다.
NON_PROSE = re.compile(r"^(?:#|[-*+] |\d+[.)] |\||>)")
# 마침표 뒤에 공백이 올 때만 문장을 나눈다. 그래야 3.5%, v1.2 같은 숫자가 쪼개지지 않는다.
SENTENCE_BREAK = re.compile(r"(?<=[.!?。])\s+")
TRAILING = " .!?。…~\"'”’)」』"


def prose_sentences(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    sentences: list[tuple[int, str]] = []
    for line_number, line in lines:
        if NON_PROSE.match(line):
            continue
        for part in SENTENCE_BREAK.split(line):
            part = part.strip()
            if part:
                sentences.append((line_number, part))
    return sentences


def speech_level(sentence: str) -> str | None:
    """문장 끝 어미로 높임 수준을 분류한다. 분류할 수 없으면 None."""
    tail = sentence.rstrip(TRAILING)
    # '~해 주세요', '~하세요' 같은 요청은 합쇼체 공지에서도 흔히 섞어 쓰므로 어느 쪽에도 세지 않는다.
    if re.search(r"세요$", tail):
        return None
    if re.search(r"(?:니다|니까|십시오|시오)$", tail):  # -습니다/-ㅂ니다/-습니까
        return "합쇼체"
    if re.search(r"(?:(?<!필)요|죠)$", tail):  # -요/-죠 ('필요'로 끝나는 개조식은 제외)
        return "해요체"
    if re.search(r"(?:다|냐|자|라)$", tail):  # -다/-냐/-자/-라 (니다는 위에서 걸러짐)
        return "평어체"
    return None


def find_mixed_levels(sentences: list[tuple[int, str]]) -> list[Hint]:
    levels = [(n, s, speech_level(s)) for n, s in sentences]
    counts = Counter(level for _, _, level in levels if level)
    used = [level for level, count in counts.items() if count >= 2]
    if len(used) < 2:
        return []
    main_level = counts.most_common(1)[0][0]
    minority = [(n, s) for n, s, level in levels if level and level != main_level]
    summary = ", ".join(f"{level} {count}문장" for level, count in counts.most_common())
    where = ", ".join(str(n) for n, _ in minority[:5])
    first_line, first_sentence = minority[0]
    return [(first_line, first_sentence,
             f"높임 수준이 섞여 있습니다({summary}). 주된 문체({main_level})와 다른 문장이 있는 줄: {where}. "
             "인용이나 의도한 전환이 아니면 하나로 통일하세요.")]


def find_repeated_endings(sentences: list[tuple[int, str]], run_length: int = 3) -> list[Hint]:
    hints: list[Hint] = []
    run: list[tuple[int, str]] = []
    previous_key: str | None = None
    for line_number, sentence in sentences + [(0, "")]:  # 끝에 빈 문장을 넣어 마지막 연속 구간도 처리
        tail = sentence.rstrip(TRAILING)
        key = tail[-6:] if len(tail) >= 6 else None  # 끝 6글자: '수 있습니다', '것이 중요합니다' 등
        if key is not None and key == previous_key:
            run.append((line_number, sentence))
        else:
            if len(run) >= run_length:
                n, s = run[run_length - 1]
                hints.append((n, s, f"같은 종결 '…{previous_key}'가 {len(run)}문장 연속으로 나옵니다. "
                                    "문장을 합치거나 구조를 바꿀 수 있는지 확인하세요."))
            run = [(line_number, sentence)] if key is not None else []
        previous_key = key
    return hints


def find_hints(text: str, avoid: tuple[Rule, ...] = (), keep: tuple[re.Pattern[str], ...] = ()) -> list[Hint]:
    lines = visible_lines(text)
    sentences = prose_sentences(lines)
    hints = find_line_hints(lines, keep) + find_mixed_levels(sentences) + find_repeated_endings(sentences)
    for line_number, line in lines:  # 사용자 피드백으로 쌓인 활성 avoid 규칙
        for pattern, fix in avoid:
            if pattern.search(line):
                hints.append((line_number, line, fix))
    return sorted(hints, key=lambda hint: hint[0])


def load_user_rules(scope: str | None = None) -> tuple[tuple[Rule, ...], tuple[re.Pattern[str], ...]]:
    """ko_tone_rules.py에서 활성 (avoid 규칙, keep 패턴)을 불러온다.
    규칙 파일이 없으면 빈 목록이고, 깨졌으면 알리고 기본 규칙만 쓴다."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ko_tone_rules", Path(__file__).with_name("ko_tone_rules.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return tuple(module.lint_patterns(scope)), tuple(module.keep_patterns(scope))
    except Exception as exc:  # 사용자 규칙 문제로 기본 검사가 멈추지 않게 한다
        print(f"NOTE  사용자 규칙을 읽지 못해 기본 규칙만 씁니다: {exc}", file=sys.stderr)
        return (), ()


# ── 자체 테스트 ──────────────────────────────────────────────
def self_test() -> int:
    bad_lines = (
        "보안 감사에 있어서 가장 중요한 것은 범위를 정하는 일이다.",
        "트랜잭션은 시퀀서에 의해 정렬된다.",
        "API를 통해 잔액을 조회한다.",
        "현재 마이그레이션을 하는 중에 있습니다.",
        "체계적이고 효율적이며 전략적인 접근이 필요하다.",
        "업데이트가 완료되어졌습니다.",
        "어제 코드 리뷰를 진행했습니다.",
        "오후에 팀 회의를 가졌습니다.",
        "성능 개선이 이루어졌습니다.",
        "급변하는 디지털 시대에 보안은 필수다.",
        "업계 전문가들은 L2가 대세라고 입을 모은다.",
        "많은 사용자들이 새 UI를 호평하고 있다.",
        "최근 연구에 따르면 이 방식이 더 빠르다.",
        "이 브리지는 생태계 확장에 중요한 역할을 합니다.",
        "혁신적인 게임 체인저 솔루션을 소개합니다.",
        "앞으로의 행보가 더욱 기대됩니다.",
        "이것은 단순한 지갑이 아니라 새로운 금융 경험입니다.",
        "이처럼 보안 감사는 프로젝트의 핵심 요소입니다.",
        "그렇다면 왜 이런 문제가 생길까요?",
        "새 버전은 — 예상대로 — 더 빠르다.",
        "## 가스비 최적화: 작은 차이가 만드는 큰 변화",
        "- ✅ 배포 완료",
        "수수료가 줄어들 수 있을 것으로 보입니다.",
        "내일까지 확인해 드릴 수 있도록 하겠습니다.",
        "도움이 되셨길 바랍니다.",
        "토큰을(를) 스왑합니다.",
        "보안은 아무리 강조해도 지나치지 않습니다.",
        "배포를 마쳤습니다. 그렇다면 다음 단계는 무엇일까요?",
        "앞으로의 발전이 더욱 기대됩니다.",
    )
    good_lines = (
        "2026년 3월 업그레이드 뒤 구버전 지갑은 서명이 실패한다.",
        "감사 보고서에서 재진입 취약점 2건이 확인됐고, 둘 다 수정했습니다.",
        "가스비가 오르면서 사용자가 줄었고, 그래서 L2로 옮겼다.",
        "이 함수는 잔액이 0이면 트랜잭션을 되돌린다.",
        "Ethereum을 기준으로 수수료를 계산합니다.",
        "배포는 금요일 오후 3시(KST)에 합니다.",
        "수수료가 약 30% 줄었습니다.",
        "```\n함수에 있어서 — 이 줄은 코드 블록이라 검사하지 않는다\n```",
    )
    failures: list[str] = []

    # 줄 단위: bad는 한 줄도 빠짐없이 걸려야 하고, good은 하나도 걸리면 안 된다.
    for line in bad_lines:
        if not find_line_hints(visible_lines(line)):
            failures.append(f"놓침: {line}")
    for line in good_lines:
        if find_line_hints(visible_lines(line)):
            failures.append(f"오탐: {line}")

    # 문서 단위
    mixed = "배포는 금요일입니다. 롤백 절차는 아래 문서에 있어요. 담당자는 운영팀이에요. 모니터링은 주말까지 이어집니다."
    uniform = "배포는 금요일입니다. 롤백 절차는 아래 문서에 있습니다. 담당자는 운영팀입니다."
    polite_requests = "배포는 금요일입니다. 롤백 절차는 문서를 참고해 주세요. 담당자는 운영팀입니다. 문제가 생기면 알려 주세요."
    repeated = "지갑을 연결할 수 있습니다. 토큰을 스왑할 수 있습니다. 거래 내역을 확인할 수 있습니다."
    if not find_mixed_levels(prose_sentences(visible_lines(mixed))):
        failures.append("놓침: 높임 수준 혼용")
    if find_mixed_levels(prose_sentences(visible_lines(uniform))):
        failures.append("오탐: 높임 수준 통일된 글")
    if find_mixed_levels(prose_sentences(visible_lines(polite_requests))):
        failures.append("오탐: 합쇼체 글 속 '~주세요' 요청")
    if not find_repeated_endings(prose_sentences(visible_lines(repeated))):
        failures.append("놓침: 같은 종결 반복")
    if find_repeated_endings(prose_sentences(visible_lines(uniform))):
        failures.append("오탐: 종결이 다른 글")

    if failures:
        print("FAIL  ko-tone lint self-test")
        for failure in failures:
            print(f"      {failure}")
        return 1
    print(f"PASS  ko-tone lint self-test ({len(bad_lines)} bad / {len(good_lines)} good / 5 document checks)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="한국어 원고에서 다시 볼 표현 후보를 찾습니다.")
    parser.add_argument("files", nargs="*", help="검사할 UTF-8 파일, 표준 입력은 -")
    parser.add_argument("--self-test", action="store_true", help="규칙 자체 테스트 실행")
    parser.add_argument("--no-user-rules", action="store_true", help="사용자 피드백 규칙 없이 기본 규칙만 쓰기")
    parser.add_argument("--scope", choices=("email", "chat", "blog", "translation", "talk", "sns", "intro", "ui"),
                        help="사용자 규칙 중 이 글 종류와 '모든 글' 규칙만 쓰기")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.files:
        parser.error("파일을 하나 이상 주거나 --self-test를 쓰세요")
    avoid, keep = ((), ()) if args.no_user_rules else load_user_rules(args.scope)
    total = 0
    for name in args.files:
        for line_number, line, fix in find_hints(read_text(name), avoid, keep):
            print(f"WARN  {name}:{line_number}: {line}\n      {fix}")
            total += 1
    if total:
        print(f"\n다시 볼 후보 {total}건. 고칠지는 문맥을 보고 정하세요.")
    else:
        print("PASS  다시 볼 표현 후보 없음 (자연스러운 글이라는 뜻은 아닙니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
