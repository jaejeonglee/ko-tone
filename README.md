<p align="center">
  <img src="./assets/readme/hero.png" width="100%" alt="ko-tone 배너. 원고지 위에서 '검토를 진행했습니다'의 '를 진행'과 '앞으로가 기대됩니다' 한 줄을 빨간 펜으로 지운 교정 예시">
</p>

AI가 쓴 한국어 글에서 'AI 티'와 번역투, 빈말을 걷어내는 Agent Skill입니다. 블로그, 이메일, 번역 글, 제품 화면 문구처럼 어조와 문장이 중요한 글에 맞춰져 있고, 국립국어원·Microsoft·토스의 공개 글쓰기 지침을 바탕으로 고칩니다. 수치, 이름, 코드 같은 사실은 바꾸지 않습니다.

## 결과 예시

| 원문 | 고친 글 |
| --- | --- |
| `지난번 미팅에서 얘기했던 지갑 SDK 연동 떄문에 연락드려요.` | `지난 미팅에서 이야기 나눈 지갑 SDK 연동 건으로 연락드립니다.` |
| `옵티미스틱 롤업의 경우에 있어서, 트랜잭션들은 기본적으로 유효하다고 가정되어지며` | `옵티미스틱 롤업은 트랜잭션이 기본적으로 유효하다고 가정하며` |
| `귀하의 지갑이 지원되지 않는 네트워크에 연결되어 있습니다. 네트워크를 변경할 것.` | `지원하지 않는 네트워크에 연결돼 있어요. 지갑에서 네트워크를 바꿔 주세요.` |

## 설치

- **claude.ai, Claude 데스크톱 앱:** [Releases](https://github.com/jaejeonglee/ko-tone/releases)에서 `ko-tone.zip`을 받아 Customize → Skills → `+` → Create skill → Upload a skill에 올립니다. GitHub의 "Download ZIP"으로 받은 파일은 폴더가 한 겹 더 있어서 인식되지 않습니다.
- **Claude Code:**

  ```bash
  git clone https://github.com/jaejeonglee/ko-tone.git
  cp -R ko-tone/skills/ko-tone ~/.claude/skills/ko-tone
  ```

- **다른 Agent:** "이 Skill을 설치해 줘: https://github.com/jaejeonglee/ko-tone"이라고 요청합니다.

## 사용

"AI 티 빼줘", "자연스럽게 다듬어줘", "번역투 고쳐줘"처럼 요청하면 실행됩니다. 공지나 보고서처럼 형식이 핵심인 문서에는 자동으로 실행되지 않으며, "ko-tone으로"를 붙여 요청하면 구성은 두고 문장만 다듬습니다.

## 피드백 학습

처음에는 내장 규칙으로 고치고, 결과를 보고 남긴 피드백은 내 규칙으로 쌓습니다. "'말씀드리겠습니다' 말고 '말씀드릴게요'로", "'온체인'은 그대로 둬" 같은 피드백은 처음엔 후보로 두었다가, 같은 말을 한 번 더 하거나 "앞으로도"라고 하면 다음 글부터 기본으로 적용합니다. 내 규칙은 내장 규칙보다 먼저 적용되지만, 원문의 수치·이름·코드는 바꾸지 않습니다.

"내 ko-tone 규칙 보여줘"라고 하면 쌓인 규칙을 보고 켜거나 끌 수 있습니다. 규칙은 내 컴퓨터의 `~/.config/ko-tone/rules.json`에 저장되고, 팀이 함께 쓸 규칙은 저장소의 `.ko-tone/rules.json`에 두고 커밋하면 됩니다. claude.ai처럼 파일이 다음 대화까지 남지 않는 곳에서는 Agent가 정리해 준 규칙 목록을 프로젝트 지침에 붙여 넣습니다.

## 보조 스크립트

Agent가 필요할 때 쓰는 선택 도구입니다. Python 3.9 이상의 표준 라이브러리만 씁니다.

```bash
python3 skills/ko-tone/scripts/ko_tone_compare.py original.md revised.md  # 원문과 고친 글의 수치·링크·코드 비교
python3 skills/ko-tone/scripts/ko_tone_facts.py weekday 2026-12-02        # 요일, 시간대, 증감률, 주소 체크섬 계산
python3 skills/ko-tone/scripts/ko_tone_lint.py draft.md                    # 상투 표현과 내 규칙 위반 후보 찾기
python3 skills/ko-tone/scripts/ko_tone_rules.py list --status all          # 쌓인 내 규칙 보기
```

## 참고

- 문체 원칙의 참고 자료와 이용 조건: [REFERENCES.md](./REFERENCES.md)
- 스크립트를 고쳤다면 `python3 -m unittest discover -s tests`로 테스트 후 적용해주세요.

## 라이선스

[oil-tone](https://github.com/oil-oil/oil-tone)(oil-oil, MIT)을 바탕으로 한 파생 작업이며, [MIT](./LICENSE) 라이선스를 따릅니다.
