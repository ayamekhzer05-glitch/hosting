from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, current_app
import os
from werkzeug.utils import secure_filename
import MySQLdb.cursors
from datetime import datetime

company_bp = Blueprint('company', __name__)

def get_db():
    from app import mysql
    return mysql

# ---------------------------------------------------------------------------------
@company_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    from app import mysql
    import MySQLdb.cursors
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor) 
    user_id = session['user_id'] 

    # 1. تعريف جميع المتغيرات بقيم افتراضية لتجنب خطأ "Undefined"
    company_name = "Company Name"
    company_id = None
    active_offers = 0
    total_applicants = 0
    in_review = 0
    recent_offers = []
    recent_applicants = []
    notifications = []
    chart_labels = ["No Data"] # قيم افتراضية للمنحنى
    chart_values = [0]

    try:
        # جلب بيانات الشركة
        cur.execute("SELECT id, company_name FROM companies WHERE user_id = %s", [user_id])
        company_row = cur.fetchone()
        
        if company_row:
            company_id = company_row['id']
            company_name = company_row['company_name']

        if company_id:
            # أ. عدد العروض النشطة
            cur.execute("SELECT COUNT(*) as total FROM internship_offers WHERE company_id = %s", (company_id,))
            active_offers = cur.fetchone()['total']
# ب. إجمالي المتقدمين - استخدام DISTINCT لضمان عدم التكرار
            cur.execute("""
               SELECT COUNT(DISTINCT a.id) as total 
               FROM applications a
               JOIN internship_offers i ON a.offer_id = i.id
               JOIN students s ON a.student_id = s.id
               JOIN users u ON s.user_id = u.id
               WHERE i.company_id = %s
            """, (company_id,))
            total_applicants = cur.fetchone()['total']
             # ج. طلبات قيد المراجعة (المصحح أيضاً)
            cur.execute("""
                SELECT COUNT(a.id) as total FROM applications a
                JOIN internship_offers i ON a.offer_id = i.id
                JOIN students s ON a.student_id = s.id  -- أضفنا هذا السطر
                JOIN users u ON s.user_id = u.id       -- وأضفنا هذا السطر
                WHERE i.company_id = %s AND a.status = 'pending'
            """, (company_id,))
            in_review = cur.fetchone()['total']
            # د. أحدث العروض
            cur.execute("""
                SELECT i.title, (SELECT COUNT(*) FROM applications WHERE offer_id = i.id) as app_count
                FROM internship_offers i
                WHERE i.company_id = %s
                ORDER BY i.created_at DESC LIMIT 3
            """, (company_id,))
            recent_offers = cur.fetchall()

            # هـ. أحدث المتقدمين
            cur.execute("""
                SELECT s.first_name, s.last_name, a.applied_at
                FROM applications a
                JOIN students s ON a.student_id = s.id
                JOIN internship_offers i ON a.offer_id = i.id
                WHERE i.company_id = %s
                ORDER BY a.applied_at DESC LIMIT 3
            """, (company_id,))
            recent_applicants = cur.fetchall()

            # و. بيانات المنحنى المضيء (إحصائيات آخر 7 أيام حتى تاريخ اليوم)
            import datetime
            
            # 1. جلب البيانات من القاعدة لآخر 7 أيام فقط
            cur.execute("""
                SELECT DATE(a.applied_at) as applied_date, COUNT(a.id) as app_count
                FROM applications a
                JOIN internship_offers i ON a.offer_id = i.id
                WHERE i.company_id = %s 
                AND a.applied_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
                GROUP BY DATE(a.applied_at)
                ORDER BY DATE(a.applied_at) ASC
            """, (company_id,))
            rows = cur.fetchall()

            # 2. تحويل النتائج لقاموس لسهولة البحث { '2026-04-18': 5 }
            data_dict = {str(row['applied_date']): row['app_count'] for row in rows}

            # 3. بناء القائمة لآخر 7 أيام (بما فيها الأيام التي قيمتها 0)
            chart_labels = []
            chart_values = []
            
            for i in range(6, -1, -1):
                # توليد التاريخ
                target_date = datetime.date.today() - datetime.timedelta(days=i)
                date_key = str(target_date) # للمقارنة مع القاعدة
                display_label = target_date.strftime('%d %b') # للعرض (مثلاً 21 Apr)
                
                chart_labels.append(display_label)
                # إذا وجد بيانات لهذا اليوم نضعها، وإلا نضع 0
                chart_values.append(int(data_dict.get(date_key, 0)))
        # ز. الإشعارات غير المقروءة
        cur.execute("""
            SELECT title, message, created_at 
            FROM notifications 
            WHERE user_id = %s AND is_read = 0 
            ORDER BY created_at DESC
        """, (user_id,))
        notif_data = cur.fetchall()
        
        for n in notif_data:
            notifications.append({
                'title': n['title'],
                'message': n['message'],
                'time': n['created_at'].strftime('%d/%m %H:%M') if n['created_at'] else ""
            })
            # --- استعلام الطلاب الأكثر تسجيلاً لدى هذه الشركة ---
            cur.execute("""
                SELECT s.first_name, s.last_name, s.field_of_study, COUNT(a.id) as total_apps
                FROM students s
                JOIN applications a ON s.id = a.student_id
                JOIN internship_offers i ON a.offer_id = i.id
                WHERE i.company_id = %s
                GROUP BY s.id
                ORDER BY total_apps DESC
                LIMIT 4
            """, (company_id,))
            top_students = cur.fetchall()
        # --- استعلام الجامعات الأكثر تعاقداً (الطلاب المقبولين فقط) ---
            cur.execute("""
                SELECT s.university, COUNT(a.id) as validated_count
                FROM students s
                JOIN applications a ON s.id = a.student_id
                JOIN internship_offers i ON a.offer_id = i.id
                WHERE i.company_id = %s AND a.status = 'validated'
                GROUP BY s.university
                ORDER BY validated_count DESC
            """, (company_id,))
            university_stats = cur.fetchall()

                                 # حساب الحد الأقصى للطلاب لجعل شريط التقدم نسبي (اختياري)
            max_val = university_stats[0]['validated_count'] if university_stats else 1
            # ز. جلب "خلاصة النشاطات" (Activity Feed) بشكل مجمع
            cur.execute("""
                (SELECT 'new_app' as type, 
                        CONCAT(s.first_name, ' ', s.last_name, ' applied for: ', i.title) as message, 
                        a.applied_at as activity_date 
                 FROM applications a
                 JOIN students s ON a.student_id = s.id
                 JOIN internship_offers i ON a.offer_id = i.id
                 WHERE i.company_id = %s)
                UNION ALL
                (SELECT 'new_offer' as type, 
                        CONCAT('You published a new offer: ', title) as message, 
                        created_at as activity_date 
                 FROM internship_offers 
                 WHERE company_id = %s)
                ORDER BY activity_date DESC 
                LIMIT 5
            """, (company_id, company_id))
            activity_feed = cur.fetchall()
            

        # إرسال كل البيانات للقالب
        return render_template('CompanyDashboard.html', 
                               user_name=company_name,
                               active_offers=active_offers,
                               total_applicants=total_applicants,
                               in_review=in_review,
                               recent_offers=recent_offers,
                               recent_applicants=recent_applicants,
                               notifications=notifications, 
                               unread_count=len(notifications),
                               chart_labels=chart_labels,
                               chart_values=chart_values,
                               top_students=top_students,
                               company_id=company_id,
                               university_stats=university_stats,
                               activity_feed=activity_feed, # أضيفي هذا السطر
                               max_val=max_val,
                                )

    except Exception as e:
        print(f"❌ Error in Company Dashboard: {e}")
        # في حالة الخطأ، نمرر القيم الافتراضية لمنع توقف الصفحة
        return render_template('CompanyDashboard.html', 
                               user_name="Error",
                               active_offers=0,
                               total_applicants=0,
                               chart_labels=["Error"],
                               chart_values=[0],
                               notifications=[],
                               unread_count=0)
    finally:
        cur.close()
        # ---------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------
@company_bp.route('/manage-offers')
def manage_offers():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    mysql = get_db()
    cur = mysql.connection.cursor()
    
    # 1. جلب بيانات الشركة أولاً للحصول على الـ id الخاص بها
    cur.execute("SELECT id FROM companies WHERE user_id = %s", [session['user_id']])
    company_data = cur.fetchone()
    
    # إذا لم توجد بيانات للشركة، يمكن توجيه المستخدم أو وضع قيمة افتراضية
    if not company_data:
        cur.close()
        return "Company profile not found", 404

    company_id = company_data['id']

    # 2. جلب العروض المرتبطة بهذه الشركة
    cur.execute("""
        SELECT * FROM internship_offers 
        WHERE company_id = %s
    """, [company_id])
    
    offers = cur.fetchall()
    cur.close()
    
    # 3. تمرير المتغيرين معاً للقالب
    return render_template('CompanyManageOffers.html', 
                           offers=offers, 
                           company_id=company_id)
#--------------------------------------------------------------------
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import MySQLdb.cursors
# تأكدي من استيراد get_db حسب هيكلة مشروعك
# from database import get_db 

@company_bp.route('/create-offer', methods=['GET', 'POST'])
def create_offer():
    # 1. التحقق من تسجيل الدخول
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    mysql = get_db()
    
    if request.method == 'POST':
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        try:
            # 2. جلب معرف الشركة المرتبط بالمستخدم الحالي
            cur.execute("SELECT id FROM companies WHERE user_id = %s", [session['user_id']])
            company_row = cur.fetchone()

            if not company_row:
                return "Error: Company profile not found. Please complete your profile.", 404
            
            company_id = company_row['id']

            # 3. جلب البيانات من الفورم
            title = request.form.get('title')
            emp_type = request.form.get('employment_type')
            positions = request.form.get('positions', 1) 
            skills_raw = request.form.get('skills_input', '') # النص القادم من الحقل
            duration = request.form.get('duration', 'Not specified')
            deadline = request.form.get('deadline')
            description = request.form.get('description')
            lat = request.form.get('latitude')
            lng = request.form.get('longitude')

            location_summary = f"Coordinates: {lat}, {lng}"

            # 4. استعلام إدخال العرض الأساسي
            query = """
                INSERT INTO internship_offers 
                (title, type, duration, deadline, location, description, company_id, status, latitude, longitude) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
            """
            
            data = (title, emp_type, duration, deadline, location_summary, description, company_id, lat, lng)
            
            cur.execute(query, data)
            
            # --- بداية التعديل: ربط المهارات ---
            offer_id = cur.lastrowid # جلب ID العرض الذي أُنشئ للتو

            # تحويل النص (Python, Java) إلى قائمة ونزع الفراغات
            skills_list = [s.strip() for s in skills_raw.split(',') if s.strip()]

            for skill_name in skills_list:
                # التأكد من وجود المهارة في جدول المهارات الأصلي
                cur.execute("SELECT id FROM skills WHERE name = %s", [skill_name])
                skill_data = cur.fetchone()

                if skill_data:
                    skill_id = skill_data['id']
                else:
                    # إذا كانت المهارة جديدة كلياً، نضيفها لجدول المهارات أولاً
                    cur.execute("INSERT INTO skills (name) VALUES (%s)", [skill_name])
                    skill_id = cur.lastrowid

                # الآن نربط المهارة بهذا العرض تحديداً في جدول الربط
                cur.execute("INSERT INTO offer_skills (offer_id, skill_id) VALUES (%s, %s)", (offer_id, skill_id))
            # --- نهاية التعديل ---

            mysql.connection.commit()
            
            print("Successfully published the offer with skills!")
            return redirect(url_for('company.manage_offers'))
            
        except Exception as e:
            print(f"DATABASE ERROR: {e}")
            mysql.connection.rollback() 
            return f"An error occurred: {str(e)}", 500
        finally: 
            cur.close()
            
    return render_template('CompanyCreateNewOffer.html')
# ---------------------------------------------------------------------------------
@company_bp.route('/applications')
def applications():
    if 'user_id' not in session: return redirect(url_for('login'))
    mysql = get_db()
    cur = mysql.connection.cursor()
    
    # 1. أولاً: جلب الـ company_id الخاص بالمستخدم الحالي لتفادي خطأ Jinja2
    cur.execute("SELECT id FROM companies WHERE user_id = %s", [session['user_id']])
    company_data = cur.fetchone()
    # إذا لم يتم العثور على شركة، نعطي قيمة افتراضية أو نعالج الخطأ
    company_id = company_data['id'] if company_data else None
    cur.execute("SELECT COUNT(*) as total FROM applications a JOIN internship_offers io ON a.offer_id = io.id WHERE io.company_id = %s", [company_id])
    total_applicants = cur.fetchone()['total']

    # 2. الطلبات قيد الانتظار
    cur.execute("SELECT COUNT(*) as total FROM applications a JOIN internship_offers io ON a.offer_id = io.id WHERE io.company_id = %s AND a.status = 'pending'", [company_id])
    in_review = cur.fetchone()['total']

    # 3. الطلبات المقبولة
    cur.execute("SELECT COUNT(*) as total FROM applications a JOIN internship_offers io ON a.offer_id = io.id WHERE io.company_id = %s AND a.status = 'accepted'", [company_id])
    approved_count = cur.fetchone()['total']

    query = """
        SELECT a.id as app_id, s.id as student_id, s.first_name, s.last_name, u.email as student_email,
               io.title as position, a.applied_at, a.status, a.cover_letter
        FROM applications a
        JOIN students s ON a.student_id = s.id
        JOIN users u ON s.user_id = u.id
        JOIN internship_offers io ON a.offer_id = io.id
        JOIN companies c ON io.company_id = c.id
        WHERE c.user_id = %s ORDER BY a.applied_at DESC
    """
    cur.execute(query, [session['user_id']])
    results = cur.fetchall()
    cur.close()

    # 3. تمرير المتغيرين معاً (applications و company_id)
    return render_template('CompanyApplicatins.html', 
                           applications=results, 
                           company_id=company_id,
                           total_applicants=total_applicants, 
                           in_review=in_review, 
                           approved_today=approved_count) # هذا السطر هو مفتاح الحل
# ---------------------------------------------------------------------------------
@company_bp.route('/student-profile/<int:student_id>')
def view_student_profile(student_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    mysql = get_db()
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    query = """
        SELECT s.*, u.email 
        FROM students s 
        JOIN users u ON s.user_id = u.id 
        WHERE s.id = %s
    """
    cur.execute(query, [student_id])
    student = cur.fetchone()
    cur.close()
    
    if not student:
        flash("Student not found", "danger")
        return redirect(url_for('company.applications'))
        
    return render_template('CompanyViewStudent.html', student=student)

#---------------------------------------------------------------------------------






@company_bp.route('/accepted_applications')
def accepted_applications():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    from app import mysql
    import MySQLdb.cursors
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor) 
    
    # 1. جلب company_id لتمريره للقالب ومنع الخطأ
    cursor.execute("SELECT id FROM companies WHERE user_id = %s", (session['user_id'],))
    company_data = cursor.fetchone()
    company_id = company_data['id'] if company_data else None

    # 2. استعلام جلب الطلبات المقبولة (Validated)
    query = """
    SELECT 
        a.id, 
        CONCAT(s.first_name, ' ', s.last_name) AS student_name, 
        i.title AS position, 
        a.agreement_pdf,
        a.applied_at
    FROM applications a
    JOIN students s ON a.student_id = s.id
    JOIN internship_offers i ON a.offer_id = i.id
    JOIN companies c ON i.company_id = c.id
    WHERE c.user_id = %s AND a.status = 'validated'
    ORDER BY a.applied_at DESC
    """
    cursor.execute(query, (session['user_id'],))
    accepted_list = cursor.fetchall()
    cursor.close()
    
    # 3. تمرير company_id مع القائمة لضمان عمل الـ Navbar والروابط
    return render_template('CompanyAccepted.html', 
                           applications=accepted_list, 
                           company_id=company_id)
                           
#---------------------------------------------------------------------                   
                           
@company_bp.route('/update-offer', methods=['POST'])
def update_offer():
    from app import mysql
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json() 
    offer_id = data.get('id') 

    if not offer_id:
        return jsonify({"success": False, "error": "Missing Offer ID"}), 400

    cur = mysql.connection.cursor()
    try:
        # --- التعديل هنا: إضافة latitude و longitude للتحديث ---
        query = """
            UPDATE internship_offers 
            SET title=%s, location=%s, duration=%s, deadline=%s, technology=%s, description=%s, latitude=%s, longitude=%s
            WHERE id=%s
        """
        cur.execute(query, (
            data.get('title'), data.get('location'), data.get('duration'), 
            data.get('deadline'), data.get('technology'), data.get('description'), 
            data.get('latitude'), # جلب خط العرض من JSON
            data.get('longitude'), # جلب خط الطول من JSON
            offer_id
        ))
        
        mysql.connection.commit()
        cur.close()
        return jsonify({"success": True})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
#-------------------------------------------------------------------------------------
@company_bp.route('/delete-offer/<int:offer_id>', methods=['DELETE'])
def delete_offer(offer_id):
    from app import mysql
    if 'user_id' not in session:
        return {"success": False, "error": "Unauthorized"}, 401

    cur = mysql.connection.cursor()
    try:
        user_id = session['user_id']
        
        # التأكد من الملكية أولاً
        cur.execute("""
            SELECT io.id FROM internship_offers io
            JOIN companies c ON io.company_id = c.id
            WHERE io.id = %s AND c.user_id = %s
        """, (offer_id, user_id))
        
        if not cur.fetchone():
            return {"success": False, "error": "Permission denied"}, 403
        
        cur.execute("DELETE FROM offer_skills WHERE offer_id = %s", (offer_id,))
        # الخطوة 1: حذف جميع الطلبات المرتبطة بهذا العرض (لتجنب خطأ Foreign Key)
        cur.execute("DELETE FROM applications WHERE offer_id = %s", (offer_id,))
        
        # الخطوة 2: حذف العرض نفسه الآن بكل أمان
        cur.execute("DELETE FROM internship_offers WHERE id = %s", (offer_id,))
        
        mysql.connection.commit()
        return {"success": True}

    except Exception as e:
        mysql.connection.rollback()
        print(f"Detailed Error: {str(e)}")
        return {"success": False, "error": "Database constraint error"}, 500
    finally:
        cur.close()
# ---------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------
@company_bp.route('/update_application_status/<int:app_id>', methods=['POST'])
def update_application_status(app_id):
    if 'user_id' not in session: 
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    from app import mysql
    import MySQLdb.cursors
    
    # تحديد الحالة القادمة من الطلب
    if request.is_json:
        data = request.get_json()
        new_status = data.get('status')
    else:
        new_status = request.form.get('status')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        # 1. جلب بيانات الطالب والجامعة قبل أي إجراء (نحتاجها في حال القبول)
        cur.execute("""
            SELECT s.id as student_id, u.id as user_id, u.university, 
                   CONCAT(s.first_name, ' ', s.last_name) AS full_name
            FROM applications a 
            JOIN students s ON a.student_id = s.id 
            JOIN users u ON s.user_id = u.id
            WHERE a.id = %s
        """, (app_id,))
        student_data = cur.fetchone()

        if not student_data:
            return jsonify({"success": False, "error": "Application not found"}), 404

        # 2. منطق الحذف عند الرفض أو التحديث عند القبول
        if new_status == 'rejected':
            # حذف الطلب نهائياً من قاعدة البيانات
            cur.execute("DELETE FROM applications WHERE id = %s", (app_id,))
            message = "Application deleted successfully"
        else:
            # تحديث الحالة إلى مقبول (accepted)
            cur.execute("UPDATE applications SET status = 'accepted' WHERE id = %s", (app_id,))
            
            # إرسال إشعار للمسؤول (Admin) في حال القبول فقط
            uni = student_data['university']
            cur.execute("""
                SELECT id FROM users 
                WHERE role = 'admin' AND LOWER(TRIM(university)) = LOWER(TRIM(%s))
                LIMIT 1
            """, (uni,))
            admin = cur.fetchone()

            if admin:
                notif_msg = f"The student {student_data['full_name']} was accepted from {uni}."
                cur.execute("""
                    INSERT INTO notifications (user_id, title, message, is_read, created_at) 
                    VALUES (%s, %s, %s, 0, NOW())
                """, (admin['id'], "New Student Accepted", notif_msg))
            
            message = "Application accepted and notification sent"

        mysql.connection.commit()
        return jsonify({"success": True, "message": message})

    except Exception as e:
        mysql.connection.rollback()
        print(f"❌ Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
#---------------------------------------------------------------------
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@company_bp.route('/settings', methods=['GET', 'POST'])
def company_settings():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    mysql = get_db()
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        # ── 1. جلب بيانات النص من الفورم ──
        company_name = request.form.get('company_name')
        industry     = request.form.get('industry')
        email        = request.form.get('email')
        phone        = request.form.get('phone')
        # ملاحظة: حذفنا متغير location لأنه غير موجود بالجدول
        address      = request.form.get('address')
        description  = request.form.get('description')

        logo_filename = None 

        # ── 2. معالجة رفع الصورة ──
        logo_file = request.files.get('logo_file')
        if logo_file and logo_file.filename != '' and allowed_file(logo_file.filename):
            filename = secure_filename(logo_file.filename)
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'logos')
            os.makedirs(upload_folder, exist_ok=True)
            save_path = os.path.join(upload_folder, filename)
            logo_file.save(save_path)
            logo_filename = filename

        try:
            # ── 3. تحديث جدول companies (تم حذف location من هنا) ──
            if logo_filename:
                cur.execute("""
                    UPDATE companies 
                    SET company_name=%s, industry=%s, address=%s, 
                        description=%s, logo=%s
                    WHERE user_id=%s
                """, (company_name, industry, address, description, logo_filename, user_id))
            else:
                # بدون تغيير الصورة
                cur.execute("""
                    UPDATE companies 
                    SET company_name=%s, industry=%s, 
                        address=%s, description=%s
                    WHERE user_id=%s
                """, (company_name, industry, address, description, user_id))

            # ── 4. تحديث جدول users (email و phoneNumber) ──
            cur.execute("""
                UPDATE users 
                SET email=%s, phoneNumber=%s 
                WHERE id=%s
            """, (email, phone, user_id))

            mysql.connection.commit()
            flash('✅ Profile updated successfully!', 'success')

        except Exception as e:
            mysql.connection.rollback()
            print(f"❌ Error updating company settings: {e}")
            flash(f'❌ Error: {str(e)}', 'danger')
        finally:
            cur.close()

        return redirect(url_for('company.company_settings'))

    # ── GET: جلب البيانات وعرضها ──
    cur.execute("""
        SELECT c.*, u.email, u.phoneNumber 
        FROM companies c 
        JOIN users u ON c.user_id = u.id 
        WHERE u.id = %s
    """, [user_id])
    company_data = cur.fetchone()
    cur.close()

    return render_template('CompanyProfile.html', company=company_data)

#---------------------------------------------------------------------------------
@company_bp.route('/view_my_profile')
def view_company_profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    mysql = get_db()
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        cur.execute("SELECT c.*, u.email FROM companies c JOIN users u ON c.user_id = u.id WHERE u.id = %s", [user_id])
        company_data = cur.fetchone()
        if not company_data: return "Profile Not Found", 404
        c_id = company_data['id']

        # حل مشكلة Ambiguous column student_id بتحديد a.student_id
        cur.execute("""
            SELECT COUNT(DISTINCT a.student_id) as alumni_count 
            FROM applications a 
            JOIN internship_offers io ON a.offer_id = io.id 
            WHERE io.company_id = %s AND a.status = 'accepted'
        """, [c_id])
        alumni_count = cur.fetchone()['alumni_count']

        cur.execute("""
            SELECT COUNT(DISTINCT s.university) as uni_count 
            FROM students s 
            JOIN applications a ON s.id = a.student_id 
            JOIN internship_offers io ON a.offer_id = io.id 
            WHERE io.company_id = %s AND a.status = 'accepted'
        """, [c_id])
        uni_count = cur.fetchone()['uni_count']

        cur.execute("SELECT * FROM internship_offers WHERE company_id = %s", [c_id])
        offers = cur.fetchall()

        return render_template('CompanyAccount.html', 
                               company=company_data, 
                               internships=offers, 
                               alumni_count=alumni_count, 
                               uni_count=uni_count)
    finally:
        cur.close()