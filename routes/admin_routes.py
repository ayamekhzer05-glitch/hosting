from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, send_file
import os
import MySQLdb.cursors
from datetime import date

# 👉 NEW PDF LIB (Render friendly)
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

admin_bp = Blueprint('admin', __name__)

#---------------------- CERTIFICATE PDF ----------------------

def generate_certificate(data):

    file_name = f"cert_{data['student_name'].replace(' ', '_')}.pdf"

    if not os.path.exists("static/certificates"):
        os.makedirs("static/certificates")

    file_path = os.path.join("static/certificates", file_name)

    c = canvas.Canvas(file_path, pagesize=letter)

    c.setFont("Helvetica", 12)

    c.drawString(100, 750, f"Student: {data['student_name']}")
    c.drawString(100, 720, f"Company: {data['company_name']}")
    c.drawString(100, 690, f"Position: {data['position']}")
    c.drawString(100, 660, f"Duration: {data['duration']}")
    c.drawString(100, 630, f"University: {data['university_name']}")
    c.drawString(100, 600, f"Date: {data['date_valid']}")

    c.save()

    return file_path


#--------------------------------- DASHBOARD --------------------------------------------

@admin_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('user_type') != 'admin':
        return redirect(url_for('login'))

    from app import mysql
    mysql.connection.commit()

    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT university FROM students WHERE user_id = %s", (user_id,))
    admin_info = cursor.fetchone()
    current_uni = admin_info['university'] if admin_info else session.get('university')

    cursor.execute("SELECT COUNT(*) as total FROM students WHERE university = %s", (current_uni,))
    total_students = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) as total FROM companies")
    total_companies = cursor.fetchone()['total']

    cursor.execute("""
        SELECT COUNT(*) as total 
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE s.university = %s AND TRIM(LOWER(a.status)) = 'pending'
    """, (current_uni,))
    pending_count = cursor.fetchone()['total']

    cursor.execute("""
        SELECT a.applied_at
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE s.university = %s
        AND TRIM(LOWER(a.status)) IN ('accepted', 'validated')
    """, (current_uni,))
    results = cursor.fetchall()

    placements_count = len(results)

    chart_labels = ["Start"]
    chart_data = [0]

    for i, _ in enumerate(results, start=1):
        chart_labels.append(f"P{i}")
        chart_data.append(i)

    cursor.close()

    return render_template(
        'AdminDashboard.html',
        students_count=total_students,
        companies_count=total_companies,
        pending_count=pending_count,
        placements_count=placements_count,
        chart_labels=chart_labels,
        chart_data=chart_data
    )


#---------------------- APPROVE APPLICATION ----------------------

@admin_bp.route('/approve/<int:app_id>')
def approve_application(app_id):

    if 'user_id' not in session or session.get('user_type') != 'admin':
        return redirect(url_for('login'))

    from app import mysql
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT 
            a.id, s.first_name, s.last_name,
            c.company_name, i.title, i.duration,
            u_company.id as company_user_id,
            u_student.id as student_user_id,
            u_student.university as student_uni
        FROM applications a
        JOIN students s ON a.student_id = s.id
        JOIN users u_student ON s.user_id = u_student.id
        JOIN internship_offers i ON a.offer_id = i.id
        JOIN companies c ON i.company_id = c.id
        JOIN users u_company ON c.user_id = u_company.id
        WHERE a.id = %s
    """, (app_id,))

    data = cursor.fetchone()

    if not data:
        return redirect(url_for('admin.dashboard'))

    cursor.execute("UPDATE applications SET status='validated' WHERE id=%s", (app_id,))

    today = date.today().strftime('%d/%m/%Y')

    certificate_data = {
        "student_name": f"{data['first_name']} {data['last_name']}",
        "company_name": data['company_name'],
        "position": data['title'],
        "duration": data['duration'],
        "university_name": data['student_uni'],
        "date_valid": today
    }

    certificate_path = generate_certificate(certificate_data)

    cursor.execute("""
        UPDATE applications SET agreement_pdf=%s WHERE id=%s
    """, (os.path.basename(certificate_path), app_id))

    mysql.connection.commit()
    cursor.close()

    return send_file(certificate_path, as_attachment=True)


#---------------- OTHER ROUTES (unchanged logic) ----------------
# (applications / reject / statistics / notifications / etc remain same)

#-------------------------------mark_read notify--------------------------------------------------------
@admin_bp.route('/mark_notifications_read')
def mark_read():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    from app import mysql
    cursor = mysql.connection.cursor()
    
    cursor.execute("""
        UPDATE notifications 
        SET is_read = 1 
        WHERE user_id = %s AND is_read = 0
    """, (session['user_id'],))
    
    affected_rows = cursor.rowcount
    mysql.connection.commit()
    cursor.close()
    
    print(f"✅ تم تحديث {affected_rows} إشعار كمقروء")  
    
    return redirect(url_for('admin.dashboard'))

#--------------------------------------------get_notifications------------------------------------------------------------

@admin_bp.route('/get_notifications')
def get_notifications():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from app import mysql
    # أضفنا MySQLdb.cursors.DictCursor هنا لنضمن أننا سنستخدم الأسماء وليس الأرقام
    import MySQLdb.cursors
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        cursor.execute("""
            SELECT title, message, created_at 
            FROM notifications 
            WHERE user_id = %s AND is_read = 0 
            ORDER BY created_at DESC
        """, (session['user_id'],))
        
        notifications = cursor.fetchall() 
        unread_count = len(notifications)
        
        notif_list = []
        for n in notifications:
            # التغيير الجذري هنا: استخدمنا الأسماء 'title' بدلاً من [0]
            notif_list.append({
                'title': n['title'],
                'message': n['message'],
                'created_at': n['created_at'].strftime('%Y-%m-%d %H:%M') if n['created_at'] else ''
            })
        
        return jsonify({
            'notifications': notif_list,
            'unread_count': unread_count
        })

    except Exception as e:
        print(f"Error fetching notifications: {str(e)}")
        return jsonify({'notifications': [], 'unread_count': 0})
        
    finally:
        cursor.close()
#---------------------------------------------reject_application------------------------------------------------------------

@admin_bp.route('/reject_application/<int:app_id>')
def reject_application(app_id):
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    from app import mysql
    import MySQLdb.cursors
    # نستخدم DictCursor لضمان الحصول على البيانات بأسماء الأعمدة وتجنب KeyError
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        # 1. جلب بيانات الشركة والطالب لإرسال الإشعار
        cursor.execute("""
            SELECT u.id as company_user_id, s.first_name, i.title
            FROM applications a
            JOIN internship_offers i ON a.offer_id = i.id
            JOIN companies c ON i.company_id = c.id
            JOIN users u ON c.user_id = u.id 
            JOIN students s ON a.student_id = s.id
            WHERE a.id = %s
        """, (app_id,))
        
        data = cursor.fetchone()
        
        if data:
            # الوصول للبيانات بأسماء الأعمدة لأننا استخدمنا DictCursor
            target_company_user_id = data['company_user_id']
            student_name = data['first_name']
            offer_title = data['title']

            # 2. تحديث حالة الطلب إلى مرفوض (يختفي من قائمة الـ accepted)
            cursor.execute("UPDATE applications SET status = 'rejected' WHERE id = %s", (app_id,))

            # 3. إرسال إشعار للشركة بالرفض
            notif_msg = f"قام الآدمن برفض طلب الطالب {student_name} بخصوص عرض: {offer_title}"
            cursor.execute("""
                INSERT INTO notifications (user_id, title, message, is_read, created_at)
                VALUES (%s, 'طلب مرفوض من الآدمن', %s, 0, NOW())
            """, (target_company_user_id, notif_msg))

            mysql.connection.commit()
            flash(f"تم رفض طلب {student_name} بنجاح وإعلام الشركة.", "success")
        else:
            flash("لم يتم العثور على الطلب.", "danger")

    except Exception as e:
        print(f"Error in rejection: {e}")
        mysql.connection.rollback()
        flash("حدث خطأ أثناء معالجة الرفض.", "danger")
        
    finally:
        cursor.close()
    
    # العودة لصفحة الطلبات (سيختفي الطالب منها لأن الاستعلام هناك يجلب 'accepted' فقط)
    return redirect(url_for('admin.applications'))
#----------------------------------------------applications--------------------------------------------------
@admin_bp.route('/applications')
def applications():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    from app import mysql
    import MySQLdb.cursors 
    from datetime import date
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    admin_university_slug = session.get('university') 
    today = date.today()

    # 1. استعلام الكروت: يعرض فقط الطلبات التي حالتها 'validated'
    # بمجرد ضغط زر القبول وتغير الحالة لـ 'accepted'، سيختفي الطالب من هنا تلقائياً
    query_list = """
    SELECT 
        a.id, 
        a.student_id,
        CONCAT(s.first_name, ' ', s.last_name) AS student_full_name, 
        c.company_name, 
        i.duration, 
        i.title AS position, 
        a.applied_at
    FROM applications a
    JOIN students s ON a.student_id = s.id
    JOIN users u ON s.user_id = u.id
    JOIN internship_offers i ON a.offer_id = i.id
    JOIN companies c ON i.company_id = c.id
    WHERE a.status = 'accepted' 
    AND LOWER(TRIM(u.university)) = LOWER(TRIM(%s))
    ORDER BY a.applied_at DESC
    """
    cursor.execute(query_list, (admin_university_slug,))
    all_requests = cursor.fetchall()

    # 2. استعلام الإحصائيات: يحسب المقبولين والمرفوضين بناءً على updated_at
    stats_query = """
    SELECT 
        COUNT(*) as total_history,
        COUNT(CASE WHEN a.status IN ('accepted', 'approved') AND DATE(a.updated_at) = %s THEN 1 END) as approved_today,
        COUNT(CASE WHEN a.status = 'rejected' AND DATE(a.updated_at) = %s THEN 1 END) as rejected_today
    FROM applications a
    JOIN students s ON a.student_id = s.id
    JOIN users u ON s.user_id = u.id
    WHERE LOWER(TRIM(u.university)) = LOWER(TRIM(%s))
    """
    cursor.execute(stats_query, (today, today, admin_university_slug))
    stats = cursor.fetchone()

    cursor.close()

    return render_template('AdminApplications.html', 
                           requests=all_requests, 
                           total=stats['total_history'], 
                           pending=len(all_requests), 
                           approved=stats['approved_today'], 
                           rejected=stats['rejected_today'])
#-----------------------------------------------validations--------------------------------------------------------
@admin_bp.route('/validations')
def validations():
    if 'user_id' not in session or session.get('user_type') != 'admin':
        return redirect(url_for('login'))
    
    from app import mysql
    import MySQLdb.cursors
    
    current_uni = session.get('university') 
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # الحل: نطلب من القاعدة عرض كل ما هو مقبول من الشركة أو موثق من الإدارة
    # مع التأكد من جلب عمود الـ agreement_pdf
    query = """
    SELECT 
        a.id, 
        CONCAT(s.first_name, ' ', s.last_name) AS student_name, 
        c.company_name, 
        i.duration, 
        i.created_at AS start_date,
        i.title AS position, 
        a.agreement_pdf,
        a.status -- أضفنا الحالة لنعرف في أي مرحلة هو
    FROM applications a
    JOIN students s ON a.student_id = s.id
    JOIN users u ON s.user_id = u.id 
    JOIN internship_offers i ON a.offer_id = i.id
    JOIN companies c ON i.company_id = c.id
    WHERE a.status IN ('accepted', 'approved', 'validated') 
      AND u.university = %s 
    ORDER BY a.applied_at DESC
    """
    
    cursor.execute(query, (current_uni,))
    validated_requests = cursor.fetchall()
    cursor.close()

    return render_template('adminvalidations.html', requests=validated_requests)
#--------------------------------------------------------------------------------------------------
@admin_bp.route('/add_todo', methods=['POST'])
def add_todo():
    if 'user_id' not in session: return jsonify({'status': 'error'}), 403
    
    from app import mysql
    data = request.get_json()
    task = data.get('task')
    user_id = session['user_id']
    
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO admin_todos (user_id, task_text) VALUES (%s, %s)", (user_id, task))
    mysql.connection.commit()
    new_id = cursor.lastrowid
    cursor.close()
    return jsonify({'status': 'success', 'id': new_id})

#-----------------------------------------------------------------------------------------------------------------------
@admin_bp.route('/delete_todo/<int:todo_id>', methods=['POST'])
def delete_todo(todo_id):
    if 'user_id' not in session: return jsonify({'status': 'error'}), 403
    
    from app import mysql
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM admin_todos WHERE id = %s AND user_id = %s", (todo_id, session['user_id']))
    mysql.connection.commit()
    cursor.close()
    return jsonify({'status': 'success'})
    
#------------------------------------------------------------------------------------------------------------------------
@admin_bp.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify([])

    from app import mysql
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # البحث في الطلاب والمهارات المرتبطة بهم
    search_query = f"%{query}%"
    cursor.execute("""
        SELECT DISTINCT s.id, s.first_name, s.last_name, s.field_of_study, 'student' as type
        FROM students s
        LEFT JOIN student_skills ss ON s.id = ss.student_id
        LEFT JOIN skills sk ON ss.skill_id = sk.id
        WHERE s.first_name LIKE %s OR s.last_name LIKE %s 
        OR s.field_of_study LIKE %s OR sk.name LIKE %s
        LIMIT 5
    """, (search_query, search_query, search_query, search_query))
    
    results = cursor.fetchall()
    cursor.close()
    return jsonify(results)
