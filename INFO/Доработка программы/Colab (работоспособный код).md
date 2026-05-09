!pip install whisperx



\# Удаляем проблемные версии и ставим стабильные

!pip uninstall -y numpy

!pip install "numpy<2.0.0"

!pip install openai-whisper



import whisperx

import gc



\# 1. Настройки

device = "cuda" 

audio\_file = "2026-04-23\_12-42-36\_meeting\_504180e6.wav" # <-- Убедитесь, что название файла в кавычках

YOUR\_HF\_TOKEN = "" # <-- Вставьте ваш токен от Hugging Face



\# 2. Загрузка модели и транскрибация

print("Начинаю расшифровку...")

\# Замените эту строку в вашем коде:

model = whisperx.load\_model("large-v3", device, compute\_type="float16")

audio = whisperx.load\_audio(audio\_file)

result = model.transcribe(audio, batch\_size=16)



\# 3. Диаризация (Принудительное указание модели 3.1)

print("Разделяю голоса... Это может занять пару минут.")

from whisperx.diarize import DiarizationPipeline



\# Явно указываем модель 3.1, на которую вы подписались

diarize\_model = DiarizationPipeline(

&#x20;   model\_name="pyannote/speaker-diarization-3.1", 

&#x20;   token=YOUR\_HF\_TOKEN, 

&#x20;   device=device

)



diarize\_segments = diarize\_model(audio)

result = whisperx.assign\_word\_speakers(diarize\_segments, result)



\# 4. Сохранение

with open("final\_dialogue.txt", "w", encoding="utf-8") as f:

&#x20;   for segment in result\["segments"]:

&#x20;       speaker = segment.get("speaker", "Unknown")

&#x20;       f.write(f"{speaker}: {segment\['text']}\\n")



print("ПОБЕДА! Файл 'final\_dialogue.txt' готов.")







