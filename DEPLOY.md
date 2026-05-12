# Deploy

## AWS App Runner (Primary)

1. Push repository to GitHub.
2. In AWS Console, open **App Runner** and create a service from source code repository.
3. Build settings:
   - Runtime: Python 3
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
4. Set environment variables:
   - `DATABASE_URL=sqlite:///./jobs.db`
   - `ENABLE_SOURCES=djinni,workua,nofluffjobs`
5. Deploy.

Notes:
- SQLite is ephemeral on App Runner instances. For durable production storage, switch to external DB (RDS/Postgres) and update `DATABASE_URL`.
- Keep `dou` disabled unless Playwright runtime/browsers are prepared.

## AWS ECS (Optional)

1. Build image:
```bash
docker build -t job-vc:latest .
```
2. Push to ECR.
3. Create ECS task definition:
   - Container port `8000`
   - Command default from Dockerfile
   - Env vars:
     - `DATABASE_URL`
     - `ENABLE_SOURCES`
4. Create ECS service (Fargate).
5. Attach Application Load Balancer and route HTTP traffic to port `8000`.

## Playwright / DOU Source

DOU parser is optional and disabled by default via `ENABLE_SOURCES`.

To enable DOU in containerized environments, install browsers during image build:
```bash
playwright install --with-deps chromium
```

