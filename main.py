from fastapi import FastAPI, Request
from app import app as flask_app

app = FastAPI()

@app.post("/callback")
async def root(request: Request):
    data = await request.json()
    response = flask_app.test_client().post('/callback', json=data)
    return response.json
