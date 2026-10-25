"""노자키군 패턴 도감 아티팩트 HTML에서 /4cut-idea 용 참고 자료를 뽑는다.

사용: python -I references/tools/extract_pattern_atlas.py <도감.html> [출력폴더=references/nozaki]

- 00~04 파일: 분석 요약(통계·유형·흐름·호 구성)과 편 ID 목록. 커밋 대상.
- strips/vol*.md: 902편 목록(컷별 대사 전사 포함). 원작 대사가 들어 있어 .gitignore 로 커밋에서 뺀다.
"""
import html
import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2] if len(sys.argv) > 2 else "references/nozaki")
js = src[src.find("<script>"):]
dec = json.JSONDecoder()


def grab(name):
    m = re.search(r"(?:const|let|var)\s+" + name + r"\s*=\s*", js)
    return dec.raw_decode(js[m.end():])[0]


strips, TYPES, CH, FLOWS = grab("strips"), grab("TYPES"), grab("CH"), grab("FLOWS")
tname = {t["key"]: t["name"] for t in TYPES}


def text_of(fragment):
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", fragment, flags=re.S)
    fragment = re.sub(r"</(h[1-3]|p|div|article|li|tr|em)>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    lines = [re.sub(r"\s+", " ", html.unescape(l)).strip() for l in fragment.split("\n")]
    return "\n".join(l for l in lines if l)


body = src[src.find('<div class="wrap">'):src.find("<script>")]
body = re.sub(r'<section id="catalog">.*?</section>', "", body, flags=re.S)
body = re.sub(r'<div class="viewer".*?</div>\s*</div>', "", body, flags=re.S)

out.mkdir(parents=True, exist_ok=True)
(out / "strips").mkdir(exist_ok=True)

(out / "00_overview.md").write_text(
    "# 노자키군 4컷 패턴 도감 — 개요·통계·규칙\n\n"
    "출처: 사용자 제작 아티팩트 「노자키군 4컷 패턴 도감」(1~7권 902편 분석). 숫자는 분석자의 집계, '왜'는 분석자의 해석.\n\n"
    + text_of(body) + "\n", encoding="utf-8")

lines = ["# 웃음을 만드는 유형\n", "각 유형의 1~4컷 기본 흐름, 변형, 대표 편 ID(예: 1-p001 = 1권 p001). 편 내용은 strips/ 참고.\n"]
for t in TYPES:
    n = sum(d["t2"] == t["key"] for d in strips)
    lines += [f"\n## {t['key']}. {t['name']} ({n}편)", f"- 한 줄: {t.get('one','')}", f"- 설명: {t.get('desc','')}"]
    if t.get("flow"):
        lines.append("- 기본 흐름: " + " → ".join(f"{i+1}컷 {s}" for i, s in enumerate(t["flow"])))
    for v in t.get("vars", []):
        lines.append(f"- 변형: {v}")
    if t.get("ex"):
        lines.append("- 대표 편: " + ", ".join(t["ex"]))
(out / "01_types.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

lines = ["# 유형별 4컷 흐름 54개\n", "유형마다 반복해 쓰인 변형 6가지. p는 1~4컷, 4컷이 펀치. ex는 근거 편 ID.\n"]
for k, fl in FLOWS.items():
    lines.append(f"\n## {k}. {tname.get(k, k)}")
    for i, f in enumerate(fl, 1):
        lines += [f"\n### {k}-{i}. {f['name']}", f"- 한 줄: {f.get('one','')}"]
        lines += [f"- {j+1}컷: {p}" for j, p in enumerate(f.get("p", []))]
        if f.get("tip"):
            lines.append(f"- 팁: {f['tip']}")
        if f.get("ex"):
            lines.append("- 근거 편: " + ", ".join(f["ex"]))
(out / "02_flows.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

lines = ["# 호(잡지 1회분) 구성\n", "| 호 | 권 | 중심 인물·주제 | 편수 | 많이 쓴 유형 |", "| --- | --- | --- | --- | --- |"]
for c in CH:
    s = [d for d in strips if d["ch"] == c["id"]]
    cnt = {}
    for d in s:
        cnt[d["t2"]] = cnt.get(d["t2"], 0) + 1
    top = ", ".join(f"{tname.get(k, '새 패턴')} {v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1])[:2])
    lines.append(f"| {c['id']} | {c['vol']} | {c.get('theme','')} | {len(s)} | {top} |")
(out / "03_issues.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

lines = ["# 편 ID 목록 (902편)\n", "근거를 적을 때 이 목록의 ID만 쓴다. 줄번호를 ID로 쓰지 않는다. 내용은 strips/ 참고.\n",
         "| ID | 제목 | 유형 | 호 | 등장 |", "| --- | --- | --- | --- | --- |"]
for d in strips:
    lines.append(f"| {d['id']} | {d['title']} | {d['t2']} | {d['ch']} | {', '.join(d.get('chars', []))} |")
(out / "04_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

for v in range(1, 8):
    rows = [f"# {v}권 편 목록 (도감 데이터)\n", "필드: 유형 / 등장 / 컷별 내용 / 웃음 원리 / 여지(복선) / 3컷 역할 / 마무리 / 지적 담당 / 연결 / 메모\n"]
    for d in (d for d in strips if d["vol"] == v):
        rows += [f"\n## {d['id']} 「{d['title']}」 — {tname.get(d['t2'], d['t2'])} ({d['ch']})",
                 f"- 등장: {', '.join(d.get('chars', []))}"]
        rows += [f"- {p}" for p in d.get("panels", [])]
        for key, lab in [("engine", "웃음 원리"), ("seed", "여지"), ("c3", "3컷 역할"), ("finish", "마무리"),
                         ("tsukkomi", "지적 담당"), ("link", "연결"), ("note", "메모"), ("tnote", "유형 메모")]:
            if d.get(key):
                rows.append(f"- {lab}: {d[key]}")
    (out / "strips" / f"vol{v}.md").write_text("\n".join(rows) + "\n", encoding="utf-8")

print(len(strips), "strips,", len(TYPES), "types,", sum(len(v) for v in FLOWS.values()), "flows ->", out)
