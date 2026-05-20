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
import subprocess
from functools import wraps

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

# ===================== CONFIG & SECURITY =====================
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 500))
SERVER_PORT = int(os.getenv('SERVER_PORT', 5000))
NGROK_AUTH_TOKEN = os.getenv('NGROK_AUTH_TOKEN', '')
NGROK_ENABLED = os.getenv('NGROK_ENABLED', 'true').lower() == 'true'

# ⚠️ التوكن السري لحماية السيرفر والتحكم في الـ CMD
# يجب إرساله في الـ Headers كـ Authorization: Bearer YourSecretToken Here
VPS_SECRET_TOKEN = os.getenv('VPS_SECRET_TOKEN', 'vps_admin_secret_2026')

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

# ===================== MIDDLEWARE (AUTH) =====================
def require_auth(f):
    """حاجز أمني للتحقق من التوكن قبل تنفيذ العمليات الحساسة"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or auth_header != f"Bearer {VPS_SECRET_TOKEN}":
            return jsonify({'error': 'Unauthorized: Invalid or missing VPS Secret Token'}), 401
        return f(*args, **kwargs)
    return decorated

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

# ===================== UTILITIES =====================
def is_safe_path(base_folder, path_to_check):
    """دالة أمنية تمنع الـ Path Traversal"""
    abs_base = os.path.abspath(base_folder)
    abs_target = os.path.abspath(path_to_check)
    return abs_target.startswith(abs_base)

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
            print(f"\n🚀 NGROK TUNNEL CREATED: {self.public_url}\n")
            return True
        except:
            return False

    def get_info(self):
        return {"connected": self.is_connected, "public_url": self.public_url}

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
    # وضع timeout=30 لحل مشكلة قفل التزامن (Database Locked)
    conn = sqlite3.connect('server.db', timeout=30)
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

# ===================== CLOUD STORAGE API =====================

@app.route('/')
def root():
    base_url = ngrok_manager.public_url or request.host_url.rstrip('/')
    return jsonify({
        'server': 'Cloud API & VPS Dashboard v3.0',
        'status': 'running',
        'ngrok': ngrok_manager.get_info(),
        'vps_protected': True
    })

@app.route('/api/storage', methods=['GET'])
@require_auth
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
@require_auth
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
                'download_url': f"{base_url}/api/files/{f['id']}?token={VPS_SECRET_TOKEN}"
            })
        
        return jsonify({'folder': folder, 'count': len(files_list), 'files': files_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload', methods=['POST'])
@require_auth
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
        
        # حماية ضد ثغرة الـ Path Traversal للمجلدات
        if not is_safe_path(app.config['UPLOAD_FOLDER'], folder_path):
            return jsonify({'error': 'Access denied: Directory traversal detected'}), 403

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
            'download_url': f"{base_url}/api/files/{file_id}?token={VPS_SECRET_TOKEN}"
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload/multiple', methods=['POST'])
@require_auth
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
                    
                    if not is_safe_path(app.config['UPLOAD_FOLDER'], folder_path):
                        continue

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
                        'download_url': f"{base_url}/api/files/{file_id}?token={VPS_SECRET_TOKEN}"
                    })
                except:
                    pass
        
        return jsonify({'success': True, 'uploaded_count': len(uploaded), 'files': uploaded}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<int:file_id>', methods=['GET'])
def download_file(file_id):
    # للتحميل المباشر من المتصفح نقبل الـ Token برابط الـ URL (Query Parameter) لسهولة التعامل
    token = request.args.get('token')
    if token != VPS_SECRET_TOKEN:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        conn = get_db()
        file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
        conn.close()
        if not file:
            return jsonify({'error': 'File not found'}), 404
            
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], file['folder'].lstrip('/'))
        file_path = os.path.join(folder_path, file['filename'])
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not on disk'}), 404
        return send_file(file_path, as_attachment=True, download_name=file['original_name'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<int:file_id>', methods=['DELETE'])
@require_auth
def delete_file(file_id):
    try:
        conn = get_db()
        file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
        if not file:
            conn.close()
            return jsonify({'error': 'File not found'}), 404
            
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], file['folder'].lstrip('/'))
        file_path = os.path.join(folder_path, file['filename'])
        
        if os.path.exists(file_path):
            os.remove(file_path)
            
        conn.execute('DELETE FROM files WHERE id = ?', (file_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f"Deleted: {file['original_name']}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/folders', methods=['GET'])
@require_auth
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
@require_auth
def create_folder():
    try:
        data = request.get_json()
        if not data or 'name' not in data:
            return jsonify({'error': 'Folder name required'}), 400
        folder_name = secure_filename(data['name'])
        parent = data.get('parent', '/')
        folder_path = f"{parent}/{folder_name}" if parent != '/' else f"/{folder_name}"
        
        actual_disk_path = os.path.join(UPLOAD_FOLDER, folder_path.lstrip('/'))
        if not is_safe_path(UPLOAD_FOLDER, actual_disk_path):
            return jsonify({'error': 'Access Denied'}), 403

        Path(actual_disk_path).mkdir(parents=True, exist_ok=True)
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
@require_auth
def delete_folder(folder_id):
    try:
        conn = get_db()
        folder = conn.execute('SELECT * FROM folders WHERE id = ?', (folder_id,)).fetchone()
        if not folder:
            conn.close()
            return jsonify({'error': 'Folder not found'}), 404
            
        actual = os.path.join(UPLOAD_FOLDER, folder['path'].lstrip('/'))
        if not is_safe_path(UPLOAD_FOLDER, actual):
            conn.close()
            return jsonify({'error': 'Forbidden'}), 403

        if os.path.exists(actual):
            import shutil
            shutil.rmtree(actual)
            
        conn.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
        # إصلاح المشكلة المنطقية: حذف كافة الملفات داخل هذا المجلد والمسارات الفرعية التابعة له في الـ DB
        conn.execute('DELETE FROM files WHERE folder = ? OR folder LIKE ?', (folder['path'], f"{folder['path']}/%"))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f"Deleted folder and its contents: {folder['name']}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===================== 🔥 NEW: VPS CONTROL & CMD API 🔥 =====================

@app.route('/api/vps/status', methods=['GET'])
@require_auth
def get_vps_status():
    """مراقبة الموارد الحية للسيرفر (CPU, RAM, OS)"""
    try:
        return jsonify({
            'cpu': {
                'usage_percent': psutil.cpu_percent(interval=0.5),
                'cores': psutil.cpu_count(logical=False),
                'threads': psutil.cpu_count(logical=True)
            },
            'memory': {
                'total_gb': round(psutil.virtual_memory().total / (1024**3), 2),
                'available_gb': round(psutil.virtual_memory().available / (1024**3), 2),
                'used_percent': psutil.virtual_memory().percent
            },
            'os': {
                'boot_time': datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S'),
                'pid_count': len(psutil.pids()),
                'current_server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vps/terminal', methods=['POST'])
@require_auth
def execute_command():
    """تنفيذ أوامر CMD على خادم الكلاود مباشرة"""
    data = request.get_json()
    if not data or 'command' not in data:
        return jsonify({'error': 'No command provided'}), 400
        
    command = data['command']
    
    # قائمة لحظر بعض الأوامر الكارثية تجنباً للأخطاء البشرية أثناء تجربة الـ API
    banned_keywords = ['rm -rf /', 'del /f /q /s', 'format']
    if any(banned in command.lower() for banned in banned_keywords):
        return jsonify({'error': 'Command blocked: Dangerous operation detected!'}), 403
        
    try:
        # تنفيذ الأمر مع وضع مهلة 30 ثانية لكي لا يعلق الخادم
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return jsonify({
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode
        }), 200
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command execution timed out (Max 30s)'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vps/processes', methods=['GET'])
@require_auth
def list_processes():
    """عرض أعلى 20 عملية تستهلك موارد السيرفر حالياً"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        # الترتيب تنازلياً حسب استهلاك المعالج
        processes = sorted(processes, key=lambda x: x['cpu_percent'] or 0, reverse=True)[:20]
        return jsonify({'count': len(processes), 'processes': processes})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vps/processes/kill', methods=['POST'])
@require_auth
def kill_process():
    """إغلاق أي عملية معلقة أو مستهلكة للموارد عبر الـ PID"""
    data = request.get_json()
    if not data or 'pid' not in data:
        return jsonify({'error': 'PID is required'}), 400
    try:
        pid = int(data['pid'])
        proc = psutil.Process(pid)
        proc.terminate() # محاولة إغلاق آمن أولاً
        return jsonify({'success': True, 'message': f"Process {pid} ({proc.name()}) has been terminated."})
    except psutil.NoSuchProcess:
        return jsonify({'error': 'Process not found'}), 404
    except psutil.AccessDenied:
        return jsonify({'error': 'Access denied to terminate this process'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===================== MAIN EXECUTION =====================
if __name__ == '__main__':
    if NGROK_ENABLED and NGROK_AUTH_TOKEN:
        threading.Thread(target=ngrok_manager.connect, args=(SERVER_PORT, NGROK_AUTH_TOKEN), daemon=True).start()
        time.sleep(2)
    
    print(f"\n⚙️ VPS SERVER RUNNING AT: http://localhost:{SERVER_PORT}")
    print(f"🔒 API SECRET TOKEN ACTIVE: {VPS_SECRET_TOKEN}")
    
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=False)