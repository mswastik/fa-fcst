from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from core.db_service import get_database_service
import json
from datetime import datetime

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))

@router.post("/api/raw_data/filter_options")
async def get_raw_data_filter_options(request: Request):
    try:
        # First try to parse as JSON (for programmatic API calls)
        body = await request.json()
        filter_name = body.get('filter_name')
        selected_value = body.get(filter_name)
    except:
        # If JSON parsing fails, try form data (for HTMX calls)
        form_data = await request.form()
        filter_name = form_data.get('filter_name')
        selected_value = form_data.get(filter_name)

        # If that fails, try query parameters
        if not filter_name:
            query_params = dict(request.query_params)
            filter_name = query_params.get('filter_name')
            selected_value = query_params.get(filter_name)

    db = get_database_service()

    # Make sure to use the correct parameter names for HTMX
    form_data = await request.form()
    location1_value = form_data.get('location1')
    product1_value = form_data.get('product1')

    if filter_name == 'location1':
        # When location1 changes, get options for location2 based on the selected location1 value
        if location1_value == 'Region':
            options = db.get_filter_options(user_id="system").get('regions', [])
            label = 'Region'
        elif location1_value == 'Country':
            options = db.get_filter_options(user_id="system").get('countries', [])
            label = 'Country'
        elif location1_value == 'Area':
            options = db.get_filter_options(user_id="system").get('areas', [])
            label = 'Area'
        else:
            # Default to countries if unknown value
            options = db.get_filter_options(user_id="system").get('countries', [])
            label = 'Country'

        return templates.TemplateResponse("partials/raw_data_location_select2.html", {"request": request, "options": options, "label": label})
    elif filter_name == 'product1':
        # When product1 changes, get options for product2 based on the selected product1 value
        if product1_value == 'Franchise':
            options = db.get_filter_options(user_id="system").get('franchises', [])
            label = 'Franchise'
        elif product1_value == 'IBP Level 5':
            options = db.get_filter_options(user_id="system").get('ibp_level_5s', [])
            label = 'IBP Level 5'
        elif product1_value == 'IBP Level 6':
            options = db.get_filter_options(user_id="system").get('ibp_level_6s', [])
            label = 'IBP Level 6'
        elif product1_value == 'CatalogNumber':
            options = db.get_filter_options(user_id="system").get('catalog_numbers', [])
            label = 'CatalogNumber'
        else:
            # Default to franchises if unknown value
            options = db.get_filter_options(user_id="system").get('franchises', [])
            label = 'Franchise'

        return templates.TemplateResponse("partials/raw_data_product_select2.html", {"request": request, "options": options, "label": label})
    return HTMLResponse("")

@router.post("/api/raw_data")
async def get_raw_data(request: Request):
    try:
        body = await request.json()
        location1 = body.get('location1')
        location2 = body.get('location2')
        product1 = body.get('product1')
        product2 = body.get('product2')
        db = get_database_service()

        # Use the new combined method to get both sales actuals and forecasts
        data = db.get_filtered_sales_actuals_with_forecasts(
            location_col=location1,
            location_val=location2,
            product_col=product1,
            product_val=product2,
            user_id="system"
        )

        # Convert polars DataFrame to list of dicts and handle datetime serialization
        data_dicts = data.to_dicts()

        return JSONResponse(content={"data": json.loads(json.dumps(data_dicts, default=json_serial))})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/api/raw_data/pivot")
async def get_raw_data_pivot(request: Request):
    try:
        # Try to parse as JSON first (for direct API calls)
        body = await request.json()
        location1 = body.get('location1')
        location2 = body.get('location2')
        product1 = body.get('product1')
        product2 = body.get('product2')
        forecast_version = body.get('forecast_version')
        print(f"Received JSON pivot filter values: location1={location1}, location2={location2}, product1={product1}, product2={product2}")
    except:
        # If JSON parsing fails, try form data (for HTMX calls)
        body = await request.form()
        location1 = body.get('location1')
        location2 = body.get('location2')
        product1 = body.get('product1')
        product2 = body.get('product2')
        forecast_version = body.get('forecast_version')
        print(f"Received form pivot filter values: location1={location1}, location2={location2}, product1={product1}, product2={product2}")

    db = get_database_service()

    # If forecast_version is selected, ALWAYS get filter values from the database (override UI selections)
    if forecast_version:
        print(f"Fetching details for forecast version: {forecast_version}")
        version_details = db.get_forecast_version_details(forecast_version, user_id="system")
        if version_details:
            # Override all filter values with those from the database
            location1 = version_details.get('location1')
            location2 = version_details.get('location2')
            product1 = version_details.get('product1')
            product2 = version_details.get('product2')
            print(f"Using filters from version details: location1={location1}, location2={location2}, product1={product1}, product2={product2}")
        else:
            print(f"Warning: No details found for forecast version '{forecast_version}'")
    
    # Check if all filters have values - if not, return empty data
    if not all([location1, location2, product1, product2]):
        print("Some filters are not present, returning empty data.")
        return JSONResponse(content={"data": []})

    # Use the new combined method to get both sales actuals and forecasts
    data = db.get_filtered_sales_actuals_with_forecasts(
        location_col=location1,
        location_val=location2,
        product_col=product1,
        product_val=product2,
        user_id="system",
        forecast_version=forecast_version
    )

    print(f"Data shape from DB: {data.shape}")

    # Convert polars DataFrame to list of dicts and handle datetime serialization
    data_dicts = data.to_dicts()
    print(f"Number of records being returned: {len(data_dicts)}")

    return JSONResponse(content={"data": json.loads(json.dumps(data_dicts, default=json_serial))})