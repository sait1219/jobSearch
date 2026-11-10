FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The application uses only Python's standard library.
COPY main.py arbeitnow.py llm_client.py ai_jobs.py agent.py ./

RUN useradd --create-home --uid 10001 jobsearch \
    && mkdir -p /app/data /app/applications \
    && chown -R jobsearch:jobsearch /app

USER jobsearch

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
