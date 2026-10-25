import type { Register } from 'claude-code'

const P = 'four-cut-comic'

// The pipeline the main agent runs. Each role is a subagent from ../agents.
function pipeline(topic: string): string {
  return `『월간순정 노자키군』 팬 4컷 만화를 만든다. 주제: ${topic}

아래 순서대로 역할별 서브에이전트(Agent 도구)를 호출하라. 각 단계의 결과 전문을 다음 단계 프롬프트에 그대로 넘긴다. 너(메인)는 진행과 저장만 하고 내용은 직접 쓰지 않는다.

1. ${P}:story-writer — 주제를 넘겨 플롯을 받는다.
2. ${P}:storyboarder — 플롯을 넘겨 컷별 구도·인물 배치·표정 콘티를 받는다.
3. ${P}:dialogue-writer — 플롯+콘티를 넘겨 대사와 말풍선 배치를 받는다.
4. ${P}:comic-editor — 플롯+콘티+대사 배치를 넘겨 통과 여부를 받는다.
   "수정 필요"면 지적된 담당 에이전트만 다시 호출해 고친 뒤 편집자에게 한 번 더 검토받는다. 수정 반복은 최대 2회. 그래도 통과하지 못하면 남은 문제점을 결과에 그대로 적는다.
5. 편집 통과(또는 반복 한도 도달) 후 다음 둘을 한 메시지에서 병렬로 호출한다.
   - ${P}:image-prompter — 확정된 플롯+콘티+대사 배치를 넘겨 캐릭터 시트와 컷 프롬프트를 받는다.
   - ${P}:layout-artist — 확정된 콘티+대사 배치와 저장 경로 comics/<영문-슬러그>/preview.html 을 넘긴다.
6. comics/<영문-슬러그>/comic.md 에 스토리·콘티·대사 배치·편집 판정·캐릭터 시트와 이미지 프롬프트를 순서대로 저장한다.
7. 사용자에게 제목, 편집 점수, 두 파일 경로만 짧게 보고한다.`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: '4cut',
      description: '노자키군 4컷 만화 제작 (예: /4cut 치요의 밸런타인 초콜릿)',
      argumentHint: '<주제>',
    })

    return next(e)
  })

  on('command.run', { command: '4cut' }, async ($, e) => {
    const topic = e.args.trim()
    if (!topic) return { text: '사용법: /4cut <주제>  예) /4cut 고양이가 키보드를 점령함' }

    void $.prompt.submit({ text: pipeline(topic), asUser: true })

    return { text: `4컷 만화 제작 시작: ${topic}` }
  })
}
