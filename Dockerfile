FROM python:3.11-slim

WORKDIR /app

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY app.py setup.py ./

# Create host mount point
VOLUME /host

EXPOSE 8000

# Default command = run the app (will be overridden for setup)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
