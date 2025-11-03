"""
Agent routes for the FastAPI application.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

router = APIRouter()

@router.get("/agent", response_class=HTMLResponse)
async def agent_route(request: Request):
    """Agent page with web search and analysis capabilities"""
    # The agent page is now served by the FastAPI route
    return templates.TemplateResponse("agent.html", {"request": request})