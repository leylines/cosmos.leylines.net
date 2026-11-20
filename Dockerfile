FROM python:3.12-slim

WORKDIR /app

# System-Abhängigkeiten für wissenschaftliche Berechnungen
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python-Bibliotheken installieren
RUN pip install --no-cache-dir fastapi uvicorn skyfield convertdate pandas

# App-Code kopieren
COPY main.py .
COPY de422.bsp .
COPY hip_main.dat .
COPY config.json .
COPY modern_st.json .
COPY viewer.html .

# Port freigeben
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
