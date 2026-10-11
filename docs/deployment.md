# Deployment Guide

## Local Development
1. Clone the repository
2. Create virtual environment: `python -m venv .venv`
3. Activate: `.venv/Scripts/Activate.ps1` (Windows) or `source .venv/bin/activate` (Linux/Mac)
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and configure
6. Run: `python main.py`

## Docker
```bash
docker build -t dq-agent .
docker run --env-file .env -p 8000:8000 -p 8501:8501 dq-agent
```

## Docker Compose
```bash
docker-compose up --build
```

## CI/CD
GitHub Actions workflow runs on push to main:
- Linting
- Unit tests
- Integration tests
