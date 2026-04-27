from flask import Blueprint, jsonify, session, redirect, url_for
import MySQLdb.cursors

student_bp = Blueprint('student', __name__)


# ── جلب الإشعارات ──────────────────────────────────────────────
@student_bp.route('/notifications')
def get_notifications():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    from app import mysql
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT title, message, created_at, is_read
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """, (session['user_id'],))

        notifications = cursor.fetchall()
        unread_count = sum(1 for n in notifications if not n['is_read'])

        notif_list = []
        for n in notifications:
            notif_list.append({
                'title': n['title'],
                'message': n['message'],
                'created_at': n['created_at'].strftime('%Y-%m-%d %H:%M') if n['created_at'] else '',
                'is_read': bool(n['is_read'])
            })

        return jsonify({
            'notifications': notif_list,
            'unread_count': unread_count
        })

    except Exception as e:
        print(f"Error fetching student notifications: {e}")
        return jsonify({'notifications': [], 'unread_count': 0})

    finally:
        cursor.close()


# ── تحديد الإشعارات كمقروءة ────────────────────────────────────
@student_bp.route('/mark-notifications-read', methods=['POST'])
def mark_notifications_read():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    from app import mysql
    cursor = mysql.connection.cursor()

    try:
        cursor.execute("""
            UPDATE notifications
            SET is_read = 1
            WHERE user_id = %s AND is_read = 0
        """, (session['user_id'],))
        mysql.connection.commit()
        return jsonify({'success': True})

    except Exception as e:
        print(f"Error marking notifications read: {e}")
        return jsonify({'error': str(e)}), 500

    finally:
        cursor.close()


# ── تحميل الشهادة ──────────────────────────────────────────────
@student_bp.route('/download-certificate/<int:app_id>')
def download_certificate(app_id):
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('login'))

    from app import mysql
    import os
    from flask import send_file, flash
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # نتأكد أن الطلب يخص هذا الطالب
        cursor.execute("SELECT id FROM students WHERE user_id = %s", (session['user_id'],))
        student = cursor.fetchone()

        if not student:
            flash("Student not found.", "danger")
            return redirect(url_for('my_applications'))

        cursor.execute("""
            SELECT agreement_pdf FROM applications
            WHERE id = %s AND student_id = %s AND status = 'validated'
        """, (app_id, student['id']))
        row = cursor.fetchone()

        if not row or not row['agreement_pdf']:
            flash("Certificate not found.", "danger")
            return redirect(url_for('my_applications'))

        file_path = os.path.join("static", "certificates", row['agreement_pdf'])

        if not os.path.exists(file_path):
            flash("Certificate file missing on server.", "danger")
            return redirect(url_for('my_applications'))

        return send_file(file_path, as_attachment=True, download_name=row['agreement_pdf'])

    except Exception as e:
        print(f"Error downloading certificate: {e}")
        flash("Error downloading certificate.", "danger")
        return redirect(url_for('my_applications'))

    finally:
        cursor.close()