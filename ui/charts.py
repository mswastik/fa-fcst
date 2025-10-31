from nicegui import ui
from core.state_manager import get_global_state
from core.utils import UIUtils
import polars as pl

def render_column_chart(container,filtered_df):
    """Render column chart in the provided container with loading indicator"""
    print(f"DEBUG: render_column_chart called - container: {container}, filtered_df: {filtered_df is not None}, rows: {len(filtered_df) if filtered_df is not None else 0}")
    container.clear()
    state = get_global_state()

    print(f"DEBUG: Chart loading states - charts: {state.loading_charts}, table: {state.loading_table}, data: {state.loading_data}")
    print(f"DEBUG: Loading message: '{state.get_loading_message('charts')}'")

    with container:
        if state.is_loading('charts'):
            print("DEBUG: Showing loading indicator for column chart")
            UIUtils.show_loading_indicator(container, state.get_loading_message('charts') or 'Loading chart data...')
        else:
            print("DEBUG: Attempting to render column chart - not loading")
            try:
                # Update state with filtered data first
                state.update_filtered_data(filtered_df)
                data = state.get_chart_data('column')
                print(f"DEBUG: Column chart data result: {data is not None}")
                if data:
                    print(f"DEBUG: Column chart data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    if 'series' in data:
                        print(f"DEBUG: Column chart series count: {len(data['series'])}")
                    chart = ui.echart({
                        #'legend': {'data': [s['name'] for s in data['series']]}, # Add legend
                        'xAxis': {'data': data['months']}, # Use the 'months' list for x-axis
                        'yAxis': {'type': 'value'},
                        'series': data['series'], # Use the pre-formatted series data
                        'tooltip':{
                            'trigger': 'axis',
                        },
                    }).classes('w-full h-full')
                    # In NiceGUI v3, options are observable, so chart.update() is not needed
                    print("DEBUG: Column chart rendered successfully")
                else:
                    print("DEBUG: No column chart data available")
                    ui.label('No data to display').classes('text-center text-gray-500')
            except Exception as e:
                print(f"DEBUG: Error rendering column chart: {e}")
                ui.label(f'Chart error: {str(e)}').classes('text-center text-red-500')

def render_line_chart(container,filtered_df):
    """Render line chart in the provided container with loading indicator"""
    print(f"DEBUG: render_line_chart called - container: {container}, filtered_df: {filtered_df is not None}, rows: {len(filtered_df) if filtered_df is not None else 0}")
    container.clear()
    state = get_global_state()

    print(f"DEBUG: Chart loading states - charts: {state.loading_charts}, table: {state.loading_table}, data: {state.loading_data}")
    print(f"DEBUG: Loading message: '{state.get_loading_message('charts')}'")

    with container:
        if state.is_loading('charts'):
            print("DEBUG: Showing loading indicator for line chart")
            UIUtils.show_loading_indicator(container, state.get_loading_message('charts') or 'Loading chart data...')
        else:
            print("DEBUG: Attempting to render line chart - not loading")
            try:
                # Update state with filtered data first
                state.update_filtered_data(filtered_df)
                data = state.get_chart_data('line')
                print(f"DEBUG: Line chart data result: {data is not None}")
                if data:
                    print(f"DEBUG: Line chart data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    if 'values' in data:
                        print(f"DEBUG: Line chart values count: {len(data['values'])}")
                    chart = ui.echart({
                        'xAxis': {'type':'time','axisLabel': {'formatter': '{MMM} {yy}'}},
                        'yAxis': {'type': 'value'},
                        'series': [
                            {
                                'type': 'line',
                                'name': 'Actual',
                                'data': [[data['categories'][i],data['values'][i]] for i in range(len(data['categories']))],
                                'marker': {'enabled': True}
                            }
                        ] + ([{
                            'type': 'line',
                            'name': 'Forecast',
                            'data': [[data['categories'][i],data['forecast_values'][i]] for i in range(len(data['forecast_values']))],
                            'marker': {'enabled': True},
                            'color': '#FF0000' # Red color for forecast
                        }] if data['forecast_values'] else []),
                        'tooltip':{ 'trigger': 'axis',},
                    }).classes('w-full h-full')
                    # In NiceGUI v3, options are observable, so chart.update() is not needed
                    print("DEBUG: Line chart rendered successfully")
                else:
                    print("DEBUG: No line chart data available")
                    ui.label('No data to display').classes('text-center text-gray-500')
            except Exception as e:
                print(f"DEBUG: Error rendering line chart: {e}")
                ui.label(f'Chart error: {str(e)}').classes('text-center text-red-500')

async def render_column_chart_async(container, filtered_df):
    """Async version of render_column_chart that handles loading states properly"""
    print("DEBUG: render_column_chart_async called - clearing loading state and rendering")
    state = get_global_state()
    state.set_loading_state('charts', False)  # Clear loading state before rendering
    render_column_chart(container, filtered_df)

async def render_line_chart_async(container, filtered_df):
    """Async version of render_line_chart that handles loading states properly"""
    print("DEBUG: render_line_chart_async called - clearing loading state and rendering")
    state = get_global_state()
    state.set_loading_state('charts', False)  # Clear loading state before rendering
    render_line_chart(container, filtered_df)

async def update_charts(column_container, line_container, filtered_df):
    """Update both charts"""
    print(f"DEBUG: update_charts called with filtered_df: {filtered_df is not None}")

    # Keep loading state during chart rendering
    state = get_global_state()
    print(f"DEBUG: Chart loading state at start of update_charts: {state.loading_charts}")

    try:
        # Force UI update to show loading indicators
        #await ui.run_javascript('void 0', timeout=3.5)
        await render_column_chart_async(column_container, filtered_df)
        await render_line_chart_async(line_container, filtered_df)
    except Exception as js_error:
        print(f"DEBUG: JavaScript update timeout in update_charts (expected): {js_error}")

    print(f"DEBUG: Charts rendered, loading state cleared - charts: {state.loading_charts}")
