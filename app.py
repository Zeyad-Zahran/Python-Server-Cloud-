from flask import Flask, request, jsonify, send_file, make_response
from werkzeug.utils import secure_filename
import os
import psutil
from datetime import datetime
from pathlib import Path
import mimetypes
import sqlite3
import threading
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '*')
    response.headers.pop('Access-Control-Allow-Origin', None)
    response.headers.pop('Access-Control-Allow-Methods', None)
    response.headers.pop('Access-Control-Allow-Headers', None)
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, ngrok-skip-browser-warning'
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
@app.route('/api', methods=['OPTIONS'])
def handle_options(path=None):
    response = make_response()
    origin = request.headers.get('Origin', '*')
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, ngrok-skip-browser-warning'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

# ===================== CONFIG =====================
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 500))
SERVER_PORT = int(os.getenv('SERVER_PORT', 5000))
NGROK_AUTH_TOKEN = os.getenv('NGROK_AUTH_TOKEN', '')
NGROK_ENABLED = os.getenv('NGROK_ENABLED', 'true').lower() == 'true'

ALLOWED_EXTENSIONS = {
    'images': {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico'},
    'videos': {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm', '3gp'},
    'documents': {'pdf', 'doc', 'docx', 'txt', 'xlsx', 'pptx', 'csv', 'json', 'xml'},
    'audio': {'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'},
    'archives': {'zip', 'rar', '7z', 'tar', 'gz'},
    'code': {'py', 'js', 'html', 'css', 'java', 'cpp', 'php'},
    'other': set()
}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE * 1024 * 1024
Path(UPLOAD_FOLDER).mkdir(exist_ok=True)

# ===================== NGROK =====================
class NgrokManager:
    def __init__(self):
        self.public_url = None
        self.is_connected = False
    
    def connect(self, port, auth_token=None):
        if not auth_token:
            return False
        try:
            from pyngrok import ngrok, conf
            conf.get_default().auth_token = auth_token
            try:
                ngrok.kill()
                time.sleep(1)
            except:
                pass
            self.tunnel = ngrok.connect(port, "http")
            self.public_url = self.tunnel.public_url
            self.is_connected = True
            print(f"\nNGROK: {self.public_url}\n")
            return True
        except:
            return False

ngrok_manager = NgrokManager()

# ===================== DATABASE =====================
def init_db():
    conn = sqlite3.connect('server.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  filename TEXT, original_name TEXT, file_type TEXT,
                  size INTEGER, folder TEXT DEFAULT '/',
                  upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  mime_type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS folders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT, path TEXT UNIQUE,
                  created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('server.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_file_category(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    for category, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return category
    return 'other'

def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    for extensions in ALLOWED_EXTENSIONS.values():
        if ext in extensions:
            return True
    return False

def format_size(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"

# ===================== API =====================

@app.route('/')
def root():
    base_url = ngrok_manager.public_url or request.host_url.rstrip('/')
    return jsonify({
        'server': 'Cloud API v2.5',
        'status': 'running',
        'ngrok': ngrok_manager.get_info(),
        'endpoints': ['GET /api/storage', 'GET /api/files', 'POST /api/upload', 'POST /api/upload/multiple', 'GET /api/files/<id>', 'DELETE /api/files/<id>', 'GET /api/folders', 'POST /api/folders', 'DELETE /api/folders/<id>']
    })

@app.route('/api/storage', methods=['GET'])
def get_storage():
    try:
        disk = psutil.disk_usage('/')
        uploads_size = 0
        total_files = 0
        for dirpath, dirnames, filenames in os.walk(UPLOAD_FOLDER):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    uploads_size += os.path.getsize(fp)
                    total_files += 1
        
        conn = get_db()
        folder_count = conn.execute('SELECT COUNT(*) FROM folders').fetchone()[0]
        conn.close()
        
        return jsonify({
            'total_gb': round(disk.total / (1024**3), 2),
            'used_gb': round(disk.used / (1024**3), 2),
            'free_gb': round(disk.free / (1024**3), 2),
            'usage_percent': disk.percent,
            'uploads_size': format_size(uploads_size),
            'uploads_mb': round(uploads_size / (1024**2), 2),
            'total_files': total_files,
            'total_folders': folder_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files', methods=['GET'])
def list_files():
    try:
        conn = get_db()
        folder = request.args.get('folder', '/')
        file_type = request.args.get('type')
        search = request.args.get('search')
        
        query = 'SELECT * FROM files WHERE 1=1'
        params = []
        
        if folder and folder != '/':
            query += ' AND folder = ?'
            params.append(folder)
        if file_type:
            query += ' AND file_type = ?'
            params.append(file_type)
        if search:
            query += ' AND original_name LIKE ?'
            params.append(f'%{search}%')
        
        query += ' ORDER BY upload_date DESC'
        files = conn.execute(query, params).fetchall()
        conn.close()
        
        base_url = ngrok_manager.public_url or request.host_url.rstrip('/')
        files_list = []
        for f in files:
            files_list.append({
                'id': f['id'],
                'original_name': f['original_name'],
                'file_type': f['file_type'],
                'size_mb': round(f['size'] / (1024**2), 2),
                'folder': f['folder'],
                'upload_date': f['upload_date'],
                'download_url': f"{base_url}/api/files/{f['id']}"
            })
        
        return jsonify({'folder': folder, 'count': len(files_list), 'files': files_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file'}), 400
        
        folder = request.form.get('folder', '/')
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        unique_filename = f"{timestamp}_{original_filename}"
        
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder.lstrip('/'))
        Path(folder_path).mkdir(parents=True, exist_ok=True)
        
        file_path = os.path.join(folder_path, unique_filename)
        file.save(file_path)
        
        file_size = os.path.getsize(file_path)
        file_category = get_file_category(original_filename)
        mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        
        conn = get_db()
        conn.execute(
            'INSERT INTO files (filename, original_name, file_type, size, folder, mime_type) VALUES (?, ?, ?, ?, ?, ?)',
            (unique_filename, original_filename, file_category, file_size, folder, mime_type)
        )
        conn.commit()
        file_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        
        base_url = ngrok_manager.public_url or request.host_url.rstrip('/')
        
        return jsonify({
            'success': True,
            'file_id': file_id,
            'original_name': original_filename,
            'size_mb': round(file_size / (1024**2), 2),
            'type': file_category,
            'download_url': f"{base_url}/api/files/{file_id}"
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload/multiple', methods=['POST'])
def upload_multiple():
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        folder = request.form.get('folder', '/')
        base_url = ngrok_manager.public_url or request.host_url.rstrip('/')
        
        uploaded = []
        for file in files:
            if file.filename and allowed_file(file.filename):
                try:
                    original_filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                    unique_filename = f"{timestamp}_{original_filename}"
                    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder.lstrip('/'))
                    Path(folder_path).mkdir(parents=True, exist_ok=True)
                    file_path = os.path.join(folder_path, unique_filename)
                    file.save(file_path)
                    file_size = os.path.getsize(file_path)
                    file_category = get_file_category(original_filename)
                    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
                    
                    conn = get_db()
                    conn.execute('INSERT INTO files (filename, original_name, file_type, size, folder, mime_type) VALUES (?, ?, ?, ?, ?, ?)',
                                 (unique_filename, original_filename, file_category, file_size, folder, mime_type))
                    file_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                    conn.commit()
                    conn.close()
                    
                    uploaded.append({
                        'file_id': file_id,
                        'original_name': original_filename,
                        'size_mb': round(file_size / (1024**2), 2),
                        'download_url': f"{base_url}/api/files/{file_id}"
                    })
                except:
                    pass
        
        return jsonify({'success': True, 'uploaded_count': len(uploaded), 'files': uploaded}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<int:file_id>', methods=['GET'])
def download_file(file_id):
    try:
        conn = get_db()
        file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
        conn.close()
        if not file:
            return jsonify({'error': 'File not found'}), 404
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file['filename'])
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not on disk'}), 404
        return send_file(file_path, as_attachment=True, download_name=file['original_name'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    try:
        conn = get_db()
        file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
        if not file:
            conn.close()
            return jsonify({'error': 'File not found'}), 404
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file['filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
        conn.execute('DELETE FROM files WHERE id = ?', (file_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f"Deleted: {file['original_name']}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/folders', methods=['GET'])
def list_folders():
    try:
        conn = get_db()
        folders = conn.execute('SELECT * FROM folders ORDER BY created_date DESC').fetchall()
        result = []
        for f in folders:
            count = conn.execute('SELECT COUNT(*) FROM files WHERE folder = ?', (f['path'],)).fetchone()[0]
            result.append({'id': f['id'], 'name': f['name'], 'path': f['path'], 'files_count': count})
        conn.close()
        return jsonify({'count': len(result), 'folders': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/folders', methods=['POST'])
def create_folder():
    try:
        data = request.get_json()
        if not data or 'name' not in data:
            return jsonify({'error': 'Folder name required'}), 400
        folder_name = secure_filename(data['name'])
        parent = data.get('parent', '/')
        folder_path = f"{parent}/{folder_name}" if parent != '/' else f"/{folder_name}"
        Path(os.path.join(UPLOAD_FOLDER, folder_path.lstrip('/'))).mkdir(parents=True, exist_ok=True)
        conn = get_db()
        try:
            conn.execute('INSERT INTO folders (name, path) VALUES (?, ?)', (folder_name, folder_path))
            conn.commit()
            fid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': 'Folder exists'}), 409
        conn.close()
        return jsonify({'success': True, 'folder_id': fid, 'name': folder_name, 'path': folder_path}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/folders/<int:folder_id>', methods=['DELETE'])
def delete_folder(folder_id):
    try:
        conn = get_db()
        folder = conn.execute('SELECT * FROM folders WHERE id = ?', (folder_id,)).fetchone()
        if not folder:
            conn.close()
            return jsonify({'error': 'Folder not found'}), 404
        actual = os.path.join(UPLOAD_FOLDER, folder['path'].lstrip('/'))
        if os.path.exists(actual):
            import shutil
            shutil.rmtree(actual)
        conn.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
        conn.execute('DELETE FROM files WHERE folder = ?', (folder['path'],))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f"Deleted folder: {folder['name']}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===================== MAIN =====================
if __name__ == '__main__':
    if NGROK_ENABLED and NGROK_AUTH_TOKEN:
        threading.Thread(target=ngrok_manager.connect, args=(SERVER_PORT, NGROK_AUTH_TOKEN), daemon=True).start()
        time.sleep(2)
    
    print(f"\nServer: http://localhost:{SERVER_PORT}")
    if ngrok_manager.is_connected:
        print(f"Public: {ngrok_manager.public_url}")
    
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=False)