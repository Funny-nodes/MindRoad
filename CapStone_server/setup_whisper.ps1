# setup_whisper.ps1
# cmkae 설치(환경변수에 추가하기 선택, 윈도우 install 설치 - cmake-4.1.0-rc2-windows-x86_64.msi): https://cmake.org/download/
# 파일 실행 명령어: 
# Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
# powershell -ExecutionPolicy Bypass -File setup_whisper.ps1
# wav 파일 16bit 변환 명령어: ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav 



# 1. whisper.cpp 클론
Write-Host "Whisper.cpp 다운로드 중..."
if(-Not (Test-path "whisper.cpp")) {
  git clone https://github.com/ggml-org/whisper.cpp.git
} else {
  Write-Host "Whisper.cpp 폴더가 이미 존재합니다."
}

# 2. 모델 다운로드
Write-Host "Whisper 모델 다운로드 중..."
$modelPath = "whisper.cpp\models\ggml-large-v1-q5_0.gguf"
if(-Not (Test-Path $modelPath)) {
  Invoke-WebRequest `
        -Uri "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v1.bin?download=true" `
        -OutFile $modelPath
} else {
  Write-Host "모델 파일이 이미 존재합니다."
}

# 3. whisper.cpp 빌드
Write-Host "whisper.cpp 빌드 중..."
Set-Location whisper.cpp
if(-Not (Test-Path "build")) {
    cmake -B build
}

cmake --build build --config Release
Set-Location ..

# 4. 완료 메시지
Write-Host "설치 완료!"
Write-Host "실행 예시: "
Write-Host ".\whisper.cpp\build\bin\Release\whisper-cli.exe -m whisper.cpp\models\ggml-large-v1.bin -f storage\audio\sample.wav --language ko"