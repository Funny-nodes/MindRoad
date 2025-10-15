import sys
import subprocess
import os, asyncio, uvicorn, threading
from tempfile import NamedTemporaryFile
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import nest_asyncio

nest_asyncio.apply()

try:
    from faster_whisper import WhisperModel
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "faster-whisper"])
    from faster_whisper import WhisperModel

# -------------------------------
# 환경 설정
# -------------------------------
DEVICE = "cuda" if os.path.exists("/usr/local/cuda") else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"
print("🔥 Using device:", DEVICE)

model = WhisperModel("medium", device=DEVICE, compute_type=COMPUTE_TYPE)
print("✅ WhisperModel loaded")

# -------------------------------
# FastAPI 초기화
# -------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# STT 실행 함수
# -------------------------------
def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def transcribe_file(tmp_path):
    segments, _ = model.transcribe(
        tmp_path,
        beam_size=5,
        best_of=5,
        vad_filter=True,
        temperature=[0.0, 0.2, 0.4],
    )
    text_with_time = []
    for seg in segments:
        start_str = format_time(seg.start)
        end_str = format_time(seg.end)
        text_with_time.append(f"[{start_str} --> {end_str}] {seg.text}")
    full_text = " ".join([seg.text for seg in segments])
    return full_text, text_with_time

# -------------------------------
# 병렬 STT
# -------------------------------
executor = ThreadPoolExecutor(max_workers=4)

async def run_parallel_stt(files):
    loop = asyncio.get_event_loop()
    tasks = []

    for file in files:
        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.write(await file.read())
        tmp_path = tmp.name
        tmp.close()

        task = loop.run_in_executor(executor, transcribe_file, tmp_path)
        tasks.append((task, tmp_path, file.filename))

    results = []
    for task, tmp_path, original_filename in tasks:
        full_text, segments = await task
        nickname = original_filename.split("_")[0]

        results.append({
            "fileName": original_filename,
            "nickname": nickname,
            "segments": segments,
        })
        os.remove(tmp_path)

    return results

@app.post("/stt_multi")
async def transcribe_multi(files: list[UploadFile] = File(...)):
    results = await run_parallel_stt(files)
    return {"results": results}

# -------------------------------
# LocalTunnel 실행
# -------------------------------
def start_localtunnel(port, subdomain="mind-road3"):
    process = subprocess.Popen(
        ["npx", "localtunnel", "--port", str(port), "--subdomain", subdomain],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for line in process.stdout:
        if "your url is:" in line.lower():
            print("🚀 Public URL:", line.strip())
            break

# -------------------------------
# 서버 실행
# -------------------------------
if __name__ == "__main__":
    PORT = 8000
    threading.Thread(target=lambda: start_localtunnel(PORT, subdomain="mind-road3")).start()
    # Uvicorn은 메인 쓰레드에서 실행
    uvicorn.run(app, host="0.0.0.0", port=PORT)
