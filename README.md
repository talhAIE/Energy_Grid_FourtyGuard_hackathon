# Energy Grid Heat-Demand Forecaster

A human-supervised, heat-driven electricity-demand risk forecasting platform. This application integrates granular thermal intelligence (from FortyGuard) with regional electricity demand data (from the EIA) to provide actionable insights for grid operators. It highlights localized heat anomalies and predicts their impact on grid load, empowering operators to make informed, data-driven decisions without directly automating grid controls.

## 🏗️ Architecture

The platform is split into a modern web frontend and a robust, scalable backend:

- **Frontend:** Built with React, TypeScript, and Vite. Styled with Tailwind CSS for a responsive, modern dashboard interface.
- **Backend:** Powered by FastAPI (Python 3.12+), utilizing SQLAlchemy for ORM and Pydantic for data validation.
- **Database:** PostgreSQL (hosted via Supabase), managing geospatial data (GeoAlchemy2) for operational zones.
- **Data Integrations:** FortyGuard (hyper-local temperature/heatmaps) and US EIA (regional grid demand).

## 🚀 Getting Started

Follow these instructions to get a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

You will need the following installed on your machine:
- [Python 3.12](https://www.python.org/downloads/) or higher
- [Node.js](https://nodejs.org/) (v18 or higher recommended)
- Git

### 1. Database Setup

This project uses PostgreSQL. You can use a local Postgres instance or a cloud provider like [Supabase](https://supabase.com/).
Ensure you have your database connection string ready (e.g., `postgresql+psycopg://user:password@host:port/dbname`).

### 2. Backend Setup

The backend handles all business logic, forecasting models, and third-party API integrations.

1. **Navigate to the backend directory:**
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   The project uses `pyproject.toml`. Install the package in editable mode with development dependencies:
   ```bash
   pip install -e .[dev]
   ```

4. **Environment Configuration:**
   Create a `.env` file in the `backend` directory (you can copy from a `.env.example` if available) and configure your variables:
   ```env
   APP_ENV=development
   DATABASE_URL=postgresql+psycopg://your_db_url_here
   FORTYGUARD_API_KEY=your_fortyguard_key_here
   EIA_API_KEY=your_eia_key_here
   REPLAY_MODE=false # Set to true to use offline demo data without API calls
   ```

5. **Run the Backend Server:**
   ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   The API will be available at `http://127.0.0.1:8000`. You can view the interactive API documentation at `http://127.0.0.1:8000/docs`.

### 3. Frontend Setup

The frontend is a Vite-powered React application.

1. **Navigate to the frontend directory:**
   Open a new terminal window/tab and navigate to:
   ```bash
   cd frontend
   ```

2. **Install Node modules:**
   ```bash
   npm install
   ```

3. **Environment Configuration:**
   Create a `.env` file in the `frontend` directory based on `.env.example`:
   ```env
   VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
   ```

4. **Run the Development Server:**
   ```bash
   npm run dev
   ```
   The dashboard will typically be available at `http://localhost:3000` or `http://localhost:5173`. Check your terminal output for the exact local link.

## 🧪 Demo & Offline Replay Mode

If you don't have active API keys for FortyGuard or the EIA, or if you simply want to demonstrate the platform reliably without network dependencies, you can enable **Replay Mode**.

In your backend `.env` file, set:
```env
REPLAY_MODE=true
```

This will load scrubbed, offline fixture data (focused on Houston, Texas) simulating a heatwave escalation scenario, allowing you to cycle through the pipeline and view recommendations without making any external API calls.

## 📁 Repository Structure

- `/backend` - FastAPI Python server, database models, AI/forecasting services, and orchestration logic.
- `/frontend` - Vite/React web application containing the operator dashboard and visualization components.
- `/backend/app/scripts/fix_zones.py` - Utility script to manage and reset the operational grid zones.

## 🛠️ Deployment

- **Backend:** Easily deployable as a web service on platforms like Render or Railway. Ensure your build command is `pip install .` and your start command is `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **Frontend:** Ready for zero-config deployment on Vercel or Netlify. Set the framework preset to Vite and configure the `VITE_API_BASE_URL` environment variable.
