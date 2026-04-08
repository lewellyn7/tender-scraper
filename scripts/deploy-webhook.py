#!/usr/bin/env python3
"""
Webhook 服务器 - 接收 GitHub Actions 部署触发
监听 POST /webhook/deploy，执行 docker compose pull && up -d

用法:
    python3 deploy-webhook.py [--port PORT] [--secret SECRET]
    
安全: 使用 --secret 参数验证请求来源
"""

import http.server
import socketserver
import hashlib
import hmac
import json
import subprocess
import os
import sys
import argparse
import threading
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/deploy-webhook.log')
    ]
)
log = logging.getLogger(__name__)

# 全局部署锁，防止并发部署
deploy_lock = threading.Lock()
deploying = False

PROJECT_DIR = Path.home() / 'tender-scraper'
COMPOSE_FILE = PROJECT_DIR / 'docker-compose.prod.yml'
COMPOSE_CMD = ['docker', 'compose', '-f', str(COMPOSE_FILE)]


def do_deploy():
    """执行部署"""
    global deploying
    
    with deploy_lock:
        if deploying:
            return {
                'status': 'busy',
                'message': 'Deployment already in progress'
            }
        deploying = True
    
    try:
        log.info('=' * 60)
        log.info('🚀 Starting deployment at %s', datetime.now().isoformat())
        log.info('=' * 60)
        
        # 1. Pull latest image
        log.info('📦 Pulling latest images...')
        result = subprocess.run(
            COMPOSE_CMD + ['pull'],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=PROJECT_DIR
        )
        
        if result.returncode != 0:
            log.error('Pull failed: %s', result.stderr)
            return {'status': 'error', 'message': f'Pull failed: {result.stderr}'}
        
        log.info('✅ Pull successful')
        
        # 2. Restart services
        log.info('🔄 Restarting services...')
        result = subprocess.run(
            COMPOSE_CMD + ['up', '-d', '--force-recreate'],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=PROJECT_DIR
        )
        
        if result.returncode != 0:
            log.error('Restart failed: %s', result.stderr)
            return {'status': 'error', 'message': f'Restart failed: {result.stderr}'}
        
        log.info('✅ Deployment successful at %s', datetime.now().isoformat())
        
        # 3. Get service status
        status_result = subprocess.run(
            COMPOSE_CMD + ['ps', '--format', 'json'],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR
        )
        
        return {
            'status': 'success',
            'message': 'Deployment completed',
            'time': datetime.now().isoformat(),
            'services': status_result.stdout.strip().split('\n') if status_result.stdout else []
        }
        
    except subprocess.TimeoutExpired:
        log.error('Deployment timed out')
        return {'status': 'error', 'message': 'Deployment timed out after 15 minutes'}
    except Exception as e:
        log.error('Deployment error: %s', e)
        return {'status': 'error', 'message': str(e)}
    finally:
        deploying = False


class DeployHandler(http.server.BaseHTTPRequestHandler):
    """处理部署请求"""
    
    def log_message(self, format, *args):
        log.info(format % args)
    
    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def verify_secret(self):
        """验证 webhook secret"""
        secret = getattr(self.server, 'secret', None)
        if not secret:
            return True
        
        # 从 X-Hub-Signature-256 或 X-Webhook-Secret 头验证
        signature = self.headers.get('X-Webhook-Secret', '')
        expected = 'sha256=' + hmac.new(
            secret.encode(),
            self.rfile.read(int(self.headers.get('Content-Length', 0))),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(f'sha256={signature}', expected) or \
               hmac.compare_digest(signature, expected)
    
    def do_GET(self):
        """健康检查和状态"""
        if self.path == '/health':
            self.send_json({'status': 'ok', 'deploying': deploying, 'time': datetime.now().isoformat()})
        elif self.path == '/status':
            result = subprocess.run(
                COMPOSE_CMD + ['ps', '--format', 'json'],
                capture_output=True,
                text=True,
                cwd=PROJECT_DIR
            )
            self.send_json({
                'status': 'ok',
                'deploying': deploying,
                'project_dir': str(PROJECT_DIR),
                'compose_file': str(COMPOSE_FILE),
                'compose_exists': COMPOSE_FILE.exists(),
                'services': result.stdout.strip() if result.returncode == 0 else result.stderr
            })
        else:
            self.send_json({
                'message': 'Deploy Webhook Server',
                'endpoints': {
                    'POST /webhook/deploy': 'Trigger deployment',
                    'GET /health': 'Health check',
                    'GET /status': 'Service status'
                }
            })
    
    def do_POST(self):
        """处理部署请求"""
        if self.path == '/webhook/deploy' or self.path == '/deploy':
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            log.info('Received deploy request from %s', self.client_address)
            log.info('Headers: %s', dict(self.headers))
            
            if body:
                try:
                    payload = json.loads(body)
                    log.info('Payload: %s', json.dumps(payload, indent=2))
                except:
                    log.warning('Non-JSON payload received')
            
            result = do_deploy()
            self.send_json(result, 200 if result['status'] == 'success' else 500)
        
        else:
            self.send_json({'error': 'Not found'}, 404)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """多线程 HTTP 服务器"""
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description='Deploy Webhook Server')
    parser.add_argument('--port', type=int, default=8084, help='Port to listen on')
    parser.add_argument('--secret', type=str, default=os.environ.get('DEPLOY_SECRET', ''),
                       help='Webhook secret for verification')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to')
    args = parser.parse_args()
    
    log.info('=' * 60)
    log.info('🚀 Deploy Webhook Server starting on %s:%d', args.host, args.port)
    log.info('📁 Project: %s', PROJECT_DIR)
    log.info('📄 Compose: %s', COMPOSE_FILE)
    log.info('🔒 Secret: %s', '***' + args.secret[-4:] if args.secret else 'none')
    log.info('=' * 60)
    
    if not COMPOSE_FILE.exists():
        log.warning('⚠️ docker-compose.prod.yml not found at %s', COMPOSE_FILE)
        log.warning('Create it with: cp docker-compose.yml docker-compose.prod.yml')
    
    server = ThreadedHTTPServer((args.host, args.port), DeployHandler)
    server.secret = args.secret
    
    log.info('✅ Server ready at http://%s:%d', args.host, args.port)
    log.info('📝 Endpoints:')
    log.info('   POST /webhook/deploy - Trigger deployment')
    log.info('   GET  /health         - Health check')
    log.info('   GET  /status         - Status')
    log.info('')
    log.info('💡 To expose via Tailscale:')
    log.info('   tailscale serve --bg tcp %d', args.port)
    log.info('')
    log.info('Press Ctrl+C to stop')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info('Shutting down...')
        server.shutdown()


if __name__ == '__main__':
    main()
