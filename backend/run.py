# run.py — local development entry point.
# Migrations and seeding are now handled inside create_app() in app.py,
# so this file just starts the Flask dev server.
from app import app

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
