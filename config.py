from flask_mysqldb import MySQL
mysql = MySQL()
def init_app(app):

     app.config['MYSQL_HOST'] = 'localhost'
     app.config['MYSQL_USER'] = 'root'
     app.config['MYSQL_PASSWORD'] = ''
     app.config['MYSQL_DB'] = 'internship_platform'
     
     mysql.init_app(app)
     
