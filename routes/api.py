"""
API routes for the FastAPI application.
Handles filter updates, chart rendering, and action buttons.
"""
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import json
from typing import Dict, Any, List
import polars as pl
import re
from typing import Optional
import asyncio

from models.schemas import FilterRequest, UpdateRequest, ActionRequest, FilterState
from core.state_manager import state_service


import core.data_service as core_data_service
from core.db_service import get_database_service
from core.utils import UIUtils

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
        db_service = get_database_service()

        # Get available options based on current selections
        filter_options = db_service.get_filter_options(user_id="system")

        # Determine which options to return based on the filter that changed
        if filter_name == "location1":
            # When location1 changes, we want to update location2 options
            # Get all available location options based on location1 selection
            if location1 == "Region":
                options = filter_options.get("regions", [])
            elif location1 == "Country":
                options = filter_options.get("countries", [])
            elif location1 == "Area":
                options = filter_options.get("areas", [])
            else:
                options = []

            # Return updated location2 dropdown
            return templates.TemplateResponse(
                "partials/location_select2.html",
                {
                    "request": request,
                    "label": location1,
                    "options": options
                }
            )
        elif filter_name == "product1":
            # When product1 changes, we want to update product2 options
            if product1 == "Franchise":
                options = filter_options.get("franchises", [])
            elif product1 == "IBP Level 5":
                options = filter_options.get("ibp_level_5s", [])
            elif product1 == "IBP Level 6":
                options = filter_options.get("ibp_level_6s", [])
            elif product1 == "CatalogNumber":
                options = filter_options.get("catalog_numbers", [])
            else:
                options = []

            # Return updated product2 dropdown
            return templates.TemplateResponse(
                "partials/product_select2.html",
                {
                    "request": request,
                    "label": product1,
                    "options": options
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
        <label class="block text-sm font-medium text-gray-700" id="{name}-label">{label}</label>
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
    product2=str(form_data.get('product2', '')) if form_data.get('product2') else '',
    forecast_version=str(form_data.get('forecast_version', '')) if form_data.get('forecast_version') else ''
    )
    print(f"Filter state in /api/update: {filter_state}")
    # Check if we have complete filter conditions before loading data
    load_data_condition = (
        (filter_state.location1 and filter_state.location2 and filter_state.location2.strip()) and
        (filter_state.product1 and filter_state.product2 and filter_state.product2.strip())
    )

    print(f"Load data condition: {load_data_condition}")
    print(f"Filter state: {filter_state}")
    db_service = get_database_service()
    if load_data_condition:
        filtered_df = db_service.get_filtered_sales_actuals_with_forecasts(
            location_col=filter_state.location1,
            location_val=filter_state.location2,
            product_col=filter_state.product1,
            product_val=filter_state.product2,
            forecast_version=filter_state.forecast_version,
            user_id="system"
        )
        # Apply standard data preparation for UI
        from core.utils import DataUtils
        if filtered_df is not None and not filtered_df.is_empty():
            filtered_df = DataUtils.prepare_data_for_ui(filtered_df)

        # Prepare metadata similar to what filter_service provided
        metadata = {
            "total_records": len(filtered_df) if filtered_df is not None and not filtered_df.is_empty() else 0,
            "filters_applied": {
                "location": f"{filter_state.location1} = {filter_state.location2}" if filter_state.location1 and filter_state.location2 else None,
                "product": f"{filter_state.product1} = {filter_state.product2}" if filter_state.product1 and filter_state.product2 else None
            },
            "columns": list(filtered_df.columns) if filtered_df is not None and not filtered_df.is_empty() else []
        }

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
            chart_html = generate_chart_html(filtered_df, chart_data or {}, column_chart_data or {}, filter_state)
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

def generate_chart_html(df: pl.DataFrame, line_chart_data: Dict[str, Any], column_chart_data: Dict[str, Any], filter_state=None) -> str:
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

        forecast_dataset_str = ""
        if forecast_values_json:
            forecast_dataset_str = f""",
                {{
                    label: 'Forecast',
                    data: {json.dumps(forecast_values_json)},
                    borderColor: 'rgb(255, 181, 0)',  // gold
                    backgroundColor: 'rgba(255, 181, 0, 0.2)',  // gold with transparency
                    borderDash: [5, 5],
                    tension: 0.1,
                    pointRadius: 3
                }}
            """

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
                                    borderColor: 'rgb(28, 86, 135)',  // blue
                                    backgroundColor: 'rgba(28, 86, 135, 0.2)',  // blue with transparency
                                    tension: 0.1,
                                    pointRadius: 3
                                }}
                                {forecast_dataset_str}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                legend: {{
                                    display: true,
                                    position: 'top',
                                    labels: {{
                                            boxWidth: 15,
                                            boxHeight: 11,
                                            font: {{
                                                size: 11
                                            }}
                                }},
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
                                    }},
                                    ticks: {{
                                        callback: function(value, index, values) {{
                                            // Convert datetime to abbreviated month-year format
                                            if (this.getLabelForValue(value)) {{
                                                const date = new Date(this.getLabelForValue(value));
                                                if (!isNaN(date.getTime())) {{
                                                    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                                                    return monthNames[date.getMonth()] + ' ' + date.getFullYear();
                                                }}
                                            }}
                                            return this.getLabelForValue(value);
                                        }}
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
                bg_color = 'rgba(28, 86, 135, 0.2)'  # blue with transparency
                border_color = 'rgb(28, 86, 135)'  # blue
            elif color_index == 1:
                bg_color = 'rgba(255, 181, 0, 0.2)'  # gold with transparency
                border_color = 'rgb(255, 181, 0)'  # gold
            else:
                bg_color = 'rgba(175, 109, 4, 0.2)'  # orange with transparency
                border_color = 'rgb(175, 109, 4)'  # orange

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
                                legend: {{
                                    display: true,
                                    position: 'top',
                                    labels: {{
                                            boxWidth: 15,
                                            boxHeight: 11,
                                            font: {{
                                                size: 11
                                            }}
                                }},
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

    # Generate dynamic filter text
    filter_text = ""
    if filter_state and filter_state.location2 and filter_state.product2:
        filter_text = f"Showing: {filter_state.location2} - {filter_state.product2}"
    elif filter_state:
        filter_text = f"Filters: {filter_state.location2 or 'Not selected'} - {filter_state.product2 or 'Not selected'}"
    else:
        filter_text = "Chart data loaded"

    return f"""
    <div id="charts-container" class="flex flex-row lg:flex-row gap-3 mb-3 w-full">
        <div id="column-chart" class="flex-1 shadow-sm rounded p-4" style="min-height: 400px; min-width: 0;">
            <div class="flex justify-between items-center mb-2">
                <h3 class="font-bold">Seasonality</h3>
                <span class="font-bold text-sm text-gray-600">{filter_text}</span>
            </div>
            <div class="w-full" style="height: 350px;">
                <canvas id="column-chart-canvas" class="w-full"></canvas>
            </div>
            {column_chart_script}
        </div>
        <div id="line-chart" class="flex-1 shadow-sm rounded p-4" style="min-height: 400px; min-width: 0;">
            <div class="flex justify-between items-center mb-2">
                <h3 class="font-bold">Trend</h3>
                <span class="font-bold text-sm text-gray-600">{filter_text}</span>
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
        # Determine the primary location column to use for indexing
        index_col = None
        if filter_state.location1 and filter_state.location1 in df.columns:
            index_col = filter_state.location1
        else:
            # Fallback to the first available location column
            available_location_cols = ['Region', 'Country', 'Area']
            for col in available_location_cols:
                if col in df.columns:
                    index_col = col
                    break

        # Define columns needed for pivot, including the index column if it exists
        base_cols = ['SALES_DATE']
        if index_col:
            base_cols.append(index_col)

        # 1. Separate Actuals and Forecasts
        actuals_df = df.filter(pl.col('Act Orders Rev').is_not_null()).select(
            base_cols + [pl.col('Act Orders Rev').alias('pivot_values')]
        ).with_columns(
            pl.lit('Actuals').alias('Metric'),
            pl.col('pivot_values').cast(pl.Float64)
        )

        forecast_df = df.filter(pl.col('NHITS').is_not_null()).select(
            base_cols + [pl.col('NHITS').alias('pivot_values')]
        ).with_columns(
            pl.lit('Forecast').alias('Metric'),
            pl.col('pivot_values').cast(pl.Float64)
        )

        # 2. Combine them
        if not actuals_df.is_empty() and not forecast_df.is_empty():
            df_for_pivot = pl.concat([actuals_df, forecast_df])
        elif not actuals_df.is_empty():
            df_for_pivot = actuals_df
        elif not forecast_df.is_empty():
            df_for_pivot = forecast_df
        else:
            df_for_pivot = pl.DataFrame()


        if df_for_pivot.is_empty():
             return '<div id="details-table"><p class="text-center p-4 text-gray-500">No data to display in table.</p></div>'

        # 3. Pivot with a multi-level index if an index column is available
        if index_col:
            index_cols = [index_col, 'Metric']
            table_df = df_for_pivot.pivot(
                values='pivot_values',
                index=index_cols,
                on='SALES_DATE',
                aggregate_function='sum'
            ).sort(index_cols)
        else:
            # If no location index, pivot only on the Metric
            table_df = df_for_pivot.pivot(
                values='pivot_values',
                index='Metric',
                on='SALES_DATE',
                aggregate_function='sum'
            ).sort('Metric')


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
        for row in table_df.iter_rows(named=True):
            # Create data attributes for row values to be used in HTMX
            row_data_attrs = ""
            for col, value in row.items():
                 row_data_attrs += f'data-{col.lower().replace(" ", "-").replace("/", "-")}="{value}" '

            html += f'<tr class="hover:bg-gray-50 cursor-pointer" {row_data_attrs} hx-post="/api/update" hx-include="[name=\'location1\'], [name=\'location2\'], [name=\'product1\'], [name=\'product2\']" hx-target="#dashboard-content" hx-indicator=".htmx-indicator">'
            for cell in row.values():
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
        import traceback
        traceback.print_exc()
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
        product2=str(form_data.get('product2', '')) if form_data.get('product2') else '',
        forecast_version=str(form_data.get('forecast_version', '')) if form_data.get('forecast_version') else ''
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

            chart_html = generate_chart_html(result_df, chart_data, column_chart_data, filter_state)
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

            # Load filtered data based on current filters using db_service
            db_service = get_database_service()
            filtered_df = db_service.get_filtered_sales_actuals(
                location_col=filter_state.location1,
                location_val=filter_state.location2,
                product_col=filter_state.product1,
                product_val=filter_state.product2,
                user_id="system"
            )

            # Apply standard data preparation for UI
            from core.utils import DataUtils
            if filtered_df is not None and not filtered_df.is_empty():
                filtered_df = DataUtils.prepare_data_for_ui(filtered_df)

            # Prepare metadata similar to what filter_service provided
            metadata = {
                "total_records": len(filtered_df) if filtered_df is not None and not filtered_df.is_empty() else 0,
                "filters_applied": {
                    "location": f"{filter_state.location1} = {filter_state.location2}" if filter_state.location1 and filter_state.location2 else None,
                    "product": f"{filter_state.product1} = {filter_state.product2}" if filter_state.product1 and filter_state.product2 else None
                },
                "columns": list(filtered_df.columns) if filtered_df is not None and not filtered_df.is_empty() else []
            }

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

            # Run forecasting model (this saves results to the database)
            core_data_service.create_models_action(filtered_df, session, forecast_version=filter_state.forecast_version)

            # Now, fetch the combined actuals and forecast data
            result_df = db_service.get_filtered_sales_actuals_with_forecasts(
                location_col=filter_state.location1,
                location_val=filter_state.location2,
                product_col=filter_state.product1,
                product_val=filter_state.product2,
                user_id="system"
            )

            # Apply standard data preparation for UI
            from core.utils import DataUtils
            if result_df is not None and not result_df.is_empty():
                result_df = DataUtils.prepare_data_for_ui(result_df)

            # Update session with the combined data
            session.df = result_df
            session.filtered_df = result_df

            # Update dashboard content
            chart_data = session.get_chart_data('line') or {}
            column_chart_data = session.get_chart_data('column') or {}

            chart_html = generate_chart_html(result_df, chart_data, column_chart_data, filter_state)
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
            result = core_data_service.change_fc_action()

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

@router.get("/api/versions", response_class=JSONResponse)
async def get_versions():
    """Get all available forecast versions."""
    try:
        db_service = get_database_service()
        versions = db_service.get_forecast_versions(user_id="system")
        return {"versions": versions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/versions/create", response_class=JSONResponse)
async def create_version(request: Request, version_name: str = Form(...)):
    """Create a new forecast version."""
    try:
        db_service = get_database_service()
        version_id = db_service._create_or_get_version_id(version_name, user_id="system")
        return {"version_name": version_name, "version_id": version_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/versions/delete", response_class=JSONResponse)
async def delete_version(request: Request, version_name: str = Form(...)):
    """Delete a forecast version."""
    try:
        db_service = get_database_service()
        success = db_service.delete_forecast_version(version_name, user_id="system")
        if success:
            return {"success": True, "message": f"Version '{version_name}' deleted successfully"}
        else:
            return {"success": False, "message": f"Version '{version_name}' not found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/charts")
async def get_charts(request: Request):
    """Return chart HTML fragments"""
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id

    session = state_service.get_or_create_session(session_id)

    # Get filter state from session or request
    filter_state = FilterState(
        location1="Region",
        location2="",
        product1="Franchise",
        product2=""
    )

    if session.filtered_df is not None:
        line_chart_data = session.get_chart_data('line') or {}
        column_chart_data = session.get_chart_data('column') or {}

        chart_html = generate_chart_html(session.filtered_df, line_chart_data, column_chart_data, filter_state)
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


@router.get("/api/regions")
async def get_regions(request: Request):
    """Get available regions for the agent page"""
    try:
        # Get regions from database
        db_service = get_database_service()
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
        db_service = get_database_service()
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

@router.post("/api/agent-stream")
async def run_agent_stream_api(request: Request):
    """Run the agent with the provided parameters and return a streaming response"""
    try:
        data = await request.json()
        product = data.get('product', '')
        region = data.get('region', '')
        search_query1 = data.get('search_query1', '')
        search_query2 = data.get('search_query2', '')
        role = data.get('role', 'Demand Planner')
        objective = data.get('objective', '')
        cagr = data.get('cagr', '0%') # New variable for CAGR, defaults to '0%'

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
                        if not cleaned_lines[-1].strip().startswith(('#', '-', '*', '+')) and not any(cleaned_lines[-1].strip().startswith(f'{n}.') for n in range(1, 10)):
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
            try:
                print(f"Attempting DDGS search for query: {query}")
                with DDGS() as ddgs:
                    results = ddgs.text(query, max_results=max_results, safesearch="on", backend="google,brave")
                    urls = [r['href'] for r in results]
                    print(f"DDGS search returned {len(urls)} results for query: {query}")
                    return urls
            except Exception as e:
                print(f"DDGS search failed for query '{query}': {str(e)}")
                import traceback
                traceback.print_exc()
                return []

        def scrape_page(url):
            try:
                print(f"Attempting to scrape page: {url}")
                html = requests.get(url, timeout=5).text
                soup = BeautifulSoup(html, "html.parser")
                content = " ".join([p.get_text() for p in soup.find_all("p")])[:1000]  # limit size
                print(f"Successfully scraped {len(content)} characters from {url}")
                return content
            except Exception as e:
                print(f"Failed to scrape page {url}: {str(e)}")
                import traceback
                traceback.print_exc()
                return ""

        def summarize_streaming(text, prompt="Summarize:", model="qwen-thinking"):
            """Generator that yields chunks of the summary as they are received, properly handling thinking content"""
            stream = client.chat.completions.create(
                model=model,  # use whatever name your server registered
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text}
                ],
                max_tokens=4500,
                stream=True
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        # Format the search queries with product and region - with safety checks
        print(f"Received product: '{product}', region: '{region}'")
        print(f"Original search query 1: '{search_query1}', search query 2: '{search_query2}'")

        # Safe formatting - replace placeholders with actual values, use fallback if needed
        try:
            formatted_query1 = search_query1.format(product=product, region=region)
        except KeyError as e:
            print(f"KeyError in search_query1 formatting: {e}")
            # Fallback to simple replacement
            formatted_query1 = search_query1.replace('{product}', str(product)).replace('{region}', str(region))

        try:
            formatted_query2 = search_query2.format(product=product, region=region)
        except KeyError as e:
            print(f"KeyError in search_query2 formatting: {e}")
            # Fallback to simple replacement
            formatted_query2 = search_query2.replace('{product}', str(product)).replace('{region}', str(region))

        print(f"Formatted query 1: '{formatted_query1}'")
        print(f"Formatted query 2: '{formatted_query2}'")

        async def generate_stream():
            # Send initial status
            yield f"data: {json.dumps({'type': 'status', 'message': f'Running search: {formatted_query1}'})}\n\n"

            # Run the first query
            print(f"Starting search for query: {formatted_query1}")
            urls = search_web(formatted_query1)
            print(f"URLs returned from search: {urls}")
            if not urls:
                print("No URLs returned from search")
                yield f"data: {json.dumps({'type': 'status', 'message': 'No results found for first query'})}\n\n"
            else:
                sources = []
                all_content = []

                for i, url in enumerate(urls, 1):
                    try:
                        scraped = scrape_page(url)
                        if scraped:
                            all_content.append(scraped)
                            sources.append({
                                'url': url,
                                'title': f'Article {i}'
                            })
                    except Exception as e:
                        print(f"Error processing {url}: {str(e)}")

                print(f"Sources collected: {len(sources)}")
                print(f"Content chunks collected: {len(all_content)}")
                yield f"data: {json.dumps({'type': 'status', 'message': sources})}\n\n"

                if all_content:
                    combined_text = "\n---\n".join(all_content)

                    # Send status that we're starting to generate summary
                    yield f"data: {json.dumps({'type': 'status', 'message': 'Generating summary...'})}\n\n"

                    # Stream the summary content
                    full_summary = ""
                    print(f"Sending start_summary event with sources: {sources}")
                    yield f"data: {json.dumps({'type': 'start_summary', 'sources': sources})}\n\n"

                    for chunk in summarize_streaming(
                        combined_text,
                        prompt=(
                            f"You are a {role}. Give your reply in concise 100 words and 3 bullet points to {objective} "
                            f"The current forecast within Stryker is giving CAGR of {cagr}. "
                            "Your main task is to look into the web articles provided by user and compare CAGR of Stryker with CAGR forecasts done in these articles. "
                            "Think step by step and provide your reasoning between <think> tags. "
                            """Always remember below important points while replying:
                                - Do not output disclaimer
                                - Do not start with Okay
                                - Be direct and to the point
                                - Do not ask user question
                                - Do not output more than 200 words
                                """
                        ),
                        model="qwen-thinking"  # Changed back to qwen-thinking to support thinking content
                    ):
                        full_summary += chunk

                        # Send the chunk as-is without extra processing
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

                        # Small delay to allow proper streaming
                        await asyncio.sleep(0.01)

                    # Send completion signal with full content
                    cleaned_summary = clean_markdown_content(full_summary)
                    print(f"Sending complete event with sources: {sources}")
                    yield f"data: {json.dumps({'type': 'complete', 'content': cleaned_summary, 'sources': sources})}\n\n"
                else:
                    print("No content from scraped pages to process")
                    yield f"data: {json.dumps({'type': 'status', 'message': 'No content found from the sources.'})}\n\n"

        return StreamingResponse(generate_stream(), media_type="text/plain")
    except Exception as e:
        print(f"Error in run_agent_stream_api: {e}")
        import traceback
        traceback.print_exc()
        # Send error as a data event
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/plain")