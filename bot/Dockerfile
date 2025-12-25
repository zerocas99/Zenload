# 1. Используем официальный легкий образ Python
FROM python:3.10-slim

# 2. Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# 3. Обновляем списки пакетов и УСТАНАВЛИВАЕМ FFMPEG (для Linux)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean

# 4. Копируем файл зависимостей и устанавливаем библиотеки Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем остальной код бота в контейнер
COPY . .

# 6. Команда запуска бота
CMD ["python", "bot.py"]