FROM python:3.9-slim

ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_SYSTEM_PYTHON=1

RUN pip install uv

WORKDIR /app

COPY requirements.txt .
RUN uv pip install -r requirements.txt

COPY . .

VOLUME /app/projects.json /app/start_script_template.txt /app/stop_script_template.txt

EXPOSE 20001

CMD ["python", "main.py"]
