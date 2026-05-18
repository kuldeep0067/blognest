from app import app
from models import db, User

with app.app_context():
    user = User.query.filter_by(
        email="ky020902@gmail.com"
    ).first()

    if user:
        user.is_admin = True

        db.session.commit()

        print("Admin created successfully")

    else:
        print("User not found")