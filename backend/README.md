# Energy Grid API

## Phase 0 local setup

1. Create a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install the project:

   ```powershell
   python -m pip install -e ".[dev]"
   ```

3. Create your local configuration:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edit `backend/.env` locally. Put your keys after these exact names:

   ```dotenv
   EIA_API_KEY=your_eia_key
   FORTYGUARD_API_KEY=your_fortyguard_key
   ```

5. Start the API:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

6. Open `http://127.0.0.1:8000/docs` and call `GET /api/v1/health`.

## Useful commands

```powershell
python -m ruff check .
python -m uvicorn app.main:app --reload
```

Docker is optional for Phase 0. Once Docker Desktop is installed, start the API container with:

```powershell
docker compose up --build
```

