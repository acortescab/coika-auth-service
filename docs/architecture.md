# Authentication Service Architecture

```mermaid
flowchart LR
    Client[Client App\nWeb / Mobile / API Consumer]

    subgraph API[FastAPI API Layer]
        Router[Routes\napp/api/v0/routes]
        Security[Auth Middleware & JWT\napp/core/security.py]
    end

    subgraph App[Application Layer]
        Dependencies[Dependency Providers\napp/dependencies.py]
        Factories[Service Factories\napp/factories.py]
        Services[Services\nAuthService / LookupService / TokenService]
        Schemas[Schemas\napp/schemas]
    end

    subgraph Data[Data Layer]
        Repositories[Repositories\nPlayerRepository / RefreshTokenRepository]
        Models[SQLAlchemy Models\nPlayer / RefreshToken]
        DB[(PostgreSQL)]
    end

    subgraph Infra[Infrastructure]
        Config[Settings & Config\napp/core/config.py]
        Migrations[Alembic Migrations\nalembic/versions]
        Docker[Docker Compose / Containers]
    end

    Client -->|HTTP requests| Router
    Router --> Dependencies
    Dependencies --> Factories
    Factories --> Services
    Services --> Repositories
    Services --> Security
    Repositories --> Models
    Models --> DB

    Router --> Schemas
    Services --> Config
    Config --> DB

    Migrations --> DB
    Docker --> API
    Docker --> DB

    classDef client fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1;
    classDef api fill:#E8F5E9,stroke:#43A047,color:#1B5E20;
    classDef app fill:#FFF3E0,stroke:#FB8C00,color:#E65100;
    classDef data fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
    classDef infra fill:#FCE4EC,stroke:#D81B60,color:#880E4F;

    class Client client;
    class Router,Security api;
    class Dependencies,Factories,Services,Schemas app;
    class Repositories,Models,DB data;
    class Config,Migrations,Docker infra;
```

## Overview

This service is a FastAPI authentication backend for the Coika platform. It handles guest login, user registration, JWT access/refresh token creation, account linking, and logout flows.

## Layers

- API layer: route handlers under app/api/v0/routes
- Service layer: business logic in app/services
- Repository layer: database access in app/repositories
- Model layer: SQLAlchemy persistence models in app/db/models
- Core layer: settings, JWT helpers, and exception handling in app/core
- Infrastructure layer: PostgreSQL, Docker, and Alembic migration tooling

## Request flow

1. A client calls an endpoint like /v0/auth/login or /v0/auth/refresh-token.
2. The route resolves the required service dependency.
3. The service validates credentials and issues or revokes tokens.
4. Repositories read/write player and refresh-token records.
5. The PostgreSQL database persists the resulting state.
6. Alembic migrations keep schema changes consistent across environments.

## Main responsibilities

- Guest account creation and login
- Email/password registration and login
- Access token validation and refresh token rotation
- Token revocation during logout
- Account linking from guest to registered user
- Health monitoring via /v0/health
