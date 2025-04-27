from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from enum import Enum

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Authentication setup
SECRET_KEY = os.environ.get("SECRET_KEY", "defaultsecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

# Define Models
class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"

class TokenData(BaseModel):
    id: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class UserBase(BaseModel):
    name: str
    email: EmailStr
    enrollment_number: Optional[str] = None
    branch: Optional[str] = None
    year: Optional[int] = None
    role: UserRole = UserRole.STUDENT

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "John Doe",
                "email": "john@example.com",
                "enrollment_number": "EN12345",
                "branch": "Computer Science",
                "year": 2,
                "role": "student",
                "created_at": "2023-01-01T00:00:00"
            }
        }

class UserInDB(User):
    hashed_password: str

class Subject(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    code: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SubjectCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None

class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"

class AttendanceRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    subject_id: str
    date: datetime
    status: AttendanceStatus
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AttendanceCreate(BaseModel):
    subject_id: str
    date: datetime
    status: AttendanceStatus

class AttendanceUpdate(BaseModel):
    status: AttendanceStatus

class AttendanceSummary(BaseModel):
    subject_id: str
    subject_name: str
    subject_code: str
    total_classes: int
    classes_attended: int
    attendance_percentage: float

# Authentication functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

async def get_user(email: str):
    user = await db.users.find_one({"email": email})
    if user:
        return UserInDB(**user)

async def authenticate_user(email: str, password: str):
    user = await get_user(email)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(id=user_id)
    except jwt.PyJWTError:
        raise credentials_exception
    user = await db.users.find_one({"id": token_data.id})
    if user is None:
        raise credentials_exception
    return User(**user)

# Auth routes
@api_router.post("/register", response_model=User)
async def register_user(user: UserCreate):
    # Check if user already exists
    db_user = await db.users.find_one({"email": user.email})
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user.password)
    user_data = user.dict()
    del user_data["password"]
    
    new_user = UserInDB(**user_data, hashed_password=hashed_password)
    new_user_dict = new_user.dict()
    
    await db.users.insert_one(new_user_dict)
    
    return User(**user_data)

@api_router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

# Subject routes
@api_router.post("/subjects", response_model=Subject)
async def create_subject(subject: SubjectCreate, current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN and current_user.role != UserRole.TEACHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create subjects"
        )
    
    new_subject = Subject(**subject.dict())
    await db.subjects.insert_one(new_subject.dict())
    
    return new_subject

@api_router.get("/subjects", response_model=List[Subject])
async def get_subjects(current_user: User = Depends(get_current_user)):
    subjects = await db.subjects.find().to_list(1000)
    return [Subject(**subject) for subject in subjects]

# Attendance routes
@api_router.post("/attendance", response_model=AttendanceRecord)
async def record_attendance(
    attendance: AttendanceCreate, 
    current_user: User = Depends(get_current_user)
):
    # Check if subject exists
    subject = await db.subjects.find_one({"id": attendance.subject_id})
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject not found"
        )
    
    # Check if attendance already recorded for this date and subject
    existing = await db.attendance.find_one({
        "student_id": current_user.id,
        "subject_id": attendance.subject_id,
        "date": {
            "$gte": attendance.date.replace(hour=0, minute=0, second=0),
            "$lt": attendance.date.replace(hour=23, minute=59, second=59)
        }
    })
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance already recorded for this date and subject"
        )
    
    # Create attendance record
    new_attendance = AttendanceRecord(
        student_id=current_user.id,
        subject_id=attendance.subject_id,
        date=attendance.date,
        status=attendance.status
    )
    
    await db.attendance.insert_one(new_attendance.dict())
    
    return new_attendance

@api_router.put("/attendance/{attendance_id}", response_model=AttendanceRecord)
async def update_attendance(
    attendance_id: str,
    attendance_update: AttendanceUpdate,
    current_user: User = Depends(get_current_user)
):
    # Find attendance record
    attendance = await db.attendance.find_one({"id": attendance_id})
    if not attendance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found"
        )
    
    # Check if user owns this record or is admin/teacher
    if attendance["student_id"] != current_user.id and current_user.role == UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this attendance record"
        )
    
    # Update attendance
    await db.attendance.update_one(
        {"id": attendance_id},
        {"$set": {"status": attendance_update.status}}
    )
    
    # Get updated record
    updated = await db.attendance.find_one({"id": attendance_id})
    
    return AttendanceRecord(**updated)

@api_router.get("/attendance", response_model=List[AttendanceRecord])
async def get_attendance(
    current_user: User = Depends(get_current_user),
    subject_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    # Build query
    query = {"student_id": current_user.id}
    
    if subject_id:
        query["subject_id"] = subject_id
    
    if start_date or end_date:
        query["date"] = {}
        if start_date:
            query["date"]["$gte"] = start_date
        if end_date:
            query["date"]["$lte"] = end_date
    
    # Get attendance records
    records = await db.attendance.find(query).to_list(1000)
    
    return [AttendanceRecord(**record) for record in records]

@api_router.get("/attendance/summary", response_model=List[AttendanceSummary])
async def get_attendance_summary(
    current_user: User = Depends(get_current_user)
):
    # Get all subjects
    subjects = await db.subjects.find().to_list(1000)
    
    result = []
    
    for subject in subjects:
        # Count total classes for this subject
        total_classes = await db.attendance.count_documents({
            "student_id": current_user.id,
            "subject_id": subject["id"]
        })
        
        # Count classes attended
        classes_attended = await db.attendance.count_documents({
            "student_id": current_user.id,
            "subject_id": subject["id"],
            "status": "present"
        })
        
        # Calculate percentage
        percentage = 0
        if total_classes > 0:
            percentage = (classes_attended / total_classes) * 100
        
        # Add to result
        result.append(AttendanceSummary(
            subject_id=subject["id"],
            subject_name=subject["name"],
            subject_code=subject["code"],
            total_classes=total_classes,
            classes_attended=classes_attended,
            attendance_percentage=percentage
        ))
    
    return result

# Sample data endpoint
@api_router.post("/sample-data", status_code=status.HTTP_201_CREATED)
async def create_sample_data():
    # Create sample subjects
    subjects = [
        {"name": "Mathematics", "code": "MATH101", "description": "Basic mathematics"},
        {"name": "Computer Science", "code": "CS101", "description": "Introduction to computer science"},
        {"name": "Physics", "code": "PHYS101", "description": "Basic physics"},
        {"name": "Chemistry", "code": "CHEM101", "description": "Introduction to chemistry"},
        {"name": "English", "code": "ENG101", "description": "English literature"}
    ]
    
    for subject_data in subjects:
        subject = Subject(
            id=str(uuid.uuid4()),
            name=subject_data["name"],
            code=subject_data["code"],
            description=subject_data["description"]
        )
        await db.subjects.insert_one(subject.dict())
    
    return {"message": "Sample data created successfully"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
