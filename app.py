from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import os
import random
import requests
import time  # Add this import
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='gevent',
    logger=True,
    engineio_logger=True
)
games = {}
MAX_GUESSES = 6

# Pre-validated words - add more if needed
VALID_WORDS = ['apple', 'beach', 'chair', 'dance', 'eagle', 'flask', 'grape', 'house', 
               'igloo', 'juice', 'knife', 'lemon', 'mango', 'night', 'ocean', 'paper', 
               'queen', 'river', 'sugar', 'table', 'under', 'voice', 'water', 'xylyl', 
               'yacht', 'zebra']

def get_random_word():
    """Fetch a random 5-letter word and verify it exists in dictionary"""
    # First try to get a word from our pre-validated list
    if VALID_WORDS:
        return random.choice(VALID_WORDS)
    
    # If that fails, try the API
    try:
        response = requests.get('https://random-word-api.herokuapp.com/word?length=5')
        if response.status_code == 200:
            words = response.json()
            if words and len(words) > 0:
                word = words[0].lower()
                # Verify the word exists in dictionary
                if is_valid_word(word):
                    logger.info(f"Successfully found valid word: {word}")
                    return word
                else:
                    logger.info(f"Word {word} not found in dictionary, trying from backup list")
                    return random.choice(VALID_WORDS)
    except Exception as e:
        logger.error(f"Error fetching random word: {e}")
    
    # Use fallback words if API fails
    logger.info("Using fallback word from pre-validated list")
    return random.choice(VALID_WORDS)

def is_valid_word(word):
    """Check if a word exists in the dictionary"""
    try:
        # Add a small delay to avoid rate limiting
        time.sleep(0.1)
        response = requests.get(f'https://api.dictionaryapi.dev/api/v2/entries/en/{word}')
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error checking word validity: {e}")
        return False

def check_word(guess, target):
    """Check the guess against the target word and return the result"""
    result = []
    remaining_letters = {}
    for letter in target:
        remaining_letters[letter] = remaining_letters.get(letter, 0) + 1

    # First pass: mark correct letters
    for i, letter in enumerate(guess):
        if letter == target[i]:
            result.append('correct')
            remaining_letters[letter] -= 1
        else:
            result.append(None)

    # Second pass: mark present and absent letters
    for i, letter in enumerate(guess):
        if result[i] is None:
            if letter in remaining_letters and remaining_letters[letter] > 0:
                result[i] = 'present'
                remaining_letters[letter] -= 1
            else:
                result[i] = 'absent'

    return result

def check_game_over(game):
    """Check if the game should end"""
    player1_guesses = len(game['guesses']['player1'])
    player2_guesses = len(game['guesses']['player2'])
    
    # Check if either player has won
    for player_id in ['player1', 'player2']:
        if game['guesses'][player_id]:
            last_guess = game['guesses'][player_id][-1]
            if all(r == 'correct' for r in last_guess['result']):
                return True, player_id
    
    # Check if both players have used all guesses
    if player1_guesses >= MAX_GUESSES and player2_guesses >= MAX_GUESSES:
        return True, None
    
    return False, None

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f"Client disconnected: {request.sid}")
    for game_id, game in list(games.items()):
        if request.sid in game['players']:
            player_id = game['players'][request.sid]
            emit('player_disconnected', {'player_id': player_id}, room=game_id)
            games.pop(game_id, None)
            print(f"Game {game_id} ended due to player disconnect")

@socketio.on('create_game')
def on_create_game():
    """Handle game creation"""
    game_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))
    word = get_random_word()
    print(f"Created game {game_id} with word: {word}")
    games[game_id] = {
        'word': word,
        'players': {},
        'guesses': {'player1': [], 'player2': []},
        'status': 'waiting'
    }
    games[game_id]['players'][request.sid] = 'player1'
    join_room(game_id)
    emit('game_created', {
        'game_id': game_id,
        'player_id': 'player1',
        'status': 'waiting'
    })
    print(f"Player1 {request.sid} joined game {game_id}")

@socketio.on('join_game')
def on_join_game(data):
    """Handle player joining a game"""
    game_id = data['game_id']
    print(f"Attempting to join game: {game_id}")
    print(f"Available games: {list(games.keys())}")
    print(f"Current players in game: {games.get(game_id, {}).get('players', {})}")
    
    if game_id not in games:
        emit('error', {'message': ''})
        return
        
    if len(games[game_id]['players']) >= 2:
        emit('error', {'message': ''})
        return

    # Add the player to the game
    games[game_id]['players'][request.sid] = 'player2'
    games[game_id]['status'] = 'playing'
    join_room(game_id)
    
    # Notify the joining player
    emit('game_joined', {
        'player_id': 'player2',
        'status': 'playing'
    })
    
    # Notify all players that game is starting
    emit('game_start', {
        'status': 'playing'
    }, room=game_id)
    
    print(f"Player2 {request.sid} joined game {game_id}")

@socketio.on('make_guess')
def on_make_guess(data):
    """Handle player guesses"""
    game_id = data['game_id']
    guess = data['guess'].lower()
    player_id = data['player_id']
    
    print(f"Received guess from {player_id} in game {game_id}: {guess}")
    
    if game_id not in games:
        emit('error', {'message': ''})
        return

    game = games[game_id]
    
    # Check if player has used all guesses
    if len(game['guesses'][player_id]) >= MAX_GUESSES:
        return

    # Validate guess length
    if len(guess) != 5:
        emit('error', {'message': ''})
        return

    # Check if word exists in dictionary
    if not is_valid_word(guess):
        emit('error', {'message': ''})
        return

    # Calculate result
    result = check_word(guess, game['word'])
    
    # Update game state
    game['guesses'][player_id].append({
        'word': guess,
        'result': result
    })
    
    # Emit the guess result to all players
    emit('guess_made', {
        'player_id': player_id,
        'guess': guess,
        'result': result
    }, room=game_id)
    
    # Check if game should end
    game_over, winner = check_game_over(game)
    if game_over:
        game['status'] = 'finished'
        emit('game_over', {
            'winner': winner,
            'word': game['word']
        }, room=game_id)
        print(f"Game {game_id} ended. Winner: {winner}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=True
    )