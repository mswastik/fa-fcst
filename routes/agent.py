"""
Agent routes for the FastAPI application.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from nicegui import ui, app
from ui.dashboard import agent

router = APIRouter()

@router.get("/agent", response_class=HTMLResponse)
async def agent_route(request: Request):
    """Agent page with web search and analysis capabilities"""
    # Create a NiceGUI page for the agent functionality
    agent_page = ui.run_dark(should_exit=False, reload=False)
    
    # Return the HTML response for the agent page
    # For now, we'll call the agent function directly
    # This integrates the NiceGUI UI with the FastAPI route
    return agent()