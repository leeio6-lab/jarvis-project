"""Part 2-2: Proactive alert test with dummy data on live server."""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

import httpx

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"


async def main():
    print("=" * 60)
    print("Part 2-2: 프로액티브 알림 테스트 (더미 데이터)")
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        now = datetime.now(timezone.utc)

        # 1. Insert dummy unreplied emails (24h+, 48h+, 72h+)
        print("\n[1] 더미 미답장 메일 3건 삽입")
        dummy_emails = [
            {"subject": "[긴급] 분기보고서 검토 요청", "sender": "김부장",
             "hours_ago": 25, "priority": "high"},
            {"subject": "고정자산 실사 일정 확인", "sender": "이팀장",
             "hours_ago": 50, "priority": "normal"},
            {"subject": "세금계산서 발행 건 확인 요청", "sender": "박대리",
             "hours_ago": 73, "priority": "high"},
        ]

        # We need to insert these via the database directly since there's no
        # email push endpoint. Use the command API to create context.
        # Instead, let's push them as screen-text records with email-like content
        for email in dummy_emails:
            record = {
                "app_name": "네이버 웍스",
                "window_title": f"미답장: {email['subject']}",
                "extracted_text": (
                    f"보낸사람: {email['sender']}\n"
                    f"제목: {email['subject']}\n"
                    f"수신 시간: {(now - timedelta(hours=email['hours_ago'])).strftime('%Y-%m-%d %H:%M')}\n"
                    f"미답장 {email['hours_ago']}시간 경과\n"
                    f"우선순위: {email['priority']}\n"
                    f"안녕하세요, 해당 건에 대해 확인 부탁드립니다."
                ),
                "text_length": 200,
                "timestamp": (now - timedelta(hours=email["hours_ago"])).isoformat(),
            }
            r = await client.post(f"{SERVER}/api/v1/push/screen-text",
                                 json={"records": [record]}, timeout=10)
            print(f"  {email['subject'][:35]} ({email['hours_ago']}h전) → {r.status_code}")

        # 2. Insert dummy tasks with deadlines
        print("\n[2] 더미 마감 임박 TODO 2건 삽입")
        tasks = [
            {"title": "월간 고정자산 마감 보고서", "due_date": (now + timedelta(hours=12)).strftime("%Y-%m-%d"),
             "priority": "high"},
            {"title": "분기별 세금계산서 점검", "due_date": (now + timedelta(hours=6)).strftime("%Y-%m-%d"),
             "priority": "high"},
        ]
        task_ids = []
        for task in tasks:
            r = await client.post(f"{SERVER}/api/v1/push/tasks", json=task, timeout=10)
            body = r.json()
            tid = body.get("task_id")
            task_ids.append(tid)
            print(f"  {task['title']} (마감: {task['due_date']}) → task_id={tid}")

        # 3. Run proactive check
        print("\n[3] 프로액티브 체크 실행")
        r = await client.post(f"{SERVER}/api/v1/data/proactive/check", timeout=30)
        body = r.json()
        alerts = body.get("alerts", [])
        print(f"  알림 {len(alerts)}건 생성")
        for alert in alerts:
            print(f"    [{alert.get('type', '?')}] {alert.get('title', '?')[:50]}")
            msg = alert.get("message", "")
            if msg:
                print(f"    메시지: \"{msg[:100]}\"")
            print()

        # 4. Check cooldown
        print("[4] cooldown 테스트 (즉시 재실행)")
        r2 = await client.post(f"{SERVER}/api/v1/data/proactive/check", timeout=30)
        body2 = r2.json()
        alerts2 = body2.get("alerts", [])
        print(f"  2차 체크 알림: {len(alerts2)}건")
        if len(alerts2) < len(alerts):
            print(f"  cooldown 작동: 이전 {len(alerts)}건 → {len(alerts2)}건 (중복 방지)")
        elif len(alerts2) == 0 and len(alerts) == 0:
            print("  알림 없음 (프로액티브 조건 불충족)")
        else:
            print(f"  cooldown 미작동 또는 조건 변경")

        # 5. Check notifications
        print("\n[5] 생성된 알림 확인")
        r = await client.get(f"{SERVER}/api/v1/data/notifications", timeout=10)
        notifs = r.json().get("notifications", [])
        print(f"  저장된 알림: {len(notifs)}건")
        for n in notifs[:5]:
            print(f"    [{n.get('type', '?')}] {n.get('title', '?')[:40]} | {n.get('created_at', '')}")

        # 6. Evaluate alert text quality
        if alerts:
            print("\n[6] 알림 텍스트 자연스러움 평가")
            for alert in alerts[:3]:
                msg = alert.get("message", "")
                # Basic quality check
                is_korean = any(ord(c) >= 0xAC00 for c in msg)
                has_detail = len(msg) > 20
                is_formal = "요" in msg or "니다" in msg or "세요" in msg
                quality = sum([is_korean, has_detail, is_formal])
                print(f"    \"{msg[:60]}...\"")
                print(f"    한국어: {'O' if is_korean else 'X'} | 상세: {'O' if has_detail else 'X'} | 자연스러움: {'O' if is_formal else 'X'} ({quality}/3)")

        # 7. Clean up dummy data
        print("\n[7] 더미 데이터 정리")
        for tid in task_ids:
            if tid:
                r = await client.delete(f"{SERVER}/api/v1/push/tasks/{tid}", timeout=10)
                print(f"  task {tid} 삭제: {r.status_code}")

    print(f"\n{'═'*60}")
    print("프로액티브 알림 테스트 완료")
    print(f"{'═'*60}")


if __name__ == "__main__":
    asyncio.run(main())
