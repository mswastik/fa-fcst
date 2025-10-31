// JavaScript utilities for the forecasting dashboard

// Function to update filter options dynamically
function updateFilterOptions(selectId, options, placeholder = "Select option...") {
    const selectElement = document.getElementById(selectId);
    if (!selectElement) {
        console.error(`Select element with ID ${selectId} not found`);
        return;
    }
    
    // Clear existing options except the first one (placeholder)
    selectElement.innerHTML = '';
    
    // Add placeholder option
    const placeholderOption = document.createElement('option');
    placeholderOption.value = '';
    placeholderOption.textContent = placeholder;
    selectElement.appendChild(placeholderOption);
    
    // Add new options
    options.forEach(function(option) {
        const optionElement = document.createElement('option');
        optionElement.value = option;
        optionElement.textContent = option;
        selectElement.appendChild(optionElement);
    });
}

// Function to show notification
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type} bg-${type === 'error' ? 'red' : type === 'success' ? 'green' : 'blue'}-100 border border-${type === 'error' ? 'red' : type === 'success' ? 'green' : 'blue'}-300 text-${type === 'error' ? 'red' : type === 'success' ? 'green' : 'blue'}-700 px-4 py-3 rounded fixed top-4 right-4 z-50`;
    notification.textContent = message;
    
    // Add to document
    document.body.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(function() {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 5000);
}

// HTMX configuration
document.addEventListener('DOMContentLoaded', function() {
    // Set up global HTMX configuration
    document.body.addEventListener('htmx:beforeSend', function(evt) {
        console.log('Sending request:', evt.detail.requestConfig);
    });
    
    document.body.addEventListener('htmx:afterOnLoad', function(evt) {
        console.log('Request completed:', evt.detail.xhr);
    });
    
    document.body.addEventListener('htmx:responseError', function(evt) {
        console.error('Request failed:', evt.detail.xhr);
        showNotification('An error occurred while processing your request', 'error');
    });
    
    document.body.addEventListener('htmx:sendError', function(evt) {
        console.error('Request failed to send:', evt.detail.xhr);
        showNotification('Failed to connect to the server', 'error');
    });
});

// Helper function to get CSRF token if needed
function getCsrfToken() {
    const tokenElement = document.querySelector('[name=csrf-token]');
    return tokenElement ? tokenElement.content : '';
}