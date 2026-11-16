#!/usr/bin/env python3
"""한국어 원고에서 문맥을 보고 다시 판단할 표현 후보를 찾는다.

oil-tone(https://github.com/oil-oil/oil-tone, MIT)의 tone_lint.py 구조
(코드 블록 제외 → 줄 단위 정규식 경고 → 자체 테스트)를 바탕으로,
한국어 패턴과 문서 단위 점검(높임 수준 혼용, 같은 종결 반복)을 새로 작성했다.

SKILL.md의 기본 흐름에서는 쓰지 않는다. 쓰임은 셋이다.
1. ko_tone_check.py --style이 불러 쓰는 규칙표(LINE_RULES는 여기에만 둔다).
2. --diagnose: 고치기 전 원문의 버릇(접속 부사 사다리, '하였습니다' 반복, 상투 다짐·공문투 묶음)을 요약.
3. 명령줄 점검. 사용자 규칙(avoid) 점검은 ko_tone_rules.py check가 맡고, 여기서는 활성 keep 표현에만
   걸린 기본 경고를 내지 않는 데만 쓴다(--no-user-rules면 그것도 하지 않는다).

동작 원리
1. visible_lines(): 코드 블록(``` · ~~~ · 들여쓴 코드), <script>/<style>, HTML 태그, 인라인 코드,
   인용 블록(>)과 따옴표 안 글을 지우고 사람이 읽는 줄만 남긴다. '<200ms', '<이름>'은 태그로 보지 않는다.
2. LINE_RULES: 줄마다 정규식을 대조한다. 규칙마다 수준(확인/참고)과 꺼 둘 글 종류가 있다.
   '~를 통해'는 한 글에 세 번 이상일 때만 알린다.
3. 문서 단위 점검: 제목·목록·표·인용을 뺀 본문 문장으로 높임 수준 혼용과 같은 종결 반복을 본다.

경고는 '다시 볼 후보'일 뿐이며 고칠지는 문맥을 보고 정한다.
종료 코드는 0이다(--strict일 때 후보가 있으면 1, 자체 테스트 실패는 1, 사용법·입력 오류는 2).
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):  # 아래 타입 표기(tuple[...])가 3.9부터 동작한다
    sys.exit("Python 3.9 이상이 필요합니다.")

import argparse
import html
import re
from collections import Counter
from pathlib import Path

CODE = ""  # 인라인 코드 자리(변수 뒤 조사 병기를 가려내려고 남긴다)
FORMAL = {"notice", "report", "minutes", "release", "doc", "letter", "reply"}  # 형식 문서
NO_STRUCT = FORMAL | {"ui"}  # 질문형 전환·콜론 제목·이모지 불릿을 끄는 글 종류
END_LINE = "표현 후보 없음. 구성, 사실, 빈칸, 덜어낸 것은 보지 않습니다."


class Rule:
    __slots__ = ("pattern", "message", "level", "off", "min_count")

    def __init__(self, pattern: str, message: str, level: str = "확인", off=(), min_count: int = 1):
        self.pattern = re.compile(pattern)
        self.message = message
        self.level = level            # 확인 | 참고
        self.off = frozenset(off)     # 이 글 종류에서는 보지 않는다
        self.min_count = min_count    # 한 글에 이만큼 나와야 알린다


# ── 줄 단위 규칙 ─────────────────────────────────────────────
# 정밀도를 우선한다. 흔히 정상적으로 쓰이는 표현은 넣지 않거나 '참고' 수준으로 둔다.
LINE_RULES: tuple = (
    # 1. 번역투
    Rule(r"에 있어서|(?:함|기|것)에 있어",
         "'~에 있어서'는 영어 직역투입니다. '~에서', '~할 때'로 바꿀 수 있는지 확인하세요('폴더에 있어서'처럼 '있다'면 그대로)."),
    Rule(r"에 의해서?",
         "행위자가 분명하면 능동문('A가 B를 ~한다')으로 바꿀 수 있는지 보세요. 법 조문이나 행위자가 없는 문장이면 그대로 둡니다.",
         level="참고"),
    Rule(r"[을를] 통(?:해|하여)서?",
         "'~를 통해'가 많습니다. 수단·경로가 분명하면 그대로 두고, '~로', '~해서'로 더 짧게 쓸 곳만 고르세요.",
         level="참고", min_count=3),
    Rule(r"하는 중에 있",
         "'~하는 중에 있다'는 '~하고 있다'로 줄일 수 있는지 확인하세요."),
    # '~적인/~적으로'가 한 줄에 3번 이상: 게으른 매칭(*?)과 고정 반복{2}로 역추적 폭주를 막는다.
    Rule(r"[가-힣]적(?:인|으로|이고|이며)(?:[^.!?]*?[가-힣]적(?:인|으로|이고|이며)){2}",
         "'~적' 수식이 몰려 있습니다. 실제 방법이나 결과로 바꿀 수 있는지 확인하세요."),

    # 2. 돌려 말하는 동사·이중 피동
    Rule(r"(?:되어|보여|쓰여|잊혀)(?:지|진|져|졌|짐|집)",
         "이중 피동인지 확인하세요. '되다', '보이다', '쓰이다', '잊히다'로 쓸 수 있습니다."),
    Rule(r"(?:검토|논의|회의|미팅|테스트|배포|업데이트|개발|분석|점검|작업|조사|확인|교육|인터뷰|리뷰|검증|구현)"
         r"[을를] (?:진행|수행)",
         "'~를 진행/수행하다' 대신 '~하다'로 바로 쓸 수 있는지 확인하세요."),
    Rule(r"(?:회의|미팅|시간|자리|간담회|논의|대화)[을를] 가(?:졌|지|진|집|질|져)",
         "영어 have 직역인지 확인하세요. '회의했다', '이야기했다'처럼 동사로 쓸 수 있습니다."),
    Rule(r"[이가] 이루어(?:졌|지|집|질|져|진)",
         "누가 무엇을 했는지 능동으로 쓸 수 있는지 확인하세요."),

    # 3. 빈말
    Rule(r"급변하는|빠르게 변화하는|급속도로 발전하는|빠르게 발전하는|디지털 전환 시대|4차 산업혁명 시대",
         "정보 없는 시대 배경인지 확인하세요. 아니면 바로 본론으로 들어갑니다."),
    Rule(r"[이가] (?:가속화|본격화|대두)되(?:면서|고 있)",
         "배경 설명이 뒤 내용과 구체적으로 이어지는지 확인하세요."),
    Rule(r"전문가들(?:은|이)|전문가들?에 따르면|업계에서는|업계 관계자|입을 모",
         "출처가 자료에 있으면 이름을 쓰고, 없으면 모호한 출처인지 확인하세요."),
    Rule(r"(?:많은|다수의|상당수의?|일부) (?:사용자|이용자|사람|개발자|고객)들?[이가은는] [^.!?]{0,20}"
         r"(?:평가|반응|호평|(?<!불)만족|말한|말합|이야기)",
         "사용자 반응에 근거 자료가 있는지 확인하세요."),
    Rule(r"연구(?:에 따르면|결과에 따르면|들에서)",
         "연구 출처가 자료에 있는지 확인하세요. 없으면 출처를 지어내지 않습니다."),
    Rule(r"중요한 역할을|핵심적인 역할|아무리 강조해도 지나치지 않|(?:것이|게) (?:매우 )?중요(?:합니다|하다|해요)",
         "중요하다는 주장 대신 무엇이 어떻게 달라지는지 쓸 수 있는지 확인하세요."),
    Rule(r"혁신적|획기적|게임 ?체인저|패러다임|시너지|새로운 지평|차원이 다른|판도를 바꾸|압도적인|독보적인",
         "홍보 문구인지 확인하세요. 기능, 조건, 수치로 바꿀 수 있습니다."),
    Rule(r"앞으로(?:가|의 [가-힣]{1,6}[이가])? (?:더욱 |더 )?기대(?:됩|된|되|합)|미래가 (?:더욱 )?(?:기대|밝)|새로운 장을 (?:열|여)"
         r"|첫걸음을 (?:내딛|뗐|떼)|무한한 가능성|가능성을 열어|한 단계 도약|귀추가 주목",
         "상투적인 결말인지 확인하세요. 지우거나 실제 결과·다음 일정으로 바꿀 수 있습니다."),

    # 4. AI 수사 습관
    Rule(r"단순(?:히|한)[^.!?]{0,30}아니(?:라|다)|선택이 아닌 필수",
         "'단순한 X가 아니라 Y' 꼴의 부정 병렬인지 확인하세요. Y를 근거와 함께 바로 쓸 수 있습니다."),
    Rule(r"(?:^|[.!?] )(?:결론적으로|요약하자면|요약하면|종합하자면|종합하면|정리하자면|이처럼|이와 같이|이렇듯)",
         "새 정보 없는 요약 문단인지 확인하세요.", off=FORMAL),
    Rule(r"(?:^|[.!?] )(?:그렇다면|과연)[^.!?]{0,40}(?:까요|가요)\?",
         "질문형 전환 대신 답을 바로 쓸 수 있는지 확인하세요.", off=NO_STRUCT | {"chat"}),
    Rule(r"[—―]",
         "줄표는 업무 글에서 드뭅니다. 쉼표, 괄호, 문장 나누기로 바꿀 수 있는지 확인하세요."),
    Rule(r"^#{1,6} [^:：]+[:：] \S",
         "콜론으로 문구를 덧붙인 제목입니다. 제목이 내용을 바로 말하는지 확인하세요.", off=NO_STRUCT),
    Rule(r"^(?:[-*+] |\d+\. )?\s*(?:✅|🚀|💡|👉|✨|🔥|📌|🎯|⚡|🌟|📈|🛠|🔑|💪|🙌)",
         "이모지 불릿입니다. 글의 성격(문서·보고·공지)에 맞는지 확인하세요.", off=NO_STRUCT | {"sns"}),

    # 5. 완충 표현·과잉 겸양: 완충이 실제로 겹친 꼴만
    Rule(r"수 있을 (?:것|듯)(?:으로|이라고)? (?:보입|보인|보여|예상|생각|판단|사료|전망)"
         r"|(?:라고|다고) (?:할|볼) 수 있을 (?:것|듯)"
         r"|것으로 (?:보일|예상될|판단될|생각될) 수 있"
         r"|(?:할|될) 것으로 (?:보|예상되|판단되|생각되)[^.!?]{0,4}(?:것 같|듯)",
         "완충 표현이 겹쳤는지 확인하세요. 사실 상태에 맞는 하나만 남기고, 추정을 단정으로 바꾸지는 않습니다."),
    Rule(r"(?:하도록|드리도록|할 수 있도록|드릴 수 있도록) 하겠습니다",
         "'~하겠습니다'로 줄일 수 있는지 확인하세요. 주어가 다르면('누구나 신청할 수 있도록') 그대로 둡니다."),

    # 6. 챗봇 말투('궁금한 점이 있으시면 … 문의해 주세요'는 공지·메일의 정상 맺음이라 보지 않는다)
    Rule(r"좋은 질문|훌륭한 질문|(?:^|[.!?] )물론(?:입니다|이죠)[.!]?\s*$|도움이 (?:되었|되셨|됐|되)(?:으면|길) (?:좋겠|바랍)",
         "독자에게 가는 글에 남은 챗봇 말투인지 확인하세요."),

    # 8. 표기: 조사 병기. 변수({…})나 코드 뒤에서는 받침을 알 수 없으니 보지 않는다.
    Rule(r"(?<![}" + CODE + r"\s])(?:을\(를\)|를\(을\)|이\(가\)|가\(이\)|은\(는\)|는\(은\)|과\(와\)|와\(과\)"
         r"|으로\(로\)|로\(으로\)|\(으\)로|\(이\)(?:나|라|여|며|랑|란|든지|라도|야))",
         "조사를 함께 적었습니다. 앞말 받침에 맞는 조사 하나만 쓰거나 문장을 바꾸세요."),
)


# ── 텍스트 추출 ──────────────────────────────────────────────
def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def read_text(name: str) -> str:
    if name == "-":
        return sys.stdin.read()
    path = Path(name)
    if not path.is_file():
        raise ValueError(f"파일을 찾을 수 없습니다: {name}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"UTF-8로 읽을 수 없습니다: {name} (UTF-8로 저장한 뒤 다시 실행하세요)") from None


FENCE_MARK = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
LIST_START = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s")
HTML_TAG = re.compile(r"<!--.*?-->|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』|'[^'\n]{2,}'")


def visible_lines(text: str, drop_quotes: bool = True) -> list:
    """사람이 읽는 텍스트 줄만 (줄 번호, 텍스트)로 돌려준다."""
    lines: list = []
    fence = None
    in_script = False
    prev_blank, in_list = True, False
    for number, raw in enumerate(text.splitlines(), start=1):
        mark = FENCE_MARK.match(raw)
        if fence:  # 코드 블록 안쪽은 검사하지 않는다
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence):
                fence = None
            continue
        if mark:
            fence = mark.group(1)
            continue
        if re.search(r"<(script|style)\b", raw, flags=re.IGNORECASE):
            in_script = True
        if in_script:
            if re.search(r"</(script|style)>", raw, flags=re.IGNORECASE):
                in_script = False
            continue
        if not raw.strip():
            prev_blank = True
            continue
        if LIST_START.match(raw) and not raw.startswith(("    ", "\t")):
            in_list = True
        elif not raw.startswith((" ", "\t")):
            in_list = False
        if raw.startswith(("    ", "\t")) and prev_blank and not in_list and not LIST_START.match(raw):
            continue  # 들여쓴 코드
        prev_blank = False
        if raw.lstrip().startswith(">"):  # 인용 블록: 남의 글
            continue
        visible = HTML_TAG.sub(" ", raw)
        visible = re.sub(r"`[^`]*`", CODE, visible)
        if drop_quotes:
            visible = QUOTED.sub("\"…\"", visible)
        visible = html.unescape(re.sub(r"\s+", " ", visible)).strip()
        if visible:
            lines.append((number, visible))
    return lines


def excerpt(line: str, start: int, end: int, width: int = 20) -> str:
    head = "…" if start > width else ""
    tail = "…" if len(line) - end > width else ""
    return (head + line[max(0, start - width):end + width].strip() + tail).replace(CODE, "`…`")


# 힌트: (줄 번호, 앞뒤 20자, 안내 문구, 수준)
def find_line_hints(lines: list, keep: tuple = (), scope=None) -> list:
    hints: list = []
    totals: Counter = Counter()
    pending: list = []
    for line_number, line in lines:
        # 사용자가 '고치지 말 표현(keep)'으로 정한 구간. 기본 규칙이 이 구간에만 걸렸다면 경고하지 않는다.
        kept = [m.span() for k in keep for m in k.finditer(line)]
        for index, rule in enumerate(LINE_RULES):
            if scope and scope in rule.off:
                continue
            spans = [m.span() for m in rule.pattern.finditer(line)
                     if not any(m.start() < k_end and k_start < m.end() for k_start, k_end in kept)]
            if spans:
                totals[index] += len(spans)
                start, end = spans[0]
                pending.append((index, (line_number, excerpt(line, start, end), rule.message, rule.level)))
    for index, hint in pending:
        if totals[index] >= LINE_RULES[index].min_count:
            hints.append(hint)
    return hints


# ── 문서 단위 점검 ───────────────────────────────────────────
# 제목(#), 목록(-, *, +, •, 1.), 표(|), 인용(>)은 관행상 종결이 달라도 되므로 본문에서 뺀다.
NON_PROSE = re.compile(r"^(?:#|[-*+•] |\d+[.)] |\||>)")
# 마침표 뒤에 공백이 올 때만 문장을 나눈다. 그래야 3.5%, v1.2 같은 숫자가 쪼개지지 않는다.
SENTENCE_BREAK = re.compile(r"(?<=[.!?。])\s+")
TRAILING = " .!?。…~\"'”’)」』"


def prose_sentences(lines: list) -> list:
    sentences: list = []
    for line_number, line in lines:
        if NON_PROSE.match(line):
            continue
        for part in SENTENCE_BREAK.split(line):
            part = part.strip()
            if part:
                sentences.append((line_number, part))
    return sentences


def speech_level(sentence: str):
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


def find_mixed_levels(sentences: list) -> list:
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
    return [(first_line, excerpt(first_sentence, max(0, len(first_sentence) - 20), len(first_sentence)),
             f"높임 수준이 섞여 있습니다({summary}). 주된 문체({main_level})와 다른 문장이 있는 줄: {where}. "
             "인용이나 의도한 전환이 아니면 하나로 맞출지 확인하세요.", "확인")]


def find_repeated_endings(sentences: list, run_length: int = 3) -> list:
    hints: list = []
    run: list = []
    previous_key = None
    for line_number, sentence in sentences + [(0, "")]:  # 끝에 빈 문장을 넣어 마지막 연속 구간도 처리
        tail = sentence.rstrip(TRAILING)
        key = tail[-6:] if len(tail) >= 6 else None  # 끝 6글자: '수 있습니다', '것이 중요합니다' 등
        if key is not None and key == previous_key:
            run.append((line_number, sentence))
        else:
            if len(run) >= run_length:
                n, s = run[run_length - 1]
                hints.append((n, excerpt(s, max(0, len(s) - 20), len(s)),
                              f"같은 종결 '…{previous_key}'가 {len(run)}문장 연속으로 나옵니다. "
                              "문장을 합치거나 구조를 바꿀 수 있는지 확인하세요.", "확인"))
            run = [(line_number, sentence)] if key is not None else []
        previous_key = key
    return hints


def find_hints(text: str, avoid: tuple = (), keep: tuple = (), scope=None, documents: bool = True) -> list:
    """avoid는 예전 호출과의 호환을 위해 받기만 한다(사용자 규칙 점검은 ko_tone_rules.py check)."""
    lines = visible_lines(text)
    hints = find_line_hints(lines, keep, scope)
    if documents:
        sentences = prose_sentences(lines)
        hints += find_mixed_levels(sentences) + find_repeated_endings(sentences)
    return sorted(hints, key=lambda hint: hint[0])


def load_keep_patterns(scope=None) -> tuple:
    """ko_tone_rules.py에서 활성 keep 패턴을 불러온다. 규칙 파일이 없으면 빈 목록이고, 깨졌으면 알리고 넘어간다."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ko_tone_rules", Path(__file__).with_name("ko_tone_rules.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return tuple(module.keep_patterns(scope))
    except Exception as exc:  # 사용자 규칙 문제로 기본 검사가 멈추지 않게 한다
        print(f"참고  사용자 규칙을 읽지 못해 keep 표현을 반영하지 않습니다: {exc}", file=sys.stderr)
        return ()


def normalize_scope(scope):
    if not scope:
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ko_tone_rules", Path(__file__).with_name("ko_tone_rules.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.normalize_scope(scope)
    except Exception:
        return scope.strip().lower()


# ── 원문 진단(--diagnose) ────────────────────────────────────
CONJUNCTIONS = ("또한", "한편", "그리고", "특히", "아울러", "따라서", "그러나", "하지만", "게다가", "더불어", "그 결과",
                "이에", "먼저", "우선", "다음으로", "마지막으로", "끝으로", "앞으로도", "나아가", "이를 통해")
LADDER = ("먼저", "우선", "다음으로", "또한", "마지막으로", "끝으로")
STOCK_GROUPS = (
    ("상투 다짐·부탁", r"최선을 다하겠습니다|많은 (?:관심|협조|참여|성원)(?:과 [가-힣]+)? 부탁드립니다|노력하겠습니다"),
    ("거창한 낱말", r"괄목할|끊임없이|여정|직면|소중한|중대한|원활한"),
    ("'~게 되었습니다'", r"게 되었습니다"),
    ("과장된 감사", r"깊은 감사의 말씀|열렬한 성원|아낌없는 (?:성원|지지|관심)"),
    ("상투 인사", r"무궁한 발전|다름이 아니오라|다름이 아니라|바쁘신 (?:와중|가운데|중)"),
    ("한자 공문투", r"금일|금번|익일|명일|상기 "),
    ("'~고자 합니다', '~오니'", r"고자 합니다|하오니|이오니"),
    ("'~와 관련하여'", r"(?:와|과) 관련하여"),
)


def diagnose(text: str) -> list:
    """고치기 전 원문의 버릇. [(이름, 설명)]"""
    lines = visible_lines(text)
    sentences = [s for _, s in prose_sentences(lines)] or [s for _, s in lines]
    out = []
    firsts = [next((c for c in CONJUNCTIONS if s.startswith(c + " ") or s.startswith(c + ",")), None) for s in sentences]
    used = [c for c in firsts if c]
    ladder = {c for c in used if c in LADDER}
    if (len(used) >= 3 and len(used) / max(1, len(sentences)) >= 0.4) or len(ladder) >= 3:
        out.append(("접속 부사 사다리", f"{len(sentences)}문장 중 {len(used)}문장이 접속 부사로 시작합니다({' → '.join(used[:6])})."))
    joined = "\n".join(line for _, line in lines)
    hayeot = joined.count("하였습니다")
    if hayeot >= 2:
        out.append(("'하였습니다' 반복", f"{hayeot}회. 딱딱한 공문투일 수 있습니다('했습니다')."))
    for name, pattern in STOCK_GROUPS:
        hits = re.findall(pattern, joined)
        if hits:
            shown = ", ".join(sorted(set(hits))[:4])
            out.append((name, f"{len(hits)}회({shown})."))
    return out


# ── 자체 테스트 ──────────────────────────────────────────────
def self_test() -> int:
    bad_lines = (
        "결제 절차에 있어서 가장 중요한 것은 범위를 정하는 일이다.",
        "신청서는 담당자에 의해 검토된다.",
        "현재 이전 작업을 하는 중에 있습니다.",
        "체계적이고 효율적이며 전략적인 접근이 필요하다.",
        "업데이트가 완료되어졌습니다.",
        "어제 코드 리뷰를 진행했습니다.",
        "오후에 팀 회의를 가졌습니다.",
        "성능 개선이 이루어졌습니다.",
        "급변하는 디지털 시대에 보안은 필수다.",
        "업계 전문가들은 구독 모델이 대세라고 입을 모은다.",
        "많은 사용자들이 새 화면을 호평하고 있다.",
        "최근 연구에 따르면 이 방식이 더 빠르다.",
        "이 제도는 지역 상권에 중요한 역할을 합니다.",
        "혁신적인 게임 체인저 서비스를 소개합니다.",
        "앞으로의 행보가 더욱 기대됩니다.",
        "이것은 단순한 가계부 앱이 아니라 새로운 소비 습관입니다.",
        "이처럼 정기 점검은 운영의 핵심 요소입니다.",
        "그렇다면 왜 이런 문제가 생길까요?",
        "새 버전은 — 예상대로 — 더 빠르다.",
        "## 비용 줄이기: 작은 차이가 만드는 큰 변화",
        "- ✅ 배포 완료",
        "수수료가 줄어들 수 있을 것으로 보입니다.",
        "내일까지 확인해 드릴 수 있도록 하겠습니다.",
        "도움이 되셨길 바랍니다.",
        "파일을(를) 삭제합니다.",
        "회원 등급(으)로 나뉩니다.",
        "고객 경험은 아무리 강조해도 지나치지 않습니다.",
        "배포를 마쳤습니다. 그렇다면 다음 단계는 무엇일까요?",
        "앞으로의 발전이 더욱 기대됩니다.",
    )
    good_lines = (
        "2026년 3월 개편 뒤 예전 앱은 로그인이 실패한다.",
        "점검 결과 결함 2건이 확인됐고, 둘 다 수정했습니다.",
        "임대료가 오르면서 손님이 줄었고, 그래서 가게를 옮겼다.",
        "이 함수는 잔액이 0이면 요청을 되돌린다.",
        "배포는 금요일 오후 3시(KST)에 합니다.",
        "수수료가 약 30% 줄었습니다.",
        "```\n함수에 있어서 — 이 줄은 코드 블록이라 검사하지 않는다\n```",
        "~~~\n혁신적인 — 이 줄도 코드 블록이다\n~~~",
        "저는 보안 전문가이자 두 아이의 아빠입니다.",
        "오늘날 대부분의 브라우저는 이 기능을 지원합니다.",
        "이 글은 테스트의 중요성을 다룹니다.",
        "이 실험은 상온에서도 동작할 가능성을 보여 줍니다.",
        "내일 오전까지는 보내 드릴 수 있을 것 같습니다.",
        "궁금한 점이 있으시면 고객센터(1588-0000)로 문의해 주세요.",
        "일정이 바뀌면 언제든 말씀해 주세요.",
        "{name}을(를) 삭제할까요?",
        "`{token}`을(를) 받았어요.",
        "그럼 내일 3시에 회의실에서 볼까요?",
        "신청은 앱을 통해서만 받습니다.",
        "\"검토를 진행했습니다\"는 고칠 예로 든 문장입니다.",
        "> 혁신적인 게임 체인저라는 말은 인용한 남의 글이다.",
        "응답 시간 <200ms 조건은 그대로 둡니다.",
        "일부 고객이 배송 지연에 불만족을 표시했습니다.",
    )
    failures: list = []

    # 줄 단위: bad는 한 줄도 빠짐없이 걸려야 하고, good은 하나도 걸리면 안 된다.
    for line in bad_lines:
        if not find_line_hints(visible_lines(line)):
            failures.append(f"놓침: {line}")
    for line in good_lines:
        if find_line_hints(visible_lines(line)):
            failures.append(f"오탐: {line}")
    if find_line_hints(visible_lines("## 부록: 설치 방법"), scope="doc"):
        failures.append("오탐: 형식 문서의 콜론 제목")
    if not find_line_hints(visible_lines("앱을 통해 신청하고, 메일을 통해 받고, 문자를 통해 확인합니다.")):
        failures.append("놓침: 한 글에 세 번 나온 '~를 통해'")
    if find_line_hints(visible_lines("<b>혁신적인</b>")) == [] or \
            visible_lines("<이름> 님께")[0][1] != "<이름> 님께":
        failures.append("HTML 태그 처리 이상")

    # 문서 단위
    mixed = "배포는 금요일입니다. 롤백 절차는 아래 문서에 있어요. 담당자는 운영팀이에요. 모니터링은 주말까지 이어집니다."
    uniform = "배포는 금요일입니다. 롤백 절차는 아래 문서에 있습니다. 담당자는 운영팀입니다."
    polite_requests = "배포는 금요일입니다. 롤백 절차는 문서를 참고해 주세요. 담당자는 운영팀입니다. 문제가 생기면 알려 주세요."
    repeated = "회원 가입을 할 수 있습니다. 쿠폰을 받을 수 있습니다. 주문 내역을 확인할 수 있습니다."
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
    diag = dict(diagnose("먼저 매출을 정리했습니다. 다음으로 비용을 보았습니다. 또한 인력을 검토하였습니다. "
                         "마지막으로 계획을 수립하였습니다. 최선을 다하겠습니다."))
    if not {"접속 부사 사다리", "'하였습니다' 반복", "상투 다짐·부탁"} <= set(diag):
        failures.append(f"원문 진단 이상: {diag}")

    if failures:
        print("자체 테스트 실패: ko-tone lint")
        for failure in failures:
            print(f"      {failure}")
        return 1
    print(f"자체 테스트 통과: ko-tone lint ({len(bad_lines)} bad / {len(good_lines)} good / 문서 점검 6)")
    return 0


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="한국어 원고에서 다시 볼 표현 후보를 찾습니다.")
    parser.add_argument("files", nargs="*", help="검사할 UTF-8 파일, 표준 입력은 -")
    parser.add_argument("--self-test", action="store_true", help="규칙 자체 테스트 실행")
    parser.add_argument("--diagnose", action="store_true", help="고치기 전 원문의 버릇 요약")
    parser.add_argument("--no-user-rules", action="store_true", help="사용자 keep 표현을 반영하지 않기")
    parser.add_argument("--scope", help="글 종류(email, chat, notice, report, ui …). 형식 문서에서 끄는 규칙을 끈다")
    parser.add_argument("--strict", action="store_true", help="후보가 있으면 종료 코드 1")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.files:
        parser.error("파일을 하나 이상 주거나 --self-test를 쓰세요")
    scope = normalize_scope(args.scope)
    keep = () if args.no_user_rules else load_keep_patterns(scope)
    total = 0
    try:
        texts = [(name, read_text(name)) for name in args.files]
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    for name, text in texts:
        if args.diagnose:
            found = diagnose(text)
            for label, note in found:
                print(f"원문 진단  {name}  {label}: {note}")
            if not found:
                print(f"원문 진단  {name}  눈에 띄는 버릇 없음.")
            continue
        for line_number, part, message, level in find_hints(text, keep=keep, scope=scope):
            print(f"{level}  {name}:{line_number}  {part}\n      {message}")
            total += 1
    if args.diagnose:
        print("버릇 요약일 뿐 'AI 티'의 증거는 아닙니다. 사람이 쓴 공문에도 흔한 표현이 있습니다.")
        return 0
    if total:
        print(f"\n다시 볼 후보 {total}건. 고칠지는 문맥을 보고 정하세요. 사용자 규칙 점검은 ko_tone_rules.py check로 합니다.")
    else:
        print(END_LINE)
    return 1 if args.strict and total else 0


if __name__ == "__main__":
    raise SystemExit(main())
