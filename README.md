# coika-auth_service

[![CI](https://github.com/acortescab/coika-auth_service/actions/workflows/ci_tests.yml/badge.svg)](https://github.com/acortescab/coika-auth_service/actions/workflows/ci_tests.yml)
[![codecov](https://codecov.io/gh/acortescab/coika-auth_service/branch/main/graph/badge.svg)](https://codecov.io/gh/acortescab/coika-auth_service)

Authentication and user session service for the Coika platform.

This project provides a FastAPI-based identity service with guest login, user registration, JWT-based authentication, refresh-token rotation, account linking, and health checks. It is designed to run locally with Docker Compose and supports PostgreSQL-backed persistence through SQLAlchemy and Alembic.

## Tech Stack

- Python 3.12+
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Pydantic + Pydantic Settings
- JWT via PyJWT
- bcrypt
- Docker / Docker Compose
- pytest

## Features

- Guest login flow
- User registration and login
- JWT access token validation
- Refresh token support and rotation
- Logout and token invalidation
- Account linking for guest users
- Health endpoint for service checks
- Dockerized local development setup

## Architecture

The service is organized around a lightweight layered structure:

- API layer: FastAPI routers under `app/api/v0/routes`
- Services: core business logic under `app/services`
- Repositories: database access logic under `app/repositories`
- Models: database schema under `app/db/models`
- Core utilities: security, config, and custom exceptions under `app/core`
- Schemas: request/response validation under `app/schemas`

## Project Structure

```text
.
├── alembic/
│   ├── versions/
│   ├── env.py
│   └── README
├── app/
│   ├── api/
│   │   └── v0/
│   │       └── routes/
│   │           ├── auth.py
│   │           └── health.py
│   ├── core/
│   │   ├── config.py
│   │   ├── exceptions/
│   │   └── security.py
│   ├── db/
│   │   ├── models/
│   │   ├── base.py
│   │   └── session.py
│   ├── dependencies.py
│   ├── factories.py
│   ├── main.py
│   ├── repositories/
│   ├── schemas/
│   └── services/
├── tests/
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci_tests.yml
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── Makefile
├── pyproject.toml
├── pytest.ini
├── requirements.txt
└── README.md
```

## Why Is It Structured This Way?

This project intentionally separates the code into small, purpose-specific layers so that authentication logic stays predictable and testable as the service grows.

- The API layer handles HTTP concerns only: request parsing, route registration, and response formatting. It should not contain business rules or persistence logic.
- Services contain the domain behavior: login, registration, token validation, session lifecycle, and account linking. This keeps the core authentication flows in one place and makes them easier to test in isolation.
- Repositories isolate database access from the rest of the application. That allows the service layer to operate on domain concepts instead of directly mixing SQLAlchemy logic with business rules.
- Models and schema definitions clearly separate persistence concerns from request/response validation. This reduces the risk of accidentally leaking database structures into API contracts.
- Core utilities centralize reusable concerns such as settings, security helpers, and custom exceptions so that the rest of the codebase remains consistent.

The result is a service that is easier to reason about, easier to extend with new auth features, and simpler to validate with focused unit and integration tests.

## Prerequisites

Before running the project locally, make sure you have:

- Docker and Docker Compose
- Python 3.12+
- uv
- Access to a local PostgreSQL instance or use the included Docker service

## Local Development

### 1. Create environment variables

Create a `.env` file in the project root with the following values:

```env
ENV=dev
DATABASE_URL_READER=postgresql://user:pass@db:5432/db
DATABASE_URL_WRITER=postgresql://user:pass@db:5432/db
```

The application reads these values at startup through the settings loader in `app/core/config.py`.

In `dev`, `SECRET_KEY` is loaded automatically from `secrets/private_key.pem`, so you do not need to set it in `.env`.

If you set `ENV` to a non-dev value, `SECRET_KEY` must be an RSA private key in PEM format (multi-line) in github secrets, because tokens are signed with `RS256`.

### 2. Start the development stack

```bash
make dev-up
```

This starts:

- the PostgreSQL database service
- the FastAPI application on port `8000`

The underlying Compose file is `docker-compose.yml`, which defines the `db` and `api` services and sets the `uvicorn` command for the API container.

### 3. Stop the stack

```bash
make dev-down
```

### 4. Rebuild containers

```bash
make dev-rebuild
```

## Testing

Run lint and the test suite with Docker Compose:

```bash
docker compose run --rm api ruff check .
docker compose run --rm api pytest -q --cov=. --cov-report=xml
```

The repository CI workflow runs the same checks in GitHub Actions.

## Useful Commands

```bash
# Start dev environment
make dev-up

# Stop dev environment
make dev-down

# Rebuild services
make dev-rebuild

# Run shell inside the API container
make shell

# Open PostgreSQL shell
make shell-db

# Generate Alembic migration
make migrate msg="describe migration"

# Apply latest migrations
make update-db

# Build the API image without starting it
docker compose build api
```

## API Overview

The service exposes versioned routes under `/v0`.

### Root and JWKS

- `GET /`
- `GET /.well-known/jwks.json`

### Health

- `GET /v0/health/`

### Auth

- `POST /v0/auth/register`
- `POST /v0/auth/login`
- `POST /v0/auth/guest-login` (see [Guest login](#guest-login))
- `POST /v0/auth/refresh-token`
- `GET /v0/auth/me`
- `POST /v0/auth/logout`
- `POST /v0/auth/link-account`

### Guest login

A guest is identified by `device_id` and authenticated by a `device_secret` issued by the server:

1. First call with only `device_id`: the guest is created and the response includes a `device_secret`.
   The server stores only its hash and never returns it again, so the client must persist it
   (keychain / secure storage).
2. Every later call must send both `device_id` and `device_secret`. A missing or wrong secret returns `401`.
3. Guests created before device secrets existed claim one on their next login (the response then includes
   `device_secret`). Until that happens, `device_id` alone is accepted for them.

If a client loses its `device_secret`, that guest can no longer log in (the account can still be reached if it
was linked to an email with `/link-account`).

## Security Notes

- Keep `SECRET_KEY` private and never commit it to source control.
- Use environment variables or a local `.env` file for development only.
- In production, rotate credentials and use secure environment configuration.

## License

This project is licensed under the terms described in the repository license file.

## CI/CD

The repository includes a GitHub Actions workflow at `.github/workflows/ci_tests.yml` that checks the project on pull requests to `develop` and `main`.

The workflow:

- builds the application image
- runs `ruff check .`
- runs `pytest -q --cov=. --cov-report=xml`

This matches the Docker Compose setup used by the service and keeps CI aligned with the local runtime configuration.

