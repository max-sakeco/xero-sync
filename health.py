from flask import Flask, jsonify
import logging
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'xero-sync'
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
