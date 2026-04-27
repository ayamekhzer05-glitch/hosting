from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, send_file
import os
import pdfkit
import shutil 
import MySQLdb.cursors
from datetime import date


#--------------------------------------agreement PDF----------------------------------------
wkhtml_path = shutil.which("wkhtmltopdf")

if not wkhtml_path:
    wkhtml_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

if wkhtml_path and os.path.exists(wkhtml_path):
    config = pdfkit.configuration(wkhtmltopdf=wkhtml_path)
else:
   
    if shutil.which("wkhtmltopdf"):
        config = pdfkit.configuration(wkhtmltopdf=shutil.which("wkhtmltopdf"))
    else:
        config = None
        print("⚠️ Warning: wkhtmltopdf not found. PDF generation might fail.")

admin_bp = Blueprint('admin', __name__)

#---------------certificate--------------------------------------------------
def generate_certificate(data):
    
    html = render_template("certificate.html", **data)
    file_name = f"cert_{data['student_name'].replace(' ', '_')}.pdf"
    if not os.path.exists("static/certificates"):
        os.makedirs("static/certificates")
        
    file_path = os.path.join("static/certificates", file_name)
    pdfkit.from_string(html, file_path, configuration=config)
    return file_path
#---------------------------------dashboard--------------------------------------------
@admin_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('user_type') != 'admin':
        return redirect(url_for('login'))
    
    from app import mysql
    mysql.connection.commit()
    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. جلب جامعة الأدمن الحالية (مهم جداً لفلترة البيانات)
    cursor.execute("""
        SELECT university 
        FROM students 
        WHERE user_id = %s
    """, (user_id,))
    admin_info = cursor.fetchone()
    current_uni = admin_info['university'] if admin_info else session.get('university')

    # --- بداية حساب إحصائيات الـ Bento Grid ---

    # أ. إجمالي الطلبة في جامعة الأدمن
    cursor.execute("SELECT COUNT(*) as total FROM students WHERE university = %s", (current_uni,))
    total_students = cursor.fetchone()['total']

    # ب. إجمالي الشركات المسجلة في النظام (عام)
    cursor.execute("SELECT COUNT(*) as total FROM companies")
    total_companies = cursor.fetchone()['total']

    # ج. الطلبات المنتظرة (Pending) لطلاب هذه الجامعة فقط
    cursor.execute("""
        SELECT COUNT(*) as total 
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE s.university = %s AND TRIM(LOWER(a.status)) = 'pending'
    """, (current_uni,))
    pending_count = cursor.fetchone()['total']

    # د. جلب بيانات التعيينات المقبولة (للمنحنى وللبطاقة الرابعة)
    cursor.execute("""
        SELECT a.applied_at
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE s.university = %s
        AND TRIM(LOWER(a.status)) IN ('accepted', 'validated')
        ORDER BY a.applied_at ASC
    """, (current_uni,))
    results = cursor.fetchall()
    placements_count = len(results) # هذا هو رقم البطاقة الرابعة

    # --- إعداد بيانات المنحنى البياني ---
    chart_labels = ["Start"]
    chart_data = [0]
    for index, _ in enumerate(results, start=1):
        chart_labels.append(f"P{index}")
        chart_data.append(index)

    if not results:
        chart_labels.append("No Data")
        chart_data.append(0)

    # --- جلب بقية أجزاء لوحة التحكم ---

    # 2. الإشعارات غير المقروءة
    cursor.execute("""
        SELECT title, message, created_at 
        FROM notifications 
        WHERE user_id = %s AND is_read = 0 
        ORDER BY created_at DESC
    """, (user_id,))
    notifs = cursor.fetchall()

    # 3. أفضل الشركاء (Top Partners)
    cursor.execute("""
        SELECT c.company_name, COUNT(*) as accepted_count
        FROM applications a
        JOIN students s ON a.student_id = s.id
        JOIN internship_offers i ON a.offer_id = i.id
        JOIN companies c ON i.company_id = c.id
        WHERE s.university = %s
        AND TRIM(LOWER(a.status)) IN ('accepted', 'validated')
        GROUP BY c.id, c.company_name
        ORDER BY accepted_count DESC
        LIMIT 5
    """, (current_uni,))
    top_partners = cursor.fetchall()

    # 4. المواهب الأكثر نشاطاً (Most Active Talents)
    cursor.execute("""
        SELECT s.first_name, s.last_name, s.field_of_study, COUNT(*) as accepted_count
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE s.university = %s
        AND TRIM(LOWER(a.status)) IN ('accepted', 'validated')
        GROUP BY s.id, s.first_name, s.last_name, s.field_of_study
        ORDER BY accepted_count DESC
        LIMIT 5
    """, (current_uni,))
    top_talents = cursor.fetchall()

    # 5. جلب ملاحظات الأدمن (Priority Checklist)
    cursor.execute("""
        SELECT id, task_text, is_completed 
        FROM admin_todos 
        WHERE user_id = %s 
        ORDER BY created_at DESC
    """, (user_id,))
    todos = cursor.fetchall()

    # جلب المهارات الأكثر طلباً (Hot Skills) بناءً على عروض التربص
    cursor.execute("""
        SELECT s.name, COUNT(os.skill_id) as demand_count
        FROM offer_skills os
        JOIN skills s ON os.skill_id = s.id
        GROUP BY s.id, s.name
        ORDER BY demand_count DESC
        LIMIT 6
    """)
    hot_skills = cursor.fetchall()

    cursor.close()

    # إرسال كل البيانات لملف الـ HTML
    return render_template(
        'AdminDashboard.html',
        students_count=total_students,   # البطاقة 1
        companies_count=total_companies, # البطاقة 2
        pending_count=pending_count,     # البطاقة 3
        placements_count=placements_count, # البطاقة 4
        chart_labels=chart_labels,
        chart_data=chart_data,
        notifications=notifs,
        unread_count=len(notifs),
        top_partners=top_partners,
        top_talents=top_talents,
        todos=todos,
        hot_skills=hot_skills
    )
#------------ statistics ---------------------------------
@admin_bp.route('/statistics')
def statistics():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    from app import mysql
    import MySQLdb.cursors
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        cursor.execute("SELECT university FROM users WHERE id = %s", (session['user_id'],))
        admin_row = cursor.fetchone()
        
        if not admin_row or not admin_row['university']:
            return "خطأ: الآدمن الحالي ليس لديه جامعة مسجلة في جدول users", 400
            
        admin_uni = admin_row['university']

        cursor.execute("SELECT COUNT(*) as total FROM students WHERE university = %s", (admin_uni,))
        total_students = cursor.fetchone()['total'] or 0
        
        cursor.execute("SELECT COUNT(*) as total FROM companies")
        total_companies = cursor.fetchone()['total'] or 0
        
        # 1. حساب عدد الطلاب الفريدين المقبولين
        cursor.execute("""
            SELECT COUNT(DISTINCT a.student_id) as total 
            FROM applications a 
            JOIN students s ON a.student_id = s.id 
            WHERE s.university = %s AND a.status IN ('accepted', 'validated', 'approved')
        """, (admin_uni,))
        students_with_internships = cursor.fetchone()['total'] or 0

        # --- السطر المهم الذي يجب إضافته لحل الخطأ ---
        completed_internships = students_with_internships 
        # --------------------------------------------

        # 2. حساب النسبة المئوية بشكل منطقي
        placement_rate = 0
        if total_students > 0:
            placement_rate = round((students_with_internships / total_students) * 100)
            
            # ضمان عدم تجاوز 100%
            if placement_rate > 100:
                placement_rate = 100
        cursor.execute("""
            SELECT location, COUNT(*) as total 
            FROM internship_offers 
            WHERE location IS NOT NULL AND location != ''
            GROUP BY location LIMIT 5
        """)
        wilaya_data = cursor.fetchall()
        w_labels = [str(r['location']) for r in wilaya_data] if wilaya_data else ["No Data"]
        w_counts = [int(r['total']) for r in wilaya_data] if wilaya_data else [0]

        cursor.execute("""
            SELECT industry, COUNT(*) as total 
            FROM companies 
            WHERE industry IS NOT NULL AND industry != ''
            GROUP BY industry LIMIT 5
        """)
        field_data = cursor.fetchall()
        f_labels = [str(r['industry']) for r in field_data] if field_data else ["General"]
        f_counts = [int(r['total']) for r in field_data] if field_data else [total_companies]


        target = (total_students or 0) // 2
        recommended_partners = max(0, target - (total_companies or 0) + 5)
        top_field = f_labels[0] if f_labels and f_labels[0] != "General" else "علوم الحاسوب"
        # استعلام لجلب عدد الطلاب الجدد حسب الأسبوع
        cursor.execute("""
            SELECT 
                CONCAT('Week ', WEEK(created_at) - WEEK(DATE_SUB(created_at, INTERVAL DAYOFMONTH(created_at)-1 DAY)) + 1) as week_label,
                COUNT(id) as count
            FROM students 
            WHERE university = %s 
              AND created_at >= DATE_SUB(NOW(), INTERVAL 1 MONTH) -- جلب بيانات آخر شهر فقط
            GROUP BY WEEK(created_at)
            ORDER BY created_at ASC
        """, (admin_uni,))
        
        week_results = cursor.fetchall()
        
        # تحويل النتائج إلى قوائم
        trend_labels = [r['week_label'] for r in week_results]
        trend_data = [r['count'] for r in week_results]

        # إذا كانت البيانات قليلة جداً، نضمن وجود نقاط للرسم
        if len(trend_labels) < 2:
            trend_labels = ["Week 1", "Week 2", "Week 3", "Week 4"]
            # نضع البيانات الحقيقية في الأسبوع الأخير والباقي أصفار للعرض
            current_count = total_students 
            trend_data = [0, 0, 0, current_count]

        return render_template('AdminStatistics.html', 
                               total_students=total_students,
                               total_companies=total_companies,
                               completed_internships=completed_internships,
                               placement_rate=placement_rate,
                               wilaya_labels=w_labels,
                               wilaya_counts=w_counts,
                               field_labels=f_labels,
                               field_counts=f_counts,
                               recommended_partners=recommended_partners, # أضف هذا
                               top_field=top_field,
                               trend_labels=trend_labels, 
                               trend_data=trend_data)

    except Exception as e:
        print(f"CRITICAL DATABASE ERROR: {e}")
        import traceback
        traceback.print_exc() 
        return f"Database Error: {e}", 500
    finally:
        cursor.close()
#--------------aprove applications-----------------------------------------------------------------------------
#------------------ aprove applications ------------------
@admin_bp.route('/approve/<int:app_id>')
def approve_application(app_id):
    if 'user_id' not in session or session.get('user_type') != 'admin':
        return redirect(url_for('login'))

    from app import mysql
    import MySQLdb.cursors 
    import os 
    
    current_uni = session.get('university') 
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # التعديل 1: إضافة u_student.id لتمكين إرسال إشعار للطالب
    cursor.execute("""
        SELECT 
            a.id, s.first_name, s.last_name, c.company_name, i.title, i.duration, 
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
        flash("Application not found!", "danger")
        return redirect(url_for('admin.dashboard'))

    if data['student_uni'] != current_uni:
        flash("Unauthorized: This student belongs to another university!", "danger")
        return redirect(url_for('admin.dashboard'))

    cursor.execute("UPDATE applications SET status = 'validated', updated_at = NOW() WHERE id = %s", (app_id,))
    
    # إشعار الشركة
    notif_msg = f"لقد قام آدمن جامعة {current_uni} بالموافقة على تربص {data['first_name']} {data['last_name']}. الاتفاقية جاهزة الآن."
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, is_read, created_at)
        VALUES (%s, 'تم تصديق الاتفاقية', %s, 0, NOW())
    """, (data['company_user_id'], notif_msg))

    # التعديل 2: إضافة إرسال إشعار للطالب
    student_notif_msg = f"تهانينا! لقد وافقت الجامعة على تربصك في {data['company_name']}. يمكنك الآن تحميل اتفاقية التربص الخاصة بك."
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, is_read, created_at)
        VALUES (%s, 'تم تصديق الاتفاقية النهائية', %s, 0, NOW())
    """, (data['student_user_id'], student_notif_msg))

    from datetime import date
    today = date.today().strftime('%d/%m/%Y')

    certificate_data = {
        "student_name": f"{data['first_name']} {data['last_name']}",
        "company_name": data['company_name'],
        "position": data['title'],
        "duration": data['duration'],
        "university_name": current_uni, 
        "date_valid": today 
    }
    
    certificate_path = generate_certificate(certificate_data)
    file_name_only = os.path.basename(certificate_path) 

    cursor.execute("UPDATE applications SET agreement_pdf = %s WHERE id = %s", (file_name_only, app_id))    
    mysql.connection.commit()
    cursor.close()
    
    flash("Success! The agreement has been validated and sent to the company.", "success")
    
    return send_file(
        certificate_path, 
        as_attachment=True, 
        download_name=f"Agreement_{data['first_name']}_{data['last_name']}.pdf"
    )
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