FROM python:3.12-slim

WORKDIR /app

# 1. Install system dependencies
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y ffmpeg build-essential python3-dev git curl libgl1 libglib2.0-0 libopus0 chromium chromium-driver && \
    rm -rf /var/lib/apt/lists/*

# 2. Install NVIDIA CUDA runtime libraries via pip to provide libcudart.so internally
RUN pip install --no-cache-dir nvidia-cudnn-cu12 nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 || true
RUN pip install --no-cache-dir nvidia-cudnn-cu13 nvidia-cublas-cu13 nvidia-cuda-runtime-cu13 || true

# Link the installed pip CUDA libraries to the system's library path
ENV LD_LIBRARY_PATH="/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:${LD_LIBRARY_PATH}"

# 3. Clone the official FaceFusion repo into the container
RUN git clone https://github.com/facefusion/facefusion.git /app/facefusion

# 4. Install FaceFusion's internal dependencies + GPU ONNX support
RUN pip install --no-cache-dir -r /app/facefusion/requirements.txt && \
    pip install --no-cache-dir "onnxruntime-gpu<1.23.0" insightface

# 5. Install your bot's standard requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -m pip install -U --pre "yt-dlp[default,curl-cffi]"
RUN python3 -m pip install -U "git+https://github.com/instaloader/instaloader.git@refs/pull/2706/head"

# 6. Copy the bot's code
COPY . .

# 7. Create a startup script to log versions to docker logs before running the bot
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

# 8. Run the startup script instead of directly running python
CMD ["/app/start.sh"]