FROM python:3.10.5-slim as base

# Python env flags
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONBUFFERED=1
ENV PYTHONFAULTHANDLER=1

# Poetry env flags
ENV POETRY_VIRTUALENVS_IN_PROJECT=false
ENV POETRY_NO_INTERACTION=1

# OS Update / Upgrade packages
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y curl gcc \
    && apt-get autoremove -y \
    && apt-get clean \
    && curl -sSL https://install.python-poetry.org | python3 - --preview

# Change workdir
WORKDIR /app

# Copy modules to cache them in docker layer
COPY . /app/

# Install dependencies
RUN /root/.local/bin/poetry config virtualenvs.create false \
    && /root/.local/bin/poetry install

ENV PYTHONPATH /app/*

CMD ["/root/.local/bin/poetry", "run", "python", "-m", "main"]