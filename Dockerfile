# Use a minimal Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy the Python script into the image
COPY watch_docker.py .

# Install required Python packages
RUN pip install --no-cache-dir docker requests

ENV WEBHOOK_URL ""

# Run the script
CMD ["python", "watch_docker.py"]
