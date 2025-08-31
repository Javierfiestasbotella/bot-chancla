from flask import Flask
from app.routes import bp

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.register_blueprint(bp)
    return app
