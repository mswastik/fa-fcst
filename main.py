"""
Main entry point for the FastAPI Forecasting Dashboard application.
"""
import sys
import os
# Add the parent directory to the path so we can import from core
sys.path.insert(0, os.path.dirname(__file__))

import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app:app", 
        host="127.0.0.1", 
        port=8001, 
        reload=True,
        reload_dirs=["."]
    )