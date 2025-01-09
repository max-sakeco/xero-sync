from flask import Flask, jsonify, request
import logging
import sys
import os

# Configure logging to output to stdout
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

@app.before_request
def log_request():
    logger.info(f'Received request: {request.method} {request.path}')
    logger.debug(f'Headers: {dict(request.headers)}')

@app.after_request
def after_request(response):
    logger.info(f'Sending response: {response.status}')
    return response

@app.route('/')
def health():
    logger.info('Health check called')
    try:
        return jsonify({
            'status': 'ok',
            'port': os.environ.get('PORT', '8080'),
            'path': request.path,
            'method': request.method
        })
    except Exception as e:
        logger.error(f'Error in health check: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Log startup
logger.info('Flask application initialized')

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)
