from app import app, mysql
from werkzeug.security import generate_password_hash

def add_uni_admin(uni_slug, password_suffix):
    with app.app_context():
        cursor = mysql.connection.cursor()
        email = f"{uni_slug}-uni@gmail.com".lower()
        full_password = f"1A2{password_suffix}"
        hashed_pw = generate_password_hash(full_password)
        
        cursor.execute("INSERT INTO users (email, password, role, university) VALUES (%s, %s, %s, %s)",
                       (email, hashed_pw, 'admin', uni_slug))
        mysql.connection.commit()
        print(f"✅ Created Admin for: {uni_slug}")

if __name__ == "__main__":
    # أمثلة:
    add_uni_admin("constantine2", "pass2026")
    add_uni_admin("alger", "uniAdmin")