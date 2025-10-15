import subprocess
import threading
import time

def run_python_script_live(script_path, start_event=None, wait_for_log=None):
    """
    실시간 로그를 출력하며, 특정 로그(wait_for_log)가 나오면 start_event를 set()합니다.
    """
    print(f"\n🚀 {script_path} 실행 중...")
    proc = subprocess.Popen(
        ['python3', '-u', script_path],
        cwd='/content',
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    try:
        for line in proc.stdout:
            print(line, end='')
            # 특정 로그가 나오면 start_event를 set()
            if wait_for_log and wait_for_log in line and start_event:
                start_event.set()
    except Exception as e:
        print(f"❌로그 스트림 중 오류: {e}")
    proc.wait()
    if proc.returncode != 0:
        print(f"❌ {script_path} 실행 에러 (exit code: {proc.returncode})")
        return False
    print(f"✅ {script_path} 실행 완료")
    return True

def run_stt_convsum_lora_sequential():
    # stt.py에서 이 로그가 나오면 convsum_inference.py 실행
    stt_wait_log = "Public URL: your url is:"
    stt_started_event = threading.Event()
    
    # convsum_inference.py에서 이 로그가 나오면 lora_extract.py 실행
    convsum_wait_log = "INFO:werkzeug:"
    convsum_started_event = threading.Event()

    # lora_extract.py에서 이 로그가 나오면 lora_inference.py 실행
    lora_extract_wait_log = "외부에서"
    lora_extract_started_event = threading.Event()

    # 1. stt.py 실행(스레드) - 특정 로그가 나오면 이벤트 발생
    stt_thread = threading.Thread(
        target=run_python_script_live,
        args=('stt.py', stt_started_event, stt_wait_log),
        daemon=True
    )
    stt_thread.start()

    # 2. stt.py에서 특정 로그가 나올 때까지 대기
    stt_started_event.wait()
    print("\n✅ stt.py 준비 완료 → convsum_inference.py 시작")

    # 3. convsum_inference.py 실행(스레드) - 특정 로그가 나오면 이벤트 발생
    convsum_thread = threading.Thread(
        target=run_python_script_live,
        args=('convsum_inference.py', convsum_started_event, convsum_wait_log),
        daemon=True
    )
    convsum_thread.start()

    # 4. convsum_inference.py에서 특정 로그가 나올 때까지 대기
    convsum_started_event.wait()
    print("\n✅ convsum_inference.py 준비 완료 → lora_extract.py 시작")

    # 5. lora_extract.py 실행(스레드) - 특정 로그가 나오면 이벤트 발생
    lora_extract_thread = threading.Thread(
        target=run_python_script_live,
        args=('lora_extract.py', lora_extract_started_event, lora_extract_wait_log),
        daemon=True
    )
    lora_extract_thread.start()

    # 6. lora_extract.py에서 특정 로그가 나올 때까지 대기
    lora_extract_started_event.wait()
    print("\n✅ lora_extract.py 준비 완료 → lora_inference.py 시작")

    # 7. lora_inference.py 실행
    lora_thread = threading.Thread(
        target=run_python_script_live,
        args=('lora_inference.py',)
    )
    lora_thread.start()

    # 모든 스레드가 끝날 때까지 대기
    lora_thread.join()
    lora_extract_thread.join()
    convsum_thread.join()
    stt_thread.join()

if __name__ == "__main__":
    # 1. tour_crawling.py 실행
    if not run_python_script_live('tour_crawling.py'):
        print("❗ tour_crawling.py 실패 → medical_crawling.py 실행 중단")
    else:
        # 2. medical_crawling.py 실행
        if not run_python_script_live('medical_crawling.py'):
            print("❗ medical_crawling.py 실패 → legal_crawling.py 실행 중단")
        else:
            # 3. legal_crawling.py 실행
            if not run_python_script_live('legal_crawling.py'):
                print("❗ legal_crawling.py 실패 → stt.py & convsum_inference.py & lora_extract.py & lora_inference.py 실행 중단")
            else:
                # 4. stt.py → convsum_inference.py → lora_extract.py → lora_inference.py 순차적 시작
                run_stt_convsum_lora_sequential()