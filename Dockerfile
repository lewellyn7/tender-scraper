FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 安装浏览器
RUN playwright install chromium

# 默认命令
CMD ["python", "main.py"]
