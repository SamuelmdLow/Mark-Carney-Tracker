pip install -r requirements.txt
python manage.py makemigrations &&
python manage.py migrate &&
python manage.py collectstatic --noinput &&
gunicorn pm_tracker.wsgi:application --bind 0.0.0.0:8000