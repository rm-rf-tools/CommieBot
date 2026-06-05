FROM python:3.11-slim

WORKDIR /app

# 1. Install system dependencies
# Added libopus0 for native discord voice encoding support
RUN apt-get update && \
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

CMD ["python", "-u", "main.py"]