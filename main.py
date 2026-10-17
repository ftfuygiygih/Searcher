import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import requests
import threading
import time
import os
import shutil
from flask import Flask

# --- НАСТРОЙКИ ---
BOT_TOKEN = '8994240402:AAGOx1hgsvl2aXfZ0YDtiSltdJLWkM3A7nA'
ADMIN_ID = 8705859046

# --- БАЗА ДАННЫХ (Для хранения тем пользователей) ---
conn = sqlite3.connect('arts.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, theme TEXT, is_active INTEGER)')
conn.commit()

# --- ФУНКЦИИ DANBOORU ---
def get_random_art(tag):
    try:
        # Ищем 1 случайный пост по тегу
        url = f"https://danbooru.donmai.us/posts.json?tags={tag}&random=true&limit=1"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers).json()
        
        if response and len(response) > 0:
            post = response[0]
            # Берем ссылку на картинку в высоком качестве
            file_url = post.get('file_url') or post.get('large_file_url')
            return file_url
    except Exception as e:
        print(f"Ошибка Danbooru: {e}")
    return None

# --- ФОНОВАЯ РАССЫЛКА (1 АРТ В МИНУТУ) ---
def art_sender():
    while True:
        try:
            cursor.execute("SELECT user_id, theme FROM users WHERE is_active=1 AND theme IS NOT NULL")
            users = cursor.fetchall()
            
            for user_id, theme in users:
                art_url = get_random_art(theme)
                if art_url:
                    markup = InlineKeyboardMarkup()
                    markup.add(
                        InlineKeyboardButton("👍 В коллекцию", callback_data="save_art"),
                        InlineKeyboardButton("🗑 В мусор", callback_data="del_art")
                    )
                    bot.send_photo(user_id, art_url, reply_markup=markup)
        except Exception as e:
            print(f"Ошибка рассылки: {e}")
        
        time.sleep(60) # Пауза 60 секунд (60 артов в час)

# --- КОМАНДЫ БОТА ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    cursor.execute('INSERT OR IGNORE INTO users (user_id, is_active) VALUES (?, 0)', (message.from_user.id,))
    conn.commit()
    bot.send_message(message.chat.id, "🎨 Привет! Я парсер артов.\n\nИспользуй `/sl [тема]`, чтобы задать тег (например: `/sl alya` или `/sl cyberpunk`).\nПосле этого я начну присылать по 1 арту в минуту!\n\nОстановить поток: `/stop`", parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop_cmd(message):
    cursor.execute('UPDATE users SET is_active=0 WHERE user_id=?', (message.from_user.id,))
    conn.commit()
    bot.send_message(message.chat.id, "⏸ Рассылка артов остановлена.")

@bot.message_handler(commands=['sl'])
def set_theme(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "❌ Укажи тег! Пример: `/sl cat_girl`", parse_mode="Markdown")
        return
    
    theme = args[1].strip().lower()
    cursor.execute('UPDATE users SET theme=?, is_active=1 WHERE user_id=?', (theme, message.from_user.id))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Тема установлена: **{theme}**.\nНачинаю поиск, первый арт прилетит в течение минуты!", parse_mode="Markdown")

@bot.message_handler(commands=['zipS'])
def create_zip(message):
    user_id = message.from_user.id
    user_folder = f"saved_arts/{user_id}"
    
    if not os.path.exists(user_folder) or not os.listdir(user_folder):
        bot.send_message(user_id, "📭 У тебя пока нет сохраненных артов. Нажимай 👍 под картинками!")
        return

    bot.send_message(user_id, "📦 Пакую арты в архив, секунду...")
    
    zip_path = f"saved_arts/arts_{user_id}.zip"
    # Создаем ZIP-архив
    shutil.make_archive(zip_path.replace('.zip', ''), 'zip', user_folder)
    
    # Отправляем
    with open(zip_path, 'rb') as f:
        bot.send_document(user_id, f, caption="🎨 Твоя коллекция!")
    
    # Очищаем папку и удаляем сам архив после отправки
    shutil.rmtree(user_folder)
    os.remove(zip_path)

# --- ОБРАБОТКА КНОПОК ---
@bot.callback_query_handler(func=lambda call: call.data in ["save_art", "del_art"])
def handle_buttons(call):
    user_id = call.from_user.id
    
    if call.data == "del_art":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "🗑 Удалено")
    
    elif call.data == "save_art":
        # Создаем папку юзера, если её нет
        user_folder = f"saved_arts/{user_id}"
        os.makedirs(user_folder, exist_ok=True)
        
        try:
            # Получаем file_id картинки прямо из сообщения Телеграма
            file_id = call.message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Сохраняем файл
            file_name = f"{user_folder}/art_{int(time.time())}.jpg"
            with open(file_name, 'wb') as new_file:
                new_file.write(downloaded_file)
            
            # Меняем кнопки, чтобы нельзя было сохранить дважды
            bot.edit_message_reply_markup(
                call.message.chat.id, 
                call.message.message_id, 
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("✅ Сохранено в архив", callback_data="none"))
            )
            bot.answer_callback_query(call.id, "✅ Сохранено!")
            
        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Ошибка сохранения", show_alert=True)
            print(e)

# --- МИКРО-СЕРВЕР ДЛЯ RENDER И ЗАПУСК ---
app = Flask(__name__)
@app.route('/')
def keep_alive(): return "Арт-парсер работает!"

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))).start()
    threading.Thread(target=art_sender).start() # Запуск фонового парсера
    print("Бот запущен!")
    bot.infinity_polling()
