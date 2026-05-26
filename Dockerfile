FROM python:3.12-slim

WORKDIR /app

COPY agent/requirements.txt .
RUN pip install -r requirements.txt

COPY agent/ .

CMD ["sh", "-c", "python web.py & python bot.py"]
