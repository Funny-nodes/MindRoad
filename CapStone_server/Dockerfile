FROM node:22

# FFmpeg 설치
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 패키지 설치
COPY package*.json ./
RUN npm ci

# 소스 복사
COPY . .

EXPOSE 8080

CMD ["node", "src/server.js"]