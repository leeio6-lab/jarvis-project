"""Part 1-6: 30-minute idle stability test.

Monitors: server health, CPU/memory, error count, API call count.
Checks every 5 minutes.
"""

import sys
import time
from datetime import datetime

import httpx
import psutil

sys.stdout.reconfigure(encoding="utf-8")

SERVER = "http://localhost:8000"
INTERVAL = 300  # 5 minutes
TOTAL_DURATION = 1800  # 30 minutes
CHECKS = []


def get_server_stats():
    """Get server process CPU and memory."""
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            if "python" in proc.info["name"].lower():
                cmdline = proc.cmdline()
                if any("server.main" in c or "uvicorn" in c for c in cmdline):
                    mem = proc.info["memory_info"].rss / 1024 / 1024
                    cpu = proc.cpu_percent(interval=1)
                    return {"pid": proc.info["pid"], "mem_mb": round(mem, 1), "cpu": round(cpu, 1)}
        except Exception:
            pass
    return {"pid": 0, "mem_mb": 0, "cpu": 0}


def check_health():
    """Hit /health and return status."""
    try:
        r = httpx.get(f"{SERVER}/health", timeout=10)
        return r.status_code == 200, r.json()
    except Exception as e:
        return False, str(e)


def check_api_calls():
    """Count screen_texts to see if the idle skip is working."""
    try:
        r = httpx.get(f"{SERVER}/api/v1/data/screen-texts?limit=100", timeout=10)
        return r.json().get("count", 0)
    except Exception:
        return -1


def main():
    start = time.time()
    print("=" * 60)
    print("Part 1-6: 30분 장시간 방치 안정성 테스트")
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 시간: {TOTAL_DURATION // 60}분, 체크 간격: {INTERVAL // 60}분")
    print("=" * 60)

    initial_screen_texts = check_api_calls()
    error_count = 0

    check_num = 0
    while True:
        elapsed = time.time() - start
        if elapsed > TOTAL_DURATION:
            break

        check_num += 1
        mins = elapsed / 60

        # Health check
        ok, body = check_health()
        if not ok:
            error_count += 1

        # Server stats
        stats = get_server_stats()

        # Screen text count
        screen_count = check_api_calls()
        new_texts = screen_count - initial_screen_texts if screen_count >= 0 else 0

        result = {
            "check": check_num,
            "elapsed_min": round(mins, 1),
            "health": ok,
            "cpu": stats["cpu"],
            "mem_mb": stats["mem_mb"],
            "screen_texts_new": new_texts,
            "errors": error_count,
        }
        CHECKS.append(result)

        ts = datetime.now().strftime("%H:%M:%S")
        status = "OK" if ok else "FAIL"
        print(f"  [{ts}] {mins:5.1f}분 | {status} | CPU {stats['cpu']:5.1f}% | MEM {stats['mem_mb']:6.1f}MB | 신규텍스트 {new_texts}건 | 에러 {error_count}건")

        # Wait for next check
        remaining = TOTAL_DURATION - elapsed
        sleep_time = min(INTERVAL, remaining)
        if sleep_time > 0:
            time.sleep(sleep_time)

    # Final summary
    end = time.time()
    total_elapsed = end - start
    final_screen = check_api_calls()

    print(f"\n{'═'*60}")
    print("30분 방치 안정성 결과")
    print(f"{'═'*60}")
    print(f"  총 시간: {total_elapsed / 60:.1f}분")
    print(f"  에러 횟수: {error_count}건")
    print(f"  CPU 최대: {max(c['cpu'] for c in CHECKS):.1f}%")
    print(f"  메모리 최대: {max(c['mem_mb'] for c in CHECKS):.1f}MB")
    print(f"  메모리 최소: {min(c['mem_mb'] for c in CHECKS):.1f}MB")
    print(f"  API 호출 (방치 중 신규 screen_text): {final_screen - initial_screen_texts}건")
    print(f"  안정성: {'양호' if error_count == 0 else '불량'}")


if __name__ == "__main__":
    main()
