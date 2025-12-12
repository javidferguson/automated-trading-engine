# Use Python 3.14 (or latest available)
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    zip \
    && apt-get install -y gcc \
    #&& apt-get install -y g++ \
    && apt-get install -y git \
    && apt-get install -y iputils-ping \
    && rm -rf /var/lib/apt/lists/*
#RUN apt-get update && apt-get install -y \
#    gcc \
#    g++ \
#    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements file
COPY ../requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY options-trading-main--TEST.py .
COPY config/options-trader-config.yaml /app/config/options-trader-config.yaml

# Create volume mount points
VOLUME ["/app/logs", "/app/config"]

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
#CMD ["python", "options-trading-main--TEST.py"]
CMD ["bash"]