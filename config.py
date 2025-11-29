import os

class Config:
    SECRET_KEY = 'your-secret-key-here-change-this-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///car_rental.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
