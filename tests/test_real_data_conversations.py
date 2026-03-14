"""Real-data conversation test: 25 diverse questions based on actual DB data."""

import asyncio
import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
RESULTS = []


async def ask(client, question, expected_keywords=None, category=""):
    """Ask JARVIS and evaluate the response."""
    t0 = time.time()
    r = await client.post(f"{SERVER}/api/v1/command",
                         json={"text": question, "locale": "ko"}, timeout=60)
    elapsed = time.time() - t0
    reply = r.json().get("reply", "") if r.status_code == 200 else f"ERROR {r.status_code}"

    # Check if expected keywords are in the reply
    found_keywords = []
    missing_keywords = []
    if expected_keywords:
        for kw in expected_keywords:
            if kw.lower() in reply.lower():
                found_keywords.append(kw)
            else:
                missing_keywords.append(kw)

    accuracy = len(found_keywords) / len(expected_keywords) * 10 if expected_keywords else 5
    accuracy = min(10, accuracy)

    result = {
        "category": category,
        "question": question,
        "reply": reply[:300],
        "elapsed_s": round(elapsed, 1),
        "reply_len": len(reply),
        "found_keywords": found_keywords,
        "missing_keywords": missing_keywords,
        "accuracy": round(accuracy, 1),
    }
    RESULTS.append(result)

    kw_status = ""
    if expected_keywords:
        kw_status = f" [{len(found_keywords)}/{len(expected_keywords)} 키워드]"
    print(f"\n[{category}] Q: {question}")
    print(f"  A: ({elapsed:.1f}s) {reply[:200]}")
    if missing_keywords:
        print(f"  누락 키워드: {missing_keywords}")
    print(f"  정확도: {accuracy:.0f}/10{kw_status}")

    return reply


async def main():
    start = time.time()
    print("=" * 65)
    print("실데이터 기반 다양한 대화 테스트 (25개 시나리오)")
    print("=" * 65)

    async with httpx.AsyncClient() as c:
        # === 카테고리 1: 활동 조회 ===
        await ask(c, "오늘 뭐했어?",
                 ["SAP", "Excel", "카카오톡"], "활동")
        await ask(c, "오늘 SAP에서 얼마나 일했어?",
                 ["SAP", "2시간", "32분"], "활동")
        await ask(c, "모바일에서 제일 많이 쓴 앱 알려줘",
                 ["카카오톡", "45분"], "활동")
        await ask(c, "오늘 PC에서 쓴 앱 목록 보여줘",
                 ["SAP", "Excel"], "활동")
        await ask(c, "오늘 총 근무 시간이 얼마야?",
                 ["9시간", "17분"], "활동")

        # === 카테고리 2: 화면 텍스트 검색 ===
        await ask(c, "오늘 네이버 웍스에서 뭐 봤어?",
                 ["손상검토", "메일"], "화면검색")
        await ask(c, "세금계산서 관련 내용 있어?",
                 ["세금계산서"], "화면검색")
        await ask(c, "고정자산 관련 화면에서 뭐 봤어?",
                 ["고정자산"], "화면검색")
        await ask(c, "임상민이 보낸 메일 뭐야?",
                 ["임상민"], "화면검색")
        await ask(c, "윤덕상 팀장이 보낸 메일 알려줘",
                 ["윤덕상"], "화면검색")
        await ask(c, "IO코드 관련 메일 있어?",
                 ["IO코드"], "화면검색")
        await ask(c, "매출대사 관련 내용 화면에서 봤어?",
                 ["매출대사"], "화면검색")

        # === 카테고리 3: 생산성 ===
        await ask(c, "오늘 생산성 점수 몇 점이야?",
                 ["70", "B"], "생산성")
        await ask(c, "이번 주 생산성 어때?",
                 ["점수", "등급"], "생산성")
        await ask(c, "오늘 집중한 시간이 얼마야?",
                 [], "생산성")

        # === 카테고리 4: 할 일 관리 ===
        await ask(c, "할 일 보여줘",
                 ["보고서", "작성"], "할일")
        await ask(c, "할 일 추가해줘. 수요일까지 분기결산 보고서 작성",
                 ["추가", "분기결산"], "할일")
        await ask(c, "마감 임박한 할 일 있어?",
                 [], "할일")

        # === 카테고리 5: 이메일/일정 ===
        await ask(c, "미답장 메일 있어?",
                 [], "이메일")
        await ask(c, "오늘 일정 알려줘",
                 [], "일정")
        await ask(c, "내일 회의 있어?",
                 [], "일정")

        # === 카테고리 6: 브리핑/리포트 ===
        await ask(c, "아침 브리핑 만들어줘",
                 ["할 일", "SAP"], "브리핑")
        await ask(c, "오늘 하루 정리해줘",
                 ["활동", "시간"], "브리핑")

        # === 카테고리 7: 자연어/일상 ===
        await ask(c, "자비스, 넌 뭘 할 수 있어?",
                 ["활동", "이메일"], "일상")
        await ask(c, "고마워 자비스",
                 [], "일상")

    # === 결과 집계 ===
    elapsed_total = time.time() - start
    print(f"\n{'=' * 65}")
    print("테스트 결과 집계")
    print(f"{'=' * 65}")

    categories = {}
    for r in RESULTS:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"scores": [], "speeds": []}
        categories[cat]["scores"].append(r["accuracy"])
        categories[cat]["speeds"].append(r["elapsed_s"])

    for cat, data in categories.items():
        avg_score = sum(data["scores"]) / len(data["scores"])
        avg_speed = sum(data["speeds"]) / len(data["speeds"])
        print(f"  {cat:10s}: 평균 {avg_score:.1f}/10 | 평균 {avg_speed:.1f}초 | {len(data['scores'])}건")

    total_avg = sum(r["accuracy"] for r in RESULTS) / len(RESULTS)
    total_speed = sum(r["elapsed_s"] for r in RESULTS) / len(RESULTS)
    print(f"\n  전체 평균: {total_avg:.1f}/10 | {total_speed:.1f}초 | {len(RESULTS)}건")
    print(f"  총 소요: {elapsed_total:.0f}초")

    # Save results
    with open("tests/real_data_test_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "results": RESULTS,
            "categories": {k: {"avg_score": sum(v["scores"])/len(v["scores"]),
                               "avg_speed": sum(v["speeds"])/len(v["speeds"]),
                               "count": len(v["scores"])}
                          for k, v in categories.items()},
            "total_avg_score": round(total_avg, 1),
            "total_avg_speed": round(total_speed, 1),
            "total_count": len(RESULTS),
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  결과 저장: tests/real_data_test_results.json")


if __name__ == "__main__":
    asyncio.run(main())
