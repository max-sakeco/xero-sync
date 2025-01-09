from flask import Flask, jsonify
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/health')
def health():
    logger.info('Health check endpoint called')
    return jsonify({'status': 'ok'}), 200

@app.route('/')
def home():
    logger.info('Home endpoint called')
    return jsonify({'message': 'Welcome to Xero Sync'}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)
