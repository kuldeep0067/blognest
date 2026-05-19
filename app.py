from flask_cors import CORS
from datetime import datetime
import re
import os
import secrets
from dotenv import load_dotenv
import google.generativeai as genai
from PIL import Image
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)

from urllib.parse import quote_plus
from flask_socketio import SocketIO, emit

load_dotenv()

app = Flask(__name__)



genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

gemini_model = genai.GenerativeModel("gemini-2.0-flash")

socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
jwt = JWTManager(app)

database_url = os.getenv("DATABASE_URL")

if database_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )
else:
    db_user = os.getenv("DB_USER")
    db_password = quote_plus(os.getenv("DB_PASSWORD"))
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )
    
    
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "static/uploads"

from models import db, login_manager, User, Post, Comment, Like, Bookmark, Follow, Notification,Message

db.init_app(app)

migrate = Migrate(app, db)

login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"



from forms import RegisterForm, LoginForm, PostForm, CommentForm, ProfileForm, ForgotPasswordForm, ResetPasswordForm



def make_slug(title):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    original_slug = slug
    counter = 1

    while Post.query.filter_by(slug=slug).first():
        slug = f"{original_slug}-{counter}"
        counter += 1

    return slug

def calculate_reading_time(content):
    clean_text = re.sub("<.*?>", "", content)
    words = clean_text.split()
    minutes = max(1, round(len(words) / 200))
    
    return minutes

def save_blog_image(image):
    random_hex = secrets.token_hex(8)
    _, file_ext = os.path.splitext(image.filename)
    image_filename = random_hex + file_ext

    image_path = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"], image_filename)

    resized_image = Image.open(image)
    resized_image.thumbnail((900, 500))
    resized_image.save(image_path)

    return image_filename

def save_profile_image(image):
    random_hex = secrets.token_hex(8)
    _, file_ext = os.path.splitext(image.filename)
    image_filename = random_hex + file_ext

    image_path = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"], image_filename)

    resized_image = Image.open(image)
    resized_image.thumbnail((600, 600))
    resized_image.save(image_path)

    return image_filename

def generate_verification_token(email):
    return serializer.dumps(
        email,
        salt="email-verification"
    )

@app.context_processor
def inject_now():
    return {"now": datetime.utcnow()}

@app.context_processor
def inject_notifications():

    if current_user.is_authenticated:

        unread_count = Notification.query.filter_by(
            user_id=current_user.id,
            is_read=False
        ).count()

    else:
        unread_count = 0

    return {"unread_count": unread_count}


@app.route("/")
def home():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "", type=str)
    category = request.args.get("category", "", type=str)
    query = Post.query.filter_by(status="Published").order_by(Post.created_at.desc())

    if search:
        query = query.filter(
            Post.title.ilike(f"%{search}%") |
            Post.summary.ilike(f"%{search}%") |
            Post.content.ilike(f"%{search}%") |
            Post.tags.ilike(f"%{search}%")
        )
       
    if category:
        query = query.filter(Post.category.ilike(category))    

    posts = query.paginate(page=page, per_page=6)
    latest_posts = Post.query.filter_by(status="Published").order_by(Post.created_at.desc()).limit(3).all()
    categories = db.session.query(Post.category).distinct().all()
    categories = [cat[0] for cat in categories]
    
    return render_template(
        "home.html",
        posts=posts,
        latest_posts=latest_posts,
        categories=categories,
        search=search,
        active_category=category
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = RegisterForm()

    if form.validate_on_submit():
        existing_user = User.query.filter(
            (User.email == form.email.data) |
            (User.username == form.username.data)
        ).first()

        if existing_user:
            flash("Username or email already exists.", "danger")
            return redirect(url_for("register"))

        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)

        db.session.add(user)
        db.session.commit()
        
        token = generate_verification_token(user.email)

        verification_link = url_for(
            "verify_email",
            token=token,
             _external=True
        )

        print("\nVERIFY EMAIL LINK:")
        print(verification_link)
        print()

        flash("Account created. Verify your email from terminal link.", "info")
        return redirect(url_for("login"))

    return render_template("register.html", form=form)

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()

    existing_user = User.query.filter_by(email=data["email"]).first()

    if existing_user:
        return {
            "success": False,
            "message": "Email already exists."
        }, 400

    user = User(
        username=data["username"],
        email=data["email"],
        is_verified=True
    )

    user.set_password(data["password"])

    db.session.add(user)
    db.session.commit()

    return {
        "success": True,
        "message": "User registered successfully."
    }

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()

    user = User.query.filter_by(email=data["email"]).first()

    if not user or not user.check_password(data["password"]):
        return {
            "success": False,
            "message": "Invalid credentials."
        }, 401

    access_token = create_access_token(identity=str(user.id))

    return {
        "success": True,
        "token": access_token,
        "username": user.username,
        "is_admin": user.is_admin
    }

@app.route("/api/ai/generate-title", methods=["POST"])
@jwt_required()
def api_generate_title():
    data = request.get_json()

    topic = data.get("topic", "")

    if not topic:
        return {
            "success": False,
            "message": "Topic is required."
        }, 400

    prompt = f"""
    Generate 5 catchy blog titles about:
    {topic}

    Keep them modern, engaging, and short.
    """

    try:
        response = gemini_model.generate_content(prompt)

        return {
           "success": True,
           "titles": response.text
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }, 500 
    
    
@app.route("/api/posts")
def api_posts():
    search = request.args.get("search", "")
    category = request.args.get("category", "")
    page = request.args.get("page", 1, type=int)

    query = Post.query.filter_by(status="Published")

    if search:
        query = query.filter(
            Post.title.ilike(f"%{search}%") |
            Post.summary.ilike(f"%{search}%") |
            Post.content.ilike(f"%{search}%") |
            Post.tags.ilike(f"%{search}%")
        )
        
    if category:
        query = query.filter(Post.category.ilike(category))

    posts = query.order_by(Post.created_at.desc()).paginate(
        page=page,
        per_page=6
    )

    posts_data = []

    for post in posts.items:
        posts_data.append({
            "id": post.id,
            "title": post.title,
            "summary": post.summary,
            "category": post.category,
            "image_file": post.image_file,
            "image_url": f"http://127.0.0.1:5000/static/uploads/{post.image_file}" if post.image_file else None,
            "author": post.author.username,
            "views": post.views,
            "likes": len(post.likes),
            "comments": len(post.comments),
            "reading_time": calculate_reading_time(post.content),
            "created_at": post.created_at.strftime("%d %b %Y")
        })

    return {
        "success": True,
        "posts": posts_data,
        "has_next": posts.has_next
    }
    
    

@app.route("/api/posts/<int:post_id>")
def api_single_post(post_id):
    post = Post.query.get_or_404(post_id)

    return {
        "success": True,
        "post": {
            "id": post.id,
            "title": post.title,
            "summary": post.summary,
            "content": post.content,
            "category": post.category,
            "image_file": post.image_file,
            "image_url": f"http://127.0.0.1:5000/static/uploads/{post.image_file}" if post.image_file else None,
            "tags": post.tags,
            "author": post.author.username,
            "views": post.views,
            "likes": len(post.likes),
            "comments": len(post.comments),
            "reading_time": calculate_reading_time(post.content),
            "created_at": post.created_at.strftime("%d %b %Y")
        }
    }

@app.route("/api/posts/<int:post_id>/comments", methods=["GET", "POST"])
@jwt_required(optional=True)
def api_post_comments(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == "POST":
        user_id = get_jwt_identity()

        if not user_id:
            return {
                "success": False,
                "message": "Login required."
            }, 401

        data = request.get_json()

        comment = Comment(
            content=data["content"],
            user_id=user_id,
            post_id=post.id
        )

        db.session.add(comment)
        
        comment_user = User.query.get(int(user_id))

        if post.author.id != int(user_id):
            notification = Notification(
                 message=f"{comment_user.username} commented on your post: {post.title}",
                 user_id=post.author.id
            )
            db.session.add(notification)
        db.session.commit()

        return {
            "success": True,
            "message": "Comment added successfully."
        }

    comments = Comment.query.filter_by(
        post_id=post.id,
        parent_id=None
    ).order_by(Comment.created_at.desc()).all()

    comments_data = []

    for comment in comments:
        comments_data.append({
            "id": comment.id,
            "content": comment.content,
            "author": comment.comment_author.username,
            "created_at": comment.created_at.strftime("%d %b %Y, %I:%M %p")
        })

    return {
        "success": True,
        "comments": comments_data
    }


@app.route("/api/posts/<int:post_id>/like", methods=["POST"])
@jwt_required()
def api_like_post(post_id):
    user_id = int(get_jwt_identity())
    post = Post.query.get_or_404(post_id)

    existing_like = Like.query.filter_by(
        user_id=user_id,
        post_id=post.id
    ).first()

    if existing_like:
        db.session.delete(existing_like)
        liked = False
        message = "Like removed."
    else:
        like = Like(user_id=user_id, post_id=post.id)
        db.session.add(like)

        liker = User.query.get(int(user_id))

        if post.author.id != int(user_id):
            notification = Notification(
               message=f"{liker.username} liked your post: {post.title}",
               user_id=post.author.id
            )
            db.session.add(notification)

        liked = True
        message = "Post liked."
    
    db.session.commit()
    
    return {
        "success": True,
        "liked": liked,
        "likes": len(post.likes),
        "message": message
    }


@app.route("/api/posts/<int:post_id>/bookmark", methods=["POST"])
@jwt_required()
def api_bookmark_post(post_id):
    user_id = int(get_jwt_identity())

    post = Post.query.get_or_404(post_id)

    existing_bookmark = Bookmark.query.filter_by(
        user_id=user_id,
        post_id=post.id
    ).first()

    if existing_bookmark:
        db.session.delete(existing_bookmark)
        bookmarked = False
        message = "Bookmark removed."
    else:
        bookmark = Bookmark(
            user_id=user_id,
            post_id=post.id
        )
        db.session.add(bookmark)
        bookmarked = True
        message = "Post saved."

    db.session.commit()

    return {
        "success": True,
        "bookmarked": bookmarked,
        "message": message
    }
    
    
@app.route("/api/bookmarks")
@jwt_required()
def api_bookmarks():
    user_id = int(get_jwt_identity())

    bookmarks = Bookmark.query.filter_by(
        user_id=user_id
    ).order_by(Bookmark.created_at.desc()).all()

    posts_data = []

    for bookmark in bookmarks:
        post = bookmark.post

        posts_data.append({
            "id": post.id,
            "title": post.title,
            "summary": post.summary,
            "category": post.category,
            "author": post.author.username
        })

    return {
        "success": True,
        "posts": posts_data
    }
    
 
@app.route("/api/users/<username>")
@jwt_required(optional=True)
def api_user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    posts = Post.query.filter_by(
        user_id=user.id,
        status="Published"
    ).order_by(Post.created_at.desc()).all()

    posts_data = []

    for post in posts:
        posts_data.append({
            "id": post.id,
            "title": post.title,
            "summary": post.summary,
            "category": post.category,
            "views": post.views,
            "likes": len(post.likes),
            "comments": len(post.comments),
            "created_at": post.created_at.strftime("%d %b %Y")
        })

    followers_count = Follow.query.filter_by(
        followed_id=user.id
    ).count()

    is_following = False

    current_user_id = (
        int(get_jwt_identity())
        if get_jwt_identity()
        else None
    )

    if current_user_id:
        is_following = Follow.query.filter_by(
            follower_id=current_user_id,
            followed_id=user.id
        ).first() is not None

    return {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "bio": user.bio
        },
        "followers_count": followers_count,
        "is_following": is_following,
        "posts": posts_data
    }
    

@app.route("/api/users/<username>/follow", methods=["POST"])
@jwt_required()
def api_follow_user(username):
    current_user_id = int(get_jwt_identity())

    user_to_follow = User.query.filter_by(
        username=username
    ).first_or_404()

    if user_to_follow.id == current_user_id:
        return {
            "success": False,
            "message": "You cannot follow yourself."
        }, 400

    existing_follow = Follow.query.filter_by(
        follower_id=current_user_id,
        followed_id=user_to_follow.id
    ).first()

    if existing_follow:
        db.session.delete(existing_follow)

        following = False

        message = "Unfollowed successfully."
    else:
       follow = Follow(
          follower_id=current_user_id,
          followed_id=user_to_follow.id
       )

       db.session.add(follow)

       follower = User.query.get(int(current_user_id))

       notification = Notification(
           message=f"{follower.username} started following you.",
           user_id=user_to_follow.id
       )
       db.session.add(notification)

       following = True
       message = "Followed successfully."

    db.session.commit()

    followers_count = Follow.query.filter_by(
        followed_id=user_to_follow.id
    ).count()

    return {
        "success": True,
        "following": following,
        "followers_count": followers_count,
        "message": message
    }    
           

@app.route("/api/posts/<int:post_id>", methods=["DELETE"])
@jwt_required()
def api_delete_post(post_id):
    user_id = int(get_jwt_identity())

    post = Post.query.get_or_404(post_id)

    print("TOKEN USER ID:", user_id)
    print("POST OWNER ID:", post.user_id)

    if int(post.user_id) != int(user_id):
        return {
            "success": False,
            "message": "Unauthorized."
        }, 403

    db.session.delete(post)
    db.session.commit()

    return {
        "success": True,
        "message": "Post deleted successfully."
    }
 
    
@app.route("/api/posts/<int:post_id>", methods=["PUT"])
@jwt_required()
def api_update_post(post_id):
    user_id = int(get_jwt_identity())

    post = Post.query.get_or_404(post_id)

    if int(post.user_id) != int(user_id):
        return {
            "success": False,
            "message": "Unauthorized."
        }, 403

    data = request.get_json()

    post.title = data["title"]
    post.summary = data["summary"]
    post.content = data["content"]
    post.category = data.get("category", "")
    post.tags = data.get("tags", "")

    db.session.commit()

    return {
        "success": True,
        "message": "Post updated successfully."
    }
 
@app.route("/api/posts", methods=["POST"])
@jwt_required()
def api_create_post():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    data = request.form

    image_file = request.files.get("image")

    image_filename = "default_blog.jpg"

    if image_file and image_file.filename:
        image_filename = save_blog_image(image_file)

    post = Post(
        title=data["title"],
        slug=make_slug(data["title"]),
        summary=data["summary"],
        content=data["content"],
        category=data.get("category", "General"),
        tags=data.get("tags", ""),
        image_file=image_filename,
        status="Published",
        author=user
    )

    db.session.add(post)
    db.session.commit()

    return {
        "success": True,
        "message": "Post created successfully."
    }
    
@app.route("/api/profile", methods=["GET", "PUT"])
@jwt_required()
def api_profile():
    user_id = int(get_jwt_identity())

    user = User.query.get_or_404(user_id)

    if request.method == "PUT":
        data = request.get_json()

        user.username = data["username"]
        user.bio = data["bio"]

        db.session.commit()

        return {
            "success": True,
            "message": "Profile updated successfully."
        }

    return {
        "success": True,
        "user": {
            "username": user.username,
            "email": user.email,
            "bio": user.bio,
            "is_admin": user.is_admin
        }
    }

@app.route("/api/notifications")
@jwt_required()
def api_notifications():
    user_id = int(get_jwt_identity())

    notifications = Notification.query.filter_by(
        user_id=user_id
    ).order_by(Notification.created_at.desc()).all()

    notifications_data = []

    for notification in notifications:
        notifications_data.append({
            "id": notification.id,
            "message": notification.message,
            "is_read": notification.is_read,
            "created_at": notification.created_at.strftime("%d %b %Y, %I:%M %p")
        })

        notification.is_read = True

    db.session.commit()

    return {
        "success": True,
        "notifications": notifications_data
    }

@app.route("/api/messages/<username>")
@jwt_required()
def api_messages(username):
    current_user_id = int(get_jwt_identity())

    other_user = User.query.filter_by(
        username=username
    ).first_or_404()

    messages = Message.query.filter(
        (
            (Message.sender_id == current_user_id) &
            (Message.receiver_id == other_user.id)
        )
        |
        (
            (Message.sender_id == other_user.id) &
            (Message.receiver_id == current_user_id)
        )
    ).order_by(Message.created_at.asc()).all()

    messages_data = []

    for message in messages:
        messages_data.append({
            "id": message.id,
            "content": message.content,
            "sender": message.sender.username,
            "created_at": message.created_at.strftime(
                "%d %b %Y, %I:%M %p"
            )
        })

    return {
        "success": True,
        "messages": messages_data
    }

@app.route("/api/inbox")
@jwt_required()
def api_inbox():
    current_user_id = int(get_jwt_identity())

    sent_messages = Message.query.filter_by(
        sender_id=current_user_id
    ).all()

    received_messages = Message.query.filter_by(
        receiver_id=current_user_id
    ).all()

    users_map = {}

    for message in sent_messages:
        user = message.receiver

        users_map[user.username] = {
            "username": user.username,
            "last_message": message.content,
            "created_at": message.created_at.strftime(
                "%d %b %Y, %I:%M %p"
            ),
            "timestamp": message.created_at.timestamp()
        }

    for message in received_messages:
        user = message.sender

        users_map[user.username] = {
            "username": user.username,
            "last_message": message.content,
            "created_at": message.created_at.strftime(
                "%d %b %Y, %I:%M %p"
            ),
            "timestamp": message.created_at.timestamp()
        }

    conversations = list(users_map.values())

    conversations.sort(
        key=lambda x: x["timestamp"],
        reverse=True
    )

    return {
        "success": True,
        "conversations": conversations
    }
    

@app.route("/api/admin/dashboard")
@jwt_required()
def api_admin_dashboard():
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)

    if not user.is_admin:
        return {
            "success": False,
            "message": "Admin access required."
        }, 403

    users = User.query.order_by(User.created_at.desc()).all()
    posts = Post.query.order_by(Post.created_at.desc()).all()
    comments = Comment.query.order_by(Comment.created_at.desc()).all()

    posts_data = []

    for post in posts:
        posts_data.append({
            "id": post.id,
            "title": post.title,
            "author": post.author.username,
            "status": post.status,
            "views": post.views,
            "comments": len(post.comments)
        })

    return {
        "success": True,
        "stats": {
            "users": len(users),
            "posts": len(posts),
            "comments": len(comments)
        },
        "posts": posts_data
    }

@app.route("/api/admin/users")
@jwt_required()
def api_admin_users():
    user_id = get_jwt_identity()
    admin = User.query.get_or_404(user_id)

    if not admin.is_admin:
        return {
            "success": False,
            "message": "Admin access required."
        }, 403

    users = User.query.order_by(User.created_at.desc()).all()

    users_data = []

    for user in users:
        users_data.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "is_verified": user.is_verified,
            "created_at": user.created_at.strftime("%d %b %Y")
        })

    return {
        "success": True,
        "users": users_data
    }
    
@app.route("/api/admin/users/<int:target_user_id>/toggle-admin", methods=["POST"])
@jwt_required()
def api_toggle_admin(target_user_id):
    user_id = get_jwt_identity()
    admin = User.query.get_or_404(user_id)

    if not admin.is_admin:
        return {
            "success": False,
            "message": "Admin access required."
        }, 403

    target_user = User.query.get_or_404(target_user_id)

    if target_user.id == admin.id:
        return {
            "success": False,
            "message": "You cannot change your own admin status."
        }, 400

    target_user.is_admin = not target_user.is_admin
    db.session.commit()

    return {
        "success": True,
        "message": "User admin status updated."
    }    
    
@app.route("/api/admin/posts/<int:post_id>", methods=["DELETE"])
@jwt_required()
def api_admin_delete_post(post_id):
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)

    if not user.is_admin:
        return {
            "success": False,
            "message": "Admin access required."
        }, 403

    post = Post.query.get_or_404(post_id)

    db.session.delete(post)
    db.session.commit()

    return {
        "success": True,
        "message": "Post deleted by admin."
    }    


@app.route("/api/notifications/unread-count")
@jwt_required()
def api_unread_notifications_count():
    user_id = int(get_jwt_identity())

    count = Notification.query.filter_by(
        user_id=user_id,
        is_read=False
    ).count()

    return {
        "success": True,
        "count": count
    }
    

@app.route("/api/my-posts")
@jwt_required()
def api_my_posts():
    user_id = int(get_jwt_identity())

    user = User.query.get(user_id)

    posts = Post.query.filter_by(author=user).order_by(Post.created_at.desc()).all()

    posts_data = []

    for post in posts:
        posts_data.append({
            "id": post.id,
            "title": post.title,
            "summary": post.summary,
            "views": post.views,
            "likes": len(post.likes),
            "comments": len(post.comments),
            "created_at": post.created_at.strftime("%d %b %Y")
        })

    return {
        "success": True,
        "username": user.username,
        "email": user.email,
        "bio": user.bio,
        "posts": posts_data
    }

@app.route("/verify-email/<token>")
def verify_email(token):
    try:
        email = serializer.loads(
            token,
            salt="email-verification",
            max_age=3600
        )
    except:
        flash("Verification link expired or invalid.", "danger")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first_or_404()

    user.is_verified = True
    db.session.commit()

    flash("Email verified successfully. You can now login.", "success")

    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and user.check_password(form.password.data):
            if not user.is_verified:
                flash("Please verify your email first.", "warning")
                return redirect(url_for("login"))
            
            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html", form=form)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if not user:
            flash("No account found with this email.", "danger")
            return redirect(url_for("forgot_password"))

        return redirect(url_for("reset_password", user_id=user.id))

    return render_template("forgot_password.html", form=form)


@app.route("/reset-password/<int:user_id>", methods=["GET", "POST"])
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    form = ResetPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()

        flash("Password reset successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    posts = Post.query.filter_by(author=current_user).order_by(Post.created_at.desc()).all()
    total_views = sum(post.views for post in posts)
    post_titles = [post.title[:15] for post in posts]
    post_views = [post.views for post in posts]
    post_likes = [len(post.likes) for post in posts]
    post_comments = [len(post.comments) for post in posts]
    following_records = Follow.query.filter_by(
        follower_id=current_user.id
    ).order_by(
        Follow.created_at.desc()
    ).all()

    following_users = [
        User.query.get(record.followed_id)
        for record in following_records
    ]
    saved_posts = Bookmark.query.filter_by(
         user_id=current_user.id
    ).order_by(
    Bookmark.created_at.desc()
    ).all()
    
    return render_template(
        "dashboard.html",
        posts=posts,
        total_views=total_views,
        saved_posts=saved_posts,
        following_users=following_users,
        post_titles=post_titles,
        post_views=post_views,
        post_likes=post_likes,
        post_comments=post_comments,
    )
    
@app.route("/notifications")
@login_required
def notifications():
    user_notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).all()

    for notification in user_notifications:
        notification.is_read = True

    db.session.commit()

    return render_template(
        "notifications.html",
        notifications=user_notifications
    )    
    
@app.route("/admin")
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)

    users = User.query.order_by(User.created_at.desc()).all()
    posts = Post.query.order_by(Post.created_at.desc()).all()
    comments = Comment.query.order_by(Comment.created_at.desc()).all()

    return render_template(
        "admin.html",
        users=users,
        posts=posts,
        comments=comments
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm()

    if form.validate_on_submit():
        username_owner = User.query.filter_by(
            username=form.username.data
        ).first()

        if username_owner and username_owner.id != current_user.id:
            flash("Username already taken.", "danger")
            return redirect(url_for("profile"))

        if form.profile_image.data:
            current_user.profile_image = save_profile_image(
                form.profile_image.data
            )

        current_user.username = form.username.data
        current_user.bio = form.bio.data

        db.session.commit()

        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    form.username.data = current_user.username
    form.bio.data = current_user.bio

    return render_template("profile.html", form=form)

@app.route("/author/<username>")
def author_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    posts = Post.query.filter_by(author=user, status="Published").order_by(Post.created_at.desc()).all()

    followers_count = Follow.query.filter_by(followed_id=user.id).count()
    following_count = Follow.query.filter_by(follower_id=user.id).count()

    is_following = False

    if current_user.is_authenticated:
        is_following = Follow.query.filter_by(
            follower_id=current_user.id,
            followed_id=user.id
        ).first() is not None

    return render_template(
        "author_profile.html",
        user=user,
        posts=posts,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following
    )
    
@app.route("/author/<int:user_id>/follow", methods=["POST"])
@login_required
def follow_user(user_id):
    user_to_follow = User.query.get_or_404(user_id)

    if user_to_follow.id == current_user.id:
        flash("You cannot follow yourself.", "warning")
        return redirect(url_for("author_profile", username=user_to_follow.username))

    existing_follow = Follow.query.filter_by(
        follower_id=current_user.id,
        followed_id=user_to_follow.id
    ).first()

    if existing_follow:
        db.session.delete(existing_follow)
        flash("Unfollowed successfully.", "info")
    else:
        follow = Follow(
            follower_id=current_user.id,
            followed_id=user_to_follow.id
        )
        db.session.add(follow)
        
        notification = Notification(
            message=f"{current_user.username} started following you.",
            user_id=user_to_follow.id
        )
        db.session.add(notification)
        
        flash("Followed successfully.", "success")

    db.session.commit()

    return redirect(url_for("author_profile", username=user_to_follow.username))

@app.route("/post/new", methods=["GET", "POST"])
@login_required
def create_post():
    form = PostForm()

    if form.validate_on_submit():
        image_filename = "default_blog.jpg"

        if form.image.data:
           image_filename = save_blog_image(form.image.data)
        
        post = Post(
            title=form.title.data,
            slug=make_slug(form.title.data),
            image_file=image_filename,
            category=form.category.data,
            status=form.status.data,
            tags=form.tags.data,
            summary=form.summary.data,
            content=form.content.data,
            author=current_user
        )

        db.session.add(post)
        db.session.commit()

        flash("Post published successfully.", "success")
        return redirect(url_for("post_detail", slug=post.slug))
    
    return render_template("post_form.html", form=form, heading="Create New Post")


@app.route("/post/<slug>", methods=["GET", "POST"])
def post_detail(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    
    if post.status == "Draft" and (not current_user.is_authenticated or post.author != current_user):
      abort(403)
      
    post.views += 1
    db.session.commit()

    form = CommentForm()

    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("Please login to comment.", "warning")
            return redirect(url_for("login"))

        comment = Comment(
            content=form.content.data,
            comment_author=current_user,
            post=post
        )

        db.session.add(comment)
        
        if post.author.id != current_user.id:
            notification = Notification(
                 message=f"{current_user.username} commented on your post: {post.title}",
                 user_id=post.author.id
            )
            db.session.add(notification)
            
        db.session.commit()

        flash("Comment added.", "success")
        return redirect(url_for("post_detail", slug=post.slug))

    comments = Comment.query.filter_by(post=post, parent_id=None).order_by(Comment.created_at.desc()).all()

    return render_template(
        "post_detail.html",
        post=post,
        form=form,
        comments=comments
    )


@app.route("/post/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()

    if post.author != current_user:
        abort(403)

    form = PostForm(obj=post)

    if form.validate_on_submit():
        if form.image.data:
           post.image_file = save_blog_image(form.image.data)
       
        post.title = form.title.data
        post.category = form.category.data
        post.status = form.status.data
        post.tags = form.tags.data
        post.summary = form.summary.data
        post.content = form.content.data
        post.updated_at = datetime.utcnow()

        db.session.commit()

        flash("Post updated successfully.", "success")
        return redirect(url_for("post_detail", slug=post.slug))

    return render_template("post_form.html", form=form, heading="Edit Post")


@app.route("/post/<slug>/delete", methods=["POST"])
@login_required
def delete_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()

    if post.author != current_user:
        abort(403)

    db.session.delete(post)
    db.session.commit()

    flash("Post deleted successfully.", "info")
    return redirect(url_for("dashboard"))

@app.route("/admin/post/<int:post_id>/delete", methods=["POST"])
@login_required
def admin_delete_post(post_id):
    if not current_user.is_admin:
        abort(403)

    post = Post.query.get_or_404(post_id)

    db.session.delete(post)
    db.session.commit()

    flash("Post deleted by admin.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)

    if comment.comment_author != current_user and comment.post.author != current_user:
        abort(403)

    post_slug = comment.post.slug

    db.session.delete(comment)
    db.session.commit()

    flash("Comment deleted.", "info")
    return redirect(url_for("post_detail", slug=post_slug))

@app.route("/comment/<int:comment_id>/reply", methods=["POST"])
@login_required
def reply_comment(comment_id):
    parent_comment = Comment.query.get_or_404(comment_id)

    reply_text = request.form.get("reply")

    if not reply_text:
        flash("Reply cannot be empty.", "danger")
        return redirect(url_for("post_detail", slug=parent_comment.post.slug))

    reply = Comment(
        content=reply_text,
        comment_author=current_user,
        post=parent_comment.post,
        parent=parent_comment
    )

    db.session.add(reply)
    db.session.commit()

    flash("Reply added.", "success")
    return redirect(url_for("post_detail", slug=parent_comment.post.slug))

@app.route("/admin/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def admin_delete_comment(comment_id):

    if not current_user.is_admin:
        abort(403)

    comment = Comment.query.get_or_404(comment_id)

    db.session.delete(comment)
    db.session.commit()

    flash("Comment deleted by admin.", "info")

    return redirect(url_for("admin_dashboard"))

@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)

    existing_like = Like.query.filter_by(
        user_id=current_user.id,
        post_id=post.id
    ).first()

    if existing_like:
        db.session.delete(existing_like)
        flash("Like removed.", "info")
    else:
        like = Like(user_id=current_user.id, post_id=post.id)
        db.session.add(like)
        
        if post.author.id != current_user.id:
            notification = Notification(
                message=f"{current_user.username} liked your post: {post.title}",
                user_id=post.author.id
            )
            db.session.add(notification)
            
        flash("Post liked.", "success")

    db.session.commit()

    return redirect(url_for("post_detail", slug=post.slug))

@app.route("/post/<int:post_id>/bookmark", methods=["POST"])
@login_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)

    existing_bookmark = Bookmark.query.filter_by(
        user_id=current_user.id,
        post_id=post.id
    ).first()

    if existing_bookmark:
        db.session.delete(existing_bookmark)
        flash("Bookmark removed.", "info")
    else:
        bookmark = Bookmark(user_id=current_user.id, post_id=post.id)
        db.session.add(bookmark)
        flash("Post saved.", "success")

    db.session.commit()

    return redirect(url_for("post_detail", slug=post.slug))

@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404

online_users = {}

@socketio.on("user_connected")
def handle_user_connected(data):
    username = data.get("username", "Guest")

    online_users[request.sid] = username

    socketio.emit(
        "online_users",
        list(set(online_users.values()))
    )


@socketio.on("disconnect")
def handle_disconnect():
    if request.sid in online_users:
        del online_users[request.sid]

    socketio.emit(
        "online_users",
        list(set(online_users.values()))
    )


@socketio.on("send_message")
def handle_send_message(data):
    socketio.emit(
        "receive_message",
        data
    )

@socketio.on("send_private_message")
def handle_private_message(data):
    sender = data["sender"]

    receiver = data["receiver"]

    content = data["message"]

    sender_user = User.query.filter_by(
        username=sender
    ).first()

    receiver_user = User.query.filter_by(
        username=receiver
    ).first()

    if sender_user and receiver_user:
        message = Message(
            sender_id=sender_user.id,
            receiver_id=receiver_user.id,
            content=content
        )

        db.session.add(message)
        db.session.commit()

    emit(
        "receive_private_message",
        data,
        broadcast=True
    )

with app.app_context():
    db.create_all()
     
if __name__ == "__main__":
    socketio.run(app, debug=True)