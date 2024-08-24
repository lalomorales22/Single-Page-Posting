import os
from flask import Flask, request, render_template_string, redirect, url_for, g, jsonify
from dotenv import load_dotenv
import sqlite3
from flask_socketio import SocketIO, emit
from datetime import datetime
import requests
import base64
import io
from PIL import Image

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
socketio = SocketIO(app)

# Database setup
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect('message_board.db')
    return db

# Add this function to handle image generation
def generate_image_with_stability(prompt):
    api_key = os.getenv("STABILITY_API_KEY")
    if not api_key:
        return None, "Stability API key not set"

    url = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "text_prompts": [{"text": prompt}],
        "cfg_scale": 7,
        "height": 1024,
        "width": 1024,
        "samples": 1,
        "steps": 30,
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        image_data = data["artifacts"][0]["base64"]
        return image_data, None
    except requests.exceptions.RequestException as e:
        return None, str(e)

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             content TEXT NOT NULL,
             image_data TEXT,
             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             message_id INTEGER,
             content TEXT NOT NULL,
             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
             FOREIGN KEY (message_id) REFERENCES messages (id))
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             name TEXT UNIQUE NOT NULL)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_tags
            (message_id INTEGER,
             tag_id INTEGER,
             FOREIGN KEY (message_id) REFERENCES messages (id),
             FOREIGN KEY (tag_id) REFERENCES tags (id),
             PRIMARY KEY (message_id, tag_id))
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reactions
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             message_id INTEGER,
             reaction TEXT,
             count INTEGER DEFAULT 0,
             FOREIGN KEY (message_id) REFERENCES messages (id),
             UNIQUE(message_id, reaction))
        ''')
        
        db.commit()

init_db()

@app.route('/')
def index():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT messages.id, messages.content, messages.image_data, messages.timestamp
        FROM messages
        ORDER BY messages.timestamp DESC
    ''')
    messages = cursor.fetchall()
    
    for i, message in enumerate(messages):
        cursor.execute('''
            SELECT comments.content, comments.timestamp
            FROM comments
            WHERE comments.message_id = ?
            ORDER BY comments.timestamp ASC
        ''', (message[0],))
        comments = cursor.fetchall()
        
        cursor.execute('''
            SELECT tags.name
            FROM tags
            JOIN message_tags ON tags.id = message_tags.tag_id
            WHERE message_tags.message_id = ?
        ''', (message[0],))
        tags = [tag[0] for tag in cursor.fetchall()]
        
        cursor.execute('''
            SELECT reaction, count
            FROM reactions
            WHERE message_id = ?
        ''', (message[0],))
        reactions = dict(cursor.fetchall())
        
        messages[i] = message + (comments, tags, reactions)
    
    cursor.execute('''
        SELECT tags.name, COUNT(*) as tag_count
        FROM tags
        JOIN message_tags ON tags.id = message_tags.tag_id
        GROUP BY tags.id
        ORDER BY tag_count DESC
        LIMIT 10
    ''')
    popular_tags = cursor.fetchall()
    
    return render_template_string(BASE_HTML, messages=messages, popular_tags=popular_tags)

@app.route('/post_message', methods=['POST'])
def post_message():
    content = request.form.get('content')
    tags = request.form.get('tags', '').split(',')
    image_data = request.form.get('image_data')
    
    if content or image_data:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO messages (content, image_data) VALUES (?, ?)",
                       (content, image_data))
        message_id = cursor.lastrowid
        
        for tag in tags:
            tag = tag.strip().lower()
            if tag:
                cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                cursor.execute("SELECT id FROM tags WHERE name = ?", (tag,))
                tag_id = cursor.fetchone()[0]
                cursor.execute("INSERT INTO message_tags (message_id, tag_id) VALUES (?, ?)",
                               (message_id, tag_id))
        
        db.commit()
        
        cursor.execute('''
            SELECT messages.id, messages.content, messages.image_data, messages.timestamp
            FROM messages
            WHERE messages.id = ?
        ''', (message_id,))
        new_message = cursor.fetchone()
        
        socketio.emit('new_message', {
            'id': new_message[0],
            'content': new_message[1],
            'image_data': new_message[2],
            'timestamp': new_message[3],
            'tags': tags,
            'reactions': {}
        })
    return redirect(url_for('index'))

@app.route('/generate_image', methods=['POST'])
def generate_image():
    prompt = request.form.get('prompt')
    image_data, error = generate_image_with_stability(prompt)
    
    if error:
        return jsonify({"error": error}), 500
    
    return jsonify({"image_data": image_data})

@app.route('/tag/<tag_name>')
def view_tag(tag_name):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT messages.id, messages.content, messages.image_data, messages.timestamp
        FROM messages
        JOIN message_tags ON messages.id = message_tags.message_id
        JOIN tags ON message_tags.tag_id = tags.id
        WHERE tags.name = ?
        ORDER BY messages.timestamp DESC
    ''', (tag_name,))
    messages = cursor.fetchall()
    
    for i, message in enumerate(messages):
        cursor.execute('''
            SELECT comments.content, comments.timestamp
            FROM comments
            WHERE comments.message_id = ?
            ORDER BY comments.timestamp ASC
        ''', (message[0],))
        comments = cursor.fetchall()
        
        cursor.execute('''
            SELECT tags.name
            FROM tags
            JOIN message_tags ON tags.id = message_tags.tag_id
            WHERE message_tags.message_id = ?
        ''', (message[0],))
        tags = [tag[0] for tag in cursor.fetchall()]
        
        cursor.execute('''
            SELECT reaction, count
            FROM reactions
            WHERE message_id = ?
        ''', (message[0],))
        reactions = dict(cursor.fetchall())
        
        messages[i] = message + (comments, tags, reactions)
    
    return render_template_string(BASE_HTML, messages=messages, current_tag=tag_name)

@app.route('/post_comment/<int:message_id>', methods=['POST'])
def post_comment(message_id):
    content = request.form.get('content')
    if content:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO comments (message_id, content) VALUES (?, ?)",
                       (message_id, content))
        comment_id = cursor.lastrowid
        db.commit()
        
        cursor.execute('''
            SELECT comments.content, comments.timestamp
            FROM comments
            WHERE comments.id = ?
        ''', (comment_id,))
        new_comment = cursor.fetchone()
        
        socketio.emit('new_comment', {
            'message_id': message_id,
            'content': new_comment[0],
            'timestamp': new_comment[1]
        })
    return redirect(url_for('index'))

@app.route('/add_reaction/<int:message_id>/<reaction>')
def add_reaction(message_id, reaction):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute('''
            INSERT INTO reactions (message_id, reaction, count)
            VALUES (?, ?, 1)
            ON CONFLICT(message_id, reaction) 
            DO UPDATE SET count = count + 1
        ''', (message_id, reaction))
        db.commit()
        
        cursor.execute('''
            SELECT reaction, count
            FROM reactions
            WHERE message_id = ?
        ''', (message_id,))
        reactions = dict(cursor.fetchall())
        
        socketio.emit('reaction_update', {
            'message_id': message_id,
            'reactions': reactions
        })
        
        return 'OK', 200
    except Exception as e:
        print(f"Error adding reaction: {e}")
        return 'Error', 500

BASE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rad Message Board</title>
    <style>
        :root {
            --bg-color: #000;
            --text-color: #fff;
            --border-color: #fff;
            --input-bg-color: #000;
            --input-text-color: #fff;
            --button-bg-color: #fff;
            --button-text-color: #000;
            --tag-bg-color: #fff;
            --tag-text-color: #000;
        }
        body {
            font-family: 'Courier New', monospace;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 20px;
            transition: background-color 0.3s, color 0.3s;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        h1, h2 {
            border-bottom: 4px solid var(--border-color);
            padding-bottom: 10px;
        }
        .message, .comment {
            border: 4px solid var(--border-color);
            padding: 10px;
            margin-bottom: 20px;
        }
        .message-content, .comment-content {
            margin-bottom: 10px;
            word-wrap: break-word;
        }
        .message-meta, .comment-meta {
            font-size: 0.8em;
            color: #ccc;
            margin-bottom: 10px;
        }
        form {
            margin-bottom: 20px;
        }
        input[type="text"], textarea {
            width: calc(100% - 24px);
            padding: 10px;
            margin-bottom: 10px;
            background-color: var(--input-bg-color);
            color: var(--input-text-color);
            border: 2px solid var(--border-color);
        }
        input[type="submit"], button {
            background-color: var(--button-bg-color);
            color: var(--button-text-color);
            border: none;
            padding: 10px 20px;
            cursor: pointer;
        }
        .comments-section {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 2px solid var(--border-color);
        }
        .tag {
            display: inline-block;
            background-color: var(--tag-bg-color);
            color: var(--tag-text-color);
            padding: 2px 5px;
            margin-right: 5px;
            font-size: 0.8em;
        }
        .tag-cloud {
            margin-bottom: 20px;
        }
        #generated-image {
            max-width: 100%;
            height: auto;
            margin-top: 10px;
        }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script>
        var socket = io();
        
        function generateImage() {
            var prompt = document.getElementById('image-prompt').value;
            fetch('/generate_image', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'prompt=' + encodeURIComponent(prompt)
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert('Error: ' + data.error);
                } else {
                    document.getElementById('generated-image').src = 'data:image/png;base64,' + data.image_data;
                    document.getElementById('generated-image').style.display = 'block';
                    document.getElementById('image-data').value = data.image_data;
                }
            });
        }
        
        socket.on('new_message', function(message) {
            var messagesContainer = document.querySelector('.container');
            var newMessageElement = document.createElement('div');
            newMessageElement.className = 'message';
            newMessageElement.innerHTML = `
                <div class="message-content">${message.content}</div>
                ${message.image_data ? `<img src="data:image/png;base64,${message.image_data}" alt="Generated Image" style="max-width: 100%; height: auto;">` : ''}
                <div class="message-meta">
                    Posted on ${message.timestamp}
                </div>
                <div class="message-tags">
                    ${message.tags.map(tag => `<span class="tag">${tag}</span>`).join('')}
                </div>
                <div class="comments-section"></div>
                <form action="/post_comment/${message.id}" method="post">
                    <input type="text" name="content" placeholder="Add a comment" required>
                    <input type="submit" value="Post Comment">
                </form>
                <div class="reactions">
                    <button onclick="addReaction(${message.id}, '👍')">👍 0</button>
                    <button onclick="addReaction(${message.id}, '❤️')">❤️ 0</button>
                    <button onclick="addReaction(${message.id}, '😂')">😂 0</button>
                    <button onclick="addReaction(${message.id}, '😮')">😮 0</button>
                </div>
            `;
            messagesContainer.insertBefore(newMessageElement, messagesContainer.firstChild);
        });
        
        socket.on('new_comment', function(comment) {
            var messageElement = document.querySelector(`[data-message-id="${comment.message_id}"]`);
            if (messageElement) {
                var commentsSection = messageElement.querySelector('.comments-section');
                var newCommentElement = document.createElement('div');
                newCommentElement.className = 'comment';
                newCommentElement.innerHTML = `
                    <div class="comment-content">${comment.content}</div>
                    <div class="comment-meta">
                        Posted on ${comment.timestamp}
                    </div>
                `;
                commentsSection.appendChild(newCommentElement);
            }
        });

        socket.on('reaction_update', function(data) {
            var messageElement = document.querySelector(`[data-message-id="${data.message_id}"]`);
            if (messageElement) {
                var reactionsElement = messageElement.querySelector('.reactions');
                if (reactionsElement) {
                    for (var reaction in data.reactions) {
                        var button = reactionsElement.querySelector(`[data-reaction="${reaction}"]`);
                        if (button) {
                            button.textContent = `${reaction} ${data.reactions[reaction]}`;
                        }
                    }
                }
            }
        });

        function addReaction(messageId, reaction) {
            fetch(`/add_reaction/${messageId}/${reaction}`, {method: 'GET'})
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                })
                .catch(error => console.error('Error:', error));
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>Rad Message Board</h1>
        {% if popular_tags %}
            <div class="tag-cloud">
                <h2>Popular Tags</h2>
                {% for tag, count in popular_tags %}
                    <a href="{{ url_for('view_tag', tag_name=tag) }}" class="tag">{{ tag }} ({{ count }})</a>
                {% endfor %}
            </div>
        {% endif %}
        <form action="{{ url_for('post_message') }}" method="post">
            <textarea name="content" placeholder="What's on your mind?" required></textarea>
            <input type="text" name="tags" placeholder="Tags (comma-separated)">
            <input type="text" id="image-prompt" placeholder="Image generation prompt">
            <button type="button" onclick="generateImage()">Generate Image</button>
            <img id="generated-image" src="" alt="Generated Image" style="display:none;">
            <input type="hidden" id="image-data" name="image_data">
            <input type="submit" value="Post Message">
        </form>
        {% for message in messages %}
            <div class="message" data-message-id="{{ message[0] }}">
                <div class="message-content">{{ message[1] }}</div>
                {% if message[2] %}
                    <img src="data:image/png;base64,{{ message[2] }}" alt="Generated Image" style="max-width: 100%; height: auto;">
                {% endif %}
                <div class="message-meta">
                    Posted on {{ message[3] }}
                </div>
                {% if message[5] %}
                    <div class="message-tags">
                        {% for tag in message[5] %}
                            <a href="{{ url_for('view_tag', tag_name=tag) }}" class="tag">{{ tag }}</a>
                        {% endfor %}
                    </div>
                {% endif %}
                <div class="reactions">
                    <button onclick="addReaction({{ message[0] }}, '👍')" data-reaction="👍">👍 {{ message[6].get('👍', 0) }}</button>
                    <button onclick="addReaction({{ message[0] }}, '❤️')" data-reaction="❤️">❤️ {{ message[6].get('❤️', 0) }}</button>
                    <button onclick="addReaction({{ message[0] }}, '😂')" data-reaction="😂">😂 {{ message[6].get('😂', 0) }}</button>
                    <button onclick="addReaction({{ message[0] }}, '😮')" data-reaction="😮">😮 {{ message[6].get('😮', 0) }}</button>
                </div>
                {% if message[4] %}
                    <div class="comments-section">
                        <h3>Comments:</h3>
                        {% for comment in message[4] %}
                            <div class="comment">
                                <div class="comment-content">{{ comment[0] }}</div>
                                <div class="comment-meta">
                                    Posted on {{ comment[1] }}
                                </div>
                            </div>
                        {% endfor %}
                    </div>
                {% endif %}
                <form action="{{ url_for('post_comment', message_id=message[0]) }}" method="post">
                    <input type="text" name="content" placeholder="Add a comment" required>
                    <input type="submit" value="Post Comment">
                </form>
            </div>
        {% endfor %}
    </div>
</body>
</html>
'''

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

if __name__ == '__main__':
    socketio.run(app, debug=True)