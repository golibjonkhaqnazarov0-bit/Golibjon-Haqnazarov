"""
Kitoblar Platformasi Bot - Telegram Bot for Book Management
Barcha xususiyatlar: Foydalanuvchi panel, Admin panel, Kitob platformasi, Chat tizimi
"""

import logging
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import asyncio

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, ReplyKeyboardRemove, ChatMember
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from telegram.error import TelegramError
from telegram.constants import ChatMemberStatus

# ============================================================================
# KONFIGURATSIYA
# ============================================================================
BOT_TOKEN = "8652036002:AAEc19eM11fub5Qw7_slpI64Q7ZqkUcoFwA"
ADMIN_ID = 5982952682
REQUIRED_CHANNEL = "kitoblarim_77_7"
REQUIRED_CHANNEL_ID = -1001234567890  # Kanalning ID raqami (botni qo'shing)

# Database fayli
DB_FILE = "kitoblar_bot.db"

# States for conversations
(
    WAITING_BOOK_TITLE,
    WAITING_BOOK_AUTHOR,
    WAITING_BOOK_DESCRIPTION,
    WAITING_BOOK_FILE,
    WAITING_ADMIN_RESPONSE,
    WAITING_USER_MESSAGE,
) = range(6)

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_db():
    """Database'ni ishga tushirish"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_admin BOOLEAN DEFAULT 0,
            is_blocked BOOLEAN DEFAULT 0,
            is_premium BOOLEAN DEFAULT 0,
            points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            joined_date TEXT,
            last_active TEXT
        )
    """)
    
    # Books table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            description TEXT,
            file_id TEXT,
            cover_id TEXT,
            category TEXT,
            rating REAL DEFAULT 0,
            downloads INTEGER DEFAULT 0,
            uploaded_by INTEGER,
            upload_date TEXT,
            is_approved BOOLEAN DEFAULT 0
        )
    """)
    
    # User books (yuklab olingan kitoblar)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            book_id INTEGER,
            downloaded_date TEXT,
            rating INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(book_id) REFERENCES books(book_id)
        )
    """)
    
    # Chat messages (Admin chat)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message_text TEXT,
            is_from_admin BOOLEAN DEFAULT 0,
            message_date TEXT,
            is_answered BOOLEAN DEFAULT 0
        )
    """)
    
    # Ratings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            book_id INTEGER,
            rating INTEGER,
            review TEXT,
            rating_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(book_id) REFERENCES books(book_id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_db_connection():
    """Database ulanish"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================================
# USER MANAGEMENT
# ============================================================================

def add_user(user_id: int, username: str, first_name: str):
    """Yangi foydalanuvchini qo'shish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, joined_date, last_active)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, first_name, datetime.now().isoformat(), datetime.now().isoformat()))
    else:
        cursor.execute("""
            UPDATE users SET last_active = ? WHERE user_id = ?
        """, (datetime.now().isoformat(), user_id))
    
    conn.commit()
    conn.close()

def get_user(user_id: int) -> Dict:
    """Foydalanuvchi ma'lumotlarini olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    return dict(user) if user else None

def add_points(user_id: int, points: int):
    """Foydalanuvchiga ball qo'shish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE users SET points = points + ? WHERE user_id = ?
    """, (points, user_id))
    
    conn.commit()
    conn.close()

# ============================================================================
# BOOK MANAGEMENT
# ============================================================================

def add_book(title: str, author: str, description: str, file_id: str, 
             category: str, uploaded_by: int) -> int:
    """Yangi kitob qo'shish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO books (title, author, description, file_id, category, uploaded_by, upload_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, author, description, file_id, category, uploaded_by, datetime.now().isoformat()))
    
    conn.commit()
    book_id = cursor.lastrowid
    conn.close()
    
    return book_id

def get_all_books(limit: int = 10, offset: int = 0) -> List[Dict]:
    """Barcha kitoblarni olish (faqat tasdiqlanganlar)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM books WHERE is_approved = 1 
        ORDER BY upload_date DESC LIMIT ? OFFSET ?
    """, (limit, offset))
    
    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return books

def get_book(book_id: int) -> Dict:
    """Kitobni ID orqali olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM books WHERE book_id = ?", (book_id,))
    book = cursor.fetchone()
    conn.close()
    
    return dict(book) if book else None

def search_books(query: str) -> List[Dict]:
    """Kitoblarni izlash"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM books 
        WHERE is_approved = 1 AND (
            title LIKE ? OR author LIKE ? OR description LIKE ?
        )
        ORDER BY rating DESC LIMIT 10
    """, (f"%{query}%", f"%{query}%", f"%{query}%"))
    
    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return books

# ============================================================================
# HANDLER FUNCTIONS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot ning start komandasi"""
    user = update.effective_user
    add_user(user.id, user.username or "Anonim", user.first_name)
    
    # Obuna tekshirish
    try:
        member = await context.bot.get_chat_member(f"@{REQUIRED_CHANNEL}", user.id)
        is_subscribed = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        is_subscribed = False
    
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Kanalga obuna bo'ling", url=f"https://t.me/{REQUIRED_CHANNEL}")],
            [InlineKeyboardButton("✅ Tekshirish", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            "🔒 Botdan foydalanish uchun avval kanalga obuna bo'lishing kerak!\n\n"
            f"Kanal: @{REQUIRED_CHANNEL}",
            reply_markup=keyboard
        )
        return
    
    # Asosiy menu
    keyboard = ReplyKeyboardMarkup([
        ["📚 Kitoblarni ko'rish", "🔍 Kitob izlash"],
        ["⭐ Mening reyitngim", "👤 Profil"],
        ["💬 Admin bilan suhbatlash", "🎮 Statistika"]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        f"👋 Assalamu alaykum, {user.first_name}!\n\n"
        "📚 Kitoblar platformasiga xush kelibsiz!\n\n"
        "🎯 Quyidagi variantlardan birini tanlang:",
        reply_markup=keyboard
    )

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obunani tekshirish"""
    user = update.effective_user
    
    try:
        member = await context.bot.get_chat_member(f"@{REQUIRED_CHANNEL}", user.id)
        is_subscribed = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        is_subscribed = False
    
    if is_subscribed:
        await update.callback_query.answer("✅ Rahmat! Siz obuna bo'ldingiz!")
        await start(update, context)
    else:
        await update.callback_query.answer("❌ Avval kanalga obuna bo'ling!", show_alert=True)

async def show_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kitoblarni ko'rsatish"""
    books = get_all_books(limit=5)
    
    if not books:
        await update.message.reply_text("📭 Hozirda kitoblar mavjud emas.")
        return
    
    message = "📚 **Eng so'nggi kitoblar:**\n\n"
    
    for book in books:
        message += f"📖 **{book['title']}**\n"
        message += f"👤 Muallif: {book['author']}\n"
        message += f"⭐ Reyting: {book['rating']}/5\n"
        message += f"📥 Yuklab olingan: {book['downloads']} marta\n"
        message += f"━━━━━━━━━\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Kitobni ochish", callback_data=f"book_{books[0]['book_id']}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_menu")]
    ])
    
    await update.message.reply_text(message, reply_markup=keyboard, parse_mode="Markdown")

async def search_books_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kitob izlash"""
    await update.message.reply_text("🔍 Izlash so'zini kiriting:")
    return WAITING_USER_MESSAGE

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin paneli"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    keyboard = ReplyKeyboardMarkup([
        ["👥 Foydalanuvchilar", "📚 Kitoblar"],
        ["💬 Xabarlar", "📊 Statistika"],
        ["⬅️ Orqaga"]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        "🛠 **Admin Paneli**\n\n"
        "Quyidagi amallardan birini tanlang:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin - Foydalanuvchilarni boshqarish"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_blocked = 1")
    blocked_users = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_premium = 1")
    premium_users = cursor.fetchone()['count']
    
    conn.close()
    
    message = f"""
📊 **Foydalanuvchilar Statistikasi**

👥 Jami foydalanuvchilar: {total_users}
💎 Premium foydalanuvchilar: {premium_users}
🚫 Bloklangan foydalanuvchilar: {blocked_users}
"""
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin - Foydalanuvchi xabarlarini ko'rish"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM chat_messages 
        WHERE is_from_admin = 0 AND is_answered = 0
        LIMIT 5
    """)
    
    messages = cursor.fetchall()
    conn.close()
    
    if not messages:
        await update.message.reply_text("📭 Javob berish uchun xabar yo'q.")
        return
    
    message_text = "💬 **Javob berish kerak bo'lgan xabarlar:**\n\n"
    
    for msg in messages:
        message_text += f"📩 User ID: {msg['user_id']}\n"
        message_text += f"💬 Xabar: {msg['message_text']}\n"
        message_text += f"⏰ Vaqti: {msg['message_date']}\n"
        message_text += "━━━━━━━━━\n"
    
    await update.message.reply_text(message_text, parse_mode="Markdown")

async def user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi xabarini admin ga yuboring"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO chat_messages (user_id, message_text, message_date)
        VALUES (?, ?, ?)
    """, (user_id, message_text, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()
    
    # Admin ga bildirishnoma yuborish
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 Yangi xabar:\n\nUser ID: {user_id}\n\n"
            f"Xabar:\n{message_text}"
        )
    except:
        pass
    
    await update.message.reply_text(
        "✅ Xabaringiz admin ga yuborildi!\n"
        "Tez orada javob olasiz."
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi profili"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Profil topilmadi.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM user_books WHERE user_id = ?", (user_id,))
    downloaded_books = cursor.fetchone()['count']
    
    conn.close()
    
    message = f"""
👤 **Mening Profilim**

👤 Ism: {user['first_name']}
💎 Daraja: Level {user['level']}
⭐ Balllar: {user['points']} 🎯
📚 Yuklab olingan kitoblar: {downloaded_books}
📅 Qo'shilgan sana: {user['joined_date'][:10]}
"""
    
    keyboard = ReplyKeyboardMarkup([
        ["⬅️ Orqaga"]
    ], resize_keyboard=True)
    
    await update.message.reply_text(message, reply_markup=keyboard, parse_mode="Markdown")

# ============================================================================
# ERROR HANDLER
# ============================================================================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xatolarni boshqarish"""
    logging.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_chat:
        await update.effective_chat.send_message(
            "❌ Xatolik yuz berdi. Iltimos keyinroq urinib ko'ring."
        )

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Bot ning asosiy funksiyasi"""
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Database'ni ishga tushirish
    init_db()
    
    # Application yaratish
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers qo'shish
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    app.add_handler(MessageHandler(filters.Regex("📚 Kitoblarni ko'rish"), show_books))
    app.add_handler(MessageHandler(filters.Regex("🔍 Kitob izlash"), search_books_handler))
    app.add_handler(MessageHandler(filters.Regex("👤 Profil"), profile))
    app.add_handler(MessageHandler(filters.Regex("👥 Foydalanuvchilar"), admin_users))
    app.add_handler(MessageHandler(filters.Regex("💬 Xabarlar"), admin_messages))
    app.add_handler(MessageHandler(filters.Regex("💬 Admin bilan suhbatlash"), user_message))
    
    app.add_handler(CallbackQueryHandler(check_subscription, pattern="check_subscription"))
    
    app.add_error_handler(error_handler)
    
    # Botni ishga tushirish
    print("🚀 Bot ishga tushdi!")
    print(f"Admin ID: {ADMIN_ID}")
    print(f"Kanal: @{REQUIRED_CHANNEL}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
