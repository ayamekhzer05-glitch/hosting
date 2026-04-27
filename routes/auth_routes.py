
from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from functools import wraps
import MySQLdb.cursors
from flask_mysqldb import MySQL
import os

# Create blueprint
auth_bp = Blueprint('auth', __name__)

# JWT Configuration
JWT_SECRET_KEY = 'your-super-secret-jwt-key-change-this-in-production'
JWT_ACCESS_TOKEN_EXPIRES = datetime.timedelta(hours=24)

# We'll need mysql instance - will be set from app.py
mysql = None

def init_auth_routes(app_mysql):
    global mysql
    mysql = app_mysql

def generate_token(user_id, email, role):
    """Generate JWT token"""
    payload = {
        'user_id': user_id,
        'email': email,
        'role': role,
        'exp': datetime.datetime.utcnow() + JWT_ACCESS_TOKEN_EXPIRES,
        'iat': datetime.datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')

def token_required(f):
    """Decorator to verify JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check if token is in headers
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Decode token
            data = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
            request.current_user = {
                'user_id': data['user_id'],
                'email': data['email'],
                'role': data['role']
            }
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    
    return decorated

# ==================== AUTH ROUTES ====================

@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        required_fields = ['email', 'password', 'role']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return jsonify({
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400
        
        # Validate role
        if data['role'] not in ['student', 'company', 'admin']:
            return jsonify({'error': 'Invalid role. Must be student, company, or admin'}), 400
        
        email = data['email']
        password = data['password']
        role = data['role']
        phone_number = data.get('phoneNumber')
        
        # Check if user already exists
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            cursor.close()
            return jsonify({'error': 'Email already registered'}), 409
        
        # Hash password
        hashed_password = generate_password_hash(password)
        
        # Insert new user
        cursor.execute("""
            INSERT INTO users (email, password, role, phoneNumber, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (email, hashed_password, role, phone_number))
        
        mysql.connection.commit()
        user_id = cursor.lastrowid
        
        # If role is student, create basic student profile
        if role == 'student' and 'student_data' in data:
            student_data = data['student_data']
            cursor.execute("""
                INSERT INTO students (user_id, first_name, last_name, bio, university, 
                                     field_of_study, degree, year, github_link, 
                                     portfolio_link, linkedin, placement_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'unplaced', NOW())
            """, (
                user_id,
                student_data.get('first_name', ''),
                student_data.get('last_name', ''),
                student_data.get('bio'),
                student_data.get('university'),
                student_data.get('field_of_study'),
                student_data.get('degree'),
                student_data.get('year'),
                student_data.get('github_link'),
                student_data.get('portfolio_link'),
                student_data.get('linkedin')
            ))
            mysql.connection.commit()
        
        cursor.close()
        
        # Generate JWT token
        token = generate_token(user_id, email, role)
        
        return jsonify({
            'message': 'User registered successfully',
            'token': token,
            'user': {
                'id': user_id,
                'email': email,
                'role': role
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """Login user and return JWT token"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password are required'}), 400
        
        email = data['email']
        password = data['password']
        
        # Find user by email
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Verify password
        if not check_password_hash(user['password'], password):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Generate JWT token
        token = generate_token(user['id'], user['email'], user['role'])
        
        # Also set session for web routes
        session['user_id'] = user['id']
        session['user_email'] = user['email']
        session['user_type'] = user['role']
        session['logged_in'] = True
        
        return jsonify({
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'role': user['role'],
                'phoneNumber': user['phoneNumber']
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/api/auth/profile', methods=['GET'])
@token_required
def get_profile():
    """Get current user profile"""
    try:
        user_id = request.current_user['user_id']
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Get user basic info
        cursor.execute("""
            SELECT id, email, role, phoneNumber, created_at 
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({'error': 'User not found'}), 404
        
        # Get role-specific profile
        profile = None
        if user['role'] == 'student':
            cursor.execute("""
                SELECT * FROM students WHERE user_id = %s
            """, (user_id,))
            profile = cursor.fetchone()
            
            # Get student skills
            if profile:
                cursor.execute("""
                    SELECT s.id, s.name 
                    FROM skills s
                    JOIN student_skills ss ON s.id = ss.skill_id
                    WHERE ss.student_id = %s
                """, (profile['id'],))
                skills = cursor.fetchall()
                profile['skills'] = skills
        
        elif user['role'] == 'company':
            cursor.execute("""
                SELECT * FROM companies WHERE user_id = %s
            """, (user_id,))
            profile = cursor.fetchone()
        
        cursor.close()
        
        return jsonify({
            'user': user,
            'profile': profile
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    session.clear()
    return jsonify({'message': 'Logged out successfully'}), 200

@auth_bp.route('/api/auth/refresh', methods=['POST'])
@token_required
def refresh_token():
    """Refresh JWT token"""
    try:
        user_id = request.current_user['user_id']
        email = request.current_user['email']
        role = request.current_user['role']
        
        # Generate new token
        new_token = generate_token(user_id, email, role)
        
        return jsonify({
            'token': new_token
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500