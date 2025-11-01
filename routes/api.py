"""
API routes for the FastAPI application.
Handles filter updates, chart rendering, and action buttons.
"""
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import json
from typing import Dict, Any, List
import polars as pl
import re
from typing import Optional

from models.schemas import FilterRequest, UpdateRequest, ActionRequest, FilterState
from services.state_service import state_service
from services.data_service import data_service
import core.data_service as core_data_service
from services.filter_service import filter_service
from core.utils import UIUtils, DatabaseUtils

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.post("/api/filters", response_class=HTMLResponse)
async def update_filters(
    request: Request,
    filter_name: str = Form(...),
    location1: str = Form("Region"),
    location2: Optional[str] = Form(None),
    product1: str = Form("Franchise"),
    product2: Optional[str] = Form(None)
):
    """
    Handle changes to location1 or product1 dropdowns.
    Returns updated HTML for the corresponding select2 element.
    """
    try:
        # Create filter state
        filter_state = FilterState(
            location1=location1,
            location2=location2 or "",
            product1=product1,
            product2=product2 or ""
        )
        
        # Get updated options based on which filter changed
        options = filter_service.get_options_for_select2(filter_state)
        
        if filter_name == "location1":
            # Return updated location2 dropdown
            return templates.TemplateResponse(
                "partials/location_select2.html",
                {
                    "request": request,
                    "label": location1,
                    "options": options['location2_options']
                }
            )
        elif filter_name == "product1":
            # Return updated product2 dropdown
            return templates.TemplateResponse(
                "partials/product_select2.html",
                {
                    "request": request,
                    "label": product1,
                    "options": options['product2_options']
                }
            )
            
    except Exception as e:
        print(f"Error in update_filters: {e}")
        import traceback
        traceback.print_exc()
        return f'<div class="text-red-500">Error updating filters: {str(e)}</div>'

def generate_filter_select_html(options: List[str], name: str, current_type: str = "", selected_value: str = "") -> str:
    """Generate HTML for a filter select dropdown"""
    # Map location types to appropriate labels
    label_mapping = {
        'Region': 'Region',
        'Country': 'Country',
        'Area': 'Area'
    }
    
    # Map product types to appropriate labels
    product_label_mapping = {
        'Franchise': 'Franchise',
        'IBP Level 5': 'IBP Level 5',
        'IBP Level 6': 'IBP Level 6',
        'CatalogNumber': 'Catalog Number'
    }
    
    # Determine the label based on current type and max width
    if name == 'location2':
        label = label_mapping.get(current_type, 'Location')
        max_width_class = 'max-w-[200px]'
    elif name == 'product2':
        label = product_label_mapping.get(current_type, 'Product')
        max_width_class = 'max-w-[250px]'
    else:
        label = name.replace('2', '').capitalize()
        max_width_class = 'max-w-[200px]'
    
    # Generate options
    options_html = f'<option value="">Select {label.lower()}...</option>'
    for option in options:
        # Only add non-empty options
        if option:
            selected = 'selected' if str(option) == selected_value else ''
            options_html += f'<option value="{option}" {selected}>{option}</option>'
    
    # Return the select element with its container to ensure consistent styling
    # The HTMX attributes are included for the select element to update the dashboard content only
    container_id = f"{name}-container"
    return f'''
    <div id="{container_id}" class="min-w-[160px] flex-1 {max_width_class}">
        <label class="block text-sm font-medium text-gray-700 mb-1" id="{name}-label">{label}</label>
        <select
            name="{name}"
            class="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm py-2 tom-select"
            hx-post="/api/update"
            hx-include="[name='location1'], [name='location2'], [name='product1'], [name='product2']"
            hx-target="#dashboard-content"
            hx-trigger="change"
            hx-indicator=".htmx-indicator"
            hx-swap="innerHTML"
        >
            {options_html}
        </select>
    </div>
    '''

@router.post("/api/update")
async def update_dashboard(request: Request):
    """Update dashboard with new filter settings using the new FilterService"""
    # Get form data
    form_data = await request.form()
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id

    session = state_service.get_or_create_session(session_id)
    
    # Get current filter state from form data
    filter_state = FilterState(
    location1=str(form_data.get('location1', 'Region')) if form_data.get('location1') else 'Region',
    location2=str(form_data.get('location2', '')) if form_data.get('location2') else '',
    product1=str(form_data.get('product1', 'Franchise')) if form_data.get('product1') else 'Franchise',
    product2=str(form_data.get('product2', '')) if form_data.get('product2') else ''
    )
    print(f"Filter state in /api/update: {filter_state}")
    # Check if we have complete filter conditions before loading data
    load_data_condition = (
        (filter_state.location1 and filter_state.location2 and filter_state.location2.strip()) and
        (filter_state.product1 and filter_state.product2 and filter_state.product2.strip())
    )
    
    print(f"Load data condition: {load_data_condition}")
    print(f"Filter state: {filter_state}")
    
    if load_data_condition:
        # Use the new FilterService to get filtered data
        try:
            filtered_df, metadata = filter_service.get_filtered_data(filter_state)
            
            print(f"Filtered DataFrame shape: {filtered_df.shape if filtered_df is not None else 'None'}")
            print(f"Metadata: {metadata}")
            
            if filtered_df is not None and not filtered_df.is_empty():
                # Update session with filtered data
                # Update both df and filtered_df with the new filtered data
                # Do not modify full_df which should remain as the original complete dataset
                session.df = filtered_df.clone()
                session.filtered_df = filtered_df.clone()
                
                # Prepare data for charts
                chart_data = session.get_chart_data('line')
                column_chart_data = session.get_chart_data('column')
                
                # Return HTML fragments for charts and table
                chart_html = generate_chart_html(filtered_df, chart_data or {}, column_chart_data or {})
                table_html = generate_table_html(filtered_df, filter_state)
                
                # Return combined HTML for the dashboard content
                combined_html = f"""
                {chart_html}
                
                <!-- Details Table -->
                <div class="w-full h-full p-0">
                    <h3 class="p-2 text-lg font-bold">Select Product and Model data</h3>
                    <div id="details-table">
                        {table_html}
                    </div>
                </div>
                """
                
                return HTMLResponse(content=combined_html)
            else:
                html = f"""
                <div class="p-4 text-center text-gray-500">
                    {metadata.get('error', 'No data found with current filters')}
                </div>
                """
                return HTMLResponse(content=html)
                
        except Exception as e:
            print(f"Error in update_dashboard: {e}")
            html = f"""
            <div class="p-4 text-center text-red-500">
                Error loading filtered data: {str(e)}
            </div>
            """
            return HTMLResponse(content=html)
    else:
        # Return a complete dashboard structure without triggering elements to prevent loops
        html = """
        <div id="charts-container" class="flex flex-col lg:flex-row gap-4 mb-6">
            <div id="column-chart" class="flex-1 border rounded p-4" style="min-height: 400px;">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold">Seasonality</h3>
                    <span class="text-sm text-gray-600">No data to display</span>
                </div>
                <div class="w-full" style="height: 350px;">
                    <p class="text-center p-8 text-gray-500">Select all filters to view charts</p>
                </div>
            </div>
            <div id="line-chart" class="flex-1 border rounded p-4" style="min-height: 400px;">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold">Trend</h3>
                    <span class="text-sm text-gray-600">No data to display</span>
                </div>
                <div class="w-full" style="height: 350px;">
                    <p class="text-center p-8 text-gray-500">Select all filters to view trends</p>
                </div>
            </div>
        </div>
        
        <!-- Details Table -->
        <div class="w-full h-full p-0">
            <h3 class="p-2 text-lg font-bold">Select Product and Model data</h3>
            <div id="details-table">
                <div class="p-8 text-center text-gray-500">
                    Please select all required filters to view data
                </div>
            </div>
        </div>
        """
        return HTMLResponse(content=html)

def generate_chart_html(df: pl.DataFrame, line_chart_data: Dict[str, Any], column_chart_data: Dict[str, Any]) -> str:
    """Generate HTML for charts with Chart.js implementation"""
    # Generate data for each chart type
    line_chart_script = ""
    column_chart_script = ""
    
    # Prepare line chart data
    if line_chart_data and 'categories' in line_chart_data and 'values' in line_chart_data:
        categories = line_chart_data['categories']
        values = line_chart_data['values']
        forecast_values = line_chart_data.get('forecast_values', [])
        
        # Convert datetime objects to strings for JSON
        categories_json = [str(c) for c in categories]
        values_json = [float(v) if v is not None else None for v in values]
        forecast_values_json = [float(v) if v is not None else None for v in forecast_values] if forecast_values else []
        
        line_chart_script = f"""
        <script>
            // Function to initialize or re-initialize the line chart
            function initLineChart() {{
                const lineCanvas = document.getElementById('line-chart-canvas');
                if (lineCanvas && typeof Chart !== 'undefined') {{
                    // Destroy existing chart if it exists
                    if (lineCanvas.chart) {{
                        lineCanvas.chart.destroy();
                    }}
                    
                    // Create new chart instance
                    lineCanvas.chart = new Chart(lineCanvas, {{
                        type: 'line',
                        data: {{
                            labels: {json.dumps(categories_json)},
                            datasets: [
                                {{
                                    label: 'Actual',
                                    data: {json.dumps(values_json)},
                                    borderColor: 'var(--brand-blue)',
                                    backgroundColor: 'rgba(var(--brand-blue-rgb), 0.2)',
                                    tension: 0.1,
                                    pointRadius: 3
                                }}
                                {", {{" +
                                  f"    label: 'Forecast',\n" +
                                  f"    data: {json.dumps(forecast_values_json)},\n" +
                                  f"    borderColor: 'var(--brand-gold)',\n" +
                                  f"    backgroundColor: 'rgba(var(--brand-gold-rgb), 0.2)',\n" +
                                  f"    borderDash: [5, 5],\n" +
                                  f"    tension: 0.1,\n" +
                                  f"    pointRadius: 3\n" +
                                  f"  }}" if forecast_values_json else ""}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                title: {{
                                    display: true,
                                    text: 'Trend Chart'
                                }},
                                legend: {{
                                    display: true,
                                    position: 'top'
                                }}
                            }},
                            scales: {{
                                y: {{
                                    beginAtZero: false
                                }},
                                x: {{
                                    display: true,
                                    title: {{
                                        display: true,
                                        text: 'Time'
                                    }}
                                }}
                            }}
                        }}
                    }});
                }}
            }}
            
            // Initialize chart on DOM load if canvas exists
            if (document.getElementById('line-chart-canvas')) {{
                // If document is already loaded, initialize immediately
                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', initLineChart);
                }} else {{
                    // Small delay to ensure canvas is in DOM
                    setTimeout(initLineChart, 100);
                }}
            }}
            
            // Re-initialize chart when HTMX finishes swapping content
            document.addEventListener('htmx:afterSettle', function(evt) {{
                // Check if the event target contains our chart or is our chart
                if (evt.target.contains(document.getElementById('line-chart-canvas')) || 
                    evt.target.id === 'line-chart-canvas' ||
                    evt.target.id === 'dashboard-content') {{
                    setTimeout(initLineChart, 50); // Small delay to ensure DOM is updated
                }}
            }});
        </script>
        """
    
    # Prepare column chart data
    if column_chart_data and 'months' in column_chart_data and 'series' in column_chart_data:
        months = column_chart_data['months']
        series = column_chart_data['series']
        
        # Prepare datasets from series
        datasets = []
        for i, s in enumerate(series):
            # Assign different colors based on position in series
            color_index = i % 3  # Cycle through 3 main colors
            if color_index == 0:
                bg_color = 'rgba(var(--brand-blue-rgb), 0.2)'
                border_color = 'var(--brand-blue)'
            elif color_index == 1:
                bg_color = 'rgba(var(--brand-gold-rgb), 0.2)'
                border_color = 'var(--brand-gold)'
            else:
                bg_color = 'rgba(var(--brand-orange-rgb), 0.2)'
                border_color = 'var(--brand-orange)'
                
            datasets.append({
                'label': s.get('name', ''),
                'data': [float(v) if v is not None else None for v in s.get('data', [])],
                'backgroundColor': s.get('color', bg_color),
                'borderColor': s.get('color', border_color),
                'borderWidth': 1,
                'type': s.get('type', 'bar')
            })
        
        column_chart_script = f"""
        <script>
            // Function to initialize or re-initialize the column chart
            function initColumnChart() {{
                const columnCanvas = document.getElementById('column-chart-canvas');
                if (columnCanvas && typeof Chart !== 'undefined') {{
                    // Destroy existing chart if it exists
                    if (columnCanvas.chart) {{
                        columnCanvas.chart.destroy();
                    }}
                    
                    // Create new chart instance
                    columnCanvas.chart = new Chart(columnCanvas, {{
                        type: 'bar',
                        data: {{
                            labels: {json.dumps(months)},
                            datasets: {json.dumps(datasets)}
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                title: {{
                                    display: true,
                                    text: 'Seasonality Chart'
                                }},
                                legend: {{
                                    display: true,
                                    position: 'top'
                                }}
                            }},
                            scales: {{
                                y: {{
                                    beginAtZero: true
                                }},
                                x: {{
                                    display: true,
                                    title: {{
                                        display: true,
                                        text: 'Months'
                                    }}
                                }}
                            }}
                        }}
                    }});
                }}
            }}
            
            // Initialize chart on DOM load if canvas exists
            if (document.getElementById('column-chart-canvas')) {{
                // If document is already loaded, initialize immediately
                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', initColumnChart);
                }} else {{
                    // Small delay to ensure canvas is in DOM
                    setTimeout(initColumnChart, 100);
                }}
            }}
            
            // Re-initialize chart when HTMX finishes swapping content
            document.addEventListener('htmx:afterSettle', function(evt) {{
                // Check if the event target contains our chart or is our chart
                if (evt.target.contains(document.getElementById('column-chart-canvas')) || 
                    evt.target.id === 'column-chart-canvas' ||
                    evt.target.id === 'dashboard-content') {{
                    setTimeout(initColumnChart, 50); // Small delay to ensure DOM is updated
                }}
            }});
        </script>
        """
    
    return f"""
    <div id="charts-container" class="flex flex-col lg:flex-row gap-4 mb-6 w-full">
        <div id="column-chart" class="flex-1 border rounded p-4" style="min-height: 400px; min-width: 0;">
            <div class="flex justify-between items-center mb-2">
                <h3 class="font-bold">Seasonality</h3>
                <span class="text-sm text-gray-600">Chart data loaded</span>
            </div>
            <div class="w-full" style="height: 350px;">
                <canvas id="column-chart-canvas" class="w-full"></canvas>
            </div>
            {column_chart_script}
        </div>
        <div id="line-chart" class="flex-1 border rounded p-4" style="min-height: 400px; min-width: 0;">
            <div class="flex justify-between items-center mb-2">
                <h3 class="font-bold">Trend</h3>
                <span class="text-sm text-gray-600">Chart data loaded</span>
            </div>
            <div class="w-full" style="height: 350px;">
                <canvas id="line-chart-canvas" class="w-full"></canvas>
            </div>
            {line_chart_script}
        </div>
    </div>
    """

def generate_table_html(df: pl.DataFrame, filter_state) -> str:
    """Generate HTML for the details table with HTMX interactions"""
    if df.is_empty():
        return '<div id="details-table"><p class="text-center p-4 text-gray-500">No data available</p></div>'
    
    try:
        # Group data based on filter state
        if filter_state.location1:
            table_df = df.pivot(
                'SALES_DATE',
                index=filter_state.location1,
                values='Act Orders Rev',
                aggregate_function='sum',
                sort_columns=True
            )
        else:
            # Use the first available location column as fallback
            available_location_cols = ['Region', 'Country', 'Area']
            index_col = None
            for col in available_location_cols:
                if col in df.columns:
                    index_col = col
                    break

            if index_col:
                table_df = df.pivot(
                    'SALES_DATE',
                    index=index_col,
                    values='Act Orders Rev',
                    aggregate_function='sum',
                    sort_columns=True
                )
            else:
                # If no location columns available, create a simple aggregated table
                table_df = df.group_by('SALES_DATE').agg(
                    pl.col('Act Orders Rev').sum()
                ).sort('SALES_DATE')
        
        # Generate HTML for the table with HTMX row click functionality
        html = '''
        <div id="details-table" class="overflow-x-auto">
            <table class="min-w-full border-collapse border border-gray-300">
        '''
        
        # Add header
        html += '<thead class="bg-gray-50"><tr>'
        for col in table_df.columns:
            html += f'<th class="border border-gray-300 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{col}</th>'
        html += '</tr></thead>'
        
        # Add rows
        html += '<tbody class="bg-white divide-y divide-gray-200">'
        for row in table_df.iter_rows():
            # Create data attributes for row values to be used in HTMX
            row_data_attrs = ""
            for i, col in enumerate(table_df.columns):
                row_data_attrs += f'data-{col.lower().replace(" ", "-").replace("/", "-")}="{row[i]}" '
                
            html += f'<tr class="hover:bg-gray-50 cursor-pointer" {row_data_attrs} hx-post="/api/update" hx-include="[name=\'location1\'], [name=\'location2\'], [name=\'product1\'], [name=\'product2\']" hx-target="#dashboard-content" hx-indicator=".htmx-indicator">'
            for cell in row:
                cell_content = str(cell) if cell is not None else ""
                # Truncate long content
                if len(cell_content) > 50:
                    cell_content = cell_content[:50] + "..."
                html += f'<td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">{cell_content}</td>'
            html += '</tr>'
        html += '</tbody></table></div>'
        
        # Add JavaScript for row click handling if needed
        html += """
        <script>
            // Add event listener for row clicks if needed
            document.addEventListener('DOMContentLoaded', function() {
                const tableRows = document.querySelectorAll('#details-table tbody tr');
                tableRows.forEach(row => {
                    row.addEventListener('click', function() {
                        // Extract relevant data from the clicked row 
                        const productCol = this.getAttribute('data-catalognumber') || 
                                         this.getAttribute('data-ibp-level-6') || 
                                         this.getAttribute('data-ibp-level-5') || 
                                         this.getAttribute('data-franchise');
                        
                        if (productCol) {
                            // Could trigger additional actions here
                            console.log('Row clicked with product:', productCol);
                        }
                    });
                });
            });
        </script>
        """
        
        return html
    except Exception as e:
        return f'<div id="details-table"><p class="text-center p-4 text-red-500">Error generating table: {str(e)}</p></div>'

@router.post("/api/actions")
async def handle_action(request: Request):
    """Handle action button clicks (Segmentation, Forecast, etc.)"""
    # Get form data
    form_data = await request.form()
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id

    session = state_service.get_or_create_session(session_id)
    
    action = form_data.get('action', '')
    
    # Get current filter state from form data
    filter_state = FilterState(
        location1=str(form_data.get('location1', 'Region')) if form_data.get('location1') else 'Region',
        location2=str(form_data.get('location2', '')) if form_data.get('location2') else '',
        product1=str(form_data.get('product1', 'Franchise')) if form_data.get('product1') else 'Franchise',
        product2=str(form_data.get('product2', '')) if form_data.get('product2') else ''
    )
    
    try:
        if action == "segmentation":
            # Get current data for clustering
            df = session.df if session.df is not None else session.full_df
            
            if df is None or df.is_empty():
                html = """
                <div class="p-4 text-center text-red-500">
                    No data available for clustering. Please load and filter data first.
                </div>
                """
                return HTMLResponse(content=html)
            
            # Import clustering function
            from core.data_service import create_enhanced_clusters
            result_df = create_enhanced_clusters(df, session)
            
            # Update session with clustered data
            session.df = result_df
            
            # Update dashboard content
            chart_data = session.get_chart_data('line') or {}
            column_chart_data = session.get_chart_data('column') or {}
            
            chart_html = generate_chart_html(result_df, chart_data, column_chart_data)
            table_html = generate_table_html(result_df, filter_state)
            
            combined_html = f"""
            {chart_html}
            
            <!-- Details Table -->
            <div class="w-full h-full p-0">
                <h3 class="p-2 text-lg font-bold">Select Product and Model data</h3>
                <div id="details-table">
                    {table_html}
                </div>
            </div>
            
            <script>
                // Show notification
                if (window.showNotification) {{
                    showNotification("Clusters created and saved to database successfully!", "success");
                }}
            </script>
            """
            
            return HTMLResponse(content=combined_html)
        
        elif action == "forecast":
            # Check if filters are set
            # Check if both location and product filters have a selected value
            if not (filter_state.location1 and filter_state.location2 and filter_state.location2.strip() and
                    filter_state.product1 and filter_state.product2 and filter_state.product2.strip()):
                html = """
                <div class="p-4 text-center text-red-500">
                    Please set both location and product filters before generating forecasts.
                </div>
                """
                return HTMLResponse(content=html)
            
            # Load filtered data based on current filters using the new FilterService
            filtered_df, metadata = filter_service.get_filtered_data(filter_state)
            
            if filtered_df is None or filtered_df.is_empty():
                html = """
                <div class="p-4 text-center text-red-500">
                    No data found with current filters. Please adjust your filters.
                </div>
                """
                return HTMLResponse(content=html)
            
            if filtered_df is None or filtered_df.is_empty():
                html = """
                <div class="p-4 text-center text-red-500">
                    No data found with current filters. Please adjust your filters.
                </div>
                """
                return HTMLResponse(content=html)
            
            # Run forecasting
            result_df = core_data_service.create_models_action(filtered_df, session)
            
            # Update session with forecasted data
            session.df = result_df
            
            # Update dashboard content
            chart_data = session.get_chart_data('line') or {}
            column_chart_data = session.get_chart_data('column') or {}
            
            chart_html = generate_chart_html(result_df, chart_data, column_chart_data)
            table_html = generate_table_html(result_df, filter_state)
            
            combined_html = f"""
            {chart_html}
            
            <!-- Details Table -->
            <div class="w-full h-full p-0">
                <h3 class="p-2 text-lg font-bold">Select Product and Model data</h3>
                <div id="details-table">
                    {table_html}
                </div>
            </div>
            
            <script>
                // Show notification
                if (window.showNotification) {{
                    showNotification("Models created and results saved to database successfully!", "success");
                }}
            </script>
            """
            
            return HTMLResponse(content=combined_html)
        
        elif action == "validate":
            # Placeholder for validation functionality
            html = """
            <div class="p-4 text-center text-green-500">
                Validation started successfully
            </div>
            """
            return HTMLResponse(content=html)
        
        elif action == "change_fc":
            # Call the existing change_fc function
            result = data_service.change_fc()
            
            html = f"""
            <div class="p-4 text-center text-blue-500">
                {result}
            </div>
            """
            return HTMLResponse(content=html)
        
        elif action == "view":
            # Return current data in HTML format for viewing
            if session.df is not None and not session.df.is_empty():
                table_html = generate_table_html(session.df, filter_state)
                
                html = f"""
                <div class="p-4 text-center text-green-500">
                    Data retrieved successfully
                </div>
                <div id="details-table">
                    {table_html}
                </div>
                """
                
                return HTMLResponse(content=html)
            else:
                html = """
                <div class="p-4 text-center text-red-500">
                    No data available
                </div>
                """
                return HTMLResponse(content=html)
        
        else:
            html = f"""
            <div class="p-4 text-center text-red-500">
                Unknown action: {action}
            </div>
            """
            return HTMLResponse(content=html)
    
    except Exception as e:
        html = f"""
        <div class="p-4 text-center text-red-500">
            Error executing action: {str(e)}
        </div>
        """
        return HTMLResponse(content=html)

@router.get("/api/charts")
async def get_charts(request: Request):
    """Return chart HTML fragments"""
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id

    session = state_service.get_or_create_session(session_id)
    
    if session.filtered_df is not None:
        line_chart_data = session.get_chart_data('line') or {}
        column_chart_data = session.get_chart_data('column') or {}
        
        chart_html = generate_chart_html(session.filtered_df, line_chart_data, column_chart_data)
        return HTMLResponse(content=chart_html)
    else:
        return HTMLResponse(content='<div class="p-4">No data available for charts</div>')

@router.get("/api/table")
async def get_table(request: Request):
    """Return table HTML fragment"""
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id

    session = state_service.get_or_create_session(session_id)
    
    # Get filter state from session or request
    # For now, we'll use default values
    filter_state = FilterState(
        location1="Region",
        location2="",
        product1="Franchise",
        product2=""
    )
    
    if session.filtered_df is not None:
        table_html = generate_table_html(session.filtered_df, filter_state)
        return HTMLResponse(content=table_html)
    else:
        return HTMLResponse(content='<div class="p-4">No data available for table</div>')

@router.get("/api/raw_data")
async def get_raw_data(request: Request):
    """Return raw data HTML fragment"""
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id

    session = state_service.get_or_create_session(session_id)
    
    # For the raw data page, get the current filtered data
    df = session.filtered_df if session.filtered_df is not None else session.df
    
    if df is not None and not df.is_empty():
        # Create a combined view of sales and forecast data
        try:
            # For now, create a simplified table view
            # In the real implementation, we would join sales and forecast data
            html = '''
            <div class="overflow-x-auto">
                <table class="min-w-full border-collapse border border-gray-300">
                    <thead class="bg-gray-50">
                        <tr>
            '''
            
            # Add headers based on available columns
            for col in df.columns[:4]:  # Take first 4 columns for display
                html += f'<th class="border border-gray-300 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{col}</th>'
            
            html += '''
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
            '''
            
            # Add first 10 rows of data
            for i, row in enumerate(df.iter_rows()):
                if i >= 10:  # Limit to 10 rows for display
                    break
                html += '<tr class="hover:bg-gray-50">'
                for j, cell in enumerate(row):
                    if j >= 4:  # Only show first 4 columns
                        break
                    cell_content = str(cell) if cell is not None else ""
                    html += f'<td class="border border-gray-300 px-4 py-2 whitespace-nowrap text-sm text-gray-900">{cell_content}</td>'
                html += '</tr>'
            
            html += '''
                    </tbody>
                </table>
            </div>
            '''
            
            return HTMLResponse(content=html)
        except Exception as e:
            return HTMLResponse(content=f'<div class="p-4 text-red-500">Error displaying raw data: {str(e)}</div>')
    else:
        return HTMLResponse(content='<div class="p-4 text-gray-500">No data available</div>')

@router.get("/api/regions")
async def get_regions(request: Request):
    """Get available regions for the agent page"""
    try:
        # Get regions from database
        db_service = DatabaseUtils.get_database_service()
        if db_service is not None:
            user_id = request.session.get('user_id', 'system')
            country_query = """
                SELECT DISTINCT country 
                FROM da.location_hierarchy 
                WHERE country IS NOT NULL 
                ORDER BY country
            """
            country_result = db_service.execute_query(country_query, user_id=user_id)
            if country_result is not None and len(country_result) > 0:
                countries = [row['country'] for row in country_result[['country']].unique().to_dicts()]
                return JSONResponse({"countries": countries})
            else:
                return JSONResponse({"countries": []})
        else:
            return JSONResponse({"countries": []})
    except Exception as e:
        print(f"Error getting regions: {e}")
        return JSONResponse({"countries": []})

@router.get("/api/agent-table-data")
async def get_agent_table_data(request: Request):
    """Get business unit and country data for the agent page"""
    try:
        # Get data from database with YoY growth and YTD growth calculation
        db_service = DatabaseUtils.get_database_service()
        if db_service is None:
            return JSONResponse({"rows": []})
        
        user_id = request.session.get('user_id', 'system')
        combined_query = """
            WITH yearly_sales AS (
                SELECT 
                    p.business_unit,
                    l.country,
                    YEAR(s.sales_date) as sales_year,
                    SUM(s.act_orders_rev) as total_sales
                FROM da.sales_actuals s
                JOIN da.product_hierarchy p ON s.item_skey = p.demantra_item_skey
                JOIN da.location_hierarchy l ON s.location_skey = l.location_skey
                WHERE p.business_unit IS NOT NULL 
                AND l.country IS NOT NULL
                GROUP BY p.business_unit, l.country, YEAR(s.sales_date)
            ),
            ytd_sales AS (
                SELECT 
                    p.business_unit,
                    l.country,
                    YEAR(s.sales_date) as sales_year,
                    SUM(s.act_orders_rev) as ytd_sales
                FROM da.sales_actuals s
                JOIN da.product_hierarchy p ON s.item_skey = p.demantra_item_skey
                JOIN da.location_hierarchy l ON s.location_skey = l.location_skey
                WHERE p.business_unit IS NOT NULL 
                AND l.country IS NOT NULL
                AND s.sales_date <= CURRENT_DATE
                AND YEAR(s.sales_date) >= YEAR(CURRENT_DATE) - 1
                AND (
                    YEAR(s.sales_date) = YEAR(CURRENT_DATE)
                    OR
                    (YEAR(s.sales_date) = YEAR(CURRENT_DATE) - 1 AND MONTH(s.sales_date) <= MONTH(CURRENT_DATE))
                )
                GROUP BY p.business_unit, l.country, YEAR(s.sales_date)
            ),
            growth_metrics AS (
                -- Last year's YoY growth (completed year)
                SELECT 
                    curr.business_unit,
                    curr.country,
                    'last_year_yoy' as metric_type,
                    CASE 
                        WHEN prev.total_sales > 0 THEN 
                            ROUND(((curr.total_sales - prev.total_sales) / prev.total_sales) * 100, 2)
                        ELSE NULL
                    END as growth_value
                FROM yearly_sales curr
                LEFT JOIN yearly_sales prev ON 
                    curr.business_unit = prev.business_unit 
                    AND curr.country = prev.country 
                    AND curr.sales_year = prev.sales_year + 1
                WHERE curr.sales_year = YEAR(CURRENT_DATE) - 1
                
                UNION ALL
                
                -- Current year YTD growth
                SELECT 
                    curr.business_unit,
                    curr.country,
                    'ytd_growth' as metric_type,
                    CASE 
                        WHEN prev.ytd_sales > 0 THEN 
                            ROUND(((curr.ytd_sales - prev.ytd_sales) / prev.ytd_sales) * 100, 2)
                        ELSE NULL
                    END as growth_value
                FROM ytd_sales curr
                LEFT JOIN ytd_sales prev ON 
                    curr.business_unit = prev.business_unit 
                    AND curr.country = prev.country 
                    AND curr.sales_year = prev.sales_year + 1
                WHERE curr.sales_year = YEAR(CURRENT_DATE)
            )
            SELECT DISTINCT 
                g.business_unit, 
                g.country,
                MAX(CASE WHEN g.metric_type = 'last_year_yoy' THEN g.growth_value END) as last_year_yoy,
                MAX(CASE WHEN g.metric_type = 'ytd_growth' THEN g.growth_value END) as ytd_growth
            FROM growth_metrics g
            GROUP BY g.business_unit, g.country
            ORDER BY g.business_unit, g.country
        """
        combined_result = db_service.execute_query(combined_query, user_id=user_id)
        if combined_result is not None and len(combined_result) > 0:
            # Handle NULL values properly
            combined_data = []
            for row in combined_result[['business_unit', 'country', 'last_year_yoy', 'ytd_growth']].to_dicts():
                combined_data.append({
                    'business_unit': row['business_unit'],
                    'country': row['country'],
                    'last_year_yoy': round(float(row['last_year_yoy']), 2) if row['last_year_yoy'] is not None else None,
                    'ytd_growth': round(float(row['ytd_growth']), 2) if row['ytd_growth'] is not None else None,
                    'row_id': f"{row['business_unit']}_{row['country']}"
                })
            # Deduplicate by (business_unit, country)
            seen = set()
            deduped_data = []
            for row in combined_data:
                key = (row['business_unit'], row['country'])
                if key not in seen:
                    seen.add(key)
                    deduped_data.append(row)
            return JSONResponse({"rows": deduped_data})
        else:
            return JSONResponse({"rows": []})
    except Exception as e:
        print(f"Error getting agent table data: {e}")
        return JSONResponse({"rows": []})

@router.post("/api/agent")
async def run_agent_api(request: Request):
    """Run the agent with the provided parameters"""
    try:
        data = await request.json()
        product = data.get('product', '')
        region = data.get('region', '')
        search_query1 = data.get('search_query1', '')
        search_query2 = data.get('search_query2', '')
        role = data.get('role', 'Demand Planner')
        objective = data.get('objective', '')
        
        # Validate inputs
        if not product or not region:
            return JSONResponse({
                "success": False,
                "error": "Both product and region are required"
            })
        
        # Import required modules for the agent functionality
        from ddgs import DDGS
        from bs4 import BeautifulSoup
        import requests
        from openai import OpenAI
        import re
        
        client = OpenAI(base_url="http://localhost:8080/v1", api_key="sk")
        
        def clean_markdown_content(content: str) -> str:
            """
            Clean and normalize markdown content to fix formatting issues.

            Args:
                content: Raw markdown content string

            Returns:
                Cleaned markdown content with proper spacing and heading levels
            """
            if not content:
                return content

            # Split into lines for processing
            lines = content.split('\n')
            cleaned_lines = []
            in_code_block = False
            code_block_marker = ''

            for i, line in enumerate(lines):
                # Handle headings - reduce level but preserve structure
                if line.strip().startswith('#'):
                    # Reduce heading levels: # -> ##, ## -> ###, ### -> ####, etc.
                    heading_match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
                    if heading_match:
                        hashes, text = heading_match.groups()
                        # Ensure minimum level is ##
                        new_level = min(len(hashes) + 1, 6)
                        new_hashes = '##' * new_level
                        line = f"{new_hashes} {text}"

                # Handle lists - ensure proper spacing
                elif line.strip().startswith(('- ', '* ', '+ ', '1. ', '2. ', '3. ', '4. ', '5. ')):
                    # Ensure list items have proper spacing before them
                    if i > 0 and cleaned_lines and cleaned_lines[-1].strip():
                        # Add blank line before list item if previous line is not blank
                        if not cleaned_lines[-1].strip().startswith(('#', '-', '*', '+')) and not cleaned_lines[-1].strip().startswith(tuple(f'{n}.' for n in range(1, 10))):
                            cleaned_lines.append('')

                # Handle paragraphs - ensure proper spacing
                elif line.strip():
                    # If this is a regular paragraph line
                    if i > 0 and cleaned_lines and cleaned_lines[-1].strip():
                        # Check if previous line is also a paragraph (not heading, list, or blank)
                        prev_line = cleaned_lines[-1].strip()
                        if (prev_line and
                            not prev_line.startswith(('#', '-', '*', '+')) and
                            not any(prev_line.startswith(f'{n}.') for n in range(1, 10)) and
                            not re.match(r'^\s*$', prev_line)):
                            # Add blank line between paragraphs if they're consecutive
                            if len(line.strip()) > 50:  # Likely a paragraph, not a short line
                                cleaned_lines.append('')

                cleaned_lines.append(line)

            # Join back and clean up excessive blank lines
            result = '\n'.join(cleaned_lines)

            # Remove excessive consecutive blank lines (more than 2)
            result = re.sub(r'\n{3,}', '\n\n', result)

            # Ensure content ends with proper spacing
            if result and not result.endswith('\n'):
                result += '\n'

            return result

        def search_web(query, max_results=5):
            with DDGS() as ddgs:
                return [r['href'] for r in ddgs.text(query, max_results=max_results, safesearch="on", backend="google,brave")]

        def scrape_page(url):
            try:
                html = requests.get(url, timeout=5).text
                soup = BeautifulSoup(html, "html.parser")
                return " ".join([p.get_text() for p in soup.find_all("p")])[:3000]  # limit size
            except:
                return ""

        def summarize(text, prompt="Summarize:", model="gemma3n"):
            stream = client.chat.completions.create(
                model=model,  # use whatever name your server registered
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text}
                ],
                max_tokens=4500,
                stream=True
            )
            collected = ""
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    collected += delta
            return collected
        
        # Format the search queries with product and region
        formatted_query1 = search_query1.format(product=product, region=region)
        formatted_query2 = search_query2.format(product=product, region=region)
        
        # Run the first query
        output_html = f"<p><strong>Running search:</strong> {formatted_query1}</p>"
        
        urls = search_web(formatted_query1)
        if not urls:
            output_html += "<p>No results found</p>"
        else:
            sources = []
            all_content = []
            
            for i, url in enumerate(urls, 1):
                try:
                    scraped = scrape_page(url)
                    if scraped:
                        all_content.append(scraped)
                        sources.append(f'<a href="{url}" target="_blank" class="text-blue-600 hover:underline">{url}</a>')
                except Exception as e:
                    print(f"Error processing {url}: {str(e)}")
            
            if all_content:
                combined_text = "\n---\n".join(all_content)
                
                # Generate summary with the specified parameters
                summary = summarize(
                    combined_text,
                    prompt=(
                        f"You are a {role}. Give your reply in concise 100 words and 3 bullet points to {objective} "
                        f"The current forecast within Stryker is giving CAGR of 0%. "  # Using 0% as placeholder since we don't have the growth data
                        "Your main task is to look into the web articles provided by user and compare CAGR of Stryker with CAGR forecasts done in these articles. "
                        """Always remember below important points while replying: 
                            - Do not output disclaimer
                            - Do not start with Okay
                            - Be direct and to the point
                            - Do not ask user question
                            - Do not output more than 200 words
                            """
                    ),
                    model="gemma3n"  # Changed from qwen-thinking since that model might not be available
                )
                
                # Clean up the markdown content
                cleaned_summary = clean_markdown_content(summary)
                
                # Format the response
                output_html += f"<div class='bg-white rounded border p-4 mb-4'><div class='prose max-w-none'>{cleaned_summary}</div></div>"
                
                # Add sources
                if sources:
                    output_html += "<div class='bg-gray-100 rounded p-3'><div class='font-semibold mb-2'>Sources:</div><ul class='list-disc pl-5 space-y-1'>"
                    for i, source in enumerate(sources, 1):
                        output_html += f"<li>{source}</li>"
                    output_html += "</ul></div>"
            else:
                output_html += "<p>No content found from the sources.</p>"
        
        return JSONResponse({
            "success": True,
            "result": output_html
        })
    except Exception as e:
        print(f"Error in run_agent_api: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })