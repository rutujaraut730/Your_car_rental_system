from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Car, Driver, Booking
from config import Config
from datetime import datetime
import os
import json
import requests
from geopy.geocoders import Nominatim
import folium
import nltk
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Download NLTK data for chatbot
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Simple AI Chatbot
class CarRentalChatbot:
    def __init__(self):
        self.patterns = {
            'greeting': ['hello', 'hi', 'hey', 'good morning', 'good afternoon'],
            'booking': ['book', 'booking', 'reserve', 'rent'],
            'pricing': ['price', 'cost', 'how much', 'rate'],
            'availability': ['available', 'in stock', 'have cars'],
            'location': ['location', 'where', 'address'],
            'contact': ['contact', 'phone', 'email', 'support'],
            'thanks': ['thank you', 'thanks', 'appreciate']
        }
        
        self.responses = {
            'greeting': "Hello! Welcome to Your Car! rental service. How can I help you today?",
            'booking': "You can book cars through our booking page. Would you like me to redirect you there?",
            'pricing': "Our prices start from $30 per day. The exact price depends on the car model and rental duration.",
            'availability': "We have various cars available! Check our booking page to see all available vehicles.",
            'location': "We have multiple pickup locations across the city. You can choose your preferred location during booking.",
            'contact': "You can reach us at support@yourcar.com or call +1-555-0123. Visit our contact page for more details!",
            'thanks': "You're welcome! Let me know if you need any other assistance.",
            'default': "I'm here to help with car rentals! You can ask about booking, prices, availability, or contact information."
        }
    
    def get_response(self, message):
        message = message.lower()
        
        for intent, patterns in self.patterns.items():
            if any(pattern in message for pattern in patterns):
                return self.responses.get(intent, self.responses['default'])
        
        return self.responses['default']

chatbot = CarRentalChatbot()

# GPS Tracking Helper
def get_coordinates(address):
    try:
        geolocator = Nominatim(user_agent="your_car_rental")
        location = geolocator.geocode(address)
        if location:
            return location.latitude, location.longitude
    except:
        pass
    return 40.7128, -74.0060  # Default to New York coordinates

def create_map(lat, lng, cars=None):
    try:
        m = folium.Map(location=[lat, lng], zoom_start=13)
        folium.Marker([lat, lng], popup='Your Location', tooltip='You are here').add_to(m)
        
        if cars:
            for car in cars:
                if car.latitude and car.longitude:
                    folium.Marker(
                        [car.latitude, car.longitude],
                        popup=f"{car.brand} {car.model} - ${car.price_per_day}/day",
                        tooltip='Available Car',
                        icon=folium.Icon(color='green', icon='car')
                    ).add_to(m)
        
        return m._repr_html_()
    except:
        return "<div class='alert alert-warning'>Map could not be loaded</div>"

# Routes
@app.route('/')
def index():
    available_cars = Car.query.filter_by(available=True).limit(6).all()
    return render_template('index.html', cars=available_cars)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form.get('role', 'user')
        
        print(f"Registration attempt: {username}, {email}")  # Debug
        
        # Check if username exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))
        
        # Check if email exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'danger')
            return redirect(url_for('register'))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            password=hashed_password,
            role=role
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Login failed. Check username and password.', 'danger')
    
    return render_template('login.html')
@app.route('/profile')
@login_required
def profile():
    # Get user's bookings with car and driver details
    user_bookings = Booking.query.filter_by(user_id=current_user.id)\
        .join(Car)\
        .outerjoin(Driver)\
        .add_columns(
            Booking.id,
            Booking.start_date,
            Booking.end_date,
            Booking.total_price,
            Booking.status,
            Booking.pickup_location,
            Car.brand,
            Car.model,
            Car.year,
            Car.image,
            Driver.name.label('driver_name')
        )\
        .order_by(Booking.created_at.desc())\
        .all()
    
    return render_template('profile.html', bookings=user_bookings)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/booking')
@login_required
def booking():
    cars = Car.query.filter_by(available=True).all()
    drivers = Driver.query.filter_by(available=True).all()
    return render_template('booking.html', cars=cars, drivers=drivers)

@app.route('/book_car', methods=['POST'])
@login_required
def book_car():
    try:
        car_id = request.form['car_id']
        driver_id = request.form.get('driver_id')
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        pickup_location = request.form['pickup_location']
        
        car = Car.query.get(car_id)
        if not car:
            flash('Car not found!', 'danger')
            return redirect(url_for('booking'))
        
        # Calculate total price
        days = (end_date - start_date).days
        if days < 1:
            flash('Invalid rental period!', 'danger')
            return redirect(url_for('booking'))
            
        total_price = car.price_per_day * days
        
        booking = Booking(
            user_id=current_user.id,
            car_id=car_id,
            driver_id=driver_id if driver_id else None,
            start_date=start_date,
            end_date=end_date,
            total_price=total_price,
            pickup_location=pickup_location,
            status='pending'
        )
        
        db.session.add(booking)
        db.session.commit()
        
        flash('Booking successful! We will confirm shortly.', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        flash('Error processing booking. Please try again.', 'danger')
        return redirect(url_for('booking'))

@app.route('/add_car', methods=['GET', 'POST'])
@login_required
def add_car():
    if current_user.role not in ['client', 'admin']:
        flash('You need client privileges to add cars!', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            brand = request.form['brand']
            model = request.form['model']
            year = int(request.form['year'])
            price_per_day = float(request.form['price_per_day'])
            seats = int(request.form['seats'])
            transmission = request.form['transmission']
            fuel_type = request.form['fuel_type']
            location = request.form['location']
            
            # Handle file upload
            image = request.files['image']
            image_filename = None
            if image and image.filename:
                image_filename = secure_filename(image.filename)
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
            
            # Get coordinates
            lat, lng = get_coordinates(location)
            
            car = Car(
                brand=brand,
                model=model,
                year=year,
                price_per_day=price_per_day,
                seats=seats,
                transmission=transmission,
                fuel_type=fuel_type,
                image=image_filename,
                location=location,
                latitude=lat,
                longitude=lng,
                client_id=current_user.id
            )
            
            db.session.add(car)
            db.session.commit()
            
            flash('Car added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash('Error adding car. Please check your inputs.', 'danger')
    
    return render_template('add_car.html')

@app.route('/add_driver', methods=['GET', 'POST'])
@login_required
def add_driver():
    if current_user.role not in ['client', 'admin']:
        flash('You need client privileges to add drivers!', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            # Required fields
            name = request.form['name']
            license_number = request.form['license_number']
            experience = int(request.form['experience'])
            phone = request.form['phone']
            
            # Optional fields with safe defaults
            email = request.form.get('email', '')
            license_type = request.form.get('license_type', 'Class C - Regular Passenger')
            
            # Handle license expiry
            license_expiry_str = request.form.get('license_expiry')
            license_expiry = None
            if license_expiry_str:
                license_expiry = datetime.strptime(license_expiry_str, '%Y-%m-%d')
            
            # Handle vehicle types
            vehicle_types_list = request.form.getlist('vehicle_types')
            vehicle_types = ', '.join(vehicle_types_list) if vehicle_types_list else 'Sedan'
            
            # Handle skills and languages
            skills_list = request.form.getlist('skills')
            skills = ', '.join(skills_list) if skills_list else ''
            
            languages_list = request.form.getlist('languages')
            languages = ', '.join(languages_list) if languages_list else 'English'
            
            # Handle availability
            availability_list = request.form.getlist('availability')
            availability = ', '.join(availability_list) if availability_list else 'All days'
            
            # Other optional fields
            hourly_rate = float(request.form.get('hourly_rate', 25))
            service_areas = request.form.get('service_areas', '')
            emergency_contact_name = request.form.get('emergency_contact_name', '')
            emergency_contact_phone = request.form.get('emergency_contact_phone', '')
            
            # Check if license number already exists
            existing_driver = Driver.query.filter_by(license_number=license_number).first()
            if existing_driver:
                flash('Driver with this license number already exists!', 'danger')
                return redirect(url_for('add_driver'))
            
            # Create driver
            driver = Driver(
                name=name,
                license_number=license_number,
                experience=experience,
                phone=phone,
                email=email,
                license_type=license_type,
                license_expiry=license_expiry,
                vehicle_types=vehicle_types,
                skills=skills,
                languages=languages,
                availability=availability,
                hourly_rate=hourly_rate,
                service_areas=service_areas,
                emergency_contact_name=emergency_contact_name,
                emergency_contact_phone=emergency_contact_phone,
                client_id=current_user.id
            )
            
            db.session.add(driver)
            db.session.commit()
            
            flash('Driver added successfully!', 'success')
            return redirect(url_for('index'))
            
        except Exception as e:
            flash(f'Error adding driver: {str(e)}', 'danger')
            print(f"Error details: {str(e)}")
    
    return render_template('add_driver.html')

@app.route('/admin')
@login_required
def admin():
    if current_user.role != 'admin':
        flash('Admin access required!', 'danger')
        return redirect(url_for('index'))
    
    users = User.query.all()
    cars = Car.query.all()
    drivers = Driver.query.all()
    bookings = Booking.query.all()
    
    return render_template('admin.html', 
                         users=users, 
                         cars=cars, 
                         drivers=drivers, 
                         bookings=bookings)

# DELETE ROUTES
@app.route('/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Admin access required!', 'danger')
        return redirect(url_for('index'))
    
    user = User.query.get(user_id)
    if user:
        # Prevent deleting yourself or other admins
        if user.id == current_user.id:
            flash('You cannot delete your own account!', 'danger')
        elif user.role == 'admin':
            flash('Cannot delete other admin accounts!', 'danger')
        else:
            # Delete user's cars, drivers, and bookings first
            Car.query.filter_by(client_id=user.id).delete()
            Driver.query.filter_by(client_id=user.id).delete()
            Booking.query.filter_by(user_id=user.id).delete()
            
            db.session.delete(user)
            db.session.commit()
            flash('User and all associated data deleted successfully!', 'success')
    else:
        flash('User not found!', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/delete_car/<int:car_id>')
@login_required
def delete_car(car_id):
    car = Car.query.get(car_id)
    if car:
        # Only admin or car owner can delete
        if current_user.role == 'admin' or car.client_id == current_user.id:
            # Delete associated bookings first
            Booking.query.filter_by(car_id=car_id).delete()
            db.session.delete(car)
            db.session.commit()
            flash('Car deleted successfully!', 'success')
        else:
            flash('You can only delete your own cars!', 'danger')
    else:
        flash('Car not found!', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/delete_booking/<int:booking_id>')
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get(booking_id)
    if booking:
        # Only admin or booking owner can delete
        if current_user.role == 'admin' or booking.user_id == current_user.id:
            db.session.delete(booking)
            db.session.commit()
            flash('Booking deleted successfully!', 'success')
        else:
            flash('You can only delete your own bookings!', 'danger')
    else:
        flash('Booking not found!', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/delete_driver/<int:driver_id>')
@login_required
def delete_driver(driver_id):
    driver = Driver.query.get(driver_id)
    if driver:
        # Only admin or driver owner can delete
        if current_user.role == 'admin' or driver.client_id == current_user.id:
            # Remove driver from bookings
            bookings = Booking.query.filter_by(driver_id=driver_id).all()
            for booking in bookings:
                booking.driver_id = None
            
            db.session.delete(driver)
            db.session.commit()
            flash('Driver deleted successfully!', 'success')
        else:
            flash('You can only delete your own drivers!', 'danger')
    else:
        flash('Driver not found!', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/chatbot', methods=['POST'])
def chat_with_bot():
    message = request.json.get('message', '')
    response = chatbot.get_response(message)
    return jsonify({'response': response})

@app.route('/driver_dashboard')
@login_required
def driver_dashboard():
    # Check if current user is a client (car/driver owner)
    if current_user.role != 'client':
        flash('Driver access required! Please register as a client to access driver features.', 'danger')
        return redirect(url_for('index'))
    
    # Get driver details for the current user
    driver = Driver.query.filter_by(client_id=current_user.id).first()
    
    if not driver:
        flash('No driver profile found! Please add your driver profile first.', 'warning')
        return redirect(url_for('add_driver'))
    
    print(f"✅ Found driver: {driver.name} (ID: {driver.id})")  # Debug
    
    # SIMPLIFIED QUERY - Get bookings assigned to this driver
    driver_bookings = Booking.query.filter_by(driver_id=driver.id)\
        .join(Car)\
        .join(User)\
        .with_entities(
            Booking,
            Car.brand,
            Car.model,
            Car.year,
            User.username,
            User.email
        )\
        .order_by(Booking.start_date.asc())\
        .all()
    
    print(f"✅ Found {len(driver_bookings)} bookings for driver")  # Debug
    
    return render_template('driver_dashboard.html', 
                         driver=driver, 
                         bookings=driver_bookings)

@app.route('/update_booking_status/<int:booking_id>', methods=['POST'])
@login_required
def update_booking_status(booking_id):
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'})
        
        # Check if current user is the assigned driver
        driver = Driver.query.filter_by(client_id=current_user.id).first()
        if not driver or booking.driver_id != driver.id:
            return jsonify({'success': False, 'error': 'Access denied'})
        
        # Update status
        booking.status = new_status
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Status updated successfully'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/track_cars')
@login_required
def track_cars():
    user_location = request.args.get('location', 'New York')
    lat, lng = get_coordinates(user_location)
    cars = Car.query.filter_by(available=True).all()
    
    map_html = create_map(lat, lng, cars)
    return render_template('tracking.html', map_html=map_html, location=user_location, cars=cars)
@app.route('/debug_drivers')
@login_required
def debug_drivers():
    if current_user.role != 'admin':
        flash('Admin access required!', 'danger')
        return redirect(url_for('index'))
    
    # Get all bookings with driver info
    bookings_with_drivers = Booking.query.filter(Booking.driver_id.isnot(None))\
        .join(Driver)\
        .add_columns(
            Booking.id,
            Booking.driver_id,
            Driver.name,
            Driver.license_number
        )\
        .all()
    
    result = []
    for item in bookings_with_drivers:
        result.append({
            'booking_id': item.id,
            'driver_id': item.driver_id,
            'driver_name': item.name,
            'license': item.license_number
        })
    
    return jsonify(result)

# Initialize database
with app.app_context():
    # Create all tables if they don't exist
    db.create_all()
    
    # Check if we need to create default users (only if no users exist)
    if not User.query.first():
        # Create admin user
        admin_user = User(
            username='admin',
            email='admin@yourcar.com',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin_user)
        print("✅ Admin user created: admin / admin123")
    
        # Create test client user
        client_user = User(
            username='client1',
            email='client@yourcar.com',
            password=generate_password_hash('client123'),
            role='client'
        )
        db.session.add(client_user)
        print("✅ Client user created: client1 / client123")
    
        # Create test regular user
        regular_user = User(
            username='user1',
            email='user@yourcar.com',
            password=generate_password_hash('user123'),
            role='user'
        )
        db.session.add(regular_user)
        print("✅ Regular user created: user1 / user123")
    
        db.session.commit()
        print("✅ Database initialized with default users!")
    else:
        print("✅ Database already exists with users!")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
