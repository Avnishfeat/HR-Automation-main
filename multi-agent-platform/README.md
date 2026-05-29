# Multi-Agent Platform

A modular FastAPI platform for managing multiple AI agents with support for various LLMs, databases, and WebSockets.

##  Quick Start

### 1. Clone the repository
```bash
git clone <repository-url>
cd multi-agent-platform
```

### 2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Setup environment variables
```bash
cp config/.env.example .env
# Edit .env with your configuration
```

### 5. Run the application (Development)
```bash
uvicorn app.main:app --reload --port 8048
```

### 6. Run the application (Production with PM2 & Nginx)

In a production environment, the backend runs on port `8048` managed by PM2, and Nginx listens on port `7010` to reverse proxy traffic to it.

#### A. Start the Backend (PM2)
```bash
pm2 start ecosystem.config.js
```

#### B. Setup Nginx Reverse Proxy
Copy the nginx config and reload:
```bash
sudo cp deploy/nginx/multi-agent-platform.conf /etc/nginx/sites-available/multi-agent-platform
sudo systemctl reload nginx
```

#### C. Useful PM2 Commands
```bash
# Check status
pm2 status

# View real-time logs
pm2 logs multi-agent-backend

# Restart application
pm2 restart multi-agent-backend

# Stop application
pm2 stop multi-agent-backend
```


## 📁 Project Structure

```
app/
├── agents/          # Individual agent modules
├── core/            # Core configuration and dependencies
├── services/        # Common reusable services
├── models/          # Pydantic schemas
└── utils/           # Utility functions
```

## 🤖 Adding a New Agent

### Step 1: Create agent folder
```bash
mkdir -p app/agents/your_agent_name
```

### Step 2: Create required files
Create these files in your agent folder:
- `__init__.py`
- `router.py` - API endpoints
- `service.py` - Business logic
- `schemas.py` - Request/response models

### Step 3: Use the example agent as template
Copy structure from `app/agents/example_agent/`

### Step 4: Register your agent router in `app/main.py`
```python
from app.agents.your_agent_name.router import router as your_agent_router
app.include_router(your_agent_router, prefix="/api/v1")
```

## 🛠️ Common Services Available

### 1. LLM Service
```python
from app.core.dependencies import get_llm_service

llm_service = get_llm_service()
response = await llm_service.generate(
    prompt="Your prompt",
    provider="gemini"  # or "openai"
)
```

### 2. File Service
```python
from app.core.dependencies import get_file_service

file_service = get_file_service()
result = await file_service.save_file(uploaded_file)
```

### 3. WebSocket Manager
```python
from app.core.dependencies import get_websocket_manager

ws_manager = get_websocket_manager()
await ws_manager.send_message("Hello", client_id)
```

## 🔄 Git Workflow

1. Create your branch: `git checkout -b feature/agent-name`
2. Make changes to your agent only
3. Commit: `git commit -m "Add: agent-name implementation"`
4. Push: `git push origin feature/agent-name`
5. Create Pull Request

## 📝 Notes for Developers

- Keep your agent code in its own folder
- Use common services instead of creating new ones
- Follow the example agent structure
- Write clear docstrings
- Test your endpoints before pushing

## 🐛 Troubleshooting

### Import Errors
- Ensure virtual environment is activated
- Run `pip install -r requirements.txt`

## 📚 Resources

- FastAPI Docs: https://fastapi.tiangolo.com
- Pydantic: https://docs.pydantic.dev
