#!/usr/bin/env python3
"""Generate docs/assets/korea.js from data/korea_conferences.json.

data/korea_conferences.json 은 "개최 장소가 한국인 학회 현황"의 원본 데이터로,
새 학회의 한국 개최가 발표되면 items 에 항목을 추가한 뒤 이 스크립트를 실행한다:

  python3 scripts/build_korea.py

specialWatch 는 특별 관리 대상 학회(빨간색 표기) 약칭 목록이며,
abbr 은 docs/assets/data.js 의 약칭과 일치해야 등급/분야 pill 이 연결된다.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "korea_conferences.json"
OUT = ROOT / "docs" / "assets" / "korea.js"

JS_HEADER = """\
// 자동 생성 파일 — 직접 수정하지 마세요.
// 원본은 data/korea_conferences.json 이며 scripts/build_korea.py 가 이 파일을 생성합니다.
//
// 개최지·일정·마감일은 조사 시점 발표 기준이므로,
// 반드시 각 학회 공식 홈페이지에서 최신 정보를 확인해야 합니다.
"""


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    data["items"].sort(key=lambda i: (i["year"], i["start"], i["abbr"]))
    OUT.write_text(JS_HEADER + "window.KIISE_KOREA = "
                   + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
                   encoding="utf-8")
    years = sorted({i["year"] for i in data["items"]})
    print(f"korea.js: {len(data['items'])} conferences across {years}")


if __name__ == "__main__":
    main()
