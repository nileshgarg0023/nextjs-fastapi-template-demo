# Setup Guide

## Quick Start

This template has been optimized for technical coding interviews with a **one-command setup**!

### Prerequisites

Before running the setup script, ensure you have:

1. **uv** - Python package manager
   - Install: https://docs.astral.sh/uv/getting-started/installation/

2. **Node.js** - JavaScript runtime
   - Install: https://nodejs.org/en/download/

3. **pnpm** - Fast package manager
   - Install: `npm install -g pnpm`

### Automated Setup (Recommended)

Run the setup script:

```bash
./setup.sh
```

This will automatically:
- ✅ Verify all prerequisites are installed
- ✅ Create `.env` files with auto-generated secret keys
- ✅ Install backend dependencies (Python packages)
- ✅ Install frontend dependencies (Node packages)
- ✅ Set up SQLite database and run migrations
- ✅ Seed database with test user
- ✅ Generate OpenAPI schema and TypeScript client

### Start the Application

After setup completes, start both servers:

```bash
# Terminal 1 - Start Backend
make start-backend

# Terminal 2 - Start Frontend
make start-frontend
```

### Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

### Gmail Priority Sorting

The dashboard includes a Gmail priority sorter at:

```bash
http://localhost:3000/dashboard/gmail
```

Configure Google OAuth and OpenAI in `fastapi_backend/.env`:

```bash
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/emails/gmail/oauth/callback
OPENAI_API_KEY=your_openai_api_key
OPENAI_EMAIL_TRIAGE_MODEL=gpt-5
FRONTEND_URL=http://localhost:3000
```

Add the redirect URI in Google Cloud Console exactly:

```bash
http://localhost:8000/emails/gmail/oauth/callback
```

The app asks Google for Gmail modify access so it can read messages and apply labels. OpenAI does not get Gmail tool access; the backend reads Gmail, asks OpenAI only for priority classification, and applies labels itself.

Manual sorting endpoint used by the UI:

```bash
POST /emails/gmail/triage-connected
```

Priority labels are category-aware:

```bash
Primary/High
Primary/Medium
Primary/Low
Updates/High
Updates/Medium
Updates/Low
Promotions/High
Promotions/Medium
Promotions/Low
```

Promotions default to low, but can be upgraded when there is real urgency, account/payment/legal/security relevance, a near deadline, an important sender, or a match with the user's active focus.

Keep `Dry run` checked to preview labels. Uncheck it only when you want the backend to create/apply Gmail labels.

For latest email events, configure Google Cloud Pub/Sub and set:

```bash
GMAIL_PUBSUB_TOPIC_NAME=projects/your-google-cloud-project/topics/gmail
GMAIL_WEBHOOK_TOKEN=change-me
OPENAI_EMAIL_TRIAGE_ON_WEBHOOK=True
```

Point the Pub/Sub push subscription at:

```bash
POST /emails/gmail/webhook?token=change-me
```

Then call:

```bash
POST /emails/gmail/watch-connected
```

Google cannot push webhooks to plain `localhost`; use a public HTTPS tunnel such as ngrok for local webhook testing.

### Test User Credentials

The setup script automatically creates a test user:

- **Email**: `test@example.com`
- **Password**: `TestPassword123#`

You can log in immediately without needing to register!

## What Changed from Original Template?

### Database Migration: PostgreSQL → SQLite

The template now uses **SQLite** instead of PostgreSQL for simplified setup:

- ✅ **No Docker required** for local development
- ✅ **Zero configuration** - database file created automatically
- ✅ **Faster setup** - perfect for coding interviews and demos
- ✅ **Production ready** - can still deploy to Vercel or any platform

### Key Changes Made

1. **Dependencies**
   - Removed: `asyncpg` (PostgreSQL driver)
   - Added: `aiosqlite` (SQLite async driver)

2. **Database Configuration**
   - Database: `app.db` (local SQLite file)
   - Test Database: `test.db` (local SQLite file)

3. **Docker**
   - Now **optional** (not required for local development)
   - PostgreSQL services commented out in `docker-compose.yml`

4. **Setup Process**
   - New: `./setup.sh` automated setup script
   - Generates unique secrets automatically
   - One-command setup from zero to running

## Manual Setup (Alternative)

If you prefer to set up manually:

### Backend

```bash
cd fastapi_backend

# 1. Create environment file
cp .env.example .env

# 2. Generate and add secret keys to .env
python3 -c "import secrets; print(secrets.token_hex(32))"
# Copy output to ACCESS_SECRET_KEY, RESET_PASSWORD_SECRET_KEY, VERIFICATION_SECRET_KEY

# 3. Install dependencies
uv sync

# 4. Generate initial migration
make generate-migration migration_name="Initial schema"

# 5. Run migrations
make migrate-db

# 6. Seed database with test user
PYTHONPATH=. uv run python3 commands/seed_db.py

# 7. Generate OpenAPI schema
PYTHONPATH=. uv run python3 commands/generate_openapi_schema.py
```

### Frontend

```bash
cd nextjs-frontend

# 1. Create environment file
cp .env.example .env.local

# 2. Install dependencies
pnpm install

# 3. Generate TypeScript client
pnpm run generate-client
```

## Useful Commands

### Backend

```bash
make start-backend          # Start the backend server
make setup-test            # Verify setup completed successfully
make test-backend          # Run backend tests
make migrate-db            # Run database migrations
make generate-migration    # Generate new migration (use: migration_name="description")
make seed-db               # Seed database with test user
```

### Frontend

```bash
make start-frontend        # Start the frontend server
make test-frontend         # Run frontend tests
```

### Database Management

```bash
# Generate a new migration after model changes
make generate-migration migration_name="Add new field"

# Apply migrations
make migrate-db

# View migration status
cd fastapi_backend && uv run alembic current

# View migration history
cd fastapi_backend && uv run alembic history
```

## Troubleshooting

### "Module not found" errors

Make sure you've run `uv sync` in the backend and `pnpm install` in the frontend.

### Database issues

Delete the database and regenerate:
```bash
cd fastapi_backend
rm app.db
make migrate-db
```

### Frontend can't connect to backend

1. Ensure backend is running on http://localhost:8000
2. Check that `nextjs-frontend/.env.local` exists with `API_BASE_URL=http://localhost:8000`
3. Regenerate OpenAPI client: `cd nextjs-frontend && pnpm run generate-client`

### "Unknown error" on login/register

Run the setup script again to regenerate all files:
```bash
./setup.sh
```

## Why SQLite for Interviews?

SQLite is perfect for coding interviews because:

1. **Zero Setup** - No external database server required
2. **Portable** - Single file database, easy to share/reset
3. **Fast** - In-memory mode available for tests
4. **Production Ready** - Used by major applications
5. **Interview Friendly** - Focus on code, not infrastructure

For production deployments, you can still use PostgreSQL or other databases by updating the `DATABASE_URL` environment variable.
