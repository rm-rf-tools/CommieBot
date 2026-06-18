FROM python:3.11-slim

WORKDIR /app

# 1. Install system dependencies
# Added libopus0 for native discord voice encoding support
# 1. Install system dependencies (added 'upgrade' to patch 0-days)
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y ffmpeg build-essential python3-dev git curl libgl1 libglib2.0-0 libopus0 && \
    rm -rf /var/lib/apt/lists/*

# 2. Clone the official FaceFusion repo into the container
RUN git clone https://github.com/facefusion/facefusion.git /app/facefusion

# 3. Install FaceFusion's internal dependencies + GPU ONNX support
RUN pip install --no-cache-dir -r /app/facefusion/requirements.txt && \
    pip install --no-cache-dir onnxruntime-gpu insightface

# 4. Install your bot's standard requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the bot's code
COPY . .

# 6. Create a startup script to log versions to docker logs before running the bot
RUN echo '#!/bin/bash\n\
echo "========================================="\n\
echo "      SYSTEM PACKAGE VERSIONS LOG        "\n\
echo "========================================="\n\
echo "[FFmpeg] Path: $(which ffmpeg)"\n\
ffmpeg -version | head -n 1\n\
echo "-----------------------------------------"\n\
echo "[Git] Path: $(which git)"\n\
git --version\n\
echo "-----------------------------------------"\n\
echo "[Curl] Path: $(which curl)"\n\
curl --version | head -n 1\n\
echo "-----------------------------------------"\n\
echo "[Python] Path: $(which python)"\n\
python --version\n\
echo "========================================="\n\
echo "Starting bot..."\n\
exec python -u main.py\n\
' > /app/start.sh && chmod +x /app/start.sh

# 7. Run the startup script instead of directly running python
CMD ["/app/start.sh"]