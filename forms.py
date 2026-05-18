from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=3, max=30)]
    )

    email = StringField(
        "Email",
        validators=[DataRequired(), Email()]
    )

    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=6)]
    )

    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password")]
    )

    submit = SubmitField("Create Account")


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email()]
    )

    password = PasswordField(
        "Password",
        validators=[DataRequired()]
    )

    submit = SubmitField("Login")


class PostForm(FlaskForm):
    image = FileField(
        "Blog Image",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"])]
    )
    
    title = StringField(
        "Post Title",
        validators=[DataRequired(), Length(min=5, max=150)]
    )

    category = StringField(
        "Category",
        validators=[DataRequired(), Length(max=50)]
    )
    
    status = SelectField(
        "Post Status",
        choices=[
            ("Published", "Published"),
            ("Draft", "Draft")
        ]
    )

    tags = StringField(
        "Tags",
        validators=[Length(max=200)]
    )

    summary = TextAreaField(
        "Short Summary",
        validators=[DataRequired(), Length(min=20, max=250)]
    )

    content = TextAreaField(
        "Full Content",
        validators=[DataRequired(), Length(min=50)]
    )

    submit = SubmitField("Publish Post")
    
    


class CommentForm(FlaskForm):
    content = TextAreaField(
        "Write a comment",
        validators=[DataRequired(), Length(min=2, max=500)]
    )

    submit = SubmitField("Post Comment")


class ProfileForm(FlaskForm):
    profile_image = FileField(
        "Profile Image",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"])]
    )

    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=3, max=30)]
    )

    bio = TextAreaField(
        "Bio",
        validators=[Length(max=250)]
    )

    submit = SubmitField("Update Profile")
    
    
class ForgotPasswordForm(FlaskForm):
    email = StringField(
        "Registered Email",
        validators=[DataRequired(), Email()]
    )

    submit = SubmitField("Find Account")


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=6)]
    )

    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("password")]
    )

    submit = SubmitField("Reset Password")