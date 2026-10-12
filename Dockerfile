FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY monitor.py test_monitor.py ./
RUN python -m unittest -v
ENV PYTHONUNBUFFERED=1 PORT=10000
EXPOSE 10000
CMD ["python", "monitor.py"]
