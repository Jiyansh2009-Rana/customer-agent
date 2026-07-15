import os
import json
from typing import List, Optional, Literal 
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from pyairtable import Api
from pyairtable.formulas import match
from groq import Groq
import jwt
import uvicorn

load_dotenv()

# --- Configurations & Environment Variables ---
AIRTABLE_PAT = os.getenv("AIRTABLE_PAT")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Security configurations
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "YOUR_SUPER_SECRET_PRODUCTION_KEY_CHANGE_THIS")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# --- Third-Party Clients ---
api = Api(AIRTABLE_PAT)
Database = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
groq_client = Groq(api_key=GROQ_API_KEY)

app = FastAPI(title="Production Secure Business Agent API")
security_scheme = HTTPBearer()

# --- Auth & Pydantic Models ---
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    role: Literal["customer", "shop owner"]

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class UserSession(BaseModel):
    email: str
    role: Literal["customer", "shop owner"]

class Base_items(BaseModel):
    Name : str
    E_mail : EmailStr  
    mobile_no : str
    Date : date
    amount : float
    Buying_products : str
    ordered_stutas : Literal["Delivered", "Panding"]

class create_item(Base_items):
    pass

class update_item(BaseModel):
    Name : Optional[str] = None
    mobile_no : Optional[str] = None
    Date : Optional[date] = None
    amount : Optional[float] = None
    Buying_products : Optional[str] = None
    ordered_stutas : Optional[Literal["Delivered", "Panding"]] = None

# --- Core Authentication Utilities ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> UserSession:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("role")
        if email is None or role not in ["customer", "shop owner"]:
            raise credentials_exception
        return UserSession(email=email, role=role)
    except jwt.PyJWTError:
        raise credentials_exception

# --- Database Helper Functions ---
def get_record(E_mail: EmailStr, Name: str):
    formula = match({"E_mail": E_mail, "Name": Name})
    record = Database.first(formula=formula)
    if not record:
        raise HTTPException(status_code=404, detail=f"No record found with email : {E_mail} and Name : {Name}")
    return record

def format_record(record):
    return {
        "id": record["id"],
        **record["fields"]
    }

def get_all_record():
    records = Database.all()
    return [format_record(record) for record in records]

def record_by_email_name(email: EmailStr, Name: str):
    record = get_record(email, Name)
    return format_record(record)
    
def create_item_fun(item: create_item):
    formula = match({"E_mail": item.E_mail})
    if Database.first(formula=formula):
        raise HTTPException(status_code=400, detail="Email or Customer already exists")
    new_record = Database.create(item.model_dump())
    return format_record(new_record) 
                    
def update_existing_record(email: str, name: str, item_update: update_item):
    record = record_by_email_name(email, name)
    updates = item_update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    updated_record = Database.update(record["id"], updates)
    return format_record(updated_record)

def delete_item_by_email(email: EmailStr, name: str):
    record = record_by_email_name(email, name)
    Database.delete(record["id"])
    return {"message": f"Order of {name} is cancelled"}

# --- LLM Function Tool Schema Definitions ---
tools = [
  {
    "type": "function",
    "function": {
      "name": "get_all_record",
      "description": "Retrieves all formatted records currently stored in the database. Restricted to shop owners.",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "record_by_email_name",
      "description": "Retrieves a specific formatted record using the provided email address and name.",
      "parameters": {
        "type": "object",
        "properties": {
          "email": {"type": "string", "format": "email", "description": "The email address associated with the record."},
          "Name": {"type": "string", "description": "The name associated with the record."}
        },
        "required": ["email", "Name"]
      }
    }
  }
  # Note: Other schemas (create, update, delete) remain structurally unchanged but are protected below...
]

# --- API Endpoints ---

@app.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    """
    Production Endpoint for authenticating users and generating JWT structures.
    Replace static validation with a secure database lookup using passlib.hash.
    """
    # DEMO CHECK: Replace with true password hashing verification in production
    if payload.password != "supersecretpassword": 
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    token_data = {"sub": payload.email, "role": payload.role}
    access_token = create_access_token(data=token_data)
    
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/your_Bussiness_agent")
def llm_agent(user_prompt: str, current_user: UserSession = Depends(get_current_user)):
    """
    Protected agent endpoint implementing RBAC validation rules at execution block level.
    """
    # Context Injection for the Agent System Prompt
    system_instruction = (
        f"You are a helpful AI assistant. You must respect authorization laws. "
        f"The current user interacting with you has the email: '{current_user.email}' and the role: '{current_user.role}'.\n"
        f"If the user role is 'customer', they CANNOT view other customer data. "
        f"When using tools, ONLY call them using the provided function schema."
    )

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        completion = groq_client.chat.completions.create(  
            model="qwen/qwen3.6-27b",  
            messages=messages,  
            tools=tools,  
            tool_choice="auto",  
        )  
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Gateway Error: {str(e)}")

    if not completion or not completion.choices:
        raise HTTPException(status_code=500, detail="Empty response received from LLM cluster.")
        
    response_message = completion.choices[0].message  
    tool_calls = response_message.tool_calls
    
    if not tool_calls:
        return {"response": response_message.content}
    
    messages.append(response_message)
    
    for tool_call in tool_calls:
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        result = None
        
        try:
            # --- STRICT ENFORCEMENT LAYER (RBAC) ---
            if current_user.role == "customer":
                # 1. Block Customers from calling global fetch APIs
                if function_name == "get_all_record":
                    raise PermissionError("Access Denied: Customers cannot list all platform records.")
                
                # 2. Force validation ensuring target emails match token details
                target_email = arguments.get("email") or arguments.get("item", {}).get("E_mail") or arguments.get("item_update", {}).get("E_mail")
                if target_email and target_email != current_user.email:
                    raise PermissionError("Access Denied: You cannot manipulate records belonging to other users.")

            # --- Tool Routing Execution ---
            if function_name == "get_all_record":
                result = get_all_record()
                
            elif function_name == "record_by_email_name":
                result = record_by_email_name(
                    email=arguments.get("email"), 
                    Name=arguments.get("Name")
                )
            
            elif function_name == "create_item_fun":
                item_data = create_item(**arguments.get("item", {}))
                result = create_item_fun(item=item_data)
        
            elif function_name == "update_existing_record":
                update_data = update_item(**arguments.get("item_update", {}))
                result = update_existing_record(
                    email=arguments.get("email"),
                    name=arguments.get("name"),
                    item_update=update_data
                )  
            
            elif function_name == "delete_item_by_email":
                result = delete_item_by_email(
                    email=arguments.get("email"),
                    name=arguments.get("name")
                )
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": json.dumps(result)
            })
            
        except Exception as tool_error:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": json.dumps({"error": str(tool_error)})
            })

    try:
        final_completion = groq_client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=messages
        )
        return {"response": final_completion.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"API Error compiling final execution tree: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)