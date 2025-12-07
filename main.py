# main.py
# GURU APP — FastAPI backend (SQLite) with:
# - Users (buyers/sellers/admin flag)
# - Items (digital/physical/service)
# - Manual till payment recording + admin verification
# - File uploads (uploads/)
# - Admin endpoints protected by ADMIN_KEY header
# - Simple password hashing
# 
# Run:
# uvicorn main:app --host 0.0.0.0 --port 10000
#
import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import SQLModel, Field, create_engine, Session, select
from passlib.context import CryptContext
from pydantic import BaseModel
from datetime import datetime
import shutil
import uuid

# ---------- Config ----------
DATABASE_FILE = "guru.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Admin key: set this as an environment variable in Render (ADMIN_KEY)
ADMIN_KEY = os.getenv("ADMIN_KEY", "change_this_to_secure_key")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="GURU APP API")

# ---------- Models ----------
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str
    password_hash: str
    role: str = "buyer"  # "buyer" or "seller"
    approved: bool = False  # sellers must be approved by admin to list
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    price: float = 0.0
    owner_id: int
    product_type: str = "digital"  # digital/physical/service
    file_path: Optional[str] = None  # path to uploaded file (if digital)
    image_path: Optional[str] = None
    paid: bool = False  # listing payment paid
    active: bool = False  # visible to buyers only when active=True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Payment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    amount: float
    till_number: Optional[str] = None
    transaction_code: Optional[str] = None
    type: str = "listing_fee"  # or "subscription", "commission", etc.
    status: str = "pending"  # pending / verified / rejected
    created_at: datetime = Field(default_factory=datetime.utcnow)

# ---------- DB Setup ----------
sqlite_url = f"sqlite:///{DATABASE_FILE}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

create_db_and_tables()

# ---------- Schemas ----------
class RegisterPayload(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "buyer"  # seller or buyer

class LoginPayload(BaseModel):
    email: str
    password: str

class ItemCreatePayload(BaseModel):
    title: str
    description: Optional[str]
    price: float
    product_type: str  # digital/physical/service

class ManualPaymentPayload(BaseModel):
    user_id: int
    amount: float
    till_number: str
    transaction_code: str
    type: Optional[str] = "listing_fee"

# ---------- Utilities ----------
def get_session():
    with Session(engine) as session:
        yield session

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str):
    return pwd_context.verify(password, password_hash)

def get_user_by_email(session: Session, email: str) -> Optional[User]:
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()

def save_upload_file(upload_file: UploadFile, destination_dir=UPLOAD_DIR) -> str:
    # Save file with uuid prefix to avoid collisions
    ext = os.path.splitext(upload_file.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(destination_dir, filename)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return dest_path

# ---------- Public Endpoints ----------
@app.get("/")
def home():
    return {"message": "GURU APP API running"}

@app.post("/auth/register")
def register(payload: RegisterPayload, session: Session = Depends(get_session)):
    existing = get_user_by_email(session, payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        approved=False if payload.role == "seller" else True,  # auto-approve buyers
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"status": "ok", "user_id": user.id, "approved": user.approved}

@app.post("/auth/login")
def login(payload: LoginPayload, session: Session = Depends(get_session)):
    user = get_user_by_email(session, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # In production return JWT. For now, return simple user info
    return {"status": "ok", "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "approved": user.approved}}

@app.post("/items/create")
def create_item(
    title: str = Form(...),
    description: str = Form(None),
    price: float = Form(0.0),
    product_type: str = Form("digital"),
    owner_id: int = Form(...),
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
):
    # Check owner exists and is a seller
    owner = session.get(User, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")
    if owner.role != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can create items")
    if not owner.approved:
        raise HTTPException(status_code=403, detail="Seller not approved by admin")
    file_path = None
    image_path = None
    if file:
        file_path = save_upload_file(file)
    if image:
        image_path = save_upload_file(image)
    item = Item(
        title=title,
        description=description,
        price=price,
        owner_id=owner_id,
        product_type=product_type,
        file_path=file_path,
        image_path=image_path,
        paid=False,
        active=False,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"status": "created", "item_id": item.id, "file_path": file_path}

@app.get("/items/list", response_model=List[Item])
def list_items(session: Session = Depends(get_session)):
    statement = select(Item).where(Item.active == True)
    results = session.exec(statement).all()
    return results

@app.get("/items/{item_id}")
def get_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

# Endpoint to download an uploaded file (digital product)
@app.get("/uploads/{filename}")
def serve_upload_file(filename: str):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)

@app.post("/payments/manual")
def manual_payment(payload: ManualPaymentPayload, session: Session = Depends(get_session)):
    # record manual till payment
    user = session.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    payment = Payment(
        user_id=payload.user_id,
        amount=payload.amount,
        till_number=payload.till_number,
        transaction_code=payload.transaction_code,
        type=payload.type,
        status="pending",
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)
    return {"status": "recorded", "payment_id": payment.id}

# ---------- Admin-protected endpoints (simple key header check) ----------
def check_admin(x_admin_key: str = Header(...)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return True

@app.get("/admin/payments")
def admin_list_payments(session: Session = Depends(get_session), ok: bool = Depends(check_admin)):
    stmt = select(Payment).order_by(Payment.created_at.desc())
    return session.exec(stmt).all()

@app.post("/admin/payments/{payment_id}/verify")
def admin_verify_payment(payment_id: int, verified: bool = Form(True), x_admin_key: str = Header(...), session: Session = Depends(get_session)):
    # x_admin_key validated by dependency already; but double-check
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    p = session.get(Payment, payment_id)
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    p.status = "verified" if verified else "rejected"
    session.add(p)
    session.commit()
    # Optionally activate user's pending items or set seller approved
    # If payment was a listing_fee, attempt to find the owner's latest inactive item and activate it
    if p.type == "listing_fee" and p.status == "verified":
        # mark owner as approved seller if not already
        owner = session.get(User, p.user_id)
        if owner and owner.role == "seller" and not owner.approved:
            owner.approved = True
            session.add(owner)
            session.commit()
    return {"status": "ok", "payment_status": p.status}

@app.get("/admin/items")
def admin_list_items(session: Session = Depends(get_session), ok: bool = Depends(check_admin)):
    stmt = select(Item).order_by(Item.created_at.desc())
    return session.exec(stmt).all()

@app.post("/admin/items/{item_id}/activate")
def admin_activate_item(item_id: int, activate: bool = Form(True), x_admin_key: str = Header(...), session: Session = Depends(get_session)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.paid = True if activate else item.paid
    item.active = True if activate else False
    session.add(item)
    session.commit()
    return {"status": "ok", "active": item.active}

@app.get("/admin/users")
def admin_list_users(session: Session = Depends(get_session), ok: bool = Depends(check_admin)):
    stmt = select(User).order_by(User.created_at.desc())
    return session.exec(stmt).all()

@app.post("/admin/users/{user_id}/approve")
def admin_approve_user(user_id: int, approve: bool = Form(True), x_admin_key: str = Header(...), session: Session = Depends(get_session)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.approved = True if approve else False
    session.add(user)
    session.commit()
    return {"status": "ok", "approved": user.approved}

# ---------- Mount static uploads for easy access ----------
app.mount("/static_uploads", StaticFiles(directory=UPLOAD_DIR), name="static_uploads")
