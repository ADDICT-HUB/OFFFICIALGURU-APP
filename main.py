from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
import sqlite3
import os

app = FastAPI()

# ==========================
# STATIC & TEMPLATES
# ==========================
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DB = "guru_app.db"


# ==========================
# DATABASE INITIAL SETUP
# ==========================
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # USERS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'user'
        )
    """)

    # SELLERS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sellers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            description TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # ITEMS / PROJECTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            name TEXT,
            price INTEGER,
            file_path TEXT,
            FOREIGN KEY (seller_id) REFERENCES sellers(id)
        )
    """)

    # MANUAL TILL PAYMENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            amount INTEGER,
            approved INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # CREATE DEFAULT ADMIN IF NOT EXISTS
    cur.execute("SELECT * FROM users WHERE username='admin'")
    if not cur.fetchone():
        hashed = pwd_context.hash("admin123")
        cur.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    ("admin", hashed, "admin"))

    conn.commit()
    conn.close()


init_db()


# ==========================
# HOME
# ==========================
@app.get("/")
def home():
    return {"message": "GURU APP API is running!"}


# ==========================
# USER SIGNUP
# ==========================
@app.post("/signup")
def signup(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    hashed = pwd_context.hash(password)

    try:
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, hashed))
        conn.commit()
    except:
        return {"error": "Username already exists"}

    return {"message": "Signup successful"}


# ==========================
# USER LOGIN
# ==========================
@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT id, password, role FROM users WHERE username=?", (username,))
    user = cur.fetchone()

    if not user:
        return {"error": "User not found"}

    if not pwd_context.verify(password, user[1]):
        return {"error": "Incorrect password"}

    return {"message": "Login successful", "user_id": user[0], "role": user[2]}


# ==========================
# SELLER REGISTRATION
# ==========================
@app.post("/seller/create")
def create_seller(user_id: int = Form(...), description: str = Form(...)):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("INSERT INTO sellers (user_id, description) VALUES (?, ?)",
                (user_id, description))
    conn.commit()

    return {"message": "Seller account created"}


# ==========================
# UPLOAD ITEM / PROJECT
# ==========================
@app.post("/item/upload")
async def upload_item(
    seller_id: int = Form(...),
    name: str = Form(...),
    price: int = Form(...),
    file: UploadFile = File(...)
):
    folder = "uploads"
    os.makedirs(folder, exist_ok=True)

    file_path = f"{folder}/{file.filename}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO items (seller_id, name, price, file_path)
        VALUES (?, ?, ?, ?)
    """, (seller_id, name, price, file_path))
    conn.commit()

    return {"message": "Item uploaded successfully"}


# ==========================
# MANUAL TILL PAYMENT UPLOAD
# ==========================
@app.post("/payment/upload")
def upload_payment(
    user_id: int = Form(...),
    code: str = Form(...),
    amount: int = Form(...)
):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO payments (user_id, code, amount)
        VALUES (?, ?, ?)
    """, (user_id, code, amount))

    conn.commit()
    return {"message": "Payment submitted, waiting for admin approval"}


# ==========================
# ADMIN LOGIN PAGE
# ==========================
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT id, password FROM users WHERE username='admin'")
    admin = cur.fetchone()

    if not admin:
        return {"error": "Admin not found"}

    if not pwd_context.verify(password, admin[1]):
        return {"error": "Wrong password"}

    return RedirectResponse("/admin/dashboard", status_code=303)


# ==========================
# ADMIN DASHBOARD
# ==========================
@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT * FROM users")
    users = cur.fetchall()

    cur.execute("SELECT * FROM sellers")
    sellers = cur.fetchall()

    cur.execute("SELECT * FROM items")
    items = cur.fetchall()

    cur.execute("SELECT * FROM payments")
    payments = cur.fetchall()

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "users": users,
        "sellers": sellers,
        "items": items,
        "payments": payments
    })
