from flask import Flask, jsonify
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def health_check():
    port = os.getenv('PORT', '8080')
    logger.info(f'Health check called. Using port: {port}')
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'port': port,
        'env': dict(os.environ)
    }), 200

@app.route('/debug')
def debug():
    logger.info('Debug endpoint called')
    return jsonify({
        'env': dict(os.environ),
        'cwd': os.getcwd(),
        'ls': os.listdir('.')
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)
