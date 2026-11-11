<p align="center">
  <img src="./assets/readme/hero.png" width="100%" alt="ko-tone 배너. 원고지 위에서 '검토를 진행했습니다'의 '를 진행'과 '앞으로가 기대됩니다' 한 줄을 빨간 펜으로 지운 교정 예시">
</p>

어조와 문장이 품질을 좌우하는 한국어 글을 자연스럽게 다듬는 Agent Skill입니다. AI 초안의 'AI 티', 번역투, 빈말을 걷어내고, 국립국어원·Microsoft·토스의 공개 글쓰기 지침과 글쓰기 서적에서 공통으로 권하는 원칙에 따라 고칩니다. 중국어·영어용 문체 규범 [oil-tone](https://github.com/oil-oil/oil-tone)을 한국어에 맞게 다시 설계했습니다.

## 맡는 글과 맡지 않는 글

| 맡는 글 | 맡지 않는 글 |
| --- | --- |
| 블로그, 회고, 칼럼 | 공지, 주간 보고, 회의록 |
| 이메일(외부, 파트너, 투자자) | 장애 보고, 릴리스 노트 |
| 업무 메신저 대화 | PR 설명, README |
| 번역 글 | 결과물이 한국어가 아닌 글 |
| 발표 대본, SNS·커뮤니티 글 | |
| 제품·회사 소개 문단 | |
| 제품 화면 문구, 에러 메시지 | |

이렇게 나눈 데는 근거가 있습니다. 다섯 번의 블라인드 비교에서 형식이 핵심인 문서는 스킬 없이 고친 쪽이 더 나았고, 어조와 문장이 핵심인 글은 ko-tone 쪽이 나았습니다. 자세한 내용은 [평가 기록](./docs/evaluation.md)에 있습니다. 형식 문서에도 ko-tone을 직접 지정하면 구성은 그대로 두고 문장만 다듬습니다.

## 고치는 예

| 원문 | ko-tone의 처리 |
| --- | --- |
| `저희 팀은 지난달 관련 검토를 진행했으며` | `저희 팀은 지난달 ~를 검토했고` (무엇을 했는지 모호하면 '확인해 주세요'로 묻습니다) |
| `이번 경험은 저희 팀에게 매우 소중한 배움의 기회였으며` | 빈말을 지우고, 본문 사실에서 나온 판단이나 남은 과제로 맺습니다 |
| `귀하의 지갑이 지원되지 않는 네트워크에 연결되어 있습니다. 네트워크를 변경할 것.` | `지원하지 않는 네트워크에 연결돼 있어요. 지갑에서 네트워크를 바꿔 주세요.` |
| `옵티미스틱 롤업의 경우에 있어서, 트랜잭션들은 기본적으로 유효하다고 가정되어지며` | `옵티미스틱 롤업은 트랜잭션이 기본적으로 유효하다고 가정한다` |
| `배포 완료. 이슈 없음. 모니터링 중.` (블로그 글에서) | `배포를 마쳤고 지금까지 이슈는 없습니다. 당분간 모니터링하겠습니다.` |

마지막 예처럼 짧게 줄이는 것이 늘 정답은 아닙니다. 조사와 연결어미가 문장 사이의 관계를 실어 나르기 때문에, 그것까지 지우면 오히려 읽기 어려워집니다.

## 결과물

1. **고친 글 전문:** 그대로 복사해 쓰기 좋은 형태입니다.
2. **바꾼 점:** 핵심만 3~5개입니다.
3. **확인해 주세요:** 짐작으로 구체화한 곳, 틀려 보이는 사실(예: 날짜와 요일이 맞지 않음), 위험한 단언이 있을 때만 붙습니다.

수치, 날짜, 이름, 버전, 주소, 링크, 코드는 본문에서 바꾸지 않습니다.

## 설치

### Agent에게 설치 부탁하기

```text
이 Skill을 설치해 줘: https://github.com/jaejeonglee/ko-tone
```

### claude.ai, Claude 데스크톱 앱

1. [Releases](https://github.com/jaejeonglee/ko-tone/releases)에서 `ko-tone.zip`을 받습니다. GitHub의 "Download ZIP"으로 받은 파일은 폴더가 한 겹 더 있어서 그대로 올리면 인식되지 않습니다.
2. Customize → Skills → `+` → Create skill → Upload a skill에서 올립니다.

claude.ai 계정에 등록한 스킬은 같은 계정으로 로그인한 Claude Code에도 동기화됩니다.

### 직접 복사하기 (Claude Code 등)

```bash
git clone https://github.com/jaejeonglee/ko-tone.git
cp -R ko-tone/skills/ko-tone ~/.claude/skills/ko-tone
```

팀 저장소에서 함께 쓰려면 `skills/ko-tone` 폴더를 그 저장소의 `.claude/skills/ko-tone`에 넣고 커밋합니다.

## 설정

따로 설정할 것이 없습니다. 계정, API 키, 네트워크 연결 없이 지시문만으로 동작합니다.

## 사용

"자연스럽게 다듬어줘", "AI 티 빼줘", "번역투 고쳐줘"처럼 말하면 스킬이 실행됩니다.

```text
회사 기술 블로그에 올릴 회고 글이야. AI 쓴 티 안 나게 다듬어 줘.
```

```text
투자자분들께 보낼 월간 업데이트 메일이야. 담백하게 고쳐 줘.
```

```text
dApp 에러 메시지 다섯 개를 사용자 친화적으로 바꿔 줘.
```

## 보조 스크립트

선택 사항인 스크립트 세 개가 들어 있습니다. 모두 Python 3.9 이상의 표준 라이브러리만 쓰고, Windows에서는 `python3` 대신 `py -3`으로 실행합니다. Agent가 코드를 실행할 수 있으면 필요할 때 알아서 사용합니다.

```bash
# 원문과 고친 글의 수치, 링크, 코드, 주소 비교. 차이가 있으면 종료 코드 1로 끝납니다.
python3 skills/ko-tone/scripts/ko_tone_compare.py original.md revised.md

# 요일, 시간대 변환, 증감률, 큰 수 읽기, 토큰 단위 환산, 컨트랙트 주소 EIP-55 체크섬
python3 skills/ko-tone/scripts/ko_tone_facts.py weekday 2026-12-02
python3 skills/ko-tone/scripts/ko_tone_facts.py tz "2026-12-31 23:59" --from UTC --to KST
python3 skills/ko-tone/scripts/ko_tone_facts.py addr 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed

# 다시 볼 만한 상투 표현 후보 찾기. 경고만 하고 고칠지는 정하지 않습니다.
python3 skills/ko-tone/scripts/ko_tone_lint.py draft.md
```

- `ko_tone_facts.py`의 체크섬 확인은 Keccak-256을 표준 라이브러리로 직접 구현했고, EIP-55 명세의 예시 주소로 검증했습니다.
- `ko_tone_lint.py`는 줄 단위 규칙 27개와 문서 단위 점검 2개(높임 수준 혼용, 같은 종결 3문장 연속)를 씁니다. 경고가 없다고 자연스러운 글이라는 뜻은 아닙니다.

## 호환성과 의존성

| 항목 | 내용 | 확인 상태 |
| --- | --- | --- |
| 스킬 지시문 | `SKILL.md` 형식의 Agent Skill을 읽는 Agent | Claude Code 2.1.322(Linux)에서 확인: 블로그 회고 다듬기 요청은 자동 호출, 회의록 정리 요청은 호출되지 않음(각 1회) |
| claude.ai 업로드 | ZIP 업로드 | 형식 검사만 통과. 실제 업로드는 확인하지 않음 |
| 보조 스크립트 | Python 3.9 이상, 표준 라이브러리만 사용 | Linux에서 Python 3.9~3.13 테스트 통과. macOS, Windows는 확인하지 않음 |
| 네트워크 | 필요 없음 | 스크립트에 네트워크를 쓰는 코드가 없음 |

## 데이터와 적용 범위

- 스킬과 스크립트는 글을 외부로 보내지 않습니다. 글은 지금 쓰는 Agent와 모델에만 전달되며, 그 처리 방식은 해당 서비스의 정책을 따릅니다.
- 사실 확인, 자료 조사, 법률·재무 검토는 하지 않습니다. 원문의 수치나 날짜가 서로 맞지 않으면 고치지 않고 알려 줍니다.
- docx·pptx 같은 파일을 만드는 일은 해당 형식 스킬이 맡고, ko-tone은 그 안에 들어갈 한국어 문장을 맡습니다.

## 문제 해결

| 증상 | 확인할 것 |
| --- | --- |
| 스킬이 자동으로 실행되지 않음 | 요청에 "ko-tone으로"를 붙여 직접 지정합니다. 설치 직후라면 새 세션을 엽니다 |
| 공지나 보고서에는 실행되지 않음 | 의도한 동작입니다. 문장만 다듬고 싶으면 "ko-tone으로"를 붙여 요청합니다 |
| claude.ai 업로드가 실패함 | ZIP을 열었을 때 맨 위에 `ko-tone/SKILL.md`가 있는지 확인합니다. Releases의 `ko-tone.zip`은 이 구조입니다 |
| 고친 글의 수치가 원문과 다름 | `ko_tone_compare.py`로 원문과 비교해 의도한 변경인지 확인합니다 |

## 저장소 구조

```text
ko-tone/
├── skills/ko-tone/
│   ├── SKILL.md                         # 범위, 기본 태도, 작업 순서, 결과 형식
│   ├── references/contexts.md           # 글 종류별 높임 수준, 흐름, 피할 표현
│   ├── references/patterns.md           # AI 문체·번역투 패턴과 고친 예
│   ├── references/style-principles.md   # 공개 지침과 서적에 근거한 원칙 28개
│   ├── scripts/ko_tone_compare.py       # 원문과 고친 글의 사실 값 비교
│   ├── scripts/ko_tone_facts.py         # 요일·시간대·증감률 계산, 주소 체크섬
│   ├── scripts/ko_tone_lint.py          # 상투 표현 후보 찾기
│   ├── evals/                           # 평가 사례 19건 (배포 파일에는 빠짐)
│   └── LICENSE.txt
├── docs/evaluation.md                   # 다섯 번의 블라인드 비교 기록
├── tests/test_scripts.py                # 스크립트 회귀 테스트
├── assets/readme/                       # README 배너 (hero.html을 render.js로 렌더링)
├── REFERENCES.md                        # 참고 자료와 이용 조건
├── LICENSE
└── README.md
```

## 기여

자주 보이는 AI 문체를 발견하면 Issue나 PR로 알려 주세요. 아래 네 가지를 함께 적어 주시면, 예문 하나를 고치려다 다른 글을 망가뜨리는 규칙이 생기는 것을 막을 수 있습니다.

1. 원문
2. 무엇이 문제인지
3. 더 자연스럽고 정확한 고친 문장
4. 이 규칙이 맞는 경우와 맞지 않는 경우

스크립트를 고쳤다면 테스트를 실행해 주세요.

```bash
python3 -m unittest discover -s tests
```

## 출처와 라이선스

[oil-tone](https://github.com/oil-oil/oil-tone)(oil-oil, MIT)의 원칙과 구조를 바탕으로 한 파생 작업입니다. 문체 원칙의 참고 자료와 이용 조건은 [REFERENCES.md](./REFERENCES.md)에 있습니다. 라이선스는 [MIT](./LICENSE)입니다.
