"""
UI Components for the dashboard.
Extracted from the monolithic dashboard function for better separation of concerns.
"""
from nicegui import ui, app, run, events
import polars as pl
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Optional
from core.state_manager import get_global_state
from core.data_model import generate_sample_data  # Keep generate_sample_data which might be used
from core.data_service import apply_filters, create_models_action, change_fc_action
from forecasting.model_validator import ModelValidator, ValidationReportGenerator
from core.auth_service import auth_service
from core.utils import DataUtils, DatabaseUtils, UIUtils, ErrorHandler


def add_auto_select_first(select: ui.select, on_change_handler: Optional[Callable] = None):
    """Attaches the auto-select-first behavior to a ui.select element.
    
    In NiceGUI v3, we only update the select value and rely on user interaction
    to trigger the on_change handler through the normal UI flow.
    """
    #@debounce(0.3)  # Debounce to handle rapid typing
    def handler(e: events.GenericEventArguments):
        # Get the current input value from the event
        input_value = e.args.get('value', '').lower()
        if not input_value:
            return  # Do nothing if input is empty

        # Get the current options (handles both list and dict)
        options = select.options
        if isinstance(options, dict):
            options = [(k, v) for k, v in options.items()]  # Convert dict to list of (value, label)
        else:
            options = [(opt, opt) for opt in options]  # Treat list as value=label

        # Filter options (case-insensitive substring match, mimicking Quasar's default)
        filtered = [opt for opt in options if input_value in opt[1].lower()]
        if filtered:
            first_match = filtered[0]  # (value, label)
            select.value = first_match[0]  # Set the value
            # In NiceGUI v3, we don't need to manually update input-value or call update()
            # The framework handles this automatically

    select.on('input', handler)  # Attach to input event
       
class AuthHeader:
    """Handles authentication header component with login/logout functionality."""

    def create_header(self, current_page=None):
        """Create the authentication header with navigation, user info and login/logout buttons."""
        with ui.header().classes('bg-white shadow-sm border-b py-1'):
            with ui.row().classes('w-full justify-between items-center px-4 py-1'):
                # Left side: App title and navigation
                with ui.row().classes('items-center gap-4'):
                    ui.label('ML Integration').classes('text-lg font-bold text-gray-800 mr-4')
                    # Navigation links
                    self._create_navigation_links(current_page)
                
                # Right side: User info and auth buttons
                with ui.row().classes('items-center gap-4'):
                    self._create_user_info()
                    self._create_auth_buttons()

    def _create_user_info(self):
        """Create user information display."""
        user_info = auth_service.get_user_info()

        if user_info.get('authenticated'):
            # Show authenticated user info
            with ui.row().classes('items-center gap-x-2'):
                ui.icon('account_circle').classes('text-blue-600')
                ui.label(f"Welcome, {user_info.get('username', 'User')}").classes('text-sm text-gray-700')
                if user_info.get('email'):
                    ui.label(user_info['email']).classes('text-xs text-gray-500')
        else:
            # Show not authenticated message
            with ui.row().classes('items-center gap-x-2'):
                ui.icon('warning').classes('mx-auto text-orange-500')
                ui.label('Not authenticated').classes('mx-auto text-sm text-gray-600')

    def _create_navigation_links(self, current_page=None):
        """Create navigation links for all pages."""
        pages = [
            ('/', 'Dashboard'),
            #('/raw_data', 'Raw Data'),
            #('/llms', 'LLMs'),
            ('/agent', 'Agent')
        ]
        
        with ui.row().classes('items-center gap-1'):
            for route, name in pages:
                is_active = (current_page == route) or (current_page is None and route == '/')
                button_classes = 'text-sm px-3 py-1 rounded transition-colors duration-200'
                if is_active:
                    button_classes += ' bg-blue-100 text-blue-700 font-semibold'
                else:
                    button_classes += ' text-gray-600 hover:bg-gray-100'
                
                # Create the link button
                ui.link(name, route).classes(button_classes).classes('no-underline')
            
    def _create_auth_buttons(self):
        """Create login/logout buttons based on authentication status."""
        user_info = auth_service.get_user_info()

        if user_info.get('authenticated'):
            # Logout button
            ui.button(
                'Logout',
                on_click=self._handle_logout,
                icon='logout'
            ).classes('text-sm').props('color=secondary outline')
        else:
            # Login button
            lb= ui.button(
                'Login',
                on_click=self._handle_login,
                icon='login'
            ).classes('text-sm').props('color=primary')
            with lb:
                ui.tooltip('Not Implemented').classes('bg-gray-200 text-red-600')
            lb.disable()

    def _handle_login(self):
        """Handle login button click."""
        ui.navigate.to('/login')

    def _handle_logout(self):
        """Handle logout button click."""
        auth_service.logout()
        ui.navigate.to('/login')
        ui.notify('Logged out successfully', type='info')


class FilterComponents:
    """Handles filter-related UI components and logic."""
    
    def __init__(self, filter_state: Dict[str, Any], on_filter_change: Callable):
        self.filter_state = filter_state
        self.on_filter_change = on_filter_change
        
        # Initialize default options structure
        self.options = {
            'products': ["Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"],
            'locations': ['Area', 'Region', 'Country'],
            'levels': ["Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"],
            'products_filt': [],
            'locations_filt': []
        }
        
        # Try to get filter options from the global state
        try:
            from core.state_manager import get_global_state
            state = get_global_state()
            if state and state.df is not None and len(state.df) > 0:
                options = state.get_filter_options()
                if options:
                    self.options.update(options)
                    print(f"DEBUG: Loaded filter options from state: {list(options.keys())}")
                else:
                    print("Warning: No filter options returned from state")
            else:
                print("Warning: State not available or no data loaded, using defaults")
        except Exception as e:
            print(f"Error getting filter options: {e}")
            
        print(f"Initialized FilterComponents with options: {list(self.options.keys())}")
    
    def create_filter_row(self):
        """Create the main filter row with all filter components."""
        with ui.row().classes('w-full gap-2'):
            self._create_location_selects()
            self._create_product_selects()
            #self._create_level_select()
    
    def _create_location_selects(self):
        """Create location filter dropdowns."""
        # Set default value from filter_state or use 'Region' as fallback
        default_location = self.filter_state.get('location1', 'Region')
        
        def update_location2_options(value):
            """Update the options of location_select2 based on location1 selection."""
            # Get updated options based on the selected location type
            state = get_global_state()
            if state:
                try:
                    options = state.get_filter_options(
                        prod=self.filter_state.get('product1', 'Franchise'),
                        loc=value
                    )
                    if 'locations_filt' in options:
                        # Clear the current value before updating options
                        self.location_select2.value = None
                        location_options = options['locations_filt']
                        self.location_select2.options = location_options
                        self.location_select2.update()
                        print(f"Updated location2 options with {len(location_options)} items")
                except Exception as e:
                    print(f"Error updating location2 options: {e}")
                    # Make sure to clear the current value when there's an error
                    self.location_select2.value = None
                    self.location_select2.update()
        
        def update_location2_label(value):
            """Update the label of location_select2 based on location1 selection."""
            location2_label = value if value in ['Area', 'Region', 'Country'] else 'Region'
            # In NiceGUI v3, we can directly update the props
            self.location_select2._props['label'] = location2_label
            # No need to call update() as props are now observable
        
        async def on_location1_change(e):
            """Handle location1 change event."""
            print(f"DEBUG: location1 changed to: {e.value}")
            # Update the filter_state to reflect the new location1 value
            self.filter_state['location1'] = e.value
            # Update the label of location_select2
            update_location2_label(e.value)
            # Update the options of location_select2
            update_location2_options(e.value)
            # Call the filter change handler (this is an async function)
            await self.on_filter_change('location1', e.value)
        
        location_select1 = ui.select(
            label='Location',
            options=self.options.get('locations', []),
            with_input=False,
            value=default_location,
            on_change=on_location1_change
        ).classes('w-40')
        
        # Set the second dropdown label based on the selected location type
        location2_label = default_location if default_location in ['Area', 'Region', 'Country'] else 'Region'
        
        async def on_location2_change(e):
            """Handler for location2 change event."""
            print(f"DEBUG: location2 changed to: {e.value}")
            # Update the filter_state to reflect the new location2 value
            self.filter_state['location2'] = e.value
            # Call the filter change handler (this is an async function)
            await self.on_filter_change('location2', e.value)
        
        # Initialize location2 options with appropriate values based on default location
        initial_location_options = []
        state = get_global_state()
        if state:
            try:
                options = state.get_filter_options(
                    prod=self.filter_state.get('product1', 'Franchise'),
                    loc=default_location
                )
                if 'locations_filt' in options:
                    initial_location_options = options['locations_filt']
            except Exception as e:
                print(f"Error getting initial location options: {e}")
        
        self.location_select2 = ui.select(
            label=location2_label,
            options=initial_location_options,
            with_input=True,
            on_change=on_location2_change,
            clearable=True,
        ).classes('w-40')
        add_auto_select_first(self.location_select2)
        # Store references to the select elements
        self.location_select1 = location_select1
        
        # If we have a value in filter_state, ensure it's selected
        if 'location2' in self.filter_state and self.filter_state['location2']:
            self.location_select2.value = self.filter_state['location2']
        
        return location_select1, self.location_select2

    def _create_product_selects(self):
        """Create product filter dropdowns."""
        # Set default value from filter_state or use 'Franchise' as fallback
        default_product = self.filter_state.get('product1', 'CatalogNumber')
        
        def update_product2_label(value):
            """Update the label of product_select2 based on product1 selection."""
            product2_label = value if value in ['Franchise', 'IBP Level 5', 'IBP Level 6', 'CatalogNumber'] else 'Product'
            # In NiceGUI v3, we can directly update the props
            self.product_select2._props['label'] = product2_label
            # No need to call update() as props are now observable
            
        def update_product2_options(value):
            """Update the options of product_select2 based on product1 selection."""
            # Get updated options based on the selected product type
            state = get_global_state()
            if state:
                try:
                    options = state.get_filter_options(
                        prod=value,
                        loc=self.filter_state.get('location1', 'Region')
                    )
                    if 'products_filt' in options:
                        # Clear the current value before updating options
                        self.product_select2.value = None
                        product_options = options['products_filt']
                        self.product_select2.options = product_options
                        self.product_select2.update()
                        print(f"Updated product2 options with {len(product_options)} items")
                except Exception as e:
                    print(f"Error updating product2 options: {e}")
                    # Make sure to clear the current value when there's an error
                    self.product_select2.value = None
                    self.product_select2.update()
        
        async def on_product1_change(e):
            """Handle product1 change event."""
            print(f"DEBUG: product1 changed to: {e.value}")
            # Update the filter_state to reflect the new product1 value
            self.filter_state['product1'] = e.value
            update_product2_label(e.value)
            update_product2_options(e.value)
            # Call the filter change handler (this is an async function)
            await self.on_filter_change('product1', e.value)
        
        self.product_select1 = ui.select(
            label='Product',
            options=self.options.get('products', []),
            with_input=False,
            value=default_product,
            on_change=on_product1_change,
        ).classes('w-40')
        
        # Set the second dropdown label based on the selected product type
        product2_label = default_product if default_product in ['Franchise', 'IBP Level 5', 'IBP Level 6', 'CatalogNumber'] else 'Product'
        
        async def on_product2_change(e):
            """Handler for product2 change event."""
            print(f"DEBUG: product2 changed to: {e.value}")
            # Update the filter_state to reflect the new product2 value
            self.filter_state['product2'] = e.value
            # Call the filter change handler (this is an async function)
            await self.on_filter_change('product2', e.value)
        
        # Initialize product2 options with appropriate values based on default product
        initial_product_options = []
        state = get_global_state()
        if state:
            try:
                options = state.get_filter_options(
                    prod=default_product,
                    loc=self.filter_state.get('location1', 'Region')
                )
                if 'products_filt' in options:
                    initial_product_options = options['products_filt']
            except Exception as e:
                print(f"Error getting initial product options: {e}")
        
        self.product_select2 = ui.select(
            label=product2_label,
            options=initial_product_options,
            with_input=True,
            on_change=on_product2_change,
            clearable=True,
        ).classes('w-40')
        add_auto_select_first(self.product_select2)
        # If we have a value in filter_state, ensure it's selected
        if 'product2' in self.filter_state and self.filter_state['product2']:
            self.product_select2.value = self.filter_state['product2']
        
        return self.product_select1, self.product_select2
    

    def _create_level_select(self):
        """Create level selection dropdown."""
        # Get the current level from filter_state or use empty string
        current_level = self.filter_state.get('level', '')
        
        async def on_level_change(e):
            """Handler for level change event."""
            print(f"DEBUG: level changed to: {e.value}")
            # Call the filter change handler (this is an async function)
            await self.on_filter_change('level', e.value)
        
        # Create the select component
        level_select = ui.select(
            label='Level',
            options=[''] + self.options.get('levels', []),
            value=current_level,
            clearable=True,
            on_change=on_level_change
        ).classes('w-40')
        
        # Store a reference to the select component
        self.level_select = level_select
        return level_select

    def update_location_options(self, options: list):
        """Update location select options.
        
        Args:
            options: List of location options to display in the dropdown
        """
        if not hasattr(self, 'location_select2'):
            print("Warning: location_select2 not initialized yet")
            return
            
        if not isinstance(options, (list, tuple)):
            print(f"Warning: Expected list of options, got {type(options)}")
            options = []
            
        print(f"Updating location options with {len(options)} items")
        # Use direct assignment with a small delay for NiceGUI v3
        ui.timer(0.01, lambda: setattr(self.location_select2, 'options', options))
        
        # Update the options in our local cache
        self.options['locations_filt'] = options
    
    def update_product_options(self, options: list):
        """Update product select options.
        
        Args:
            options: List of product options to display in the dropdown
        """
        if not hasattr(self, 'product_select2'):
            print("Warning: product_select2 not initialized yet")
            return
            
        if not isinstance(options, (list, tuple)):
            print(f"Warning: Expected list of options, got {type(options)}")
            options = []
            
        print(f"Updating product options with {len(options)} items")
        # Use direct assignment with a small delay for NiceGUI v3
        ui.timer(0.01, lambda: setattr(self.product_select2, 'options', options))
        
        # Update the options in our local cache
        self.options['products_filt'] = options
        
    def update_level_options(self, options: list):
        """Update level select options.
        
        Args:
            options: List of level options to display in the dropdown
        """
        if not hasattr(self, 'level_select'):
            print("Warning: level_select not initialized yet")
            return
            
        if not isinstance(options, (list, tuple)):
            print(f"Warning: Expected list of options, got {type(options)}")
            options = []
            
        # Always include an empty option for clearing the selection
        all_options = [''] + list(options)
        
        print(f"Updating level options with {len(all_options)} items")
        # Clear current options first
        self.level_select.options = []
        # Force a small delay to ensure the clear is processed
        ui.timer(0.01, lambda: setattr(self.level_select, 'options', all_options))
        
        # Update the options in our local cache
        self.options['levels'] = options


class ChartComponents:
    """Handles chart-related UI components."""
    
    def __init__(self):
        self.column_chart_container = None
        self.line_chart_container = None
    
    def create_charts_row(self):
        """Create the charts row with both column and line charts."""
        with ui.row().classes('w-full gap-2 mr-0'):
            self.column_chart_container = self._create_column_chart()
            self.line_chart_container = self._create_line_chart()
        return self.column_chart_container, self.line_chart_container
    
    def _create_column_chart(self):
        # Create card with fixed height and flex column layout
        card = ui.card().classes('flex-1 w-1/2 h-[400px] flex flex-col p-0 overflow-hidden')
        with card:
            # Title bar with fixed height
            with ui.row().classes('w-full px-4 py-2 border-b'):
                ui.label('Seasonality').classes('text-md font-medium')
                ui.separator().props('vertical').classes('mx-2')
                self.column_chart_title = ui.label().classes('text-sm font-medium')
            
            # Chart container that takes remaining space and is scrollable
            with ui.column().classes('w-full flex-1 min-h-0 p-2'):
                self.column_chart_content = ui.column().classes('w-full h-full')
                print(f"DEBUG: Created column chart content container: {self.column_chart_content}")
        return card
            
    def _create_line_chart(self):
        # Create card with fixed height and flex column layout
        card = ui.card().classes('flex-1 w-1/2 h-[400px] flex flex-col p-0 overflow-hidden')
        with card:
            # Title bar with fixed height
            with ui.row().classes('w-full px-4 py-2 border-b'):
                ui.label('Trend').classes('text-md font-medium')
                ui.separator().props('vertical').classes('mx-2')
                self.line_chart_title = ui.label().classes('text-sm font-medium')
            
            # Chart container that takes remaining space and is scrollable
            with ui.column().classes('w-full flex-1 min-h-0 p-2'):
                self.line_chart_content = ui.column().classes('w-full h-full')
                print(f"DEBUG: Created line chart content container: {self.line_chart_content}")
        return card
            
    def update_chart_titles(self, filter_state):
        """Update chart titles with current filter values."""
        # Get selected values from filter state
        location = filter_state.get('location', 'All Locations')
        product = filter_state.get('product', 'All Products')
        
        # Update titles if they exist
        if hasattr(self, 'column_chart_title'):
            self.column_chart_title.text = f"{product} | {location}"
        if hasattr(self, 'line_chart_title'):
            self.line_chart_title.text = f"{product} | {location}"


class ActionButtons:
    """Handles action button components and their functionality."""
    
    def __init__(self, dwn_data, filter_state: Dict[str, Any]):
        self.dwn_data = dwn_data
        self.filter_state = filter_state
    
    def create_action_buttons(self):
        """Create all action buttons."""
        with ui.row().classes('gap-2'):
            ui.button('Segmentation', on_click=self._run_cluster).classes('bg-green-100')
            ui.button('Generate Forecast', on_click=self._run_create_models).classes('bg-green-100')
            ui.button('Validate Models', on_click=self._run_validation).classes('bg-blue-100')
            ui.button('Change FC', on_click=self._change_forecast).classes('bg-green-100')
            ui.button('View', on_click=self._show_view_dialog).classes('bg-green-100')
    
    async def _run_cluster(self):
        """Handle clustering action."""
        # Get filtered data from global state for clustering
        state = get_global_state()
        filtered_df = state.filtered_df if state.filtered_df is not None else self.dwn_data.df

        if filtered_df is None or len(filtered_df) == 0:
            UIUtils.show_error_message('No data available for clustering. Please load and filter data first.', type='warning')
            return

        # Show progress notification
        n = UIUtils.create_loading_notification()
        n.message = "Creating clusters... This may take a few minutes."

        try:
            # Set loading states for all components
            state.set_loading_state('charts', True, 'Running...')
            state.set_loading_state('table', True, 'Running...')
            state.set_loading_state('data', True, 'Running...')

            # Create a simple wrapper for clustering that uses filtered data
            async def cluster_wrapper():
                from core.data_service import create_enhanced_clusters
                result = create_enhanced_clusters(filtered_df, "", state)

                # Verify data was saved to database
                db_service = DatabaseUtils.get_database_service()
                if db_service:
                    cluster_count = db_service.get_cluster_count()
                    print(f"Clusters saved to database. Total cluster records: {cluster_count}")

                return result

            self.dwn_data.df = await cluster_wrapper()

            n.message = 'Clustering completed successfully!'
            n.spinner = False
            n.dismiss()
            UIUtils.show_success_message('Clusters created and saved to database!')

            # Update UI with new data
            from ui.charts import update_charts
            from ui.dashboard import details_table, chart_components, details_container
            await update_charts(chart_components.column_chart_container,
                               chart_components.line_chart_container, self.dwn_data.df)
            await details_table.create_table(self.dwn_data.df, details_container)

        except Exception as e:
            n.dismiss()
            ErrorHandler.handle_ui_update_error(e, "Clustering")
        finally:
            # Clear all loading states
            state.set_loading_state('charts', False)
            state.set_loading_state('table', False)
            state.set_loading_state('data', False)
    
    async def _run_create_models(self):
        """Handle model creation action."""
        # Get current filters from filter state
        current_filters = self.filter_state
        
        # Only forecast if both location and product filters are set
        if not (current_filters.get('location2') and current_filters.get('location1') and
                current_filters.get('product2') and current_filters.get('product1')):
            UIUtils.show_error_message('Please set both location and product filters before generating forecasts.', type='warning')
            return

        # Use the same data source as viewing - query database with current filters
        try:
            from core.data_service import DatabaseUtils
            db_service = DatabaseUtils.get_database_service()
            if db_service is None:
                UIUtils.show_error_message('Database service not available.', type='warning')
                return
                
            # Get the same filtered data that will be used for viewing
            filtered_df = db_service.get_filtered_sales_actuals(
                location_col=current_filters.get('location1'),
                location_val=current_filters.get('location2'),
                product_col=current_filters.get('product1'),
                product_val=current_filters.get('product2')
            )
            
            if filtered_df is None or len(filtered_df) == 0:
                UIUtils.show_error_message('No data found with current filters. Please adjust your filters.', type='warning')
                return
                
        except Exception as e:
            UIUtils.show_error_message(f'Error loading filtered data: {str(e)}', type='warning')
            return

        # Show detailed progress notification
        n = UIUtils.create_loading_notification()
        n.message = "Initializing forecasting pipeline..."

        try:
            # Set loading states for all components
            state = get_global_state()
            state.set_loading_state('charts', True, 'Running forecasting models...')
            state.set_loading_state('table', True, 'Running forecasting models...')
            state.set_loading_state('data', True, 'Running forecasting models...')

            # Update progress
            n.message = "Processing data and running forecasting models... This may take several minutes."

            # Debugging chart_components
            from ui.dashboard import chart_components, details_table, details_container # Ensure import is here
            print(f"DEBUG: chart_components is {chart_components}")
            if chart_components is None:
                UIUtils.show_error_message('Internal Error: chart_components not initialized. Please refresh the page.', type='error')
                n.dismiss()
                return

            # Use the correct function from data_service instead of simple_pipeline
            result_df = await run.cpu_bound(
                create_models_action,
                filtered_df, "", state
            )
            validation_results = {'mae': 0.0, 'mape': 0.0, 'rmse': 0.0}  # Default validation results

            # Update progress
            n.message = "Saving results to database..."

            # Handle the result
            if result_df is not None:
                self.dwn_data.df = result_df
                # Update global state with the processed data
                state.df = result_df

                # Verify data was saved to database
                db_service = DatabaseUtils.get_database_service()
                if db_service:
                    # Check if forecasts were saved (if forecast table exists)
                    try:
                        forecast_count = db_service.get_forecast_count()
                        print(f"Forecasts saved to database. Total forecast records: {forecast_count}")
                    except:
                        print("Forecast table not yet implemented, but clustering data was processed")

                n.message = 'Forecasting completed successfully!'
                n.spinner = False
                n.dismiss()
                UIUtils.show_success_message('Models created and results saved to database!')

                # Update UI with new data
                from ui.charts import update_charts
                await update_charts(chart_components.column_chart_container,
                                   chart_components.line_chart_container, result_df)
                await details_table.create_table(result_df, details_container)
            else:
                n.dismiss()
                UIUtils.show_info_message('Forecasting completed but no results returned')

        except Exception as e:
            n.dismiss()
            ErrorHandler.handle_ui_update_error(e, "Forecasting")
        finally:
            # Clear all loading states
            state.set_loading_state('charts', False)
            state.set_loading_state('table', False)
            state.set_loading_state('data', False)
    
    def _change_forecast(self):
        """Handle forecast change action."""
        UIUtils.show_info_message(change_fc_action())
    
    # ... (rest of the code remains the same)
    async def _run_validation(self):
        """Handle model validation action."""
        if not hasattr(self.dwn_data, 'df') or self.dwn_data.df is None or len(self.dwn_data.df) == 0:
            UIUtils.show_error_message('No data available for validation. Please load data first.', type='warning')
            return

        n = UIUtils.create_loading_notification()
        n.message = "Running model validation for last 3 months..."

        try:
            validator = ModelValidator()
            # Use filtered data for validation
            state = get_global_state()
            filtered_df = state.filtered_df if state.filtered_df is not None else self.dwn_data.df

            validation_results = await run.cpu_bound(
                validator.validate_last_3_months,
                filtered_df.to_dict(as_series=False)
            )

            n.dismiss()
            ValidationResultsDialog(validation_results).show()

        except Exception as e:
            n.dismiss()
            ErrorHandler.handle_ui_update_error(e, "Model validation")
    
    def _show_view_dialog(self):
        """Show the view data dialog."""
        ViewDataDialog().show()


class ViewDataDialog:
    """Handles the view data dialog functionality."""
    
    def show(self):
        """Show the view data dialog."""
        if 'dwn_df_json' not in app.storage.user:
            ui.notify('No data available to view', type='warning')
            return
        
        # Create temporary file for data processing
        import tempfile
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, 'temp_data.json')
        
        with open(temp_file, 'w') as f:
            f.write(app.storage.user['dwn_df_json'])
        
        # Define schema to avoid deserialization errors
        schema = {
            'SALES_DATE': pl.Utf8,
            'Act Orders Rev': pl.Float64,
            'unique_id': pl.Utf8,
            'CatalogNumber': pl.Utf8,
            'Country': pl.Utf8,
            'Area': pl.Utf8,
            'Stryker Group Region': pl.Utf8,
            'Region': pl.Utf8,
            'Business Sector': pl.Utf8,
            'Business Unit': pl.Utf8,
            'Franchise': pl.Utf8,
            'Product Line': pl.Utf8,
            'IBP Level 5': pl.Utf8,
            'IBP Level 6': pl.Utf8,
            'IBP Level 7': pl.Utf8,
            'UOM': pl.Float64,
            'Pack Content': pl.Float64,
            'ASP Final Rev': pl.Float64,
            'Act Orders Rev Val': pl.Float64,
            'L2 DF Final Rev': pl.Float64,
            'L1 DF Final Rev': pl.Float64,
            'L0 DF Final Rev': pl.Float64,
            'L2 Stat Final Rev': pl.Float64,
            'Fcst DF Final Rev': pl.Float64,
            'Fcst Stat Final Rev': pl.Float64,
            'Fcst Stat Prelim Rev': pl.Float64,
            'Fcst DF Final Rev Val': pl.Float64,
            'birch': pl.Float64,
            'cluster': pl.Utf8,
            'AutoARIMA': pl.Float64,
            'AutoETS': pl.Float64,
            'SeasonalNaive': pl.Float64,
            'ensemble': pl.Float64,
            'NHITS': pl.Float64,
            'LSTM': pl.Float64,
            'Selling Division': pl.Utf8
        }
        
        try:
            full_df = pl.read_json(temp_file, schema=schema)
        except Exception:
            # Fallback without schema if specific schema fails
            full_df = pl.read_json(temp_file, infer_schema_length=None)
        
        # Apply standard data preparation
        full_df = DataUtils.prepare_data_for_ui(full_df)

        # Convert date and numeric columns
        if 'SALES_DATE' in full_df.columns:
            full_df = full_df.with_columns(pl.col('SALES_DATE').str.to_datetime())
        if 'Act Orders Rev' in full_df.columns:
            full_df = full_df.with_columns(pl.col('Act Orders Rev').cast(pl.Float32))
        
        # Handle cluster column if present
        if 'cluster' in full_df.columns:
            full_df = full_df.with_columns(
                cluster=pl.col("cluster").forward_fill().backward_fill().over("unique_id")
            )
            full_df = full_df.with_columns(pl.col('cluster').cast(pl.Utf8))
        
        self._show_date_filter_dialog(full_df)
    
    def _show_date_filter_dialog(self, full_df: pl.DataFrame):
        """Show date filtering dialog."""
        if 'SALES_DATE' in full_df.columns:
            min_date = full_df['SALES_DATE'].min().date()
            max_date = full_df['SALES_DATE'].max().date()
        else:
            min_date = (datetime.now() - timedelta(days=365)).date()
            max_date = datetime.now().date()
        
        with ui.dialog() as date_dialog, ui.card().style('min-width: 700px'):
            ui.label('Filter Data by Date Range').classes('text-h6 mb-4')
            ui.label(f'Data available: {min_date} to {max_date}').classes('text-caption mb-4')
            
            with ui.row().classes('w-full gap-4'):
                start_date_input = ui.date(value=min_date)
                end_date_input = ui.date(value=max_date)
            
            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=lambda: ui.navigate.back()).props('flat')
                ui.button(
                    'Load Data',
                    on_click=lambda: self._filter_and_load_data(
                        full_df, start_date_input.value, end_date_input.value, date_dialog
                    )
                ).props('color=primary')
        
        date_dialog.open()
    
    async def _filter_and_load_data(self, full_df: pl.DataFrame, start_date, end_date, dialog):
        """Filter and load the selected data."""
        try:
            ui.notify("Filtering data...", type='info')
            
            start_datetime = datetime.strptime(str(start_date), '%Y-%m-%d')
            end_datetime = datetime.strptime(str(end_date), '%Y-%m-%d') + timedelta(days=1)

            filtered_df = full_df.filter(
                (pl.col('SALES_DATE').dt.date() >= start_datetime.date()) &
                (pl.col('SALES_DATE').dt.date() < end_datetime.date())
            )
            
            if filtered_df.height == 0:
                ui.notify(f"No data found between {start_date} and {end_date}", type='warning')
                return
            
            filtered_json = filtered_df.write_json()
            dialog.close()
            app.storage.user['dwn_df_json'] = filtered_json
            
            ui.open('/raw_data', new_tab=True)
            ui.notify(f"Successfully loaded {filtered_df.height} records", type='positive')
        
        except Exception as e:
            ui.notify(f"Error: {str(e)}", type='negative')


class DetailsTable:
    """Handles the details table component."""
    
    def __init__(self, filter_state: Dict[str, Any], update_ui_callback: Callable):
        self.filter_state = filter_state
        self.update_ui_callback = update_ui_callback
        self.table_container = None
    
    def create_details_container(self):
        """Create the details container with table."""
        with ui.card().classes('w-full h-full p-0'):
            details_container = ui.column().classes('w-full h-full')
            with details_container:
                ui.label('Select Product and Model data').classes('p-2 text-lg font-bold')
                # Store reference to the table container for loading indicators
                self.table_container = ui.column().classes('w-full flex-1')
        
        return details_container
    
    async def create_table(self, filtered_df: pl.DataFrame, container):
        """Create and populate the data table with loading indicator."""
        if self.table_container is None:
            return

        # Show loading state
        state = get_global_state()
        state.set_loading_state('table', True, 'Loading table data...')

        # Clear existing content and show loading
        self.table_container.clear()
        with self.table_container:
            UIUtils.show_loading_indicator(self.table_container, 'Loading table data...')

        # Force UI update to show loading state
        await ui.run_javascript('void 0', timeout=2.5)

        try:
            if len(filtered_df) == 0:
                self.table_container.clear()
                with self.table_container:
                    ui.label('No data available').classes('text-center text-gray-500 p-8')
                return

            self.table_container.clear()
            with self.table_container:
                f1 = filtered_df.with_columns(pl.col('SALES_DATE').dt.date())

                # Create the appropriate table based on filter state
                if self.filter_state['level']:
                    table_df = f1.pivot(
                        'SALES_DATE',
                        index=[self.filter_state['location1'], self.filter_state['level']],
                        values='Act Orders Rev',
                        aggregate_function='sum',
                        sort_columns=True
                    )
                elif self.filter_state['location1']:
                    table_df = f1.pivot(
                        'SALES_DATE',
                        index=self.filter_state['location1'],
                        values='Act Orders Rev',
                        aggregate_function='sum',
                        sort_columns=True
                    )
                else:
                    # Use the first available location column as fallback
                    available_location_cols = ['Region', 'Country', 'Area']
                    index_col = None
                    for col in available_location_cols:
                        if col in f1.columns:
                            index_col = col
                            break

                    if index_col:
                        table_df = f1.pivot(
                            'SALES_DATE',
                            index=index_col,
                            values='Act Orders Rev',
                            aggregate_function='sum',
                            sort_columns=True
                        )
                    else:
                        # If no location columns available, create a simple aggregated table
                        table_df = f1.group_by('SALES_DATE').agg(
                            pl.col('Act Orders Rev').sum()
                        ).sort('SALES_DATE')

                table = ui.table.from_polars(table_df, pagination=10).classes('w-full').props('virtual-scroll').on('rowClick', self._on_row_click)
                # In NiceGUI v3, table data modifications trigger automatic updates
        finally:
            # Clear loading state
            state.set_loading_state('table', False)
    
    async def _on_row_click(self, e):
        """Handle row click events."""
        # Get the selected row data
        row_data = e.args[1]
        
        # Determine which product column to use based on current filter
        product_col = None
        product_value = None
        
        # Try to find the appropriate product identifier
        if 'CatalogNumber' in row_data and row_data['CatalogNumber']:
            product_col = 'CatalogNumber'
            product_value = row_data['CatalogNumber']
        elif 'IBP Level 6' in row_data and row_data['IBP Level 6']:
            product_col = 'IBP Level 6'
            product_value = row_data['IBP Level 6']
        elif 'IBP Level 5' in row_data and row_data['IBP Level 5']:
            product_col = 'IBP Level 5'
            product_value = row_data['IBP Level 5']
        elif 'Franchise' in row_data and row_data['Franchise']:
            product_col = 'Franchise'
            product_value = row_data['Franchise']
        
        if product_col and product_value:
            self.filter_state['product1'] = product_col
            self.filter_state['product2'] = product_value
            
            apply_filters(self.filter_state)
            state = get_global_state()
            global_filtered_df = state.filtered_df
            await self.update_ui_callback(global_filtered_df)
            ui.notify(f"Filtered by {product_col}: {product_value}", type='info')
        else:
            ui.notify("Could not determine product identifier from selected row", type='warning')


class ValidationResultsDialog:
    """Handles the validation results display dialog."""
    
    def __init__(self, validation_results: Dict):
        self.validation_results = validation_results
    
    def show(self):
        """Show the validation results dialog."""
        with ui.dialog().props('maximized') as dialog, ui.card().classes('w-full h-full'):
            self._create_dialog_header()
            self._create_dialog_content()
            self._create_dialog_footer(dialog)
        dialog.open()
    
    def _create_dialog_header(self):
        """Create the dialog header."""
        with ui.row().classes('w-full justify-between items-center p-4 bg-blue-50'):
            ui.label('Model Validation Results - Last 3 Months').classes('text-h5 font-bold')
            ui.label(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}').classes('text-caption')
    
    def _create_dialog_content(self):
        """Create the main content of the dialog."""
        with ui.column().classes('w-full h-full p-4 gap-4'):
            # Summary statistics
            self._create_summary_section()
            
            # Detailed results tabs
            with ui.tabs().classes('w-full') as tabs:
                comparison_tab = ui.tab('Comparison')
                ensemble_tab = ui.tab('Ensemble')
                nhits_tab = ui.tab('NHITS')
                lstm_tab = ui.tab('LSTM')
                arima_tab = ui.tab('AutoARIMA')
                ets_tab = ui.tab('AutoETS')
                naive_tab = ui.tab('SeasonalNaive')
                report_tab = ui.tab('Full Report')
            
            with ui.tab_panels(tabs, value=comparison_tab).classes('w-full h-96'):
                with ui.tab_panel(comparison_tab):
                    self._create_comparison_panel()
                
                with ui.tab_panel(ensemble_tab):
                    self._create_model_panel('ensemble', 'Ensemble')
                
                with ui.tab_panel(nhits_tab):
                    self._create_model_panel('nhits', 'NHITS')
                
                with ui.tab_panel(lstm_tab):
                    self._create_model_panel('lstm', 'LSTM')
                
                with ui.tab_panel(arima_tab):
                    self._create_model_panel('autoarima', 'AutoARIMA')
                
                with ui.tab_panel(ets_tab):
                    self._create_model_panel('autoets', 'AutoETS')
                
                with ui.tab_panel(naive_tab):
                    self._create_model_panel('seasonalnaive', 'SeasonalNaive')
                
                with ui.tab_panel(report_tab):
                    self._create_report_panel()
    
    def _create_summary_section(self):
        """Create the summary statistics section."""
        validator = ModelValidator()
        validator.validation_results = self.validation_results
        summary = validator.get_summary_statistics()
        
        with ui.card().classes('w-full'):
            ui.label('Summary Statistics').classes('text-h6 font-bold mb-2')
            
            # Create summary cards for all models
            model_colors = {
                'ensemble': 'bg-green-50',
                'nhits': 'bg-blue-50', 
                'lstm': 'bg-purple-50',
                'autoarima': 'bg-orange-50',
                'autoets': 'bg-red-50',
                'seasonalnaive': 'bg-yellow-50'
            }
            
            model_display_names = {
                'ensemble': 'Ensemble',
                'nhits': 'NHITS',
                'lstm': 'LSTM',
                'autoarima': 'AutoARIMA',
                'autoets': 'AutoETS',
                'seasonalnaive': 'SeasonalNaive'
            }
            
            # Create rows of model summary cards
            with ui.row().classes('w-full gap-2 flex-wrap'):
                for model_key, model_name in model_display_names.items():
                    if model_key in summary and summary[model_key].get('num_validations', 0) > 0:
                        with ui.card().classes(f'flex-1 min-w-48 {model_colors.get(model_key, "bg-gray-50")}'):
                            ui.label(model_name).classes('font-bold text-center')
                            model_stats = summary[model_key]
                            ui.label(f"Avg Accuracy: {model_stats.get('avg_accuracy', 0):.1f}%")
                            ui.label(f"Avg MAE: {model_stats.get('avg_mae', 0):.2f}")
                            ui.label(f"Validations: {model_stats.get('num_validations', 0)}")
            
            # Overall comparison summary
            if 'overall_comparison' in summary and summary['overall_comparison']:
                with ui.card().classes('w-full bg-gray-100 mt-4'):
                    ui.label('Overall Performance').classes('font-bold text-center mb-2')
                    overall = summary['overall_comparison']
                    
                    with ui.row().classes('w-full gap-4 justify-center'):
                        for key, value in overall.items():
                            if key.endswith('_wins') and value > 0:
                                model_name = key.replace('_wins', '').title()
                                ui.label(f"{model_name}: {value} wins").classes('text-sm')
    
    def _create_comparison_panel(self):
        """Create the model comparison panel."""
        comparison_results = self.validation_results.get('comparison', [])
        
        if not comparison_results:
            ui.label('No comparison data available').classes('text-center text-gray-500 mt-8')
            return
        
        # Create summary table
        summary_df = ValidationReportGenerator.generate_summary_table(self.validation_results)
        
        if summary_df.height > 0:
            with ui.column().classes('w-full'):
                ui.label('Month-by-Month Comparison').classes('text-h6 font-bold mb-4')
                ui.table.from_polars(summary_df).classes('w-full')
        
        # Create comparison chart
        self._create_comparison_chart(comparison_results)
    
    def _create_comparison_chart(self, comparison_results):
        """Create a comparison chart."""
        if not comparison_results:
            return
        
        # Prepare data for chart - include all models
        months = [comp['month'] for comp in comparison_results]
        
        # Define model colors and names
        model_info = {
            'ensemble': {'name': 'Ensemble', 'color': '#10B981'},
            'nhits': {'name': 'NHITS', 'color': '#3B82F6'},
            'lstm': {'name': 'LSTM', 'color': '#8B5CF6'},
            'autoarima': {'name': 'AutoARIMA', 'color': '#F59E0B'},
            'autoets': {'name': 'AutoETS', 'color': '#EF4444'},
            'seasonalnaive': {'name': 'SeasonalNaive', 'color': '#84CC16'}
        }
        
        # Collect data for all models
        chart_series = []
        for model_key, info in model_info.items():
            model_data = []
            for comp in comparison_results:
                accuracy = comp.get(f'{model_key}_accuracy')
                model_data.append(accuracy if accuracy is not None else None)
            
            # Only add series if there's at least one non-null value
            if any(val is not None for val in model_data):
                chart_series.append({
                    'name': info['name'],
                    'data': model_data,
                    'color': info['color'],
                    'connectNulls': False
                })
        
        if chart_series:
            with ui.card().classes('w-full mt-4'):
                ui.label('Accuracy Comparison Chart - All Models').classes('text-h6 font-bold mb-2')
                
                chart_config = {
                    'chart': {'type': 'line', 'height': 400},
                    'title': {'text': 'Model Accuracy Comparison'},
                    'xAxis': {'categories': months},
                    'yAxis': {'title': {'text': 'Accuracy (%)'}, 'min': 0, 'max': 100},
                    'series': chart_series,
                    'legend': {'enabled': True},
                    'tooltip': {
                        'shared': True,
                        'valueSuffix': '%'
                    }
                }
                
                ui.highchart(chart_config).classes('w-full')
    
    def _create_model_panel(self, model_key: str, model_display_name: str):
        """Create a results panel for a specific model."""
        model_results = self.validation_results.get(model_key, [])
        
        if not model_results:
            ui.label(f'No {model_display_name} validation results available').classes('text-center text-gray-500 mt-8')
            return
        
        # Create detailed results table
        model_data = []
        for result in model_results:
            model_data.append({
                'Month': result.month,
                'Accuracy': f"{result.accuracy_percentage:.2f}%",
                'MAE': f"{result.mae:.2f}",
                'MAPE': f"{result.mape:.2f}%",
                'RMSE': f"{result.rmse:.2f}",
                'Bias': f"{result.forecast_bias:.2f}"
            })
        
        if model_data:
            model_df = pl.DataFrame(model_data)
            ui.label(f'{model_display_name} Model Detailed Results').classes('text-h6 font-bold mb-4')
            ui.table.from_polars(model_df).classes('w-full')
    
    def _create_report_panel(self):
        """Create the full report panel."""
        report_text = ValidationReportGenerator.generate_text_report(self.validation_results)
        
        with ui.column().classes('w-full'):
            ui.label('Full Validation Report').classes('text-h6 font-bold mb-4')
            
            with ui.card().classes('w-full bg-gray-50'):
                ui.code(report_text).classes('w-full whitespace-pre-wrap text-sm')
    
    def _create_dialog_footer(self, dialog):
        """Create the dialog footer with action buttons."""
        with ui.row().classes('w-full justify-end gap-2 p-4 bg-gray-50'):
            ui.button('Export Report', on_click=self._export_report).props('color=primary outline')
            ui.button('Close', on_click=dialog.close).props('color=primary')
    
    def _export_report(self):
        """Export the validation report."""
        try:
            report_text = ValidationReportGenerator.generate_text_report(self.validation_results)
            
            # Save to file in temporary directory
            import tempfile
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"validation_report_{timestamp}.txt"
            filepath = os.path.join(tempfile.gettempdir(), filename)
            
            with open(filepath, 'w') as f:
                f.write(report_text)
            
            ui.notify(f'Report exported to {filepath}', type='positive')
            
        except Exception as e:
            ui.notify(f'Export failed: {str(e)}', type='negative')
