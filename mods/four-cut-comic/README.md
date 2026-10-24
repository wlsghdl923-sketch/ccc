# four-cut-comic

역할을 하나씩 맡은 Claude 서브에이전트 6명이 협업해 4컷 만화를 만드는 Claude Code 모드(플러그인)입니다.

## 사용법

```
/4cut 월요일 아침 알람과의 전쟁
```

결과물:
- `comics/<슬러그>/comic.md` — 스토리, 콘티, 대사, 편집 판정, 이미지 생성 AI용 프롬프트
- `comics/<슬러그>/preview.html` — 말풍선 배치를 확인하는 4컷 레이아웃 미리보기(단순 도형)

## 역할

| 에이전트 | 역할 | 도구 |
| --- | --- | --- |
| `story-writer` | 기승전결 플롯, 펀치라인, 캐릭터 외형 키워드 | Read |
| `storyboarder` | 컷별 샷·배치·표정·배경·말풍선 여백 | Read |
| `dialogue-writer` | 말풍선 대사(컷당 2개, 20자 이내), 효과음 | Read |
| `comic-editor` | 통과/수정 판정, 담당별 수정 지시 (최대 2회 반복) | Read |
| `image-prompter` | 캐릭터 시트 + 컷별 영어 이미지 프롬프트 + negative prompt | Read |
| `layout-artist` | 인라인 SVG 4컷 미리보기 HTML | Read, Write |

진행 순서: 스토리 → 콘티 → 대사 → 편집(수정 루프) → 이미지 프롬프트·레이아웃(병렬) → 저장.
메인 Claude는 순서 진행과 파일 저장만 하고, 각 에이전트는 자기 역할 밖의 내용은 바꾸지 않습니다.
에이전트는 `four-cut-comic:story-writer`처럼 직접 호출할 수도 있습니다.

## 한계

Claude는 완성된 그림을 그리지 않습니다. 실제 그림은 `image-prompter`가 만든 프롬프트를 이미지 생성 AI에 넣어 얻고, 대사는 편집 툴로 얹어야 합니다.

## 설치

이 폴더를 `--plugin-dir`로 지정하거나 `CLAUDE_CODE_PLUGIN_DIRS`에 추가합니다.

```
claude --plugin-dir ./mods/four-cut-comic
```
