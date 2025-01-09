from flask import Flask, jsonify, request
import os
import logging
import socket
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.before_request
def log_request_info():
    logger.debug('Headers: %s', dict(request.headers))
    logger.debug('Body: %s', request.get_data())

@app.route('/')
def health_check():
    port = os.getenv('PORT', '8080')
    hostname = socket.gethostname()
    logger.info(f'Health check called. Using port: {port} on host: {hostname}')
    
    try:
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'port': port,
            'hostname': hostname,
            'request_headers': dict(request.headers),
            'env': {k: v for k, v in os.environ.items() if not k.startswith('AWS_')}
        }), 200
    except Exception as e:
        logger.error(f'Error in health check: {str(e)}', exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/debug')
def debug():
    logger.info('Debug endpoint called')
    return jsonify({
        'env': dict(os.environ),
        'cwd': os.getcwd(),
        'ls': os.listdir('.'),
        'hostname': socket.gethostname(),
        'ip': socket.gethostbyname(socket.gethostname())
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)
