from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "GURU APP API running"}

# Placeholder endpoints
@app.post("/auth/register")
def register():
    return {"status": "ok"}

@app.post("/auth/login")
def login():
    return {"status": "ok"}

@app.post("/items/create")
def create_item():
    return {"status": "item_created"}

@app.post("/payments/manual")
def pay_manual():
    return {"status": "payment_recorded", "note": "Manual till payment placeholder"}    
