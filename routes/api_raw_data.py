"""
Additional API routes for the FastAPI application.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
import json
from typing import Dict, Any

router = APIRouter()

@router.get("/api/raw_data")
async def get_raw_data(request: Request):
    """Return raw data HTML fragment"""
    # For now, return a placeholder - we'll implement this with real data later
    html = """
    <div class="overflow-x-auto">
        <table class="min-w-full border-collapse border border-gray-300">
            <thead class="bg-gray-50">
                <tr>
                    <th class="border border-gray-300 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                    <th class="border border-gray-300 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actual Sales</th>
                    <th class="border border-gray-300 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Forecast</th>
                    <th class="border border-gray-300 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model Type</th>
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
                <tr>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">2023-01-01</td>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">1000.00</td>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">1050.00</td>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">MLForecast</td>
                </tr>
                <tr>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">2023-02-01</td>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">1100.00</td>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">1150.00</td>
                    <td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">MLForecast</td>
                </tr>
            </tbody>
        </table>
    </div>
    """
    return HTMLResponse(content=html)