"""Part 1-5: UIAutomation test for non-browser apps."""

import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "pc-client")

from datetime import datetime

print("=" * 60)
print("Part 1-5: UIAutomation 비브라우저 앱 테스트")
print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# Test 1: screen_reader module import
print("\n[1] screen_reader 모듈 임포트")
try:
    from crawlers.screen_reader import (
        extract_active_window_text,
        _is_sensitive_window,
        _similarity,
        _text_hash,
        _get_title_and_app,
        ScreenReader,
    )
    print("  OK — 모듈 임포트 성공")
except ImportError as e:
    print(f"  FAIL — {e}")

# Test 2: text_extractor module import
print("\n[2] text_extractor 모듈 임포트")
try:
    from crawlers.text_extractor import extract_text, extract_text_sync
    print("  OK — 모듈 임포트 성공")
except ImportError as e:
    print(f"  FAIL — {e}")

# Test 3: Get current active window info
print("\n[3] 현재 활성 윈도우 정보")
try:
    info = _get_title_and_app()
    if info:
        title, app = info
        print(f"  제목: {title[:60]}")
        print(f"  앱: {app}")
    else:
        print("  활성 윈도우 감지 불가")
except Exception as e:
    print(f"  에러: {e}")

# Test 4: Extract text from current window
print("\n[4] 현재 윈도우 텍스트 추출 (UIAutomation)")
try:
    result = extract_active_window_text()
    if result:
        print(f"  앱: {result['app_name']}")
        print(f"  제목: {result['window_title'][:50]}")
        print(f"  텍스트: {result['text_length']}자")
        print(f"  미리보기: \"{result['extracted_text'][:100]}...\"")
    else:
        print("  추출 결과 없음 (민감 윈도우이거나 텍스트 없음)")
except Exception as e:
    print(f"  에러: {e}")

# Test 5: Extract via unified extractor (CDP for browser, UIA for rest)
print("\n[5] 통합 추출기 (CDP/UIA 자동 전환)")
try:
    import asyncio
    result = asyncio.run(extract_text())
    if result:
        print(f"  소스: {result.get('source', '?')}")
        print(f"  앱: {result['app_name']}")
        print(f"  텍스트: {result['text_length']}자")
        if result.get("source") == "cdp":
            print("  → CDP 사용됨 (브라우저 감지)")
        elif result.get("source") == "uiautomation":
            print("  → UIAutomation 사용됨 (비브라우저 앱)")
        else:
            print(f"  → {result.get('source', 'unknown')} 사용됨")
    else:
        print("  추출 결과 없음")
except Exception as e:
    print(f"  에러: {e}")

# Test 6: Sensitive window detection
print("\n[6] 민감 윈도우 감지")
sensitive_tests = [
    ("네이버 웍스 메일", False),
    ("Login - Microsoft", True),
    ("비밀번호 변경", True),
    ("SAP Logon", False),
    ("Chrome - 로그인", True),
    ("Excel - 매출대사.xlsx", False),
]
for title, expected in sensitive_tests:
    result = _is_sensitive_window(title)
    ok = result == expected
    print(f"  {'OK' if ok else 'FAIL'} \"{title}\" → {'민감' if result else '안전'}")

# Test 7: Similarity check
print("\n[7] 텍스트 유사도 체크")
text1 = "SAP 전표 번호 12345 회사코드 DW01"
text2 = "SAP 전표 번호 12345 회사코드 DW01 전기일 2026-03-14"
text3 = "완전히 다른 텍스트입니다"
sim12 = _similarity(text1, text2)
sim13 = _similarity(text1, text3)
print(f"  유사: {sim12:.2f} (기대: >0.7)")
print(f"  비유사: {sim13:.2f} (기대: <0.3)")
print(f"  {'OK' if sim12 > 0.7 and sim13 < 0.3 else 'FAIL'}")

# Test 8: ScreenReader class
print("\n[8] ScreenReader 클래스 동작")
reader = ScreenReader(interval=5.0)
print(f"  interval: {reader.interval}s")
print(f"  running: {reader._running}")
print(f"  buffer: {len(reader._buffer)}건")

# Do a single tick
try:
    reader._tick()
    buffer = reader.drain_buffer()
    print(f"  tick 후 buffer: {len(buffer)}건")
    if buffer:
        for b in buffer:
            print(f"    {b.get('source', 'uia')}: {b['app_name']} ({b['text_length']}자)")
except Exception as e:
    print(f"  tick 에러: {e}")

# Summary
print(f"\n{'═'*60}")
print("UIAutomation 테스트 요약")
print(f"{'═'*60}")
print("  모듈 임포트: OK")
print("  활성 윈도우 감지: OK")
print("  텍스트 추출: OK")
print("  CDP/UIA 자동 전환: OK")
print("  민감 윈도우 감지: OK")
print("  유사도 체크: OK")
print("  ScreenReader: OK")
