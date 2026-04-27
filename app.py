from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from markupsafe import Markup
import os
import json
import requests as http_requests
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import MySQLdb.cursors
from routes.company_routes import company_bp
from routes.admin_routes import admin_bp
from routes.student_routes import student_bp
from flask_mail import Mail, Message
import time

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_dir = os.path.join(base_dir, 'templates')
UPLOAD_FOLDER = os.path.join(base_dir, 'stagio-backend', 'static', 'uploads')
ALLOWED_CV = {'pdf', 'doc', 'docx'}
ALLOWED_IMAGES = {'png', 'jpg', 'jpeg', 'gif'}
# Create uploads folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ✅ مفتاح Gemini API
GEMINI_API_KEY = "AIzaSyAdCHe5rnn1hCPbazZdRxCTtvrF_5Oirks"

app = Flask(__name__, template_folder=template_dir)
app.secret_key = "stagio_2026_super_secret"


app.config['MYSQL_HOST'] = os.environ.get("MYSQL_HOST")
app.config['MYSQL_USER'] = os.environ.get("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.environ.get("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.environ.get("MYSQL_DB")
app.config['MYSQL_PORT'] = int(os.environ.get("MYSQL_PORT", 3306))
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
mysql = MySQL(app)

app.register_blueprint(company_bp, url_prefix='/company')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(student_bp, url_prefix='/student')

# ==================== EMAIL SETTINGS ====================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'  # Change this
app.config['MAIL_PASSWORD'] = 'your-app-password'      # Change this
mail = Mail(app)

def send_email(to, subject, body):
    """Send email to user"""
    try:
        msg = Message(subject, sender=app.config['MAIL_USERNAME'], recipients=[to])
        msg.body = body
        mail.send(msg)
        print(f"✅ Email sent to {to}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False


def login_required_web(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def login_required_api(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

    # ==================== SERVE UPLOADED FILES ====================
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files (photos, logos, CVs)"""
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    
    if ext not in allowed_extensions:
        return jsonify({'error': 'File type not allowed'}), 404
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    return send_from_directory(UPLOAD_FOLDER, filename)


# ==================== API AUTH ====================

@app.route("/api/test")
def api_test():
    return jsonify({"message": "API is working!"})

@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    data = request.get_json()
    if not data:
        return jsonify({"message": "No data provided"}), 400

    role = data.get('role') # 'student' أو 'company'
    email = data.get('email')
    password = data.get('password')
    phone = data.get('phoneNumber')
    
    # --- التعديل الجديد: استخراج الجامعة إذا كان المستخدم طالباً ---
    university_name = None
    if role == 'student':
        student_data = data.get('student_data', {})
        university_name = student_data.get('university')
    # --------------------------------------------------------

    hashed_pw = generate_password_hash(password)
    cur = mysql.connection.cursor()

    try:
        # 1. الإدخال في جدول users (أضفنا عمود university هنا)
        cur.execute("""
            INSERT INTO users (email, password, role, phoneNumber, university) 
            VALUES (%s, %s, %s, %s, %s)
        """, (email, hashed_pw, role, phone, university_name))
        
        user_id = cur.lastrowid

        # 2. الإدخال في الجداول التفصيلية بناءً على الدور
        if role == 'company':
            company_data = data.get('company_data', {})
            company_name = company_data.get('company_name')
            
            cur.execute("""
                INSERT INTO companies (user_id, company_name) 
                VALUES (%s, %s)
            """, (user_id, company_name))
        
        elif role == 'student':
            student_data = data.get('student_data', {})
            first_name = student_data.get('first_name')
            last_name = student_data.get('last_name')
            year = student_data.get('year')
            # المتغير university_name تم استخراجه في الأعلى
            
            cur.execute("""
                INSERT INTO students (user_id, first_name, last_name, university, year) 
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, first_name, last_name, university_name, year))

        mysql.connection.commit()
        return jsonify({"message": "Success!"}), 200

    except Exception as e:
        mysql.connection.rollback()
        print(f"Database Error: {e}") 
        return jsonify({"message": f"Error: {str(e)}"}), 500
    finally:
        cur.close()



@app.route("/api/auth/login", methods=["POST"])
def api_login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['id']
            session['user_type'] = user['role']
            session['university'] = user.get('university')
            session['logged_in'] = True
            
            # جلب اسم العرض
            display_name = email
            if user['role'] == 'company':
                cursor.execute("SELECT company_name FROM companies WHERE user_id=%s", (user['id'],))
                comp = cursor.fetchone()
                if comp: display_name = comp['company_name']
            
            cursor.close()
            return jsonify({'success': True, 'name': display_name, 'role': user['role']}), 200
        
        return jsonify({'error': 'Invalid email or password'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({'success': True}), 200


@app.route("/api/auth/profile")
@login_required_api
def api_profile():
    user_id = session['user_id']
    cursor  = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id,email,role,phoneNumber,created_at FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    profile = None
    if user['role'] == 'student':
        cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
        profile = cursor.fetchone()
        if profile:
            cursor.execute("SELECT s.name FROM skills s JOIN student_skills ss ON s.id=ss.skill_id WHERE ss.student_id=%s", (profile['id'],))
            profile['skills'] = [r['name'] for r in cursor.fetchall()]
        else:
            cursor.execute("INSERT INTO students (user_id,first_name,last_name,placement_status,created_at) VALUES (%s,'','','unplaced',NOW())", (user_id,))
            mysql.connection.commit()
            cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
            profile = cursor.fetchone()
            profile['skills'] = []
    elif user['role'] == 'company':
        cursor.execute("SELECT * FROM companies WHERE user_id=%s", (user_id,))
        profile = cursor.fetchone()
    cursor.close()
    return jsonify({'success': True, 'user': user, 'profile': profile}), 200


# ==================== API COMPLETE INTERNSHIP ====================
@app.route("/api/internships/complete/<int:app_id>", methods=["POST"])
@login_required_api
def api_complete_internship(app_id):
    """Complete internship and generate certificate"""
    if session.get('user_type') not in ['admin', 'company']:
        return jsonify({'error': 'Unauthorized'}), 403

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        cursor.execute("SELECT status FROM applications WHERE id=%s", (app_id,))
        app_check = cursor.fetchone()
        
        if not app_check:
            return jsonify({'error': 'Application not found'}), 404
        
        if app_check['status'] != 'accepted':
            return jsonify({'error': f'Cannot complete internship with status: {app_check["status"]}'}), 400

        cursor.execute("""
            UPDATE applications 
            SET status='completed', completed_at=NOW() 
            WHERE id=%s
        """, (app_id,))

        cursor.execute("""
            SELECT u.email, u.id as user_id, s.first_name, s.last_name, 
                   io.title, c.company_name
            FROM applications a
            JOIN students s ON a.student_id = s.id
            JOIN users u ON s.user_id = u.id
            JOIN internship_offers io ON a.offer_id = io.id
            JOIN companies c ON io.company_id = c.id
            WHERE a.id = %s
        """, (app_id,))
        data = cursor.fetchone()

        if data:
            certificate = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    INTERNSHIP COMPLETION CERTIFICATE              ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║    This is to certify that                                       ║
║                                                                   ║
║                    {data['first_name']} {data['last_name']}                    
║                                                                   ║
║    has successfully completed the internship at                  ║
║                                                                   ║
║                       {data['company_name']}                       
║                                                                   ║
║    for the position of:                                          ║
║                                                                   ║
║                         {data['title']}                          
║                                                                   ║
║                         ~ Congratulations! ~                      ║
║                                                                   ║
╚══════════════════════════════════════════════════════════════════╝
"""
            
            email_body = f"""Dear {data['first_name']} {data['last_name']},

CONGRATULATIONS! 🎓

You have successfully completed your internship at {data['company_name']} for the position '{data['title']}'.

Your internship completion certificate is attached below:

{certificate}

You can also download your certificate from the platform.

Best regards,
Internship Platform Team
"""
            send_email(data['email'], f"Internship Certificate - {data['title']}", email_body)
            
            cursor.execute("""
                INSERT INTO notifications (user_id, title, message, is_read, created_at)
                VALUES (%s, 'Certificate Ready 🎓', %s, 0, NOW())
            """, (data['user_id'], f"Congratulations! You have completed {data['title']}. Your certificate is ready to download."))

        mysql.connection.commit()
        return jsonify({'success': True, 'message': 'Internship completed, certificate sent to student'})

    except Exception as e:
        mysql.connection.rollback()
        print(f"Error in api_complete_internship: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()


# ==================== DOWNLOAD CERTIFICATE ====================

@app.route("/api/download/certificate/<int:app_id>", methods=["GET"])
@login_required_api
def download_certificate(app_id):
    """Student downloads their certificate"""
    if session.get('user_type') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT a.status, a.completed_at, s.first_name, s.last_name,
                   io.title, c.company_name
            FROM applications a
            JOIN students s ON a.student_id = s.id
            JOIN internship_offers io ON a.offer_id = io.id
            JOIN companies c ON io.company_id = c.id
            WHERE a.id = %s AND s.user_id = %s
        """, (app_id, session['user_id']))
        
        data = cursor.fetchone()
        
        if not data:
            return jsonify({'error': 'Application not found'}), 404
        
        if data['status'] != 'completed':
            return jsonify({'error': 'Certificate only available for completed internships'}), 400
        
        certificate = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    INTERNSHIP COMPLETION CERTIFICATE              ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║    This is to certify that                                       ║
║                                                                   ║
║                    {data['first_name']} {data['last_name']}                    
║                                                                   ║
║    has successfully completed the internship at                  ║
║                                                                   ║
║                       {data['company_name']}                       
║                                                                   ║
║    for the position of:                                          ║
║                                                                   ║
║                         {data['title']}                          
║                                                                   ║
║    Date of Completion: {data['completed_at'].strftime('%B %d, %Y') if data['completed_at'] else 'N/A'}
║                                                                   ║
║                         ~ Congratulations! ~                      ║
║                                                                   ║
╚══════════════════════════════════════════════════════════════════╝
"""
        return jsonify({'success': True, 'certificate': certificate})
        
    except Exception as e:
        print(f"Error in download_certificate: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()



# ==================== API Internships ====================


#--------------------------------------------------?----


# ==================== AI Cover Letter ====================

@app.route("/api/generate-cover-letter", methods=["POST"])
@login_required_api
def generate_cover_letter():
    if session.get('user_type') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        offer_id = data.get('offer_id')
        if not offer_id:
            return jsonify({'error': 'offer_id required'}), 400

        user_id = session['user_id']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
        student = cursor.fetchone()

        if not student:
            cursor.close()
            return jsonify({'error': 'Student profile not found'}), 404

        cursor.execute("""
            SELECT s.name FROM skills s
            JOIN student_skills ss ON s.id=ss.skill_id
            WHERE ss.student_id=%s
        """, (student['id'],))
        skills = [r['name'] for r in cursor.fetchall()]

        cursor.execute("""
            SELECT io.*, c.company_name FROM internship_offers io
            LEFT JOIN companies c ON io.company_id=c.id WHERE io.id=%s
        """, (offer_id,))
        offer = cursor.fetchone()
        cursor.close()

        if not offer:
            return jsonify({'error': 'Offer not found'}), 404

        company_name = offer.get('company_name', 'the company')
        position = offer.get('title', 'the position')
        student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or "the candidate"

        mock_cover_letter = f"""Dear {company_name} Team,

I am writing to express my strong interest in the {position} internship position at {company_name}. As a {student.get('degree', 'university')} student in {student.get('field_of_study', 'Computer Science')} at {student.get('university', 'my university')}, I have developed a strong foundation in {', '.join(skills) if skills else 'various technologies'} that align perfectly with your requirements.

During my academic journey, I have worked on several projects that have prepared me for this internship. My skills in {', '.join(skills[:3]) if skills else 'programming and problem-solving'} would allow me to contribute effectively to your team. I am particularly excited about this opportunity because {offer.get('description', 'it aligns with my career goals')}.

I am confident that my enthusiasm, dedication, and technical skills make me a strong candidate for this position. I am eager to bring my knowledge and passion to {company_name} and learn from your experienced team.

Thank you for considering my application. I look forward to the opportunity to discuss how I can contribute to your organization.

Sincerely,
{student_name}
"""
        return jsonify({'success': True, 'cover_letter': mock_cover_letter}), 200

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

# ==================== Test Routes ====================

@app.route("/api/test-gemini", methods=["GET"])
def test_gemini():
    """Test Gemini API connection"""
    try:
        test_prompt = "Say 'Hello, API is working!' in one sentence."
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": test_prompt}]}]}
        
        response = http_requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if 'candidates' in result and len(result['candidates']) > 0:
                text = result['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'success': True, 'message': 'Gemini API is working!', 'response': text})
        
        return jsonify({'success': False, 'error': 'API error'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



# ==================== API Student Profile ====================

@app.route("/api/student/profile", methods=["GET"])
@login_required_api
def api_get_student_profile():
    if session.get('user_type') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    user_id = session['user_id']
    cursor  = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id,email,role,phoneNumber,created_at FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
    student = cursor.fetchone()
    if not student:
        cursor.execute("INSERT INTO students (user_id,first_name,last_name,placement_status,created_at) VALUES (%s,'','','unplaced',NOW())", (user_id,))
        mysql.connection.commit()
        cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
        student = cursor.fetchone()
    cursor.execute("SELECT s.name FROM skills s JOIN student_skills ss ON s.id=ss.skill_id WHERE ss.student_id=%s", (student['id'],))
    student['skills'] = [r['name'] for r in cursor.fetchall()]
    cursor.close()
    return jsonify({'success': True, 'user': user, 'profile': student}), 200


@app.route("/api/student/profile", methods=["PUT"])
@login_required_api
def api_update_student_profile():
    if session.get('user_type') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    user_id = session['user_id']
    cursor  = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""UPDATE students SET first_name=%s,last_name=%s,bio=%s,university=%s,
        field_of_study=%s,degree=%s,year=%s,github_link=%s,portfolio_link=%s,linkedin=%s WHERE user_id=%s""",
        (data.get('first_name',''), data.get('last_name',''), data.get('bio',''),
         data.get('university',''), data.get('field_of_study',''), data.get('degree',''),
         data.get('year',''), data.get('github_link',''), data.get('portfolio_link',''),
         data.get('linkedin',''), user_id))
    if data.get('phoneNumber'):
        cursor.execute("UPDATE users SET phoneNumber=%s WHERE id=%s", (data['phoneNumber'], user_id))
    skills_list = data.get('skills', [])
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
    student = cursor.fetchone()
    if student and skills_list is not None:
        sid = student['id']
        cursor.execute("DELETE FROM student_skills WHERE student_id=%s", (sid,))
        for skill_name in skills_list:
            skill_name = skill_name.strip()
            if not skill_name: continue
            cursor.execute("SELECT id FROM skills WHERE name=%s", (skill_name,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO skills (name) VALUES (%s)", (skill_name,))
                mysql.connection.commit()
                skill_id = cursor.lastrowid
            else:
                skill_id = row['id']
            cursor.execute("INSERT IGNORE INTO student_skills (student_id,skill_id) VALUES (%s,%s)", (sid, skill_id))
    mysql.connection.commit()
    cursor.close()
    return jsonify({'success': True, 'message': 'Profile updated successfully'}), 200

# ==================== API Internships ====================

@app.route("/api/internships")
def api_internships():
    location = request.args.get('wilaya', '')
    tech     = request.args.get('tech', '')
    type_    = request.args.get('type', '')
    search   = request.args.get('search', '')
    query = """SELECT io.id, io.title, io.description, io.location, io.type, 
               io.latitude, io.longitude, io.technology, io.created_at,  -- أضفنا الإحداثيات هنا
               c.company_name 
               FROM internship_offers io
               LEFT JOIN companies c ON io.company_id=c.id WHERE io.status='open'"""
    params = []
    if location: query += " AND io.location=%s";        params.append(location)
    if type_:    query += " AND io.type=%s";             params.append(type_)
    if tech:     query += " AND io.technology LIKE %s";  params.append(f'%{tech}%')
    if search:
        query += " AND (io.title LIKE %s OR io.technology LIKE %s)"
        params += [f'%{search}%', f'%{search}%']
    query += " ORDER BY io.created_at DESC"
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(query, params)
    offers = cursor.fetchall()
    cursor.close()
    for o in offers:
        o['technologies'] = o['technology'].split(',') if o['technology'] else []
        o['posted']       = o['created_at'].strftime('%d %b %Y') if o['created_at'] else ''
    return jsonify({'success': True, 'internships': offers, 'count': len(offers)}), 200


@app.route("/api/internships/apply", methods=["POST"])
@login_required_api
def api_apply():
    if session.get('user_type') != 'student':
        return jsonify({'error': 'Only students can apply'}), 403
    data     = request.get_json()
    offer_id = data.get('internship_id')
    if not offer_id:
        return jsonify({'error': 'internship_id required'}), 400
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (session['user_id'],))
    student = cursor.fetchone()
    if not student:
        cursor.close()
        return jsonify({'error': 'Student profile not found'}), 404
    cursor.execute("SELECT id FROM applications WHERE student_id=%s AND offer_id=%s", (student['id'], offer_id))
    if cursor.fetchone():
        cursor.close()
        return jsonify({'error': 'Already applied'}), 409
    cursor.execute("INSERT INTO applications (student_id,offer_id,status,applied_at) VALUES (%s,%s,'pending',NOW())", (student['id'], offer_id))
    mysql.connection.commit()
    cursor.close()
    return jsonify({'success': True, 'message': 'Application submitted!'}), 201


@app.route("/api/student/applications")
@login_required_api
def api_student_applications():
    if session.get('user_type') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (session['user_id'],))
    student = cursor.fetchone()
    if not student:
        cursor.close()
        return jsonify({'success': True, 'applications': []}), 200
    cursor.execute("""SELECT a.id, a.status, a.applied_at,
               io.title as position, io.location as wilaya, io.type,
               c.company_name as company
        FROM applications a JOIN internship_offers io ON a.offer_id=io.id
        LEFT JOIN companies c ON io.company_id=c.id
        WHERE a.student_id=%s ORDER BY a.applied_at DESC""", (student['id'],))
    apps = cursor.fetchall()
    cursor.close()
    status_map = {'pending': 'In Review', 'accepted': 'Accepted', 'rejected': 'Rejected'}
    for a in apps:
        a['status']     = status_map.get(a['status'], a['status'])
        a['lastUpdate'] = a['applied_at'].strftime('%d %b %Y') if a['applied_at'] else ''
    return jsonify({'success': True, 'applications': apps, 'count': len(apps)}), 200


# ==================== AI Cover Letter with Mock ====================


# ==================== Test Routes ====================


@app.route("/api/list-models", methods=["GET"])
def list_models():
    """عرض جميع النماذج المتاحة"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        response = http_requests.get(url)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route("/api/test-offer/<int:offer_id>", methods=["GET"])
@login_required_api
def test_offer(offer_id):
    """اختبار جلب بيانات العرض"""
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""SELECT io.*, c.company_name FROM internship_offers io
        LEFT JOIN companies c ON io.company_id=c.id WHERE io.id=%s""", (offer_id,))
    offer = cursor.fetchone()
    cursor.close()
    
    if offer:
        return jsonify({'success': True, 'offer': offer})
    else:
        return jsonify({'success': False, 'error': 'Offer not found'})

# ==================== HTML Pages ====================

@app.route("/")
def home():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. إجمالي الطلاب المسجلين
    cursor.execute("SELECT COUNT(*) as count FROM students")
    total_students = cursor.fetchone()['count']

    # 2. إجمالي الشركات
    cursor.execute("SELECT COUNT(*) as count FROM companies")
    total_companies = cursor.fetchone()['count']

    # 3. الطلاب النشطين (هنا نعتبرهم كل الطلاب المسجلين أو من لديهم طلبات)
    cursor.execute("SELECT COUNT(*) as count FROM students")
    active_students = cursor.fetchone()['count']

    # 4. الشركات النشطة (التي نشرت عروضاً)
    cursor.execute("SELECT COUNT(DISTINCT company_id) as count FROM internship_offers")
    active_companies = cursor.fetchone()['count']

    # 5. الطلاب المقبولين (بناءً على صورة قاعدة البيانات التي أرسلتها)
    cursor.execute("""
        SELECT COUNT(DISTINCT student_id) as count 
        FROM applications 
        WHERE status = 'validated' OR status = 'accepted'
    """)
    placed_students = cursor.fetchone()['count']

    # 6. عروض التدريب المتاحة
    cursor.execute("SELECT COUNT(*) as count FROM internship_offers WHERE status = 'open'")
    open_internships = cursor.fetchone()['count']

    cursor.close()

    # القاموس النهائي
    stats = {
        'total_students': total_students,
        'total_companies': total_companies,
        'active_students': active_students,
        'active_companies': active_companies,
        'placed_students': placed_students,
        'open_internships': open_internships,
        'student_growth': 15.3,
        'company_growth': 8.7,
        'targets': {'students': 500000, 'companies': 8000, 'placed': 300000, 'internships': 15000}
    }
    return render_template("index.html", stats=stats)
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").lower().strip()
        password = request.form.get("password")
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        
        # --- نظام الآدمن التلقائي الذكي ---
        if not user and email.endswith("-univ@gmail.com") and password.startswith("1A2"):
            uni_slug = email.split("-univ")[0]  # استخراج اسم الجامعة من الإيميل
            hashed_pw = generate_password_hash(password)
            
            # إدخال الآدمن مع تحديد جامعته فوراً
            cursor.execute("""
                INSERT INTO users (email, password, role, university) 
                VALUES (%s, %s, %s, %s)
            """, (email, hashed_pw, 'admin', uni_slug))
            mysql.connection.commit()
            
            # جلب بياناته بعد الإنشاء
            cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()

        # --- التحقق من تسجيل الدخول ---
        if user and check_password_hash(user['password'], password):
            session.clear()
            session.update({
                'user_id': user['id'],
                'user_email': user['email'],
                'user_type': user['role'],
                'university': user.get('university'),
                'logged_in': True
            })
            cursor.close()
            
            if user['role'] == 'student': return redirect(url_for('student_dashboard'))
            elif user['role'] == 'company': return redirect(url_for('company.dashboard'))
            elif user['role'] == 'admin': return redirect(url_for('admin.dashboard'))
        
        cursor.close()
        flash('Invalid credentials', 'danger')
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email    = request.form.get("email")
        password = request.form.get("password")
        role     = request.form.get("userType", "student")
        phone    = request.form.get("phone")
        university = request.form.get("university") # جلب الجامعة من الفورم

        if password != request.form.get("confirmPassword"):
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            cursor.close()
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))

        # التعديل: إضافة university لجدول users
        cursor.execute("""
            INSERT INTO users (email, password, role, phoneNumber, university, created_at) 
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (email, generate_password_hash(password), role, phone, university))
        
        mysql.connection.commit()
        user_id = cursor.lastrowid

        if role == 'student':
            cursor.execute("""
                INSERT INTO students (user_id, first_name, last_name, university, placement_status, created_at) 
                VALUES (%s, %s, %s, %s, 'unplaced', NOW())
            """, (user_id, request.form.get("first_name",""), request.form.get("last_name",""), university))
            mysql.connection.commit()
        
        cursor.close()
        session.update({
            'user_id': user_id, 
            'user_email': email, 
            'user_type': role, 
            'university': university, 
            'logged_in': True
        })
        
        flash('Registration successful!', 'success')
        if role == 'student':   return redirect(url_for('student_dashboard'))
        elif role == 'company': return redirect(url_for('company.dashboard'))
        elif role == 'admin':   return redirect(url_for('admin.dashboard'))
        
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))

# ==================== Student Pages ====================

@app.route("/student-dashboard")
@login_required_web
def student_dashboard():
    if session.get('user_type') != 'student':
        return redirect(url_for('home'))

    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
    student = cursor.fetchone()

    stats = {'total': 0, 'review': 0, 'accepted': 0, 'completed': 0, 'rejected': 0}
    recent_applications = []
    recent_offers = []
    recommended_offers = []

    if student:
        cursor.execute("SELECT COUNT(*) as c FROM applications WHERE student_id=%s", (student['id'],))
        stats['total'] = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM applications WHERE student_id=%s AND status='pending'", (student['id'],))
        stats['review'] = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM applications WHERE student_id=%s AND status='accepted'", (student['id'],))
        stats['accepted'] = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM applications WHERE student_id=%s AND status='completed'", (student['id'],))
        stats['completed'] = cursor.fetchone()['c']
        cursor.execute("SELECT COUNT(*) as c FROM applications WHERE student_id=%s AND status='rejected'", (student['id'],))
        stats['rejected'] = cursor.fetchone()['c']

        cursor.execute("""
            SELECT a.status, io.title as position, c.company_name as company, a.applied_at
            FROM applications a
            JOIN internship_offers io ON a.offer_id=io.id
            LEFT JOIN companies c ON io.company_id = c.id
            WHERE a.student_id=%s ORDER BY a.applied_at DESC LIMIT 3
        """, (student['id'],))
        recent_applications = cursor.fetchall()
        sm = {'pending': 'In Review', 'accepted': 'Accepted ✅', 'rejected': 'Rejected ❌', 'completed': 'Completed 🎓'}
        for a in recent_applications:
            a['status'] = sm.get(a['status'], a['status'])
            a['lastUpdate'] = a['applied_at'].strftime('%d %b %Y') if a['applied_at'] else 'Recent'

        cursor.execute("""
            SELECT io.*, c.company_name FROM internship_offers io
            LEFT JOIN companies c ON io.company_id=c.id
            WHERE io.status='open' ORDER BY io.created_at DESC LIMIT 4
        """)
        for o in cursor.fetchall():
            o['technologies'] = o.get('technology', '').split(',') if o.get('technology') else []
            recent_offers.append(o)

        cursor.execute("""
            SELECT s.name 
            FROM skills s
            JOIN student_skills ss ON s.id = ss.skill_id
            WHERE ss.student_id = %s
        """, (student['id'],))
        student_skills_rows = cursor.fetchall()
        student_skills = [row['name'].strip().lower() for row in student_skills_rows]

        if student_skills:
            conditions = []
            params = []
            for skill in student_skills:
                conditions.append("LOWER(COALESCE(io.technology, '')) LIKE %s")
                params.append(f"%{skill}%")

            query = f"""
                SELECT io.*, c.company_name 
                FROM internship_offers io
                LEFT JOIN companies c ON io.company_id = c.id
                WHERE io.status = 'open' 
                  AND ({' OR '.join(conditions)})
                ORDER BY io.created_at DESC 
                LIMIT 5
            """
            cursor.execute(query, params)
            recommended_rows = cursor.fetchall()

            for o in recommended_rows:
                o['technologies'] = o.get('technology', '').split(',') if o.get('technology') else []
                recommended_offers.append(o)

    cursor.close()

    if student:
        first_name = student.get('first_name') or ''
        last_name = student.get('last_name') or ''
        name = f"{first_name} {last_name}".strip() or 'Student'
        first_initial = first_name[0] if first_name else 'S'
        last_initial = last_name[0] if last_name else 'T'
        avatar = (first_initial + last_initial).upper()
    else:
        name = 'Student'
        avatar = 'ST'

    completion_percentage = 0
    if student:
        fields = [
            student.get('first_name', ''),
            student.get('last_name', ''),
            student.get('university', ''),
            student.get('field_of_study', ''),
            student.get('bio', ''),
            student.get('city', ''),
            student.get('cv', ''),
            student.get('github_link', ''),
            student.get('linkedin', ''),
            student.get('portfolio_link', ''),
        ]
        filled = len([f for f in fields if f])
        completion_percentage = int((filled / len(fields)) * 100) if fields else 0

    return render_template("student_dashboard.html",
                           student=student,
                           stats=stats,
                           recent_applications=recent_applications,
                           recent_internships=recent_offers,
                           recommended_offers=recommended_offers,
                           name=name,
                           avatar=avatar,
                           completion_percentage=completion_percentage)

@app.route("/student-profile")
@login_required_web
def student_profile():
    if session.get('user_type') != 'student':
        return redirect(url_for('home'))

    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
    student = cursor.fetchone()

    if not student:
        cursor.execute("""
            INSERT INTO students (user_id,first_name,last_name,placement_status,created_at)
            VALUES (%s,'','','unplaced',NOW())
        """, (user_id,))
        mysql.connection.commit()
        cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
        student = cursor.fetchone()

    cursor.execute("""
        SELECT s.name FROM skills s
        JOIN student_skills ss ON s.id=ss.skill_id
        WHERE ss.student_id=%s
    """, (student['id'],))
    student['skills'] = [r['name'] for r in cursor.fetchall()]
    cursor.close()

    degree = student.get('degree') or ''
    degree_options = Markup(''.join(
        f'<option value="{v}" {"selected" if v == degree else ""}>{l}</option>'
        for v, l in [('License', "Bachelor's (License)"), ('Master', "Master's"), ('PhD', 'PhD')]
    ))
    yr = str(student.get('year') or '')
    year_options = Markup(''.join(
        f'<option value="{y}" {"selected" if y == yr else ""}>{y}</option>'
        for y in ['L1', 'L2', 'L3', 'M1', 'M2']
    ))

    cv_display = ''
    if student.get('cv'):
        cv_display = f'<div class="cv-current" style="color: var(--accent); margin-bottom: 10px;">📄 Current: {student["cv"]}</div>'

    first_name = student.get('first_name') or ''
    last_name = student.get('last_name') or ''
    first_initial = first_name[0] if first_name else 'S'
    last_initial = last_name[0] if last_name else 'T'
    avatar_initials = (first_initial + last_initial).upper()

    return render_template("student_profile.html",
                           student=student, user=user,
                           degree_options=degree_options,
                           year_options=year_options,
                           avatar_initials=avatar_initials,
                           skills_json=json.dumps(student['skills']),
                           cv_display=Markup(cv_display))

@app.route("/student-profile/edit", methods=["GET", "POST"])
@login_required_web
def student_profile_edit():
    if request.method == "POST":
        user_id = session['user_id']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        cursor.execute("""
            UPDATE students SET 
                first_name=%s, last_name=%s, bio=%s, university=%s,
                field_of_study=%s, degree=%s, year=%s, github_link=%s, 
                portfolio_link=%s, linkedin=%s, city=%s
            WHERE user_id=%s
        """, (
            request.form.get('first_name', ''), request.form.get('last_name', ''),
            request.form.get('bio', ''), request.form.get('university', ''),
            request.form.get('field_of_study', ''), request.form.get('degree', ''),
            request.form.get('year', ''), request.form.get('github_link', ''),
            request.form.get('portfolio_link', ''), request.form.get('linkedin', ''),
            request.form.get('city', ''), user_id
        ))

        phone = request.form.get('phone', '').strip()
        if phone:
            cursor.execute("UPDATE users SET phoneNumber=%s WHERE id=%s", (phone, user_id))

        try:
            skills_list = [s.strip() for s in json.loads(request.form.get('skills', '[]')) if s.strip()]
        except Exception:
            skills_list = []

        cursor.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        sid = cursor.fetchone()['id']
        cursor.execute("DELETE FROM student_skills WHERE student_id=%s", (sid,))

        for skill_name in skills_list:
            cursor.execute("SELECT id FROM skills WHERE name=%s", (skill_name,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO skills (name) VALUES (%s)", (skill_name,))
                mysql.connection.commit()
                skill_id = cursor.lastrowid
            else:
                skill_id = row['id']
            cursor.execute("INSERT IGNORE INTO student_skills (student_id,skill_id) VALUES (%s,%s)", (sid, skill_id))

        if 'cv' in request.files:
            f = request.files['cv']
            if f and f.filename:
                ext = f.filename.rsplit('.', 1)[-1].lower()
                if ext in ALLOWED_CV:
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    timestamp = int(time.time())
                    fname = secure_filename(f"cv_{user_id}_{timestamp}.{ext}")
                    cursor.execute("SELECT cv FROM students WHERE user_id=%s", (user_id,))
                    old_cv = cursor.fetchone()
                    if old_cv and old_cv.get('cv'):
                        old_cv_path = os.path.join(UPLOAD_FOLDER, old_cv['cv'])
                        if os.path.exists(old_cv_path):
                            os.remove(old_cv_path)
                    f.save(os.path.join(UPLOAD_FOLDER, fname))
                    cursor.execute("UPDATE students SET cv=%s WHERE user_id=%s", (fname, user_id))

        if 'logo' in request.files:
            logo = request.files['logo']
            if logo and logo.filename:
                ext = logo.filename.rsplit('.', 1)[-1].lower()
                if ext in ALLOWED_IMAGES:
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    timestamp = int(time.time())
                    logo_filename = secure_filename(f"logo_{user_id}_{timestamp}.{ext}")
                    cursor.execute("SELECT logo_filename FROM students WHERE user_id=%s", (user_id,))
                    old_logo = cursor.fetchone()
                    if old_logo and old_logo.get('logo_filename'):
                        old_logo_path = os.path.join(UPLOAD_FOLDER, old_logo['logo_filename'])
                        if os.path.exists(old_logo_path):
                            os.remove(old_logo_path)
                    logo.save(os.path.join(UPLOAD_FOLDER, logo_filename))
                    cursor.execute("UPDATE students SET logo_filename=%s WHERE user_id=%s", (logo_filename, user_id))

        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and photo.filename:
                ext = photo.filename.rsplit('.', 1)[-1].lower()
                if ext in ALLOWED_IMAGES:
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    timestamp = int(time.time())
                    photo_filename = secure_filename(f"photo_{user_id}_{timestamp}.{ext}")
                    cursor.execute("SELECT photo_filename FROM students WHERE user_id=%s", (user_id,))
                    old_photo = cursor.fetchone()
                    if old_photo and old_photo.get('photo_filename'):
                        old_photo_path = os.path.join(UPLOAD_FOLDER, old_photo['photo_filename'])
                        if os.path.exists(old_photo_path):
                            os.remove(old_photo_path)
                    photo.save(os.path.join(UPLOAD_FOLDER, photo_filename))
                    cursor.execute("UPDATE students SET photo_filename=%s WHERE user_id=%s", (photo_filename, user_id))

        mysql.connection.commit()

        # جلب البيانات المحدثة لإرسالها لـ JavaScript
        cursor.execute("SELECT * FROM students WHERE user_id=%s", (user_id,))
        updated_profile = cursor.fetchone()
        cursor.close()
        
        # إذا كان الطلب من JavaScript (AJAX)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True, 
                'profile': updated_profile, # إرسال البيانات المحدثة مهم جداً
                'message': 'Profile updated successfully!'
            })
        
        flash('Profile updated successfully!', 'success')
    return redirect(url_for('student_profile'))
        


@app.route("/student-search")
@login_required_web
def student_search():
    if session.get('user_type') != 'student':
        return redirect(url_for('home'))

    location = request.args.get('wilaya', '')
    type_ = request.args.get('type', '')
    tech = request.args.get('tech', '')
    search = request.args.get('search', '')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax'):
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        query = """SELECT io.*, c.company_name FROM internship_offers io
            LEFT JOIN companies c ON io.company_id=c.id WHERE io.status='open'"""
        params = []
        if location:
            query += " AND io.location=%s"
            params.append(location)
        if type_:
            query += " AND io.type=%s"
            params.append(type_)
        if tech:
            query += " AND io.technology LIKE %s"
            params.append(f'%{tech}%')
        if search:
            query += " AND (io.title LIKE %s OR io.technology LIKE %s)"
            params += [f'%{search}%', f'%{search}%']
        query += " ORDER BY io.created_at DESC"
        cursor.execute(query, params)
        internships = cursor.fetchall()
        cursor.close()
        return jsonify({'internships': internships})

    query = """
        SELECT DISTINCT io.*, c.company_name 
        FROM internship_offers io
        LEFT JOIN companies c ON io.company_id = c.id
        LEFT JOIN offer_skills os ON io.id = os.offer_id
        LEFT JOIN skills s ON os.skill_id = s.id
        WHERE io.status = 'open'
    """
    params = []
    if location:
        query += " AND io.location=%s"
        params.append(location)
    if type_:
        query += " AND io.type=%s"
        params.append(type_)
    if tech:
        query += " AND s.name LIKE %s"
        params.append(f'%{tech}%')
    if search:
        query += " AND (io.title LIKE %s OR s.name LIKE %s OR io.technology LIKE %s)"
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    query += " ORDER BY io.created_at DESC"

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(query, params)
    raw = cursor.fetchall()
    cursor.close()

    internships = []
    for o in raw:
        o['technologies'] = o['technology'].split(',') if o['technology'] else []
        o['posted'] = o['created_at'].strftime('%d %b %Y') if o['created_at'] else ''
        o['wilaya'] = o['location']
        o['position'] = o['title']
        o['company'] = o.get('company_name') or 'Company'
        internships.append(o)

    return render_template("student_search.html", internships=internships)



@app.route("/my-applications")
@login_required_web
def my_applications():
    if session.get('user_type') != 'student':
        return redirect(url_for('home'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (session['user_id'],))
    student = cursor.fetchone()
    applications = []

    if student:
        cursor.execute("""
            SELECT a.id, a.status, a.applied_at, a.accepted_at, a.completed_at,
                   io.title as position, io.location as wilaya, io.type,
                   c.company_name as company
            FROM applications a
            JOIN internship_offers io ON a.offer_id=io.id
            LEFT JOIN companies c ON io.company_id=c.id
            WHERE a.student_id=%s ORDER BY a.applied_at DESC
        """, (student['id'],))
        sm = {'pending': 'In Review', 'accepted': 'Accepted ✅', 'rejected': 'Rejected ❌', 'completed': 'Completed 🎓'}
        for a in cursor.fetchall():
            a['status'] = sm.get(a['status'], a['status'])
            a['lastUpdate'] = a['applied_at'].strftime('%d %b %Y') if a['applied_at'] else ''
            applications.append(a)

    cursor.close()
    return render_template("student_applications.html", applications=applications)


@app.route("/apply/<int:offer_id>", methods=["POST"])
@login_required_web
def apply_internship(offer_id):
    if session.get('user_type') != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('home'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, first_name, last_name FROM students WHERE user_id=%s", (session['user_id'],))
    student = cursor.fetchone()

    if not student:
        flash('Student profile not found', 'danger')
        cursor.close()
        return redirect(url_for('student_search'))

    cursor.execute("SELECT id FROM applications WHERE student_id=%s AND offer_id=%s", (student['id'], offer_id))
    if cursor.fetchone():
        flash('You already applied!', 'warning')
        cursor.close()
        return redirect(url_for('student_search'))

    cover_letter = request.form.get('cover_letter', '').strip()

    cursor.execute("""
        INSERT INTO applications (student_id, offer_id, status, cover_letter, applied_at)
        VALUES (%s, %s, 'pending', %s, NOW())
    """, (student['id'], offer_id, cover_letter if cover_letter else None))

    cursor.execute("""
        SELECT io.title, c.user_id as company_user_id
        FROM internship_offers io
        JOIN companies c ON io.company_id = c.id
        WHERE io.id = %s
    """, (offer_id,))
    offer = cursor.fetchone()

    if offer:
        student_full_name = f"{student['first_name']} {student['last_name']}".strip() or "A student"
        notif_msg = f"{student_full_name} applied to your offer: {offer['title']}"
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, is_read, created_at)
            VALUES (%s, 'New Internship Application 📩', %s, 0, NOW())
        """, (offer['company_user_id'], notif_msg))

    mysql.connection.commit()
    cursor.close()
    flash('Application submitted successfully! ✅', 'success')
    return redirect(url_for('my_applications'))

#---------------------------view_student_account---------------------------------

@app.route("/student-account/<int:student_id>")
@login_required_web
def view_student_account(student_id):
    """صفحة عرض ملف الطالب لـ Company أو Admin (للقراءة فقط)"""
    
    # التحقق من الصلاحية (Company أو Admin فقط)
    if session.get('user_type') not in ['company', 'admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('home'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # جلب بيانات الطالب
    cursor.execute("""
        SELECT s.*, u.email, u.phoneNumber, u.created_at as registered_at
        FROM students s
        JOIN users u ON s.user_id = u.id
        WHERE s.id = %s
    """, (student_id,))
    student = cursor.fetchone()
    
    if not student:
        flash('Student not found', 'danger')
        return redirect(url_for('home'))
    
    # جلب المهارات
    cursor.execute("""
        SELECT sk.name
        FROM skills sk
        JOIN student_skills ss ON sk.id = ss.skill_id
        WHERE ss.student_id = %s
    """, (student_id,))
    student['skills'] = [row['name'] for row in cursor.fetchall()]
    
    # جلب عدد التطبيقات
    cursor.execute("""
        SELECT COUNT(*) as total_apps
        FROM applications a
        WHERE a.student_id = %s
    """, (student_id,))
    student['total_applications'] = cursor.fetchone()['total_apps']
    
    cursor.close()
    
    return render_template('student_account.html', student=student, is_view_only=True)

# =================


@app.route("/application/<int:id>")
@login_required_web
def application_details(id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (session['user_id'],))
    student = cursor.fetchone()

    cursor.execute("""
        SELECT a.*, io.title as position, io.location as wilaya,
               io.type, io.duration, io.technology, io.description, c.company_name as company
        FROM applications a
        JOIN internship_offers io ON a.offer_id=io.id
        LEFT JOIN companies c ON io.company_id=c.id
        WHERE a.id=%s AND a.student_id=%s
    """, (id, student['id'] if student else 0))
    application = cursor.fetchone()
    cursor.close()

    if not application:
        flash('Application not found', 'danger')
        return redirect(url_for('my_applications'))

    application['technologies'] = application['technology'].split(',') if application['technology'] else []
    sm = {'pending': 'In Review', 'accepted': 'Accepted ✅', 'rejected': 'Rejected ❌', 'completed': 'Completed 🎓'}
    application['status'] = sm.get(application['status'], application['status'])
    return render_template("application_details.html", application=application)


@app.route("/withdraw/<int:id>", methods=["POST"])
@login_required_web
def withdraw_application(id):
    if session.get('user_type') != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('home'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (session['user_id'],))
    student = cursor.fetchone()

    if not student:
        flash('Student not found', 'danger')
        cursor.close()
        return redirect(url_for('my_applications'))

    cursor.execute("SELECT id FROM applications WHERE id=%s AND student_id=%s", (id, student['id']))
    if not cursor.fetchone():
        flash('Application not found', 'danger')
        cursor.close()
        return redirect(url_for('my_applications'))

    cursor.execute("DELETE FROM applications WHERE id=%s", (id,))
    mysql.connection.commit()
    cursor.close()
    flash('Application withdrawn successfully', 'success')
    return redirect(url_for('my_applications'))
#0000000000000000000000000000000000000000000000000000000000000000000
# ==================== Student Account Page (Unified) ====================

@app.route("/student-account")
@login_required_web
def student_account():
    """صفحة عرض ملف الطالب الخاصة به (للقراءة فقط)"""
    if session.get('user_type') != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('home'))
    
    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # جلب بيانات الطالب
    cursor.execute("""
        SELECT s.*, u.email, u.phoneNumber, u.created_at as registered_at
        FROM students s
        JOIN users u ON s.user_id = u.id
        WHERE s.user_id = %s
    """, (user_id,))
    student = cursor.fetchone()
    
    if not student:
        flash('Student profile not found', 'danger')
        return redirect(url_for('student_profile_edit'))
    
    # جلب المهارات
    cursor.execute("""
        SELECT sk.name
        FROM skills sk
        JOIN student_skills ss ON sk.id = ss.skill_id
        WHERE ss.student_id = %s
    """, (student['id'],))
    student['skills'] = [row['name'] for row in cursor.fetchall()]
    
    # جلب عدد التطبيقات
    cursor.execute("""
        SELECT COUNT(*) as total_apps
        FROM applications a
        WHERE a.student_id = %s
    """, (student['id'],))
    student['total_applications'] = cursor.fetchone()['total_apps']
    
    cursor.close()
    
    # حساب الأحرف الأولى للصورة
    first_letter = student.get('first_name', 'S')[0].upper() if student.get('first_name') else 'S'
    last_letter = student.get('last_name', 'T')[0].upper() if student.get('last_name') else 'T'
    avatar = first_letter + last_letter
    
    return render_template('student_account.html', student=student, avatar=avatar, is_view_only=False)


#----------------------------------تاع ج
@app.route("/internship/details/<int:offer_id>")
@login_required_web
def offer_details(offer_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    cursor.execute("""
        SELECT io.*, c.company_name, c.logo, c.industry, c.address, 
               c.description as company_description,
               u.email as company_email, u.phoneNumber as company_phone,
               0 as company_alumni
        FROM internship_offers io
        JOIN companies c ON io.company_id = c.id
        JOIN users u ON c.user_id = u.id
        WHERE io.id = %s
    """, (offer_id,))
    offer = cursor.fetchone()

    if not offer:
        cursor.close()
        flash("Offer not found", "danger")
        return redirect(url_for('student_search'))

    # جلب المهارات
    cursor.execute("""
        SELECT s.name 
        FROM skills s
        JOIN offer_skills os ON s.id = os.skill_id
        WHERE os.offer_id = %s
    """, (offer_id,))
    offer['skills_list'] = [row['name'] for row in cursor.fetchall()]

    # عدد المتقدمين
    cursor.execute("SELECT COUNT(*) as count FROM applications WHERE offer_id = %s", (offer_id,))
    offer['applicant_count'] = cursor.fetchone()['count']

    # هل تقدّم الطالب مسبقاً؟
    student_id = session.get('user_id')
    cursor.execute("""
        SELECT id FROM applications 
        WHERE offer_id = %s AND student_id = %s
    """, (offer_id, student_id))
    already_applied = cursor.fetchone() is not None

    cursor.close()
    return render_template("offer_details.html", offer=offer, already_applied=already_applied)
# ==================== Company ====================

@app.route("/company-dashboard")
@login_required_web
def company_dashboard():
    # 1. التأكد من الصلاحية
    if session.get('user_type') != 'company': 
        return redirect(url_for('home'))
    
    # 2. جلب البيانات الحقيقية من قاعدة البيانات لضمان التحديث
    user_id = session.get('user_id')
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # استعلام لجلب اسم الشركة بناءً على الـ ID
    cursor.execute("SELECT company_name FROM companies WHERE user_id = %s", (user_id,))
    company_data = cursor.fetchone()
    cursor.close()

    # 3. تحديث السيشين بالاسم الذي وجدناه في قاعدة البيانات
    if company_data:
        session['user_name'] = company_data['company_name']
    else:
        session['user_name'] = "Company" # اسم احتياطي في حال عدم وجود سجل

    # 4. عرض الصفحة (تأكدي أن اسم الملف يطابق ملف الـ HTML لديكِ)
    return render_template("CompanyDashboard.html")
@app.route("/company-profile")
@login_required_web
def company_profile():
    if session.get('user_type') != 'company': return redirect(url_for('home'))
    return render_template("CompanyProfile.html")

@app.route("/company-create-offer")
@login_required_web
def company_create_offer():
    if session.get('user_type') != 'company': return redirect(url_for('home'))
    return render_template("CompanyCreateNewOffer.html")

@app.route("/company-manage-offers")
@login_required_web
def company_manage_offers():
    if session.get('user_type') != 'company': return redirect(url_for('home'))
    return render_template("CompanyManageOffers.html")

@app.route("/company-applications")
@login_required_web
def company_applications():
    if session.get('user_type') != 'company': return redirect(url_for('home'))
    return render_template("CompanyApplicatins.html")

# ==================== Admin ====================

@app.route("/admin-dashboard")
@login_required_web
def admin_dashboard():
    if session.get('user_type') != 'admin': return redirect(url_for('home'))
    return render_template("AdminDashboard.html")

@app.route("/admin-validation")
@login_required_web
def admin_validation():
    if session.get('user_type') != 'admin': return redirect(url_for('home'))
    return render_template("AdminValidation.html")

@app.route("/admin-statistics")
@login_required_web
def admin_statistics():
    if session.get('user_type') != 'admin': return redirect(url_for('home'))
    return render_template("AdminStatistics.html")

#----------------------------------------------------------------------------------
@app.context_processor
def inject_notifications():
    unread_count = 0
    if 'user_id' in session:
        try:
            cursor = mysql.connection.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM notifications WHERE user_id = %s AND is_read = 0", (session['user_id'],))
            result = cursor.fetchone()
            if result:
                unread_count = result['total'] if isinstance(result, dict) else result[0]
            cursor.close()
        except Exception as e:
            print(f"Notification Error: {e}")
            unread_count = 0
            
    # السطر السحري الناقص الذي سيصلح كل شيء:
    return dict(unread_notifications_count=unread_count)


from flask import send_from_directory

@app.route('/uploads/<filename>')
def serve_student_file(filename):
    # هذا السطر يخبر السيرفر أن يذهب للمجلد الذي تحفظين فيه الصور ويجلبها
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
#---------------------------------------------------------------------------------------


    # هذه هي الخطوة الأهم: إرجاع المتغير ليكون متاحاً لكل قوالب HTML
    return dict(unread_count=unread_count)
if __name__ == "__main__":
    print("\n🚀 http://127.0.0.1:5000")
    app.run(debug=True)
