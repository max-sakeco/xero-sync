from flask import Flask, jsonify
import os
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', '8080'))
        logger.info(f'Starting server on port {port}')
        app.run(host='0.0.0.0', port=port, debug=True)
    except Exception as e:
        logger.error(f'Failed to start server: {e}')
