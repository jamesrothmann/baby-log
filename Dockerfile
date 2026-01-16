# Use a lightweight Python image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create a directory for temporary files if it doesn't exist
RUN mkdir -p /tmp

# Expose the port (Render/Fly usually set the PORT env var, but this is good practice)
EXPOSE 5000

# Command to run the app using Gunicorn (Production server)
CMD gunicorn --bind 0.0.0.0:$PORT app:app