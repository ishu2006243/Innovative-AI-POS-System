# Intelligent POS

A point-of-sale frontend and FastAPI backend with demand forecasting, dynamic pricing, and anomaly detection.

## Requirements

- Python 3.10 or newer
- MySQL with the database and tables expected by the backend

## Run locally

1. Create and activate a virtual environment in the project directory.
2. Install backend dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set your MySQL connection values. Do not commit `.env`.
4. Start the API from the `backend` directory:

   ```powershell
   cd backend
   uvicorn main:app --reload
   ```

5. Open `index.html` in a browser. The frontend calls the API at `http://127.0.0.1:8000`.
   API documentation is available at `http://127.0.0.1:8000/docs`.

The project does not include database credentials or a database schema. Configure the
database and tables required by the API before using database-backed features.
