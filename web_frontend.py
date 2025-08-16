import os
import ftplib
import humanize
from flask import (Flask, render_template, request, redirect, url_for, 
                   session, send_file, flash)

# --- Flask App Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-super-secret-key-for-sessions'
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- FTP Server Details ---
FTP_HOST = "localhost" # For offline or ngrok use
FTP_PORT = 2121
ADMIN_USER = "ezaz"

# --- Helper Functions ---
def get_ftp_connection():
    ftp = ftplib.FTP()
    try:
        ftp.connect(FTP_HOST, FTP_PORT, timeout=10)
        if 'username' in session and session['username'] == ADMIN_USER:
            ftp.login(session['username'], session['password'])
        else:
            ftp.login() # Anonymous guest login
        return ftp
    except ftplib.all_errors as e:
        flash(f"FTP Server is not available: {e}", 'danger')
        return None

def generate_breadcrumbs(path):
    if path == ".": return []
    clean_path = path.strip('./')
    if not clean_path: return[]
    parts = clean_path.split('/')
    breadcrumbs = []
    current_path = ''
    for part in parts:
        current_path = os.path.join(current_path, part).replace('\\', '/')
        breadcrumbs.append({'name': part, 'path': current_path})
    return breadcrumbs

def parse_ftp_listing(lines):
    entries = []
    for line in lines:
        try:
            parts = line.split(maxsplit=8)
            if len(parts) < 9: continue
            
            entry_type = "dir" if parts[0].startswith('d') else "file"
            size = int(parts[4])
            
            entries.append({
                'name': parts[8],
                'type': entry_type,
                'size': size,
                'modify': ' '.join(parts[5:8]),
                'hr_size': humanize.naturalsize(size) if entry_type == 'file' else ''
            })
        except (ValueError, IndexError):
            continue 
    return entries

# --- Web Routes ---
@app.route("/")
@app.route("/files/")
@app.route("/files/<path:remote_path>")
def list_files(remote_path="."):
    if 'username' not in session and '..' in remote_path:
        flash("Access denied. Guests cannot navigate up.", "danger")
        return redirect(url_for('list_files'))

    ftp = get_ftp_connection()
    if not ftp:
        return render_template('files.html', entries=[], current_path=".", breadcrumbs=[], parent_path=None, error="Could not connect to FTP Server.")

    entries = []
    try:
        # MLSD is the modern, preferred method
        raw_entries = list(ftp.mlsd(path=remote_path, facts=["type", "size", "modify"]))
        for name, facts in raw_entries:
            if name in ('.', '..'): continue
            facts['name'] = name
            facts['hr_size'] = humanize.naturalsize(int(facts.get('size', 0))) if facts.get('type') == 'file' else ''
            entries.append(facts)
    except ftplib.error_perm: # Fallback to LIST if MLSD is not supported
        lines = []
        ftp.dir(remote_path, lines.append)
        entries = parse_ftp_listing(lines)
    except ftplib.all_errors as e:
        flash(f"Error listing files: {e}", "danger")
    finally:
        if ftp: ftp.quit()

    entries.sort(key=lambda x: (x.get('type') != 'dir', x.get('name').lower()))
    
    breadcrumbs = generate_breadcrumbs(remote_path)
    parent_path = os.path.dirname(remote_path) if remote_path not in ('.', '/') else None

    if 'username' not in session and remote_path == ".":
        parent_path = None

    return render_template('files.html', 
                           entries=entries,
                           current_path=remote_path,
                           breadcrumbs=breadcrumbs,
                           parent_path=parent_path)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username != ADMIN_USER:
            flash("Invalid credentials. Only admin can log in.", "danger")
            return redirect(url_for('login'))
        try:
            ftp = ftplib.FTP()
            ftp.connect(FTP_HOST, FTP_PORT)
            ftp.login(username, password)
            ftp.quit()
            
            session['username'] = username
            session['password'] = password
            flash(f"Welcome, Admin! You are logged in.", "success")
            return redirect(url_for('list_files'))
        except ftplib.all_errors:
            flash(f"Login failed for user '{username}'. Please check password.", "danger")
            return redirect(url_for('login'))
            
    # This serves the login.html page on a GET request
    return render_template('login.html')

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('list_files'))

@app.route('/delete', methods=['POST'])
def delete_item():
    if 'username' not in session or session['username'] != ADMIN_USER:
        flash("You do not have permission to delete items.", "danger")
        return redirect(url_for('list_files'))
    item_path = request.form.get('item_path')
    item_type = request.form.get('item_type')
    current_path = os.path.dirname(item_path) or '.'
    if not item_path or not item_type:
        flash("Invalid delete request.", "danger")
        return redirect(url_for('list_files', remote_path=current_path))
    ftp = get_ftp_connection()
    if not ftp: return redirect(url_for('list_files'))
    try:
        if item_type == 'file':
            ftp.delete(item_path)
            flash(f"File '{os.path.basename(item_path)}' deleted successfully.", "success")
        elif item_type == 'dir':
            ftp.rmd(item_path)
            flash(f"Directory '{os.path.basename(item_path)}' deleted successfully.", "success")
    except ftplib.all_errors as e:
        flash(f"Could not delete item: {e}", "danger")
    finally:
        if ftp: ftp.quit()
    return redirect(url_for('list_files', remote_path=current_path))

@app.route('/upload/<path:current_path>', methods=['POST'])
def upload_file(current_path):
    if 'username' not in session:
        flash("Please log in to upload files.", "warning")
        return redirect(url_for('list_files', remote_path=current_path))
    if 'file' not in request.files or request.files['file'].filename == '':
        flash("No file selected for upload.", "warning")
        return redirect(url_for('list_files', remote_path=current_path))
    file = request.files['file']
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(temp_path)
    ftp = get_ftp_connection()
    if not ftp: return redirect(url_for('login'))
    try:
        if current_path and current_path != '.':
            ftp.cwd(current_path)
        with open(temp_path, 'rb') as f:
            ftp.storbinary(f'STOR {file.filename}', f)
        flash(f"File '{file.filename}' uploaded successfully.", "success")
    except ftplib.all_errors as e:
        flash(f"Upload failed: {e}", "danger")
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)
        if ftp: ftp.quit()
    return redirect(url_for('list_files', remote_path=current_path))

@app.route('/mkdir/<path:current_path>', methods=['POST'])
def make_directory(current_path):
    if 'username' not in session:
        flash("Please log in to create directories.", "warning")
        return redirect(url_for('list_files', remote_path=current_path))
    dirname = request.form.get('dirname')
    if not dirname:
        flash("Directory name cannot be empty.", "warning")
        return redirect(url_for('list_files', remote_path=current_path))
    ftp = get_ftp_connection()
    if not ftp: return redirect(url_for('login'))
    try:
        if current_path and current_path != '.':
            ftp.cwd(current_path)
        ftp.mkd(dirname)
        flash(f"Directory '{dirname}' created successfully.", "success")
    except ftplib.all_errors as e:
        flash(f"Could not create directory: {e}", "danger")
    finally:
        if ftp: ftp.quit()
    return redirect(url_for('list_files', remote_path=current_path))

@app.route('/download/<path:filepath>')
def download_file(filepath):
    ftp = get_ftp_connection()
    if not ftp: return redirect(url_for('list_files'))
    try:
        filename = os.path.basename(filepath)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(temp_path, 'wb') as f:
            ftp.retrbinary(f'RETR {filepath}', f.write)
        return send_file(temp_path, as_attachment=True)
    except ftplib.all_errors as e:
        flash(f"Could not download file: {e}", "danger")
        return redirect(request.referrer or url_for('list_files'))
    finally:
        if ftp: ftp.quit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)