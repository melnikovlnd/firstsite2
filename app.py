from flask import Flask, render_template, request, redirect, url_for, jsonify
import requests
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from cryptography.fernet import Fernet
import os
import base64
import json
from datetime import datetime

app = Flask(__name__)

# Конфигурация базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///contacts.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'  # Required for Flask-SocketIO
db = SQLAlchemy(app)
socketio = SocketIO(app)

# Конфигурация Telegram бота
BOT_TOKEN = '7402155217:AAGBtXrkawByrHGZu6jJQGmWBTmx4Lysgf4'
CHAT_ID = '1676019994'

# Генерация/загрузка ключа для шифрования
if not os.path.exists('secret.key'):
    key = Fernet.generate_key()
    with open('secret.key', 'wb') as key_file:
        key_file.write(key)
else:
    with open('secret.key', 'rb') as key_file:
        key = key_file.read()

cipher_suite = Fernet(key)

# Модель для базы данных
class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    message = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # Исправлено здесь

    def __repr__(self):
        return f'<Contact {self.name}>'
    
    def get_decrypted_message(self):
        """Метод для расшифровки сообщения"""
        return cipher_suite.decrypt(self.message).decode()

# New model for likes/dislikes
class VideoInteraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.String(100), nullable=False)
    likes = db.Column(db.Integer, default=0)
    dislikes = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            'video_id': self.video_id,
            'likes': self.likes,
            'dislikes': self.dislikes
        }

# В В В В В В В В  В В В В В В  В В В В  В В В В В В 

# JSON file path for storing video interactions
INTERACTIONS_FILE = 'video_interactions.json'

# Function to load interactions from JSON file
def load_interactions():
    if os.path.exists(INTERACTIONS_FILE):
        try:
            with open(INTERACTIONS_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

# Function to save interactions to JSON file
def save_interactions(interactions):
    with open(INTERACTIONS_FILE, 'w') as f:
        json.dump(interactions, f, indent=4)

# Function to initialize data from JSON file
def initialize_data():
    interactions = load_interactions()
    with app.app_context():
        for video_id, counts in interactions.items():
            # Check if video interaction exists in database
            video = VideoInteraction.query.filter_by(video_id=video_id).first()
            if not video:
                # Create new database record
                video = VideoInteraction(
                    video_id=video_id,
                    likes=counts['likes'],
                    dislikes=counts['dislikes']
                )
                db.session.add(video)
        db.session.commit()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/page2')
def page2():
    return render_template('page2.html')

@app.route('/page3', methods=['GET', 'POST'])
def page3():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        email = request.form['email']
        message = request.form['message']

        errors = []
        if not name or len(name) < 2 or name[0].islower():
            errors.append("Имя должно быть c большой буквы и иметь не менее 2 символов.")
        if not email or '@' not in email or '.' not in email:
            errors.append("Неправильный формат электронной почты.")
        if not phone or not phone.isdigit() or len(phone) > 20 :
            errors.append("Номер телефона должен содержать только цифры и меньше 20 символов.")
        if not message or len(message) < 5:
            errors.append("Сообщение должно быть не менее 5 символов.")

        if errors:
            return render_template('page3.html', errors=errors)
        else:
            # Шифрование сообщения
            encrypted_message = cipher_suite.encrypt(message.encode())
            
            # Сохранение в базу данных
            new_contact = Contact(
                name=name,
                email=email,
                phone=phone,
                message=encrypted_message
                # created_at добавится автоматически
            )
            db.session.add(new_contact)
            db.session.commit()

            # Отправка в Telegram с данными из БД
            send_contact_to_telegram(new_contact.id)

            return redirect(url_for('page3'))

    return render_template('page3.html')

def send_contact_to_telegram(contact_id):
    """Отправляет контакт из БД в Telegram"""
    contact = Contact.query.get(contact_id)
    if not contact:
        print(f"Контакт с ID {contact_id} не найден")
        return

    try:
        # Расшифровываем сообщение из БД
        decrypted_message = contact.get_decrypted_message()
        
        text = (
            f"?? Новое сообщение из базы данных (ID: {contact.id})\n"
            f"?? Дата: {contact.created_at}\n"
            f"?? Имя: {contact.name}\n"
            f"?? Телефон: {contact.phone}\n"
            f"?? Email: {contact.email}\n"
            f"?? Сообщение: {decrypted_message}\n\n"
            f"?? Зашифрованное сообщение (из БД):\n"
            f"{base64.b64encode(contact.message).decode()}"
        )
        
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, data=payload)
        response.raise_for_status()
        
    except Exception as e:
                print(f"Ошибка при отправке контакта в Telegram: {e}")


@app.route('/api/interact', methods=['POST'])
def interact():
    data = request.json
    video_id = data.get('video_id')
    interaction_type = data.get('type')  # 'like', 'dislike', 'remove_like', or 'remove_dislike'
    
    video = VideoInteraction.query.filter_by(video_id=video_id).first()
    
    if not video:
        video = VideoInteraction(video_id=video_id, likes=0, dislikes=0)
        db.session.add(video)
    
    if interaction_type == 'like':
        video.likes += 1
    elif interaction_type == 'dislike':
        video.dislikes += 1
    elif interaction_type == 'remove_like' and video.likes > 0:
        video.likes -= 1
    elif interaction_type == 'remove_dislike' and video.dislikes > 0:
        video.dislikes -= 1
    
    db.session.commit()
    
    # Update JSON file
    interactions = load_interactions()
    if video_id not in interactions:
        interactions[video_id] = {'likes': 0, 'dislikes': 0}
    
    if interaction_type == 'like':
        interactions[video_id]['likes'] += 1
    elif interaction_type == 'dislike':
        interactions[video_id]['dislikes'] += 1
    elif interaction_type == 'remove_like' and interactions[video_id]['likes'] > 0:
        interactions[video_id]['likes'] -= 1
    elif interaction_type == 'remove_dislike' and interactions[video_id]['dislikes'] > 0:
        interactions[video_id]['dislikes'] -= 1
    
    save_interactions(interactions)
    
    # Emit the update to all connected clients
    socketio.emit('interaction_update', video.to_dict())
    
    return jsonify(video.to_dict())

@app.route('/api/get_interactions/<video_id>')
def get_interactions(video_id):
    # Try to get from database first
    video = VideoInteraction.query.filter_by(video_id=video_id).first()
    
    # If not in database, check JSON file
    if not video:
        interactions = load_interactions()
        if video_id in interactions:
            # Create new database record from JSON data
            video = VideoInteraction(
                video_id=video_id,
                likes=interactions[video_id]['likes'],
                dislikes=interactions[video_id]['dislikes']
            )
            db.session.add(video)
            db.session.commit()
    
    if video:
        return jsonify(video.to_dict())
    return jsonify({'video_id': video_id, 'likes': 0, 'dislikes': 0})

# Создание таблиц базы данных
with app.app_context():
    db.drop_all()  # Удаляем старые таблицы
    db.create_all()  # Создаем новые с актуальной структурой
    initialize_data()  # Initialize data from JSON file

if __name__ == '__main__':
    # Development only
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
else:
    # Production - Gunicorn will handle the app
    port = int(os.environ.get('PORT', 5000))
    socketio.init_app(app, 
                     async_mode='eventlet',
                     cors_allowed_origins='*',
                     path='/socket.io')