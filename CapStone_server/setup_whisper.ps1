# setup_whisper.ps1
# cmkae 설치(환경변수에 추가하기 선택, 윈도우 install 설치 - cmake-4.1.0-rc2-windows-x86_64.msi): https://cmake.org/download/
# 파일 실행 명령어: 
# Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
# powershell -ExecutionPolicy Bypass -File setup_whisper.ps1
# wav 파일 16bit 변환 명령어: ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav 

# 0. 설정
# "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser"
# "powershell -ExecutionPolicy Bypass -File setup_whisper.ps1"
# 중요! 만약 모델 다운로드가 안될 시 아래 링크에서 직접다운로드하여 whisper.cpp\models 폴더 밑에 넣으면 됨
# https://huggingface.co/ggerganov/whisper.cpp/blob/main/ggml-medium.bin medium모델 다운로드 링크

# 이후 c파일이기에 빌드 해주어야 함
# cmake -B build
# cmake --build build --config Release

# 1. whisper.cpp 클론
Write-Host "Whisper.cpp 다운로드 중..."
if(-Not (Test-path "whisper.cpp")) {
  git clone https://github.com/ggml-org/whisper.cpp.git
} else {
  Write-Host "Whisper.cpp 폴더가 이미 존재합니다."
}

# 2. 모델 다운로드
Write-Host "Whisper 모델 다운로드 중..."
$modelName = "ggml-medium.bin"
$modelPath = "whisper.cpp\models\$modelName"
if(-Not (Test-Path $modelPath)) {
  Invoke-WebRequest `
        -Uri "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$modelName" `
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
# Write-Host ".\whisper.cpp\build\bin\Release\whisper-cli.exe -m whisper.cpp\models\ggml-large-v2-q5_0.bin -f storage\audio\sample_01.wav --language ko"