# Cloud Run image for the review console.
#
# The console and the agent fleet share the `provenance` package, so the image
# carries both: the console imports the same models and Firestore helpers the
# agents write with, which is what keeps one source of truth rather than a
# reporting copy that drifts.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not invalidate the wheel layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32" python-multipart

COPY provenance/ ./provenance/
COPY console/ ./console/

# On Cloud Run the attached service account supplies Application Default
# Credentials from the metadata server, so provenance.auth resolves without the
# local gcloud fallback ever being reached.
ENV GOOGLE_GENAI_USE_VERTEXAI=true \
    GEMINI_LOCATION=global

# Cloud Run injects PORT and expects the container to honour it.
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn console.main:app --host 0.0.0.0 --port ${PORT} --workers 1
