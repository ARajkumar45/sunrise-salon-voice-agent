# Piper text to speech (open source, GPL-3.0) as a small HTTP service.
# It runs in its own container; our code only talks to it over HTTP.
FROM python:3.12-slim
RUN pip install --no-cache-dir "piper-tts[http]==1.8.0"
WORKDIR /voices
ARG PIPER_VOICE=en_US-lessac-medium
ENV PIPER_VOICE=${PIPER_VOICE}
# The voice model is baked into the image so a call never waits for a download.
RUN python -m piper.download_voices ${PIPER_VOICE}
EXPOSE 5000
CMD ["sh", "-c", "python -m piper.http_server -m ${PIPER_VOICE} --host 0.0.0.0 --port 5000"]
