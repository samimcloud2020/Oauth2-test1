import os
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Modern Password Hashing for Python 3.12+
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

# LangChain & LangGraph Imports
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import Annotated, TypedDict

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "default_secret_key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
DB_FILE = "users.db"

app = FastAPI(title="OAuth2 Compliant FastAPI + LangGraph Agent Portal")
pwd_context = PasswordHash((BcryptHasher(),))

# OAuth2 Scheme specifying token URL for Swagger /docs compatibility
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# ------------------- LANGCHAIN TOOL DEFINITION -------------------


@tool
def get_current_time() -> str:
    """Returns the current date and time. Useful when the user asks for current time or date."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


tools = [get_current_time]
tool_node = ToolNode(tools)

# ------------------- LANGGRAPH AGENT SETUP -------------------


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


llm = ChatOpenAI(
    model="gpt-4o", api_key=OPENAI_API_KEY, temperature=0
).bind_tools(tools)


def call_model(state: AgentState):
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "action"
    return END


workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("action", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges(
    "agent", should_continue, {"action": "action", END: END}
)
workflow.add_edge("action", "agent")

agent_app = workflow.compile()

# ------------------- DATABASE SETUP -------------------


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users (username)
        )
    """
    )
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ------------------- SCHEMAS & HELPERS -------------------


class UserRegisterSchema(BaseModel):
    username: str
    password: str


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class ChatRequestSchema(BaseModel):
    prompt: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(username: str, db: sqlite3.Connection) -> str:
    token = secrets.token_urlsafe(64)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO refresh_tokens (username, token, expires_at) VALUES (?, ?, ?)",
        (username, token, expires_at.isoformat()),
    )
    db.commit()
    return token


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except jwt.PyJWTError:
        raise credentials_exception


# ------------------- OAUTH2 & AUTH ENDPOINTS -------------------


@app.post("/register", status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegisterSchema, db: sqlite3.Connection = Depends(get_db)):
    if not user_data.username or not user_data.password:
        raise HTTPException(
            status_code=400, detail="Username and password are required"
        )

    hashed_pwd = hash_password(user_data.password)
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (user_data.username, hashed_pwd),
        )
        db.commit()
        return {"message": "User registered successfully"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")


@app.post("/token")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: sqlite3.Connection = Depends(get_db),
):
    """OAuth2 Spec Standard Token Endpoint accepting form-encoded data."""
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE username = ?", (form_data.username,)
    )
    user = cursor.fetchone()

    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user["username"]})
    refresh_token = create_refresh_token(user["username"], db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "username": user["username"],
    }


@app.post("/refresh")
def refresh_access_token(
    body: RefreshTokenSchema, db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM refresh_tokens WHERE token = ?", (body.refresh_token,)
    )
    record = cursor.fetchone()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    expires_at = datetime.fromisoformat(record["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        cursor.execute("DELETE FROM refresh_tokens WHERE token = ?", (body.refresh_token,))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )

    # Rotate refresh token
    cursor.execute("DELETE FROM refresh_tokens WHERE token = ?", (body.refresh_token,))
    new_access_token = create_access_token(data={"sub": record["username"]})
    new_refresh_token = create_refresh_token(record["username"], db)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@app.post("/logout")
def logout(body: RefreshTokenSchema, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("DELETE FROM refresh_tokens WHERE token = ?", (body.refresh_token,))
    db.commit()
    return {"message": "Logged out successfully"}


# ------------------- PROTECTED AGENT ENDPOINT -------------------


@app.post("/api/agent")
def run_agent(
    request: ChatRequestSchema,
    current_user: str = Depends(get_current_user),
):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    try:
        inputs = {"messages": [HumanMessage(content=request.prompt)]}
        result = agent_app.invoke(inputs)
        final_message = result["messages"][-1].content
        return {"reply": final_message, "user": current_user}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"LangGraph Execution Error: {str(e)}"
        )


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
