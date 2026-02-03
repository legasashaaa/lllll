import asyncio
import json
import os
import re
import time
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty, InputPeerUser, InputPeerChannel
import logging

# Конфигурация - ОБА: и бот, и сессия
API_ID = 2040  # Телеграм API ID
API_HASH = 'b18441a1ff607e10a989891a5462e627'  # Телеграм API Hash
BOT_TOKEN = '8274874473:AAGQTVHI3CkwzotIuqiS6M2Whptcp-EpTnY'  # Ваш токен бота
OWNER_ID = 8524326478  # Ваш ID
SESSION_NAME = '+380962151936'  # Имя сессии вашего аккаунта

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Файлы для хранения данных
CONFIG_FILE = 'bot_config.json'
CACHE_FILE = 'cache.json'
RECORDINGS_FILE = 'recordings.json'
TYPING_SPEED_FILE = 'typing_speed.json'  # Новый файл для хранения скорости печати

class BotInterface:
    """Класс для работы с ботом (кнопки, меню)"""
    
    def __init__(self, token):
        self.token = token
        self.bot = None
        self.user_client = None  # Клиент для сессии пользователя
        self.config = {}
        self.recordings = {}
        self.typing_speed = {}  # Данные о скорости печати
        self.active_monitoring = True
        self.is_recording = False  # Флаг записи
        self.is_typing_test = False  # Флаг теста скорости печати
        self.current_recording = []  # Текущая запись
        self.current_recording_chat = None  # Чат текущей записи
        self.pending_recording_send = None  # Ожидающая отправка записи
        self.pending_file_send = None  # Ожидающая отправка из файла
        self.pending_typing_test = None  # Ожидающий тест скорости
        self.deletion_stats = {
            'total_deleted': 0,
            'deleted_today': 0,
            'by_user': {},
            'by_chat': {}
        }
        self.recording_start_time = 0  # Время начала записи
        self.last_message_time = 0  # Время последнего сообщения в записи
        self.typing_test_data = []  # Данные теста скорости печати
        self.typing_test_start_time = 0  # Время начала теста
        self.typing_test_last_time = 0  # Время последнего сообщения в тесте
        
    async def initialize(self):
        """Инициализация бота"""
        logger.info("Инициализация бота...")
        
        # Загружаем конфигурацию и записи
        self.config = self.load_config()
        self.recordings = self.load_recordings()
        self.typing_speed = self.load_typing_speed()  # Загружаем скорость печати
        
        # Восстанавливаем правильные задержки для старых записей
        self.fix_old_recordings()
        
        # Создаем клиент для бота
        self.bot = TelegramClient(
            'bot_session',
            API_ID,
            API_HASH
        )
        
        # Запускаем бота с токеном
        await self.bot.start(bot_token=self.token)
        
        # Получаем информацию о боте
        me = await self.bot.get_me()
        logger.info(f"🤖 Бот запущен как @{me.username}")
        
        # Регистрируем обработчики команд бота
        await self.register_bot_handlers()
        
        return self.bot
    
    async def start_user_session(self):
        """Запуск сессии пользователя для удаления сообщений"""
        logger.info("Запуск сессии пользователя...")
        
        # Создаем клиент для сессии пользователя
        self.user_client = TelegramClient(
            SESSION_NAME,
            API_ID,
            API_HASH
        )
        
        # Запускаем сессию пользователя
        await self.user_client.start()
        
        # Получаем информацию о пользователе
        user_me = await self.user_client.get_me()
        logger.info(f"👤 Сессия пользователя: {user_me.first_name} (ID: {user_me.id})")
        
        # Регистрируем обработчик для удаления сообщений
        await self.register_user_handlers()
        
        return self.user_client
    
    def load_config(self):
        """Загрузка конфигурации"""
        default_config = {
            'blacklist': [],  # Список пользователей
            'enabled_chats': [],  # Список чатов
            'enabled_for_all': True,  # Работать во всех чатах
            'delete_notifications': False,  # Уведомления ВЫКЛЮЧЕНЫ по умолчанию
            'delete_delay': 0  # Задержка удаления
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
        
        return default_config
    
    def load_recordings(self):
        """Загрузка записей"""
        try:
            if os.path.exists(RECORDINGS_FILE):
                with open(RECORDINGS_FILE, 'r', encoding='utf-8') as f:
                    recordings = json.load(f)
                    
                    # Конвертируем старый формат в новый
                    return self.convert_old_recordings(recordings)
        except Exception as e:
            logger.error(f"Ошибка загрузки записей: {e}")
        
        return {}
    
    def load_typing_speed(self):
        """Загрузка данных о скорости печати"""
        default_speed = {
            'words_per_minute': 200,  # слов в минуту по умолчанию
            'words_per_second': 3.33,  # слов в секунду по умолчанию
            'characters_per_minute': 1000,  # символов в минуту по умолчанию
            'average_words_per_message': 1,  # среднее количество слов в сообщении
            'average_delay_between_messages': 0.3,  # средняя задержка между сообщениями
            'last_test_date': None,  # дата последнего теста
            'test_messages_count': 0  # количество сообщений в тесте
        }
        
        try:
            if os.path.exists(TYPING_SPEED_FILE):
                with open(TYPING_SPEED_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки скорости печати: {e}")
        
        return default_speed
    
    def save_typing_speed(self):
        """Сохранение данных о скорости печати"""
        try:
            with open(TYPING_SPEED_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.typing_speed, f, ensure_ascii=False, indent=2)
            logger.info("Данные о скорости печати сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения скорости печати: {e}")
    
    def convert_old_recordings(self, recordings):
        """Конвертация старых записей в новый формат"""
        converted = {}
        
        for rec_id, recording in recordings.items():
            # Проверяем, есть ли поле messages
            if 'messages' not in recording:
                continue
                
            messages = recording['messages']
            
            # Если это старый формат без delay_since_last
            if messages and len(messages) > 0 and 'delay_since_last' not in messages[0]:
                logger.info(f"Конвертируем старую запись: {rec_id}")
                
                # Пересчитываем задержки
                for i, msg in enumerate(messages):
                    if i == 0:
                        msg['delay_since_last'] = 0.0
                    else:
                        # Вычисляем разницу во времени между сообщениями
                        time_diff = msg['time_offset'] - messages[i-1]['time_offset']
                        msg['delay_since_last'] = max(0.0, time_diff)  # Убедимся, что не отрицательное
                
                recording['messages'] = messages
                recording['message_count'] = len(messages)
            
            converted[rec_id] = recording
        
        return converted
    
    def fix_old_recordings(self):
        """Исправление старых записей при загрузке"""
        for rec_id, recording in self.recordings.items():
            if 'messages' in recording:
                messages = recording['messages']
                
                # Проверяем и исправляем каждое сообщение
                for i, msg in enumerate(messages):
                    # Убедимся, что все необходимые поля есть
                    if 'delay_since_last' not in msg:
                        msg['delay_since_last'] = 0.0
                    
                    # Исправляем отрицательные задержки
                    if msg['delay_since_last'] < 0:
                        msg['delay_since_last'] = 0.0
                    
                    # Исправляем слишком большие задержки (больше 60 секунд)
                    if msg['delay_since_last'] > 60:
                        msg['delay_since_last'] = 1.0  # Устанавливаем разумную задержку
                
                recording['messages'] = messages
        
        # Сохраняем исправленные записи
        self.save_recordings()
    
    def save_config(self):
        """Сохранение конфигурации"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
    
    def save_recordings(self):
        """Сохранение записей"""
        try:
            with open(RECORDINGS_FILE, 'w', encoding='utf-8') as f:
                # Убедимся, что все записи в правильном формате
                clean_recordings = {}
                for rec_id, recording in self.recordings.items():
                    clean_recording = recording.copy()
                    # Удаляем временные поля
                    if 'temp' in clean_recording:
                        del clean_recording['temp']
                    clean_recordings[rec_id] = clean_recording
                
                json.dump(clean_recordings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения записей: {e}")
    
    async def register_bot_handlers(self):
        """Регистрация обработчиков для бота (меню, команды)"""
        
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            """Обработчик команды /start"""
            if event.sender_id == OWNER_ID:
                await self.send_main_menu(event)
        
        @self.bot.on(events.NewMessage(pattern='/menu'))
        async def menu_handler(event):
            """Обработчик команды /menu"""
            if event.sender_id == OWNER_ID:
                await self.send_main_menu(event)
        
        @self.bot.on(events.NewMessage(pattern='/add'))
        async def add_handler(event):
            """Обработчик команды /add"""
            if event.sender_id == OWNER_ID:
                await self.handle_add_command(event)
        
        @self.bot.on(events.NewMessage(pattern='/remove'))
        async def remove_handler(event):
            """Обработчик команды /remove"""
            if event.sender_id == OWNER_ID:
                await self.handle_remove_command(event)
        
        @self.bot.on(events.NewMessage(pattern='/list'))
        async def list_handler(event):
            """Обработчик команды /list"""
            if event.sender_id == OWNER_ID:
                await self.show_blacklist(event)
        
        @self.bot.on(events.NewMessage(pattern='/stats'))
        async def stats_handler(event):
            """Обработчик команды /stats"""
            if event.sender_id == OWNER_ID:
                await self.show_stats(event)
        
        @self.bot.on(events.NewMessage(pattern='/toggle'))
        async def toggle_handler(event):
            """Обработчик команды /toggle"""
            if event.sender_id == OWNER_ID:
                self.active_monitoring = not self.active_monitoring
                status = "✅ Включен" if self.active_monitoring else "⏸️ Приостановлен"
                await event.reply(f"**Мониторинг:** {status}")
        
        @self.bot.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            """Обработчик команды /help"""
            if event.sender_id == OWNER_ID:
                await self.show_help(event)
        
        @self.bot.on(events.NewMessage(pattern='/chats'))
        async def chats_handler(event):
            """Обработчик команды /chats"""
            if event.sender_id == OWNER_ID:
                await self.show_chat_menu(event)
        
        @self.bot.on(events.NewMessage(pattern='/record'))
        async def record_handler(event):
            """Обработчик команды /record - начать запись"""
            if event.sender_id == OWNER_ID:
                await self.start_recording(event)
        
        @self.bot.on(events.NewMessage(pattern='/stop'))
        async def stop_handler(event):
            """Обработчик команды /stop - остановить запись"""
            if event.sender_id == OWNER_ID:
                await self.stop_recording(event)
        
        @self.bot.on(events.NewMessage(pattern='/recordings'))
        async def recordings_handler(event):
            """Обработчик команды /recordings - показать записи"""
            if event.sender_id == OWNER_ID:
                await self.show_recordings_menu(event)
        
        @self.bot.on(events.NewMessage(pattern='/speed_test'))
        async def speed_test_handler(event):
            """Обработчик команды /speed_test - анализ скорости печати"""
            if event.sender_id == OWNER_ID:
                await self.start_typing_speed_test(event)
        
        @self.bot.on(events.NewMessage(pattern='/stop_test'))
        async def stop_test_handler(event):
            """Обработчик команды /stop_test - остановить тест скорости"""
            if event.sender_id == OWNER_ID:
                await self.stop_typing_speed_test(event)
        
        @self.bot.on(events.NewMessage(pattern='/speed_stats'))
        async def speed_stats_handler(event):
            """Обработчик команды /speed_stats - статистика скорости"""
            if event.sender_id == OWNER_ID:
                await self.show_typing_speed_stats(event)
        
        @self.bot.on(events.NewMessage(pattern='/send_file'))
        async def send_file_handler(event):
            """Обработчик команды /send_file - отправка из файла"""
            if event.sender_id == OWNER_ID:
                await self.start_file_send_mode(event)
        
        # Обработчик ввода ID чата для отправки записи
        @self.bot.on(events.NewMessage)
        async def chat_input_handler(event):
            """Обработка ввода ID чата для отправки записи"""
            if event.sender_id == OWNER_ID:
                if self.pending_recording_send:
                    if self.pending_recording_send.get('step') == 'chat_input':
                        await self.handle_chat_input(event)
                    elif self.pending_recording_send.get('step') == 'user_input':
                        await self.process_target_user(event)
                    elif self.pending_recording_send.get('step') == 'message_link':
                        await self.process_message_link(event, event.message.text)
                elif self.pending_file_send:
                    if self.pending_file_send.get('step') == 'chat_input':
                        await self.handle_file_chat_input(event)
                    elif self.pending_file_send.get('step') == 'target_user':
                        await self.handle_file_target_user(event)
                    elif self.pending_file_send.get('step') == 'words_per_message':
                        await self.handle_words_per_message_input(event)
        
        # Обработчик пересланных сообщений для добавления пользователей
        @self.bot.on(events.NewMessage)
        async def forwarded_handler(event):
            """Обработка пересланных сообщений"""
            if event.sender_id == OWNER_ID and event.message.forward:
                await self.handle_forwarded_message(event)
        
        # Обработчик медиа (файлов)
        @self.bot.on(events.NewMessage(func=lambda e: e.message.file))
        async def file_handler(event):
            """Обработка файлов"""
            if event.sender_id == OWNER_ID:
                await self.handle_file_upload(event)
        
        # Обработчик callback запросов (кнопки)
        @self.bot.on(events.CallbackQuery)
        async def callback_handler(event):
            """Обработчик нажатий на кнопки"""
            await self.handle_callback(event)
    
    async def register_user_handlers(self):
        """Регистрация обработчиков для сессии пользователя (удаление)"""
        
        @self.user_client.on(events.NewMessage())
        async def message_handler(event):
            """Обработчик сообщений для удаления"""
            if not self.active_monitoring:
                return
            
            try:
                # Проверяем, является ли сообщение реплаем
                if event.message.reply_to_msg_id:
                    await self.handle_reply_for_deletion(event)
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}")
            
            # Если идет запись, сохраняем сообщение
            if self.is_recording and event.sender_id == OWNER_ID:
                await self.save_to_recording(event)
            
            # Если идет тест скорости печати
            if self.is_typing_test and event.sender_id == OWNER_ID:
                await self.save_typing_test_data(event)
    
    async def save_to_recording(self, event):
        """Сохранение сообщения в текущую запись"""
        try:
            # Пропускаем служебные команды
            if event.message.text in ['/record', '/stop', '/recordings']:
                return
            
            # Получаем текущее время
            current_time = time.time()
            
            # Если это первое сообщение в записи
            if not self.current_recording:
                self.recording_start_time = current_time
                time_offset = 0.0
                delay_since_last = 0.0
            else:
                # Рассчитываем время от начала записи
                time_offset = current_time - self.recording_start_time
                # Рассчитываем задержку с предыдущего сообщения
                delay_since_last = current_time - self.last_message_time
            
            # Сохраняем данные сообщения
            message_data = {
                'timestamp': current_time,
                'time_offset': round(time_offset, 3),  # Округляем до миллисекунд
                'delay_since_last': round(delay_since_last, 3),  # Округляем до миллисекунд
                'text': event.message.text or '',
                'chat_id': event.chat_id,
                'message_id': event.message.id
            }
            
            # Если есть медиа, сохраняем информацию
            if event.message.media:
                message_data['has_media'] = True
                # Здесь можно добавить сохранение медиа
            
            self.current_recording.append(message_data)
            self.last_message_time = current_time
            
            # Логируем
            logger.info(f"📝 Запись: сохранено сообщение в {time_offset:.3f}с (задержка: {delay_since_last:.3f}с)")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения в запись: {e}")
    
    async def save_typing_test_data(self, event):
        """Сохранение данных теста скорости печати"""
        try:
            # Пропускаем служебные команды
            if event.message.text in ['/speed_test', '/stop_test']:
                return
            
            # Получаем текущее время
            current_time = time.time()
            
            # Если это первое сообщение в тесте
            if not self.typing_test_data:
                self.typing_test_start_time = current_time
                time_offset = 0.0
                delay_since_last = 0.0
            else:
                # Рассчитываем время от начала теста
                time_offset = current_time - self.typing_test_start_time
                # Рассчитываем задержку с предыдущего сообщения
                delay_since_last = current_time - self.typing_test_last_time
            
            # Подсчитываем слова в сообщении
            text = event.message.text or ''
            words = len(text.split())
            characters = len(text)
            
            # Сохраняем данные теста
            test_data = {
                'timestamp': current_time,
                'time_offset': round(time_offset, 3),
                'delay_since_last': round(delay_since_last, 3),
                'text': text,
                'words': words,
                'characters': characters,
                'chat_id': event.chat_id,
                'message_id': event.message.id
            }
            
            self.typing_test_data.append(test_data)
            self.typing_test_last_time = current_time
            
            # Логируем
            logger.info(f"📊 Тест скорости: {words} слов, {characters} символов, задержка: {delay_since_last:.3f}с")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения данных теста: {e}")
    
    async def start_typing_speed_test(self, event):
        """Начать тест скорости печати"""
        if self.is_typing_test:
            await event.reply("⚠️ Тест скорости уже идет!")
            return
        
        self.is_typing_test = True
        self.typing_test_data = []
        self.typing_test_start_time = 0
        self.typing_test_last_time = 0
        
        await event.reply(
            "📊 **Начат тест скорости печати!**\n\n"
            "Теперь все ваши сообщения будут анализироваться для определения скорости печати.\n\n"
            "**Что анализируется:**\n"
            "• Количество слов в сообщении\n"
            "• Количество символов\n"
            "• Задержки между сообщениями\n"
            "• Общая скорость печати\n\n"
            "**Рекомендации:**\n"
            "1. Пишите как обычно, без спешки\n"
            "2. Отправляйте хотя бы 10-20 сообщений\n"
            "3. Разные сообщения (короткие и длинные)\n"
            "4. Используйте /stop_test чтобы завершить тест\n\n"
            "⚠️ Не используйте команды /speed_test, /stop_test во время теста!"
        )
        logger.info("Тест скорости печати начат")
    
    async def stop_typing_speed_test(self, event):
        """Остановить тест скорости и проанализировать данные"""
        if not self.is_typing_test:
            await event.reply("⚠️ Тест скорости не идет!")
            return
        
        if not self.typing_test_data:
            self.is_typing_test = False
            await event.reply("❌ Данные теста пусты!")
            return
        
        # Анализируем данные
        await self.analyze_typing_speed(event)
        
        # Сбрасываем состояние теста
        self.is_typing_test = False
        test_data = self.typing_test_data
        self.typing_test_data = []
        self.typing_test_start_time = 0
        self.typing_test_last_time = 0
        
        logger.info("Тест скорости печати завершен")
    
    async def analyze_typing_speed(self, event):
        """Проанализировать скорость печати"""
        if not self.typing_test_data:
            return
        
        try:
            # Рассчитываем статистику
            total_words = sum(msg['words'] for msg in self.typing_test_data)
            total_characters = sum(msg['characters'] for msg in self.typing_test_data)
            total_messages = len(self.typing_test_data)
            
            if total_messages == 0:
                await event.reply("❌ Нет данных для анализа!")
                return
            
            # Общее время теста
            total_time = self.typing_test_data[-1]['time_offset'] if self.typing_test_data else 0
            total_time_minutes = total_time / 60
            
            # Рассчитываем скорости
            words_per_minute = total_words / total_time_minutes if total_time_minutes > 0 else 0
            words_per_second = words_per_minute / 60
            characters_per_minute = total_characters / total_time_minutes if total_time_minutes > 0 else 0
            
            # Среднее количество слов в сообщении
            avg_words_per_message = total_words / total_messages
            
            # Средняя задержка между сообщениями
            total_delays = sum(msg['delay_since_last'] for msg in self.typing_test_data[1:])  # Первое сообщение имеет задержку 0
            avg_delay = total_delays / (total_messages - 1) if total_messages > 1 else 0
            
            # Сохраняем результаты
            self.typing_speed = {
                'words_per_minute': round(words_per_minute, 2),
                'words_per_second': round(words_per_second, 3),
                'characters_per_minute': round(characters_per_minute, 2),
                'average_words_per_message': round(avg_words_per_message, 2),
                'average_delay_between_messages': round(avg_delay, 3),
                'last_test_date': time.time(),
                'test_messages_count': total_messages,
                'total_test_time': round(total_time, 2)
            }
            
            # Сохраняем данные
            self.save_typing_speed()
            
            # Формируем отчет
            report = (
                f"📊 **Анализ скорости печати завершен!**\n\n"
                f"**📈 Результаты:**\n"
                f"• 📝 Сообщений проанализировано: **{total_messages}**\n"
                f"• ⏱️ Общее время теста: **{total_time:.1f} секунд**\n"
                f"• 🔤 Всего слов: **{total_words}**\n"
                f"• 🔡 Всего символов: **{total_characters}**\n\n"
                f"**⚡ Скорость печати:**\n"
                f"• 🚀 Слов в минуту: **{words_per_minute:.1f}**\n"
                f"• ⚡ Слов в секунду: **{words_per_second:.3f}**\n"
                f"• 🔤 Символов в минуту: **{characters_per_minute:.0f}**\n\n"
                f"**📊 Средние показатели:**\n"
                f"• 💬 Слов в сообщении: **{avg_words_per_message:.1f}**\n"
                f"• ⏱️ Задержка между сообщениями: **{avg_delay:.3f}с**\n\n"
                f"✅ **Данные сохранены!**\n"
                f"Теперь вы можете использовать функцию отправки из файла."
            )
            
            # Добавляем сравнение
            if self.typing_speed.get('last_test_date'):
                old_wpm = self.typing_speed.get('words_per_minute', 0)
                diff = words_per_minute - old_wpm
                if diff != 0:
                    trend = "⬆️ Выше" if diff > 0 else "⬇️ Ниже"
                    report += f"\n\n📊 **Изменение:** {trend} на {abs(diff):.1f} слов/минуту"
            
            await event.reply(report)
            
            logger.info(f"Скорость печати: {words_per_minute:.1f} WPM, {words_per_second:.3f} WPS")
            
        except Exception as e:
            logger.error(f"Ошибка анализа скорости печати: {e}")
            await event.reply(f"❌ Ошибка анализа: {str(e)}")
    
    async def show_typing_speed_stats(self, event):
        """Показать статистику скорости печати"""
        if not self.typing_speed or 'words_per_minute' not in self.typing_speed:
            await event.reply(
                "📊 **Данные о скорости печати отсутствуют**\n\n"
                "Для анализа вашей скорости печати:\n"
                "1. Используйте /speed_test или кнопку 'Анализ скорости'\n"
                "2. Пишите сообщения как обычно\n"
                "3. Используйте /stop_test для завершения\n\n"
                "Бот проанализирует вашу скорость и сохранит данные.",
                buttons=[
                    [Button.inline("📊 Анализ скорости", b"typing_speed_test")],
                    [Button.inline("↩️ Назад", b"main_menu")]
                ]
            )
            return
        
        last_test_date = self.typing_speed.get('last_test_date')
        if last_test_date:
            date_str = datetime.fromtimestamp(last_test_date).strftime('%d.%m.%Y %H:%M')
        else:
            date_str = "Неизвестно"
        
        stats_text = (
            f"📊 **Ваша скорость печати**\n\n"
            f"**📈 Основные показатели:**\n"
            f"• 🚀 Слов в минуту: **{self.typing_speed['words_per_minute']:.1f}**\n"
            f"• ⚡ Слов в секунду: **{self.typing_speed['words_per_second']:.3f}**\n"
            f"• 🔤 Символов в минуту: **{self.typing_speed['characters_per_minute']:.0f}**\n\n"
            f"**📊 Средние показатели:**\n"
            f"• 💬 Слов в сообщении: **{self.typing_speed['average_words_per_message']:.1f}**\n"
            f"• ⏱️ Задержка между сообщениями: **{self.typing_speed['average_delay_between_messages']:.3f}с**\n\n"
            f"**📅 Тест проведен:** {date_str}\n"
            f"📝 Сообщений в тесте: **{self.typing_speed.get('test_messages_count', 0)}**\n"
            f"⏱️ Время теста: **{self.typing_speed.get('total_test_time', 0):.1f}с**\n\n"
            f"📎 **Скорость будет использована для отправки из файла**"
        )
        
        buttons = [
            [Button.inline("🔄 Новый тест", b"typing_speed_test")],
            [Button.inline("📤 Отправить из файла", b"send_from_file")],
            [Button.inline("⚙️ Настроить отправку", b"file_send_settings")],
            [Button.inline("↩️ Назад", b"main_menu")]
        ]
        
        await event.reply(stats_text, buttons=buttons, parse_mode='md')
    
    async def start_file_send_mode(self, event):
        """Начать режим отправки из файла"""
        if not self.typing_speed or 'words_per_minute' not in self.typing_speed:
            await event.reply(
                "📄 **Для отправки из файла нужна ваша скорость печати!**\n\n"
                "Сначала проведите тест скорости:\n"
                "1. Используйте /speed_test или кнопку 'Анализ скорости'\n"
                "2. Пишите сообщения как обычно\n"
                "3. Используйте /stop_test для завершения\n\n"
                "Бот сохранит вашу скорость и тогда вы сможете отправлять сообщения из файла.",
                buttons=[
                    [Button.inline("📊 Анализ скорости", b"typing_speed_test")],
                    [Button.inline("↩️ Назад", b"main_menu")]
                ]
            )
            return
        
        await event.reply(
            "📄 **Режим отправки сообщений из файла**\n\n"
            "**Шаг 1:** Отправьте текстовый файл (.txt) с сообщениями\n"
            "**Шаг 2:** Укажите чат для отправки\n"
            "**Шаг 3:** Укажите пользователя для ответа (опционально)\n"
            "**Шаг 4:** Настройте отправку\n\n"
            "**Формат файла:**\n"
            "• Обычный текст\n"
            "• Каждое сообщение на новой строке (опционально)\n"
            "• Бот разобьет текст на слова\n\n"
            "**Как работает:**\n"
            "• Бот отправляет по 1-4 слова в сообщении\n"
            "• Сохраняет вашу оригинальную скорость печати\n"
            "• Может отвечать на сообщения пользователя\n"
            "• Найдет новое сообщение если старое удалено\n\n"
            "📎 **Отправьте текстовый файл (.txt) чтобы начать**",
            buttons=[
                [Button.inline("↩️ Назад", b"main_menu")]
            ]
        )
        
        # Устанавливаем ожидание файла
        self.pending_file_send = {
            'step': 'awaiting_file',
            'event': event
        }
    
    async def handle_file_upload(self, event):
        """Обработка загрузки файла"""
        if not self.pending_file_send:
            return
        
        try:
            file = event.message.file
            if not file.name or not file.name.endswith('.txt'):
                await event.reply("❌ Пожалуйста, отправьте текстовый файл (.txt)")
                return
            
            # Скачиваем файл
            await event.reply("📥 **Загружаю файл...**")
            file_path = await event.message.download_media()
            
            # Читаем содержимое файла
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Очищаем текст
            content = content.strip()
            
            if not content:
                await event.reply("❌ Файл пуст!")
                os.remove(file_path)
                return
            
            # Разбиваем на слова
            words = content.split()
            
            if not words:
                await event.reply("❌ В файле нет слов!")
                os.remove(file_path)
                return
            
            # Сохраняем данные файла
            self.pending_file_send['file_path'] = file_path
            self.pending_file_send['content'] = content
            self.pending_file_send['words'] = words
            self.pending_file_send['total_words'] = len(words)
            self.pending_file_send['step'] = 'chat_input'
            
            await event.reply(
                f"✅ **Файл загружен!**\n\n"
                f"📄 Имя файла: {file.name}\n"
                f"📊 Всего слов: **{len(words)}**\n"
                f"🔤 Символов: **{len(content)}**\n\n"
                f"**Шаг 2:** Укажите чат для отправки\n\n"
                f"Отправьте ID чата или username:\n"
                f"Примеры:\n"
                f"• `-1001234567890` (ID группы/канала)\n"
                f"• `@username` (юзернейм)\n"
                f"• `username` (без @)\n"
                f"• `123456789` (ID пользователя)\n\n"
                f"Или нажмите кнопку 'Отправить сюда'",
                buttons=[
                    [Button.inline("📨 Отправить сюда", b"file_send_here")],
                    [Button.inline("↩️ Отмена", b"main_menu")]
                ]
            )
            
        except Exception as e:
            logger.error(f"Ошибка обработки файла: {e}")
            await event.reply(f"❌ Ошибка обработки файла: {str(e)}")
    
    async def handle_file_chat_input(self, event):
        """Обработка ввода чата для отправки из файла"""
        if not self.pending_file_send or self.pending_file_send.get('step') != 'chat_input':
            return
        
        try:
            # Получаем введенный текст
            chat_input = event.message.text.strip()
            
            # Получаем информацию о чате
            chat_info = await self.get_chat_info(chat_input)
            
            if not chat_info:
                await event.reply("❌ Не удалось найти чат. Попробуйте еще раз.")
                return
            
            # Сохраняем информацию о чате
            self.pending_file_send['chat_info'] = chat_info
            self.pending_file_send['step'] = 'target_user'
            
            await event.reply(
                f"✅ **Чат определен:** {chat_info.get('title', f'ID: {chat_info[\"id\"]}')}\n\n"
                f"**Шаг 3:** Выберите пользователя для ответа (опционально)\n\n"
                f"Отправьте username или ID пользователя, на чье сообщение отвечать:\n"
                f"Примеры:\n"
                f"• `@username`\n"
                f"• `123456789` (ID пользователя)\n\n"
                f"**Как это работает:**\n"
                f"• Бот найдет последнее сообщение пользователя\n"
                f"• Будет отправлять сообщения, отвечая на него\n"
                f"• Если сообщение удалено, найдет новое или предыдущее\n"
                f"• Если не указать пользователя - отправка без ответа\n\n"
                f"**Если не хотите отвечать на сообщение, нажмите кнопку:**",
                buttons=[
                    [Button.inline("📤 Без ответа", b"file_no_reply")],
                    [Button.inline("↩️ Назад", b"main_menu")]
                ]
            )
            
            # Удаляем сообщение с вводом
            try:
                await event.delete()
            except:
                pass
            
        except Exception as e:
            logger.error(f"Ошибка обработки ввода чата: {e}")
            await event.reply(f"❌ Ошибка: {str(e)}")
    
    async def handle_file_target_user(self, event):
        """Обработка целевого пользователя для отправки из файла"""
        if not self.pending_file_send or self.pending_file_send.get('step') != 'target_user':
            return
        
        try:
            user_input = event.message.text.strip()
            
            if user_input.lower() in ['нет', 'no', 'без ответа', 'skip']:
                # Пропускаем выбор пользователя
                self.pending_file_send['target_user'] = None
                self.pending_file_send['step'] = 'words_per_message'
                await self.ask_words_per_message(event)
                return
            
            # Получаем информацию о пользователе
            user_info = await self.get_user_info(user_input)
            
            if not user_info:
                await event.reply("❌ Не удалось найти пользователя. Попробуйте еще раз или нажмите 'Без ответа'.")
                return
            
            # Сохраняем информацию о пользователе
            self.pending_file_send['target_user'] = user_info
            self.pending_file_send['step'] = 'words_per_message'
            
            # Ищем последнее сообщение пользователя
            chat_info = self.pending_file_send['chat_info']
            user_display = self.format_user_display(user_info)
            
            await event.reply(f"🔍 **Ищу последнее сообщение пользователя {user_display}...**")
            
            target_message = await self.find_user_message(chat_info['id'], user_info['id'])
            
            if target_message:
                self.pending_file_send['target_message_id'] = target_message.id
                await self.ask_words_per_message(event)
            else:
                await event.reply(
                    f"❌ **Сообщение не найдено!**\n\n"
                    f"Не удалось найти сообщения пользователя {user_display} в этом чате.\n"
                    f"Продолжить без ответа на сообщение?",
                    buttons=[
                        [Button.inline("📤 Без ответа", b"file_no_reply")],
                        [Button.inline("↩️ Отмена", b"main_menu")]
                    ]
                )
            
            # Удаляем сообщение с вводом
            try:
                await event.delete()
            except:
                pass
            
        except Exception as e:
            logger.error(f"Ошибка обработки целевого пользователя: {e}")
            await event.reply(f"❌ Ошибка: {str(e)}")
    
    async def ask_words_per_message(self, event):
        """Спросить количество слов в сообщении"""
        chat_info = self.pending_file_send['chat_info']
        target_user = self.pending_file_send.get('target_user')
        
        chat_title = chat_info.get('title', f'ID: {chat_info["id"]}')
        
        if target_user:
            user_display = self.format_user_display(target_user)
            reply_info = f"📎 **Ответ пользователю:** {user_display}"
            if self.pending_file_send.get('target_message_id'):
                reply_info += f"\n💬 Ответ на сообщение: `{self.pending_file_send['target_message_id']}`"
        else:
            reply_info = "📤 **Отправка без ответа**"
        
        await event.reply(
            f"✅ **Настройка отправки**\n\n"
            f"💬 **Чат:** {chat_title}\n"
            f"{reply_info}\n\n"
            f"**Шаг 4:** Настройте отправку\n\n"
            f"📊 **Ваша скорость печати:**\n"
            f"• 🚀 {self.typing_speed['words_per_minute']:.1f} слов/минуту\n"
            f"• ⚡ {self.typing_speed['words_per_second']:.3f} слов/секунду\n"
            f"• 💬 Обычно {self.typing_speed['average_words_per_message']:.1f} слов в сообщении\n\n"
            f"📝 **Из файла:** {self.pending_file_send['total_words']} слов\n"
            f"⏱️ **Примерное время:** {self.pending_file_send['total_words'] / self.typing_speed['words_per_minute'] * 60:.1f} сек.\n\n"
            f"**Выберите количество слов в сообщении:**",
            buttons=[
                [Button.inline("1 слово в сообщении", b"file_words_1")],
                [Button.inline("2 слова в сообщении", b"file_words_2")],
                [Button.inline("3 слова в сообщении", b"file_words_3")],
                [Button.inline("4 слова в сообщении", b"file_words_4")],
                [Button.inline("↩️ Назад", b"main_menu")]
            ]
        )
    
    async def handle_words_per_message_input(self, event):
        """Обработка ввода количества слов в сообщении"""
        if not self.pending_file_send or self.pending_file_send.get('step') != 'words_per_message':
            return
        
        try:
            text = event.message.text.strip()
            if text.isdigit():
                words_per_message = int(text)
                if 1 <= words_per_message <= 10:
                    self.pending_file_send['words_per_message'] = words_per_message
                    await self.confirm_file_send(event)
                    return
            
            await event.reply("❌ Пожалуйста, введите число от 1 до 10")
            
        except Exception as e:
            logger.error(f"Ошибка обработки ввода слов: {e}")
            await event.reply(f"❌ Ошибка: {str(e)}")
    
    async def confirm_file_send(self, event):
        """Подтверждение отправки из файла"""
        chat_info = self.pending_file_send['chat_info']
        target_user = self.pending_file_send.get('target_user')
        words_per_message = self.pending_file_send.get('words_per_message', 1)
        total_words = self.pending_file_send['total_words']
        
        chat_title = chat_info.get('title', f'ID: {chat_info["id"]}')
        
        if target_user:
            user_display = self.format_user_display(target_user)
            reply_info = f"📎 **Ответ пользователю:** {user_display}"
            if self.pending_file_send.get('target_message_id'):
                reply_info += f"\n💬 Ответ на сообщение: `{self.pending_file_send['target_message_id']}`"
        else:
            reply_info = "📤 **Отправка без ответа**"
        
        # Рассчитываем статистику
        total_messages = (total_words + words_per_message - 1) // words_per_message  # Округляем вверх
        estimated_time = total_words / self.typing_speed['words_per_minute'] * 60
        delay_between_messages = self.typing_speed['average_delay_between_messages']
        
        await event.reply(
            f"✅ **Подтверждение отправки**\n\n"
            f"💬 **Чат:** {chat_title}\n"
            f"{reply_info}\n\n"
            f"📄 **Файл:**\n"
            f"• 📊 Всего слов: **{total_words}**\n"
            f"• 💬 Слов в сообщении: **{words_per_message}**\n"
            f"• 📝 Всего сообщений: **{total_messages}**\n\n"
            f"⚡ **Скорость отправки:**\n"
            f"• 🚀 {self.typing_speed['words_per_minute']:.1f} слов/минуту\n"
            f"• ⚡ {self.typing_speed['words_per_second']:.3f} слов/секунду\n"
            f"• ⏱️ Задержка между сообщениями: **{delay_between_messages:.3f}с**\n\n"
            f"⏱️ **Примерное время отправки:** {estimated_time:.1f} секунд\n"
            f"📅 **Начало:** {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"**Начать отправку?**",
            buttons=[
                [Button.inline("🚀 Начать отправку", b"file_execute_send")],
                [Button.inline("⚙️ Изменить настройки", b"file_change_settings")],
                [Button.inline("↩️ Отмена", b"main_menu")]
            ]
        )
    
    async def execute_file_send(self, event):
        """Выполнить отправку из файла"""
        if not self.pending_file_send:
            await event.answer("❌ Нет данных для отправки", alert=True)
            return
        
        try:
            # Получаем данные
            chat_info = self.pending_file_send['chat_info']
            target_user = self.pending_file_send.get('target_user')
            target_message_id = self.pending_file_send.get('target_message_id')
            words_per_message = self.pending_file_send.get('words_per_message', 1)
            words = self.pending_file_send['words']
            total_words = len(words)
            
            chat_id = chat_info['id']
            chat_title = chat_info.get('title', f'ID: {chat_id}')
            
            # Рассчитываем общее количество сообщений
            total_messages = (total_words + words_per_message - 1) // words_per_message
            
            # Обновляем сообщение
            await event.edit(f"🚀 **Начинаю отправку из файла...**\n\n⏳ 0% (0/{total_messages})")
            
            # Начинаем отправку
            sent_count = 0
            start_time = time.time()
            last_progress_update = start_time
            
            # Подготавливаем слова для отправки
            word_groups = []
            for i in range(0, len(words), words_per_message):
                group = words[i:i + words_per_message]
                word_groups.append(' '.join(group))
            
            # Текущее сообщение для ответа (если есть)
            current_reply_to = target_message_id
            failed_attempts = 0
            max_failed_attempts = 3
            
            for i, text in enumerate(word_groups):
                # Рассчитываем задержку для сохранения оригинальной скорости
                if i > 0:
                    # Используем сохраненную задержку между сообщениями
                    delay = self.typing_speed['average_delay_between_messages']
                    if delay > 0:
                        await asyncio.sleep(delay)
                
                # Отправляем сообщение
                try:
                    if current_reply_to and i == 0:
                        # Первое сообщение как реплай
                        sent_msg = await self.user_client.send_message(
                            chat_id,
                            text,
                            reply_to=current_reply_to
                        )
                    else:
                        # Остальные как обычные сообщения
                        sent_msg = await self.user_client.send_message(
                            chat_id,
                            text
                        )
                    
                    sent_count += 1
                    failed_attempts = 0  # Сброс счетчика ошибок
                    
                except Exception as e:
                    error_str = str(e)
                    
                    # Если ошибка из-за удаленного сообщения и это первое сообщение с реплаем
                    if i == 0 and current_reply_to and ("MESSAGE_ID_INVALID" in error_str or "REPLY_MESSAGE_ID_INVALID" in error_str):
                        logger.info(f"⚠️ Сообщение {current_reply_to} удалено, ищу новое...")
                        failed_attempts += 1
                        
                        if failed_attempts <= max_failed_attempts and target_user:
                            # Ищем новое сообщение пользователя
                            new_message = await self.find_user_message(chat_id, target_user['id'], current_reply_to)
                            
                            if new_message:
                                logger.info(f"✅ Найдено новое сообщение: {new_message.id}")
                                current_reply_to = new_message.id
                                
                                # Пробуем отправить с новым reply_to
                                try:
                                    sent_msg = await self.user_client.send_message(
                                        chat_id,
                                        text,
                                        reply_to=current_reply_to
                                    )
                                    sent_count += 1
                                    continue  # Успешно отправили, переходим к следующему
                                except Exception as e2:
                                    logger.info(f"⚠️ Ошибка с новым сообщением {current_reply_to}: {e2}")
                                    # Пробуем отправить без ответа
                        
                        # Если не нашли новое сообщение или ошибка, отправляем без ответа
                        logger.info(f"📤 Отправляю первое сообщение без ответа")
                        try:
                            sent_msg = await self.user_client.send_message(
                                chat_id,
                                text
                            )
                            sent_count += 1
                        except Exception as e3:
                            logger.error(f"❌ Не удалось отправить сообщение {i}: {e3}")
                    else:
                        # Другая ошибка
                        logger.error(f"❌ Не удалось отправить сообщение {i}: {error_str}")
                
                # Обновляем прогресс
                progress = int((i + 1) / len(word_groups) * 100)
                current_time = time.time()
                
                if progress % 10 == 0 or current_time - last_progress_update > 2:
                    try:
                        await event.edit(f"🚀 **Отправка из файла...**\n\n⏳ {progress}% ({i+1}/{len(word_groups)})")
                    except:
                        pass  # Игнорируем ошибки редактирования
                    last_progress_update = current_time
            
            total_time = time.time() - start_time
            
            # Формируем итоговое сообщение
            result_text = (
                f"✅ **Отправка из файла завершена!**\n\n"
                f"📊 **Результаты:**\n"
                f"• 📝 Отправлено сообщений: **{sent_count}/{len(word_groups)}**\n"
                f"• 🔤 Отправлено слов: **{min(sent_count * words_per_message, total_words)}/{total_words}**\n"
                f"• ⏱️ Общее время: **{total_time:.1f} секунд**\n"
                f"• 💬 Чат: {chat_title}\n"
            )
            
            if target_user:
                user_display = self.format_user_display(target_user)
                result_text += f"• 👤 Ответ пользователю: {user_display}\n"
                if current_reply_to:
                    result_text += f"• 📎 Последнее сообщение: `{current_reply_to}`\n"
            
            # Рассчитываем фактическую скорость
            actual_words_per_minute = (sent_count * words_per_message) / (total_time / 60) if total_time > 0 else 0
            result_text += f"\n⚡ **Фактическая скорость:** {actual_words_per_minute:.1f} слов/минуту\n"
            
            if abs(actual_words_per_minute - self.typing_speed['words_per_minute']) > 10:
                result_text += f"📊 **Отклонение от вашей скорости:** {abs(actual_words_per_minute - self.typing_speed['words_per_minute']):.1f} слов/минуту\n"
            
            try:
                await event.edit(result_text)
            except:
                pass
            
            logger.info(f"Отправка из файла завершена: {sent_count} сообщений в чат {chat_id}")
            
            # Очищаем временный файл
            if 'file_path' in self.pending_file_send and os.path.exists(self.pending_file_send['file_path']):
                os.remove(self.pending_file_send['file_path'])
            
            # Сбрасываем состояние
            self.pending_file_send = None
            
        except Exception as e:
            logger.error(f"Ошибка отправки из файла: {e}")
            try:
                await event.edit(f"❌ **Ошибка отправки:**\n\n{str(e)[:300]}")
            except:
                pass
            
            # Очищаем временный файл при ошибке
            if self.pending_file_send and 'file_path' in self.pending_file_send and os.path.exists(self.pending_file_send['file_path']):
                os.remove(self.pending_file_send['file_path'])
            
            self.pending_file_send = None
    
    async def handle_reply_for_deletion(self, event):
        """Обработка реплаев для удаления ВСЕХ сообщений владельца в цепочке"""
        try:
            # Получаем сообщение, на которое сделан реплай
            chat_id = event.chat_id
            replied_msg = await event.get_reply_message()
            
            if not replied_msg:
                return
            
            # Проверяем, что реплай сделан на сообщение владельца
            if replied_msg.sender_id != OWNER_ID:
                return
            
            # Проверяем, включен ли мониторинг для этого чата
            if not self.config['enabled_for_all'] and chat_id not in self.config['enabled_chats']:
                return
            
            # Получаем информацию об отправителе реплая
            sender_id = event.sender_id
            sender = await event.get_sender()
            sender_username = getattr(sender, 'username', None)
            
            # Проверяем, находится ли отправитель в черном списке
            is_blacklisted = self.is_user_in_blacklist(sender_id, sender_username)
            
            if not is_blacklisted:
                return
            
            # Удаляем все сообщения владельца в цепочке
            await self.delete_all_owner_messages(event, replied_msg)
            
        except Exception as e:
            logger.error(f"Ошибка обработки реплая: {e}")
    
    async def delete_all_owner_messages(self, event, start_message):
        """Удаление всех сообщений владельца в цепочке"""
        try:
            chat_id = event.chat_id
            deleted_count = 0
            
            # Собираем все сообщения владельца в этой цепочке
            messages_to_delete = []
            
            # Начинаем с исходного сообщения
            current_msg = start_message
            
            while current_msg and current_msg.sender_id == OWNER_ID:
                messages_to_delete.append(current_msg)
                
                # Ищем следующее сообщение владельца в цепочке
                # (предыдущее по времени, так как обычно это ответы в одном потоке)
                try:
                    # Получаем предыдущие сообщения
                    async for msg in self.user_client.iter_messages(
                        chat_id,
                        min_id=current_msg.id - 50,
                        max_id=current_msg.id - 1,
                        from_user=OWNER_ID
                    ):
                        # Проверяем, является ли это частью той же цепочки
                        # (простая проверка по близости ID и времени)
                        messages_to_delete.append(msg)
                        break  # Берем только одно предыдущее
                        
                except:
                    pass
                
                # Прерываем цикл для предотвращения бесконечного поиска
                if len(messages_to_delete) >= 10:  # Максимум 10 сообщений
                    break
                
                # Для поиска вперед по цепочке
                try:
                    # Пробуем найти ответы на это сообщение от владельца
                    async for msg in self.user_client.iter_messages(
                        chat_id,
                        min_id=current_msg.id + 1,
                        max_id=current_msg.id + 50,
                        from_user=OWNER_ID,
                        reply_to=current_msg.id
                    ):
                        messages_to_delete.append(msg)
                        current_msg = msg
                        break
                    else:
                        # Если ответов нет, прерываем цикл
                        break
                except:
                    break
            
            # Удаляем все собранные сообщения
            for msg in messages_to_delete:
                try:
                    # Небольшая задержка для надежности
                    if self.config['delete_delay'] > 0:
                        await asyncio.sleep(self.config['delete_delay'])
                    
                    await msg.delete()
                    deleted_count += 1
                    
                    # Обновляем статистику
                    self.deletion_stats['total_deleted'] += 1
                    self.deletion_stats['deleted_today'] += 1
                    
                    user_id_str = str(event.sender_id)
                    chat_id_str = str(chat_id)
                    
                    if user_id_str not in self.deletion_stats['by_user']:
                        self.deletion_stats['by_user'][user_id_str] = 0
                    self.deletion_stats['by_user'][user_id_str] += 1
                    
                    if chat_id_str not in self.deletion_stats['by_chat']:
                        self.deletion_stats['by_chat'][chat_id_str] = 0
                    self.deletion_stats['by_chat'][chat_id_str] += 1
                    
                    # Логируем удаление (без отправки уведомлений, как вы просили)
                    logger.info(f"✅ Удалено сообщение {msg.id} в чате {chat_id}")
                    
                    # Небольшая пауза между удалениями
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    error_msg = f"❌ Ошибка при удалении сообщения {msg.id}: {str(e)}"
                    logger.error(error_msg)
            
            logger.info(f"🗑️ Удалено {deleted_count} сообщений от владельца")
            
        except Exception as e:
            logger.error(f"Ошибка при массовом удалении: {e}")
    
    def is_user_in_blacklist(self, user_id, username=None):
        """Проверка, находится ли пользователь в черном списке"""
        for user in self.config['blacklist']:
            # Проверка по ID
            if user['id'] == user_id:
                return True
            
            # Проверка по username
            if username and user.get('username'):
                if user['username'].lower() == username.lower():
                    return True
        
        return False
    
    async def send_main_menu(self, event):
        """Отправка главного меню"""
        menu_text = (
            f"🤖 **Главное меню - Автоудаление сообщений**\n\n"
            f"📊 **Статистика:**\n"
            f"• 👤 Пользователей в черном списке: **{len(self.config['blacklist'])}**\n"
            f"• 💬 Активных чатов: **{len(self.config['enabled_chats'])}**\n"
            f"• 🗑️ Всего удалено: **{self.deletion_stats['total_deleted']}**\n"
            f"• 🗑️ Удалено сегодня: **{self.deletion_stats['deleted_today']}**\n"
            f"• ⚡ Мониторинг: **{'✅ Активен' if self.active_monitoring else '⏸️ Приостановлен'}**\n"
            f"• 📝 Запись: **{'🔴 ВКЛ' if self.is_recording else '⚪ ВЫКЛ'}**\n"
            f"• 📊 Тест скорости: **{'🔴 ИДЕТ' if self.is_typing_test else '⚪ ВЫКЛ'}**\n\n"
            f"🌐 **Режим:** {'Все чаты' if self.config['enabled_for_all'] else 'Только выбранные'}\n"
        )
        
        # Добавляем информацию о скорости печати, если есть
        if self.typing_speed and 'words_per_minute' in self.typing_speed:
            menu_text += f"⚡ **Ваша скорость:** {self.typing_speed['words_per_minute']:.1f} слов/минуту\n"
        
        buttons = [
            [Button.inline("👤 Управление пользователями", b"user_management"),
             Button.inline("💬 Управление чатами", b"chat_management")],
            [Button.inline("📊 Статистика", b"stats_menu"),
             Button.inline("⚙️ Настройки", b"settings_menu")],
            [Button.inline("🎙️ Записи", b"recordings_menu"),
             Button.inline("📋 Помощь", b"help_menu")],
            [Button.inline("📊 Анализ скорости", b"typing_speed_test"),
             Button.inline("📄 Отправка из файла", b"send_from_file")]
        ]
        
        if self.is_recording:
            buttons.insert(2, [Button.inline("⏹️ Остановить запись", b"stop_recording")])
        else:
            buttons.insert(2, [Button.inline("🎬 Начать запись", b"start_recording")])
        
        if self.is_typing_test:
            buttons.insert(3, [Button.inline("⏹️ Стоп тест скорости", b"stop_typing_test")])
        
        try:
            await event.reply(menu_text, buttons=buttons, parse_mode='md')
        except Exception as e:
            logger.error(f"Ошибка отправки главного меню: {e}")
    
    async def start_recording(self, event):
        """Начать запись сообщений"""
        if self.is_recording:
            await event.reply("⚠️ Запись уже идет!")
            return
        
        self.is_recording = True
        self.current_recording = []
        self.current_recording_chat = event.chat_id
        self.recording_start_time = 0
        self.last_message_time = 0
        
        await event.reply(
            "🎬 **Запись начата!**\n\n"
            "Теперь все ваши сообщения будут записываться.\n"
            "Используйте /stop для остановки записи.\n\n"
            "**Что записывается:**\n"
            "• Текст сообщений\n"
            "• Точное время отправки\n"
            "• Точные паузы между сообщениями\n"
            "• Порядок сообщений\n\n"
            "⚠️ Не используйте команды /record, /stop, /recordings во время записи!"
        )
        logger.info("Запись сообщений начата")
    
    async def stop_recording(self, event):
        """Остановить запись и сохранить"""
        if not self.is_recording:
            await event.reply("⚠️ Запись не идет!")
            return
        
        if not self.current_recording:
            self.is_recording = False
            await event.reply("❌ Запись пуста!")
            return
        
        # Проверяем и корректируем задержки перед сохранением
        self.fix_recording_delays()
        
        # Сохраняем запись
        recording_id = f"recording_{int(time.time())}"
        self.recordings[recording_id] = {
            'id': recording_id,
            'name': f"Запись от {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            'messages': self.current_recording.copy(),  # Используем копию
            'created_at': time.time(),
            'chat_id': self.current_recording_chat,
            'message_count': len(self.current_recording),
            'total_duration': self.current_recording[-1]['time_offset'] if self.current_recording else 0
        }
        
        self.save_recordings()
        
        # Сбрасываем состояние записи
        self.is_recording = False
        recording_data = self.current_recording
        self.current_recording = []
        self.current_recording_chat = None
        self.recording_start_time = 0
        self.last_message_time = 0
        
        await event.reply(
            f"✅ **Запись сохранена!**\n\n"
            f"📝 ID записи: `{recording_id}`\n"
            f"📊 Сообщений записано: **{len(recording_data)}**\n"
            f"⏱️ Длительность: **{recording_data[-1]['time_offset']:.3f} секунд**\n\n"
            f"Используйте /recordings для управления записями."
        )
        logger.info(f"Запись сохранена: {recording_id} ({len(recording_data)} сообщений)")
    
    def fix_recording_delays(self):
        """Исправление задержек в текущей записи"""
        if not self.current_recording:
            return
        
        # Пересчитываем задержки для надежности
        for i, msg in enumerate(self.current_recording):
            if i == 0:
                msg['delay_since_last'] = 0.0
            else:
                # Вычисляем разницу во времени между сообщениями
                time_diff = msg['time_offset'] - self.current_recording[i-1]['time_offset']
                # Убедимся, что задержка не отрицательная и не слишком большая
                msg['delay_since_last'] = max(0.0, min(time_diff, 60.0))
    
    async def show_recordings_menu(self, event):
        """Показать меню записей"""
        if not self.recordings:
            await event.reply(
                "📝 **У вас пока нет записей**\n\n"
                "Чтобы создать запись:\n"
                "1. Используйте /record или кнопку 'Начать запись'\n"
                "2. Пишите сообщения как обычно\n"
                "3. Используйте /stop для сохранения\n\n"
                "Запись сохранит все ваши сообщения с оригинальной скоростью и порядком.",
                buttons=[
                    [Button.inline("🎬 Начать запись", b"start_recording")],
                    [Button.inline("↩️ Назад", b"main_menu")]
                ]
            )
            return
        
        text = "📝 **Ваши записи:**\n\n"
        buttons = []
        
        for rec_id, recording in sorted(self.recordings.items(), 
                                        key=lambda x: x[1]['created_at'], 
                                        reverse=True)[:10]:  # Показываем последние 10
            
            rec_name = recording.get('name', f"Запись {rec_id[:8]}")
            msg_count = recording.get('message_count', len(recording.get('messages', [])))
            created_time = datetime.fromtimestamp(recording['created_at']).strftime('%d.%m %H:%M')
            duration = recording.get('total_duration', recording['messages'][-1]['time_offset'] if recording['messages'] else 0)
            
            text_line = f"• **{rec_name}**\n"
            text_line += f"  📊 {msg_count} сообщ., ⏱️ {duration:.1f}с, 📅 {created_time}\n"
            text += text_line
            
            buttons.append([Button.inline(f"▶️ {rec_name[:30]}", f"play_recording_{rec_id}")])
        
        buttons.append([Button.inline("🗑️ Удалить запись", b"delete_recording_menu")])
        buttons.append([Button.inline("↩️ Назад", b"main_menu")])
        
        await event.reply(text, buttons=buttons, parse_mode='md')
    
    async def play_recording(self, event, recording_id):
        """Воспроизвести запись"""
        if recording_id not in self.recordings:
            await event.answer("❌ Запись не найдена!", alert=True)
            return
        
        recording = self.recordings[recording_id]
        
        # Проверяем и исправляем запись перед воспроизведением
        self.check_and_fix_recording(recording)
        
        try:
            await event.edit(
                f"▶️ **Воспроизведение записи:** {recording.get('name', 'Без названия')}\n\n"
                f"📊 Сообщений: {recording.get('message_count', 0)}\n"
                f"⏱️ Длительность: {recording.get('total_duration', recording['messages'][-1]['time_offset'] if recording['messages'] else 0):.3f}с\n\n"
                "**Шаг 1: Куда отправить запись?**\n"
                "Отправьте ID чата или username:\n"
                "Примеры:\n"
                "• `-1001234567890` (ID группы/канала)\n"
                "• `@username` (юзернейм)\n"
                "• `username` (без @)\n"
                "• `123456789` (ID пользователя)\n\n"
                "Или нажмите кнопку 'Отправить сюда'",
                buttons=[
                    [Button.inline("📨 Отправить сюда", f"send_here_{recording_id}")],
                    [Button.inline("↩️ Назад", b"recordings_menu")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка редактирования сообщения", alert=True)
        
        # Сохраняем ожидающую отправку
        self.pending_recording_send = {
            'recording_id': recording_id,
            'step': 'chat_input',
            'event': event
        }
    
    def check_and_fix_recording(self, recording):
        """Проверить и исправить запись перед воспроизведением"""
        if 'messages' not in recording:
            return
        
        messages = recording['messages']
        needs_fix = False
        
        for i, msg in enumerate(messages):
            # Проверяем наличие всех необходимых полей
            if 'delay_since_last' not in msg:
                msg['delay_since_last'] = 0.0
                needs_fix = True
            
            if 'time_offset' not in msg:
                # Если нет time_offset, создаем его из delay_since_last
                if i == 0:
                    msg['time_offset'] = 0.0
                else:
                    msg['time_offset'] = messages[i-1]['time_offset'] + msg.get('delay_since_last', 0.0)
                needs_fix = True
            
            # Исправляем отрицательные или слишком большие задержки
            if msg['delay_since_last'] < 0:
                msg['delay_since_last'] = 0.0
                needs_fix = True
            
            if msg['delay_since_last'] > 60:
                msg['delay_since_last'] = 1.0
                needs_fix = True
        
        if needs_fix:
            # Пересчитываем time_offset на основе delay_since_last
            total_time = 0.0
            for i, msg in enumerate(messages):
                if i == 0:
                    msg['time_offset'] = 0.0
                else:
                    total_time += msg['delay_since_last']
                    msg['time_offset'] = total_time
            
            # Обновляем запись
            recording['messages'] = messages
            recording['total_duration'] = total_time if messages else 0.0
            
            # Сохраняем исправленную запись
            self.save_recordings()
            logger.info(f"Исправлена запись: {recording.get('name', 'Без названия')}")
    
    async def handle_chat_input(self, event):
        """Обработка ввода чата для отправки записи"""
        if not self.pending_recording_send:
            return
        
        try:
            recording_id = self.pending_recording_send['recording_id']
            original_event = self.pending_recording_send['event']
            
            # Получаем введенный текст
            chat_input = event.message.text.strip()
            
            # Получаем информацию о чате
            chat_info = await self.get_chat_info(chat_input)
            
            if not chat_info:
                await event.reply("❌ Не удалось найти чат. Попробуйте еще раз.")
                return
            
            # Сохраняем информацию о чате
            self.pending_recording_send['chat_info'] = chat_info
            
            # Переходим к следующему шагу
            await self.ask_send_mode(original_event, recording_id, chat_info)
            
            # Удаляем сообщение с вводом
            try:
                await event.delete()
            except:
                pass
            
        except Exception as e:
            logger.error(f"Ошибка обработки ввода чата: {e}")
            await event.reply(f"❌ Ошибка: {str(e)}")
    
    async def get_chat_info(self, chat_input):
        """Получение информации о чате"""
        try:
            # Убираем пробелы
            chat_input = chat_input.strip()
            
            # Если это @username или просто username
            if chat_input.startswith('@'):
                chat_input = chat_input[1:]
            
            # Пробуем получить информацию о чате
            try:
                entity = await self.user_client.get_entity(chat_input)
                chat_title = getattr(entity, 'title', getattr(entity, 'first_name', ''))
                return {
                    'id': entity.id,
                    'type': 'channel' if hasattr(entity, 'broadcast') else 
                            'chat' if hasattr(entity, 'megagroup') else 
                            'user',
                    'username': getattr(entity, 'username', None),
                    'title': chat_title,
                    'access_hash': getattr(entity, 'access_hash', None)
                }
            except:
                # Пробуем как числовой ID
                try:
                    chat_id = int(chat_input)
                    # Для ID без @ нужно использовать специальные методы
                    if chat_id < 0:  # Группа/канал
                        return {'id': chat_id, 'type': 'channel', 'title': f'ID: {chat_id}'}
                    else:  # Пользователь
                        return {'id': chat_id, 'type': 'user', 'title': f'ID: {chat_id}'}
                except:
                    return None
            
        except Exception as e:
            logger.error(f"Ошибка получения информации о чате: {e}")
            return None
    
    async def ask_send_mode(self, event, recording_id, chat_info):
        """Спросить режим отправки"""
        chat_title = chat_info.get('title', f'ID: {chat_info["id"]}')
        
        try:
            await event.edit(
                f"✅ **Чат определен:** {chat_title}\n\n"
                f"**Выберите режим отправки:**\n\n"
                f"**👁️ Отслеживать пользователя**\n"
                f"• Бот будет следить за указанным пользователем\n"
                f"• Отправит сообщения, отвечая на его последнее сообщение\n"
                f"• Если сообщение удалено, найдет новое или предыдущее сообщение\n\n"
                f"**📨 Ответить на сообщение**\n"
                f"• Укажите username пользователя (например @username)\n"
                f"• Бот найдет его последнее сообщение\n"
                f"• Отправит все сообщения, отвечая на него\n"
                f"• Если сообщение удалено, найдет новое\n\n"
                f"**📤 Отправить как есть**\n"
                f"• Просто отправит сообщения без ответа",
                buttons=[
                    [Button.inline("👁️ Отслеживать пользователя", f"track_user_{recording_id}_{chat_info['id']}")],
                    [Button.inline("📨 Ответить на сообщение", f"reply_to_user_{recording_id}_{chat_info['id']}")],
                    [Button.inline("📤 Отправить как есть", f"send_plain_{recording_id}_{chat_info['id']}")],
                    [Button.inline("↩️ Назад", b"recordings_menu")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка", alert=True)
    
    async def track_user_mode(self, event, recording_id, chat_id):
        """Режим отслеживания пользователя"""
        recording = self.recordings[recording_id]
        
        try:
            await event.edit(
                f"👁️ **Режим отслеживания**\n\n"
                f"Введите username или ID пользователя, за которым нужно следить:\n"
                f"Примеры:\n"
                f"• `@username`\n"
                f"• `123456789` (ID пользователя)\n\n"
                f"**Как это работает:**\n"
                f"1. Бот найдет последнее сообщение пользователя\n"
                f"2. Отправит ваши сообщения, отвечая на него\n"
                f"3. Если пользователь удалит сообщение\n"
                f"4. Бот найдет его предыдущее или следующее сообщение\n"
                f"5. Продолжит отвечать на него\n"
                f"6. Сохранит оригинальную скорость и паузы",
                buttons=[
                    [Button.inline("↩️ Назад", f"play_recording_{recording_id}")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка", alert=True)
        
        # Обновляем ожидающую отправку
        self.pending_recording_send = {
            'recording_id': recording_id,
            'chat_id': chat_id,
            'mode': 'track',
            'step': 'user_input',
            'event': event
        }
    
    async def reply_to_user_mode(self, event, recording_id, chat_id):
        """Режим ответа на пользователя"""
        recording = self.recordings[recording_id]
        
        try:
            await event.edit(
                f"📨 **Режим ответа на пользователя**\n\n"
                f"Введите username или ID пользователя:\n"
                f"Примеры:\n"
                f"• `@username`\n"
                f"• `123456789` (ID пользователя)\n\n"
                f"**Как это работает:**\n"
                f"1. Бот найдет последнее сообщение пользователя\n"
                f"2. Отправит все ваши сообщения, отвечая на него\n"
                f"3. Если сообщение удалено, найдет предыдущее или следующее\n"
                f"4. Продолжит отвечать на новое сообщение\n"
                f"5. Сохранит оригинальную скорость и паузы",
                buttons=[
                    [Button.inline("↩️ Назад", f"play_recording_{recording_id}")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка", alert=True)
        
        # Обновляем ожидающую отправку
        self.pending_recording_send = {
            'recording_id': recording_id,
            'chat_id': chat_id,
            'mode': 'reply',
            'step': 'user_input',
            'event': event
        }
    
    async def process_target_user(self, event):
        """Обработка ввода целевого пользователя"""
        if not self.pending_recording_send:
            return
        
        try:
            recording_id = self.pending_recording_send['recording_id']
            chat_id = self.pending_recording_send['chat_id']
            mode = self.pending_recording_send.get('mode', 'track')
            
            if not chat_id:
                await event.reply("❌ Ошибка: информация о чате потеряна.")
                return
            
            # Получаем информацию о пользователе
            user_input = event.message.text.strip()
            user_info = await self.get_user_info(user_input)
            
            if not user_info:
                await event.reply("❌ Не удалось найти пользователя. Попробуйте еще раз.")
                return
            
            # Сохраняем информацию о пользователе
            self.pending_recording_send['target_user'] = user_info
            
            # Ищем последнее сообщение пользователя
            original_event = self.pending_recording_send['event']
            await self.find_and_confirm_message(original_event, recording_id, chat_id, user_info, mode)
            
            # Удаляем сообщение с вводом
            try:
                await event.delete()
            except:
                pass
            
        except Exception as e:
            logger.error(f"Ошибка обработки целевого пользователя: {e}")
            await event.reply(f"❌ Ошибка: {str(e)}")
    
    async def find_and_confirm_message(self, event, recording_id, chat_id, user_info, mode):
        """Найти сообщение пользователя и подтвердить отправку"""
        recording = self.recordings[recording_id]
        user_display = self.format_user_display(user_info)
        
        try:
            await event.edit("🔍 **Ищу последнее сообщение пользователя...**")
        except:
            pass
        
        try:
            # Ищем последнее сообщение пользователя в чате
            target_message = await self.find_user_message(chat_id, user_info['id'])
            
            if target_message:
                if mode == 'track':
                    await self.confirm_track_mode(event, recording_id, chat_id, user_info, target_message.id)
                else:
                    await self.confirm_reply_mode(event, recording_id, chat_id, user_info, target_message.id)
            else:
                await event.edit(
                    "❌ **Сообщение не найдено!**\n\n"
                    f"Не удалось найти сообщения пользователя {user_display} в этом чате.\n"
                    "Выберите другой вариант отправки:",
                    buttons=[
                        [Button.inline("📤 Отправить как есть", f"send_plain_{recording_id}_{chat_id}")],
                        [Button.inline("↩️ Отмена", b"recordings_menu")]
                    ]
                )
                
        except Exception as e:
            logger.error(f"Ошибка поиска сообщения: {e}")
            try:
                await event.edit(f"❌ Ошибка поиска: {str(e)[:200]}")
            except:
                pass
    
    async def find_user_message(self, chat_id, user_id, reference_message_id=None):
        """Найти сообщение пользователя в чате"""
        try:
            # Если есть reference_message_id, ищем вокруг него
            if reference_message_id:
                # Ищем сообщение до reference_message_id
                async for message in self.user_client.iter_messages(
                    chat_id, 
                    limit=20,
                    max_id=reference_message_id - 1,
                    from_user=user_id
                ):
                    return message
                
                # Ищем сообщение после reference_message_id
                async for message in self.user_client.iter_messages(
                    chat_id, 
                    limit=20,
                    min_id=reference_message_id + 1,
                    from_user=user_id
                ):
                    return message
            
            # Если нет reference или не нашли рядом, ищем последние сообщения
            async for message in self.user_client.iter_messages(chat_id, limit=50, from_user=user_id):
                return message
            
            # Если не нашли, ищем в более старых сообщениях
            async for message in self.user_client.iter_messages(chat_id, limit=100, offset_id=0, from_user=user_id):
                return message
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка поиска сообщения пользователя: {e}")
            return None
    
    async def confirm_track_mode(self, event, recording_id, chat_id, user_info, message_id):
        """Подтверждение отправки с отслеживанием"""
        recording = self.recordings[recording_id]
        user_display = self.format_user_display(user_info)
        
        try:
            await event.edit(
                f"✅ **Найдено сообщение для ответа!**\n\n"
                f"📝 Запись: {recording.get('name', 'Без названия')}\n"
                f"💬 Чат: `{chat_id}`\n"
                f"👤 Пользователь: {user_display}\n"
                f"📎 Ответ на сообщение: `{message_id}`\n"
                f"📊 Сообщений: {recording.get('message_count', 0)}\n"
                f"⏱️ Длительность: {recording.get('total_duration', recording['messages'][-1]['time_offset'] if recording['messages'] else 0):.3f}с\n\n"
                f"**Бот будет:**\n"
                f"1. Отправлять сообщения, отвечая на это сообщение\n"
                f"2. Если сообщение удалено, найдет предыдущее или следующее\n"
                f"3. Продолжит отвечать на новое сообщение\n"
                f"4. Отправлять все сообщения с оригинальной скоростью и паузами",
                buttons=[
                    [Button.inline("🚀 Начать отправку", f"execute_tracked_{recording_id}_{chat_id}_{user_info['id']}_{message_id}")],
                    [Button.inline("↩️ Отмена", b"recordings_menu")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка", alert=True)
    
    async def confirm_reply_mode(self, event, recording_id, chat_id, user_info, message_id):
        """Подтверждение отправки с ответом на конкретное сообщение"""
        recording = self.recordings[recording_id]
        user_display = self.format_user_display(user_info)
        
        try:
            await event.edit(
                f"✅ **Найдено сообщение для ответа!**\n\n"
                f"📝 Запись: {recording.get('name', 'Без названия')}\n"
                f"💬 Чат: `{chat_id}`\n"
                f"👤 Пользователь: {user_display}\n"
                f"📎 Ответ на сообщение: `{message_id}`\n"
                f"📊 Сообщений: {recording.get('message_count', 0)}\n"
                f"⏱️ Длительность: {recording.get('total_duration', recording['messages'][-1]['time_offset'] if recording['messages'] else 0):.3f}с\n\n"
                f"**Бот будет:**\n"
                f"1. Отправить все сообщения, отвечая на это сообщение\n"
                f"2. Если сообщение удалено, найдет предыдущее или следующее\n"
                f"3. Продолжит отвечать на новое сообщение\n"
                f"4. Сохранить оригинальную скорость и паузы",
                buttons=[
                    [Button.inline("🚀 Начать отправку", f"execute_reply_{recording_id}_{chat_id}_{message_id}")],
                    [Button.inline("↩️ Отмена", b"recordings_menu")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка", alert=True)
    
    async def execute_tracked_send(self, event, recording_id, chat_id, user_id, initial_message_id):
        """Выполнить отправку с отслеживанием"""
        recording = self.recordings[recording_id]
        messages = recording['messages']
        
        # Проверяем запись перед отправкой
        self.check_and_fix_recording(recording)
        
        try:
            await event.edit("🚀 **Начинаю отправку с отслеживанием...**\n\n⏳ 0% (0/{})".format(len(messages)))
        except:
            pass
        
        try:
            sent_count = 0
            start_time = time.time()
            last_progress_update = start_time
            
            # Текущее сообщение для ответа
            current_reply_to = initial_message_id
            failed_attempts = 0
            max_failed_attempts = 3
            
            for i, msg_data in enumerate(messages):
                # Рассчитываем задержку для сохранения оригинальной скорости
                delay = msg_data.get('delay_since_last', 0.0)
                if delay > 0:
                    # Логируем задержку
                    logger.info(f"Задержка {i}: {delay:.3f} секунд")
                    await asyncio.sleep(delay)
                
                # Пробуем отправить с текущим reply_to
                try:
                    sent_msg = await self.user_client.send_message(
                        chat_id,
                        msg_data['text'],
                        reply_to=current_reply_to
                    )
                    sent_count += 1
                    failed_attempts = 0  # Сброс счетчика ошибок
                    
                except Exception as e:
                    error_str = str(e)
                    
                    # Если ошибка из-за удаленного сообщения
                    if "MESSAGE_ID_INVALID" in error_str or "REPLY_MESSAGE_ID_INVALID" in error_str:
                        logger.info(f"⚠️ Сообщение {current_reply_to} удалено, ищу новое...")
                        failed_attempts += 1
                        
                        if failed_attempts <= max_failed_attempts:
                            # Ищем новое сообщение пользователя рядом с удаленным
                            new_message = await self.find_user_message(chat_id, user_id, current_reply_to)
                            
                            if new_message:
                                logger.info(f"✅ Найдено новое сообщение: {new_message.id}")
                                current_reply_to = new_message.id
                                
                                # Пробуем отправить с новым reply_to
                                try:
                                    sent_msg = await self.user_client.send_message(
                                        chat_id,
                                        msg_data['text'],
                                        reply_to=current_reply_to
                                    )
                                    sent_count += 1
                                    continue  # Успешно отправили, переходим к следующему
                                except Exception as e2:
                                    logger.info(f"⚠️ Ошибка с новым сообщением {current_reply_to}: {e2}")
                                    # Пробуем отправить без ответа
                        
                        # Если не нашли новое сообщение или ошибка, отправляем без ответа
                        logger.info(f"📤 Отправляю сообщение {i} без ответа")
                        try:
                            sent_msg = await self.user_client.send_message(
                                chat_id,
                                msg_data['text']
                            )
                            sent_count += 1
                        except Exception as e3:
                            logger.error(f"❌ Не удалось отправить сообщение {i}: {e3}")
                    else:
                        # Другая ошибка, пробуем отправить без ответа
                        logger.error(f"⚠️ Другая ошибка: {error_str}")
                        try:
                            sent_msg = await self.user_client.send_message(
                                chat_id,
                                msg_data['text']
                            )
                            sent_count += 1
                        except Exception as e3:
                            logger.error(f"❌ Не удалось отправить сообщение {i}: {e3}")
                
                # Обновляем прогресс каждые 10% или каждые 2 секунды
                progress = int((i + 1) / len(messages) * 100)
                current_time = time.time()
                
                if progress % 10 == 0 or current_time - last_progress_update > 2:
                    try:
                        await event.edit(f"🚀 **Отправка с отслеживанием...**\n\n⏳ {progress}% ({i+1}/{len(messages)})")
                    except:
                        pass  # Игнорируем ошибки редактирования
                    last_progress_update = current_time
            
            total_time = time.time() - start_time
            original_time = recording.get('total_duration', messages[-1]['time_offset'] if messages else 0)
            
            try:
                await event.edit(
                    f"✅ **Запись успешно отправлена с отслеживанием!**\n\n"
                    f"📊 Отправлено сообщений: **{sent_count}/{len(messages)}**\n"
                    f"⏱️ Оригинальное время: **{original_time:.3f}с**\n"
                    f"⏱️ Фактическое время: **{total_time:.3f}с**\n"
                    f"💬 Чат: `{chat_id}`\n"
                    f"👤 Отслеживаемый пользователь: `{user_id}`\n"
                    f"🔄 Найдено новых сообщений: **{failed_attempts}**"
                )
            except:
                pass
            
            logger.info(f"Запись {recording_id} отправлена в чат {chat_id} с отслеживанием пользователя {user_id}")
            
            # Сбрасываем ожидающую отправку
            self.pending_recording_send = None
            
        except Exception as e:
            try:
                await event.edit(f"❌ **Ошибка отправки:**\n\n{str(e)[:300]}")
            except:
                pass
            logger.error(f"Ошибка отправки записи с отслеживанием: {e}")
            self.pending_recording_send = None
    
    async def execute_reply_send(self, event, recording_id, chat_id, initial_message_id):
        """Выполнить отправку с ответом на конкретное сообщение"""
        recording = self.recordings[recording_id]
        messages = recording['messages']
        
        # Проверяем запись перед отправкой
        self.check_and_fix_recording(recording)
        
        try:
            await event.edit("🚀 **Начинаю отправку с ответом...**\n\n⏳ 0% (0/{})".format(len(messages)))
        except:
            pass
        
        try:
            sent_count = 0
            start_time = time.time()
            last_progress_update = start_time
            
            # Текущее сообщение для ответа
            current_reply_to = initial_message_id
            failed_attempts = 0
            max_failed_attempts = 3
            
            for i, msg_data in enumerate(messages):
                # Рассчитываем задержку для сохранения оригинальной скорости
                delay = msg_data.get('delay_since_last', 0.0)
                if delay > 0:
                    await asyncio.sleep(delay)
                
                # Отправляем сообщение
                try:
                    if i == 0:
                        # Первое сообщение как реплай на указанное сообщение
                        sent_msg = await self.user_client.send_message(
                            chat_id,
                            msg_data['text'],
                            reply_to=current_reply_to
                        )
                    else:
                        # Остальные как обычные сообщения
                        sent_msg = await self.user_client.send_message(
                            chat_id,
                            msg_data['text']
                        )
                    
                    sent_count += 1
                    failed_attempts = 0  # Сброс счетчика ошибок
                    
                except Exception as e:
                    error_str = str(e)
                    
                    # Если ошибка из-за удаленного сообщения и это первое сообщение
                    if i == 0 and ("MESSAGE_ID_INVALID" in error_str or "REPLY_MESSAGE_ID_INVALID" in error_str):
                        logger.info(f"⚠️ Сообщение {current_reply_to} удалено, ищу новое...")
                        failed_attempts += 1
                        
                        if failed_attempts <= max_failed_attempts:
                            # Находим пользователя, который отправил это сообщение
                            try:
                                # Получаем информацию о сообщении
                                original_msg = await self.user_client.get_messages(chat_id, ids=[current_reply_to])
                                if original_msg and original_msg[0]:
                                    user_id = original_msg[0].sender_id
                                    
                                    # Ищем новое сообщение этого пользователя
                                    new_message = await self.find_user_message(chat_id, user_id, current_reply_to)
                                    
                                    if new_message:
                                        logger.info(f"✅ Найдено новое сообщение: {new_message.id}")
                                        current_reply_to = new_message.id
                                        
                                        # Пробуем отправить с новым reply_to
                                        try:
                                            sent_msg = await self.user_client.send_message(
                                                chat_id,
                                                msg_data['text'],
                                                reply_to=current_reply_to
                                            )
                                            sent_count += 1
                                            continue  # Успешно отправили, переходим к следующему
                                        except Exception as e2:
                                            logger.info(f"⚠️ Ошибка с новым сообщением {current_reply_to}: {e2}")
                                            # Пробуем отправить без ответа
                            except:
                                pass
                        
                        # Если не нашли новое сообщение или ошибка, отправляем без ответа
                        logger.info(f"📤 Отправляю первое сообщение без ответа")
                        try:
                            sent_msg = await self.user_client.send_message(
                                chat_id,
                                msg_data['text']
                            )
                            sent_count += 1
                        except Exception as e3:
                            logger.error(f"❌ Не удалось отправить сообщение {i}: {e3}")
                    else:
                        # Другая ошибка
                        logger.error(f"❌ Не удалось отправить сообщение {i}: {error_str}")
                
                # Обновляем прогресс
                progress = int((i + 1) / len(messages) * 100)
                current_time = time.time()
                
                if progress % 10 == 0 or current_time - last_progress_update > 2:
                    try:
                        await event.edit(f"🚀 **Отправка с ответом...**\n\n⏳ {progress}% ({i+1}/{len(messages)})")
                    except:
                        pass
                    last_progress_update = current_time
            
            total_time = time.time() - start_time
            original_time = recording.get('total_duration', messages[-1]['time_offset'] if messages else 0)
            
            try:
                await event.edit(
                    f"✅ **Запись успешно отправлена!**\n\n"
                    f"📊 Отправлено сообщений: **{sent_count}/{len(messages)}**\n"
                    f"⏱️ Оригинальное время: **{original_time:.3f}с**\n"
                    f"⏱️ Фактическое время: **{total_time:.3f}с**\n"
                    f"💬 Чат: `{chat_id}`\n"
                    f"📎 Ответ на сообщение: `{initial_message_id}`"
                )
            except:
                pass
            
            logger.info(f"Запись {recording_id} отправлена в чат {chat_id} с ответом на {initial_message_id}")
            
            # Сбрасываем ожидающую отправку
            self.pending_recording_send = None
            
        except Exception as e:
            try:
                await event.edit(f"❌ **Ошибка отправки:**\n\n{str(e)[:300]}")
            except:
                pass
            logger.error(f"Ошибка отправки записи с ответом: {e}")
            self.pending_recording_send = None
    
    async def send_plain_recording(self, event, recording_id, chat_id):
        """Отправить запись без ответа"""
        recording = self.recordings[recording_id]
        
        try:
            await event.edit(
                f"✅ **Отправка записи как есть**\n\n"
                f"📝 Запись: {recording.get('name', 'Без названия')}\n"
                f"💬 Чат: `{chat_id}`\n"
                f"📊 Сообщений: {recording.get('message_count', 0)}\n"
                f"⏱️ Длительность: {recording.get('total_duration', recording['messages'][-1]['time_offset'] if recording['messages'] else 0):.3f}с\n\n"
                f"Сообщения будут отправлены без ответа на другие сообщения.",
                buttons=[
                    [Button.inline("🚀 Начать отправку", f"execute_plain_{recording_id}_{chat_id}")],
                    [Button.inline("↩️ Отмена", b"recordings_menu")]
                ]
            )
        except Exception as e:
            if "message was not modified" not in str(e):
                await event.answer("❌ Ошибка", alert=True)
    
    async def execute_plain_send(self, event, recording_id, chat_id):
        """Выполнить отправку без ответа"""
        recording = self.recordings[recording_id]
        messages = recording['messages']
        
        # Проверяем запись перед отправкой
        self.check_and_fix_recording(recording)
        
        try:
            await event.edit("🚀 **Начинаю отправку...**\n\n⏳ 0% (0/{})".format(len(messages)))
        except:
            pass
        
        try:
            sent_count = 0
            start_time = time.time()
            last_progress_update = start_time
            
            for i, msg_data in enumerate(messages):
                # Рассчитываем задержку для сохранения оригинальной скорости
                delay = msg_data.get('delay_since_last', 0.0)
                if delay > 0:
                    await asyncio.sleep(delay)
                
                # Отправляем сообщение
                try:
                    sent_msg = await self.user_client.send_message(
                        chat_id,
                        msg_data['text']
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Не удалось отправить сообщение {i}: {e}")
                
                # Обновляем прогресс
                progress = int((i + 1) / len(messages) * 100)
                current_time = time.time()
                
                if progress % 10 == 0 or current_time - last_progress_update > 2:
                    try:
                        await event.edit(f"🚀 **Отправка записи...**\n\n⏳ {progress}% ({i+1}/{len(messages)})")
                    except:
                        pass
                    last_progress_update = current_time
            
            total_time = time.time() - start_time
            original_time = recording.get('total_duration', messages[-1]['time_offset'] if messages else 0)
            
            try:
                await event.edit(
                    f"✅ **Запись успешно отправлена!**\n\n"
                    f"📊 Отправлено сообщений: **{sent_count}/{len(messages)}**\n"
                    f"⏱️ Оригинальное время: **{original_time:.3f}с**\n"
                    f"⏱️ Фактическое время: **{total_time:.3f}с**\n"
                    f"💬 Чат: `{chat_id}`"
                )
            except:
                pass
            
            logger.info(f"Запись {recording_id} отправлена в чат {chat_id} без ответа")
            
            # Сбрасываем ожидающую отправку
            self.pending_recording_send = None
            
        except Exception as e:
            try:
                await event.edit(f"❌ **Ошибка отправки:**\n\n{str(e)[:300]}")
            except:
                pass
            logger.error(f"Ошибка отправки записи: {e}")
            self.pending_recording_send = None
    
    async def handle_add_command(self, event):
        """Обработка команды добавления"""
        args = event.message.text.split()
        
        if len(args) < 2:
            # Показываем меню добавления
            await event.reply(
                "👤 **Добавление пользователя**\n\n"
                "Отправьте:\n"
                "• ID пользователя\n"
                "• @username\n"
                "• Или перешлите сообщение от пользователя\n\n"
                "Пример: `/add @username`",
                buttons=[
                    [Button.inline("📋 Способы добавления", b"add_methods")],
                    [Button.inline("↩️ Назад", b"main_menu")]
                ]
            )
        else:
            user_input = ' '.join(args[1:])
            await self.add_user(event, user_input)
    
    async def handle_remove_command(self, event):
        """Обработка команды удаления"""
        args = event.message.text.split()
        
        if len(args) < 2:
            # Показываем черный список для удаления
            await self.show_blacklist_for_removal(event)
        else:
            user_input = ' '.join(args[1:])
            await self.remove_user(event, user_input)
    
    async def add_user(self, event, user_input):
        """Добавление пользователя в черный список"""
        status_msg = await event.reply("🔄 Обработка...")
        
        # Получаем информацию о пользователе
        user_info = await self.get_user_info(user_input)
        
        if not user_info:
            await status_msg.edit("❌ Не удалось найти пользователя.")
            return
        
        # Проверяем, есть ли уже пользователь
        if self.is_user_in_blacklist(user_info['id'], user_info.get('username')):
            await status_msg.edit("⚠️ Пользователь уже в черном списке!")
            return
        
        # Добавляем пользователя
        self.config['blacklist'].append(user_info)
        self.save_config()
        
        user_display = self.format_user_display(user_info)
        
        await status_msg.edit(
            f"✅ **Пользователь добавлен!**\n\n"
            f"{user_display}\n"
            f"🆔 ID: `{user_info['id']}`"
        )
        
        logger.info(f"Добавлен пользователь: {user_display}")
    
    async def remove_user(self, event, user_input):
        """Удаление пользователя из черного списка"""
        status_msg = await event.reply("🔄 Обработка...")
        
        # Получаем информацию о пользователе
        user_info = await self.get_user_info(user_input)
        
        if not user_info:
            await status_msg.edit("❌ Не удалось найти пользователя.")
            return
        
        # Ищем пользователя в черном списке
        for i, user in enumerate(self.config['blacklist']):
            if user['id'] == user_info['id']:
                # Удаляем пользователя
                removed_user = self.config['blacklist'].pop(i)
                self.save_config()
                
                user_display = self.format_user_display(removed_user)
                await status_msg.edit(f"✅ **Пользователь удален:**\n{user_display}")
                return
        
        await status_msg.edit("❌ Пользователь не найден в черном списке.")
    
    async def get_user_info(self, user_input):
        """Получение информации о пользователе"""
        try:
            # Убираем пробелы
            user_input = user_input.strip()
            
            # Если это ID
            if user_input.isdigit():
                user_id = int(user_input)
                try:
                    # Пробуем получить через бота
                    user = await self.bot.get_entity(user_id)
                    return {
                        'id': user.id,
                        'username': getattr(user, 'username', None),
                        'first_name': getattr(user, 'first_name', ''),
                        'last_name': getattr(user, 'last_name', '')
                    }
                except:
                    return {'id': user_id, 'username': None}
            
            # Если это @username
            elif user_input.startswith('@'):
                username = user_input[1:]
                user = await self.bot.get_entity(username)
                return {
                    'id': user.id,
                    'username': username,
                    'first_name': getattr(user, 'first_name', ''),
                    'last_name': getattr(user, 'last_name', '')
                }
            
            # Если это ссылка
            elif 't.me/' in user_input:
                username = user_input.split('t.me/')[-1]
                user = await self.bot.get_entity(username)
                return {
                    'id': user.id,
                    'username': username,
                    'first_name': getattr(user, 'first_name', ''),
                    'last_name': getattr(user, 'last_name', '')
                }
            
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе: {e}")
        
        return None
    
    def format_user_display(self, user_info):
        """Форматирование отображения пользователя"""
        parts = []
        if user_info.get('first_name'):
            parts.append(user_info['first_name'])
        if user_info.get('last_name'):
            parts.append(user_info['last_name'])
        
        display = ' '.join(parts) if parts else f"ID: {user_info['id']}"
        
        if user_info.get('username'):
            display += f" (@{user_info['username']})"
        
        return display
    
    async def show_blacklist(self, event):
        """Показать черный список"""
        if not self.config['blacklist']:
            await event.reply("📋 **Черный список пуст.**", parse_mode='md')
            return
        
        text = "📋 **Черный список пользователей:**\n\n"
        
        for i, user in enumerate(self.config['blacklist'], 1):
            user_display = self.format_user_display(user)
            text += f"{i}. {user_display}\n"
            text += f"   🆔 `{user['id']}`\n\n"
        
        buttons = [
            [Button.inline("➖ Удалить пользователя", b"remove_user_menu")],
            [Button.inline("↩️ Назад", b"main_menu")]
        ]
        
        await event.reply(text, buttons=buttons, parse_mode='md')
    
    async def show_blacklist_for_removal(self, event):
        """Показать черный список для удаления"""
        if not self.config['blacklist']:
            await event.reply("📋 **Черный список пуст.**", parse_mode='md')
            return
        
        text = "👤 **Выберите пользователя для удаления:**\n\n"
        buttons = []
        
        for user in self.config['blacklist']:
            user_display = self.format_user_display(user)[:30]
            buttons.append([Button.inline(f"❌ {user_display}", f"remove_{user['id']}")])
        
        buttons.append([Button.inline("↩️ Назад", b"main_menu")])
        
        await event.reply(text, buttons=buttons)
    
    async def show_stats(self, event):
        """Показать статистику"""
        stats_text = (
            f"📊 **Статистика бота**\n\n"
            f"📅 **Дата:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"**Общая статистика:**\n"
            f"• 🗑️ Всего удалено сообщений: **{self.deletion_stats['total_deleted']}**\n"
            f"• 🗑️ Удалено сегодня: **{self.deletion_stats['deleted_today']}**\n"
            f"• 👤 Пользователей в черном списке: **{len(self.config['blacklist'])}**\n"
            f"• 💬 Мониторится чатов: **{'Все' if self.config['enabled_for_all'] else len(self.config['enabled_chats'])}**\n"
            f"• 📝 Записей сохранено: **{len(self.recordings)}**\n"
            f"• ⚡ Статус мониторинга: **{'✅ Активен' if self.active_monitoring else '⏸️ Приостановлен'}**"
        )
        
        # Добавляем статистику скорости печати, если есть
        if self.typing_speed and 'words_per_minute' in self.typing_speed:
            stats_text += f"\n• ⚡ Скорость печати: **{self.typing_speed['words_per_minute']:.1f} слов/минуту**"
        
        buttons = [
            [Button.inline("🔄 Обновить", b"refresh_stats")],
            [Button.inline("📊 Статистика скорости", b"typing_speed_stats")],
            [Button.inline("↩️ Назад", b"main_menu")]
        ]
        
        await event.reply(stats_text, buttons=buttons, parse_mode='md')
    
    async def show_help(self, event):
        """Показать помощь"""
        help_text = """
        🤖 **Помощь по боту**\n\n
        **📋 Основные команды:**
        `/menu` - Главное меню
        `/add @username` - Добавить пользователя
        `/remove @username` - Удалить пользователя
        `/list` - Показать черный список
        `/stats` - Статистика
        `/toggle` - Вкл/выкл мониторинг
        `/record` - Начать запись сообщений
        `/stop` - Остановить запись
        `/recordings` - Управление записями
        `/speed_test` - Анализ скорости печати
        `/stop_test` - Остановить тест скорости
        `/speed_stats` - Статистика скорости
        `/send_file` - Отправка сообщений из файла
        `/help` - Эта справка\n\n
        **⚡ Как это работает:**
        1. Добавьте пользователей в черный список
        2. Бот мониторит все чаты
        3. При реплае от пользователя из черного списка
        4. Все ваши сообщения в цепочке удаляются
        5. **Уведомления отключены**\n\n
        **🎬 Система записей:**
        1. Используйте /record или кнопку
        2. Пишите сообщения как обычно
        3. Бот записывает текст, время и точные паузы
        4. Используйте /stop для сохранения
        5. Воспроизводите записи в любом чате
        6. **Можно следить за сообщениями врага и отвечать на них**
        7. **Если враг удалил сообщение, бот найдет его предыдущее или следующее**
        8. **Сохраняются точные паузы между сообщениями**\n\n
        **📄 Отправка из файла:**
        1. Сначала пройдите тест скорости (/speed_test)
        2. Бот проанализирует вашу скорость печати
        3. Отправьте текстовый файл (.txt)
        4. Укажите чат и пользователя для ответа
        5. Бот отправит сообщения с вашей оригинальной скоростью
        6. **Сообщения разбиваются на 1-4 слова в каждом**
        7. **Точное сохранение вашей скорости печати**
        8. **Автопоиск сообщений если враг удалил свое сообщение**
        """
        
        buttons = [
            [Button.inline("📚 Примеры команд", b"examples")],
            [Button.inline("↩️ Назад", b"main_menu")]
        ]
        
        await event.reply(help_text, buttons=buttons, parse_mode='md')
    
    async def show_chat_menu(self, event):
        """Показать меню управления чатами"""
        mode = "🌐 Все чаты" if self.config['enabled_for_all'] else "💬 Только выбранные"
        
        text = (
            f"💬 **Управление чатами**\n\n"
            f"Текущий режим: **{mode}**\n"
            f"Активных чатов: **{len(self.config['enabled_chats'])}**\n\n"
            f"Выберите действие:"
        )
        
        buttons = [
            [Button.inline("🌐 Переключить режим", b"toggle_chat_mode")],
            [Button.inline("➕ Добавить чат", b"add_chat")],
            [Button.inline("➖ Удалить чат", b"remove_chat")],
            [Button.inline("📋 Список чатов", b"list_chats")],
            [Button.inline("↩️ Назад", b"main_menu")]
        ]
        
        await event.reply(text, buttons=buttons, parse_mode='md')
    
    async def handle_forwarded_message(self, event):
        """Обработка пересланных сообщений"""
        try:
            forwarded = event.message.forward
            if forwarded:
                sender_id = forwarded.sender_id
                
                # Получаем информацию о пользователе
                try:
                    user = await self.bot.get_entity(sender_id)
                    user_info = {
                        'id': user.id,
                        'username': getattr(user, 'username', None),
                        'first_name': getattr(user, 'first_name', ''),
                        'last_name': getattr(user, 'last_name', '')
                    }
                    
                    # Проверяем, есть ли уже пользователь
                    if self.is_user_in_blacklist(user_info['id'], user_info.get('username')):
                        await event.reply("⚠️ Пользователь уже в черном списке!")
                        return
                    
                    # Добавляем пользователя
                    self.config['blacklist'].append(user_info)
                    self.save_config()
                    
                    user_display = self.format_user_display(user_info)
                    
                    await event.reply(
                        f"✅ **Пользователь добавлен из пересланного сообщения!**\n\n"
                        f"{user_display}\n"
                        f"🆔 ID: `{user_info['id']}`"
                    )
                    
                except Exception as e:
                    await event.reply(f"❌ Ошибка: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Ошибка обработки пересланного сообщения: {e}")
    
    async def handle_callback(self, event):
        """Обработка нажатий на кнопки"""
        try:
            data = event.data.decode('utf-8')
            
            if data == 'main_menu':
                await self.send_main_menu(event)
            
            elif data == 'user_management':
                await event.edit(
                    "👤 **Управление пользователями**\n\n"
                    "Выберите действие:",
                    buttons=[
                        [Button.inline("➕ Добавить пользователя", b"add_user_menu")],
                        [Button.inline("➖ Удалить пользователя", b"remove_user_menu")],
                        [Button.inline("📋 Показать черный список", b"show_blacklist")],
                        [Button.inline("↩️ Назад", b"main_menu")]
                    ]
                )
            
            elif data == 'chat_management':
                await self.show_chat_menu(event)
            
            elif data == 'stats_menu':
                await self.show_stats(event)
            
            elif data == 'settings_menu':
                await self.show_settings(event)
            
            elif data == 'help_menu':
                await self.show_help(event)
            
            elif data == 'recordings_menu':
                await self.show_recordings_menu(event)
            
            elif data == 'start_recording':
                await self.start_recording(event)
            
            elif data == 'stop_recording':
                await self.stop_recording(event)
            
            elif data == 'typing_speed_test':
                await self.start_typing_speed_test(event)
            
            elif data == 'stop_typing_test':
                await self.stop_typing_speed_test(event)
            
            elif data == 'typing_speed_stats':
                await self.show_typing_speed_stats(event)
            
            elif data == 'send_from_file':
                await self.start_file_send_mode(event)
            
            elif data == 'file_send_here':
                # Отправить из файла в текущий чат
                if self.pending_file_send:
                    self.pending_file_send['chat_info'] = {
                        'id': event.chat_id,
                        'title': 'Текущий чат'
                    }
                    self.pending_file_send['step'] = 'target_user'
                    await self.ask_words_per_message(event)
            
            elif data == 'file_no_reply':
                # Без ответа на сообщение
                if self.pending_file_send:
                    self.pending_file_send['target_user'] = None
                    self.pending_file_send['step'] = 'words_per_message'
                    await self.ask_words_per_message(event)
            
            elif data.startswith('file_words_'):
                # Выбор количества слов в сообщении
                words_count = int(data.split('_')[-1])
                if self.pending_file_send:
                    self.pending_file_send['words_per_message'] = words_count
                    await self.confirm_file_send(event)
            
            elif data == 'file_execute_send':
                # Выполнить отправку из файла
                await self.execute_file_send(event)
            
            elif data == 'file_change_settings':
                # Изменить настройки отправки из файла
                if self.pending_file_send:
                    self.pending_file_send['step'] = 'words_per_message'
                    await self.ask_words_per_message(event)
            
            elif data == 'file_send_settings':
                # Настройки отправки из файла
                await event.edit(
                    "⚙️ **Настройки отправки из файла**\n\n"
                    "Здесь вы можете настроить параметры отправки:\n"
                    "• Количество слов в сообщении\n"
                    "• Скорость отправки\n"
                    "• Задержки между сообщениями\n\n"
                    "**Текущие настройки:**\n"
                    f"• 💬 Слов в сообщении: **{self.pending_file_send.get('words_per_message', 1) if self.pending_file_send else 1}**\n"
                    f"• ⚡ Скорость: **{self.typing_speed.get('words_per_minute', 200) if self.typing_speed else 200} слов/минуту**\n"
                    f"• ⏱️ Задержка: **{self.typing_speed.get('average_delay_between_messages', 0.3) if self.typing_speed else 0.3}с**",
                    buttons=[
                        [Button.inline("1 слово", b"file_words_1")],
                        [Button.inline("2 слова", b"file_words_2")],
                        [Button.inline("3 слова", b"file_words_3")],
                        [Button.inline("4 слова", b"file_words_4")],
                        [Button.inline("↩️ Назад", b"main_menu")]
                    ]
                )
            
            elif data.startswith('play_recording_'):
                recording_id = data.replace('play_recording_', '')
                await self.play_recording(event, recording_id)
            
            elif data.startswith('send_here_'):
                # Формат: send_here_{recording_id}
                recording_id = data.replace('send_here_', '')
                chat_id = event.chat_id
                
                # Переходим к выбору режима отправки
                await self.ask_send_mode(event, recording_id, {'id': chat_id, 'title': 'Текущий чат'})
            
            elif data.startswith('track_user_'):
                # Формат: track_user_{recording_id}_{chat_id}
                parts = data.split('_')
                recording_id = f"{parts[2]}_{parts[3]}"
                chat_id = int(parts[4])
                await self.track_user_mode(event, recording_id, chat_id)
            
            elif data.startswith('reply_to_user_'):
                # Формат: reply_to_user_{recording_id}_{chat_id}
                parts = data.split('_')
                recording_id = f"{parts[2]}_{parts[3]}"
                chat_id = int(parts[4])
                await self.reply_to_user_mode(event, recording_id, chat_id)
            
            elif data.startswith('send_plain_'):
                # Формат: send_plain_{recording_id}_{chat_id}
                parts = data.split('_')
                recording_id = f"{parts[2]}_{parts[3]}"
                chat_id = int(parts[4])
                await self.send_plain_recording(event, recording_id, chat_id)
            
            elif data.startswith('execute_tracked_'):
                # Формат: execute_tracked_{recording_id}_{chat_id}_{user_id}_{message_id}
                parts = data.split('_')
                recording_id = f"{parts[2]}_{parts[3]}"
                chat_id = int(parts[4])
                user_id = int(parts[5])
                message_id = int(parts[6])
                await self.execute_tracked_send(event, recording_id, chat_id, user_id, message_id)
            
            elif data.startswith('execute_reply_'):
                # Формат: execute_reply_{recording_id}_{chat_id}_{message_id}
                parts = data.split('_')
                recording_id = f"{parts[2]}_{parts[3]}"
                chat_id = int(parts[4])
                message_id = int(parts[5])
                await self.execute_reply_send(event, recording_id, chat_id, message_id)
            
            elif data.startswith('execute_plain_'):
                # Формат: execute_plain_{recording_id}_{chat_id}
                parts = data.split('_')
                recording_id = f"{parts[2]}_{parts[3]}"
                chat_id = int(parts[4])
                await self.execute_plain_send(event, recording_id, chat_id)
            
            elif data == 'add_user_menu':
                await event.edit(
                    "👤 **Добавление пользователя**\n\n"
                    "Отправьте команду:\n"
                    "`/add @username`\n\n"
                    "Или перешлите сообщение от пользователя.",
                    buttons=[[Button.inline("↩️ Назад", b"user_management")]]
                )
            
            elif data == 'remove_user_menu':
                await self.show_blacklist_for_removal(event)
            
            elif data == 'show_blacklist':
                await self.show_blacklist(event)
            
            elif data == 'refresh_stats':
                await self.show_stats(event)
            
            elif data == 'examples':
                await event.edit(
                    "📚 **Примеры команд:**\n\n"
                    "`/add @username`\n"
                    "`/add 123456789`\n"
                    "`/add t.me/username`\n"
                    "`/remove @username`\n"
                    "`/list`\n"
                    "`/stats`\n"
                    "`/toggle`\n"
                    "`/record`\n"
                    "`/stop`\n"
                    "`/recordings`\n"
                    "`/speed_test`\n"
                    "`/stop_test`\n"
                    "`/speed_stats`\n"
                    "`/send_file`",
                    buttons=[[Button.inline("↩️ Назад", b"help_menu")]]
                )
            
            elif data == 'toggle_chat_mode':
                self.config['enabled_for_all'] = not self.config['enabled_for_all']
                self.save_config()
                
                mode = "🌐 Все чаты" if self.config['enabled_for_all'] else "💬 Только выбранные"
                await event.answer(f"Режим изменен: {mode}", alert=False)
                await self.show_chat_menu(event)
            
            elif data == 'add_chat':
                await event.edit(
                    "➕ **Добавление чата**\n\n"
                    "Перешлите сообщение из чата или отправьте ID чата.",
                    buttons=[[Button.inline("↩️ Назад", b"chat_management")]]
                )
            
            elif data == 'remove_chat':
                await event.edit(
                    "➖ **Удаление чата**\n\n"
                    "Эта функция в разработке.",
                    buttons=[[Button.inline("↩️ Назад", b"chat_management")]]
                )
            
            elif data == 'list_chats':
                await event.edit(
                    "📋 **Список чатов**\n\n"
                    "Активных чатов: 0",
                    buttons=[[Button.inline("↩️ Назад", b"chat_management")]]
                )
            
            elif data.startswith('remove_'):
                user_id = int(data.split('_')[1])
                await self.remove_user_by_id(event, user_id)
            
            elif data == 'add_methods':
                await event.edit(
                    "📋 **Способы добавления:**\n\n"
                    "1. **Командой:** `/add @username`\n"
                    "2. **По ID:** `/add 123456789`\n"
                    "3. **По ссылке:** `/add t.me/username`\n"
                    "4. **Пересылкой:** Просто перешлите сообщение",
                    buttons=[[Button.inline("↩️ Назад", b"add_user_menu")]]
                )
            
            elif data == 'toggle_notifications':
                self.config['delete_notifications'] = not self.config['delete_notifications']
                self.save_config()
                
                status = "✅ Включены" if self.config['delete_notifications'] else "❌ Выключены"
                await event.answer(f"Уведомления: {status}", alert=False)
                await self.show_settings(event)
            
            await event.answer()
            
        except Exception as e:
            logger.error(f"Ошибка обработки callback: {e}")
            await event.answer("❌ Ошибка", alert=True)
    
    async def remove_user_by_id(self, event, user_id):
        """Удаление пользователя по ID"""
        for i, user in enumerate(self.config['blacklist']):
            if user['id'] == user_id:
                # Удаляем пользователя
                removed_user = self.config['blacklist'].pop(i)
                self.save_config()
                
                user_display = self.format_user_display(removed_user)
                await event.edit(f"✅ **Пользователь удален:**\n{user_display}")
                
                # Ждем и возвращаемся в меню
                await asyncio.sleep(2)
                await self.show_blacklist_for_removal(event)
                return
        
        await event.answer("❌ Пользователь не найден", alert=True)
    
    async def show_settings(self, event):
        """Показать настройки"""
        notifications = "✅ Включены" if self.config['delete_notifications'] else "❌ Выключены"
        
        text = (
            f"⚙️ **Настройки**\n\n"
            f"**Текущие настройки:**\n"
            f"• 🔔 Уведомления: {notifications}\n"
            f"• ⏱️ Задержка удаления: {self.config['delete_delay']} сек.\n\n"
            f"Выберите настройку для изменения:"
        )
        
        buttons = [
            [Button.inline("🔔 Уведомления", b"toggle_notifications")],
            [Button.inline("↩️ Назад", b"main_menu")]
        ]
        
        await event.edit(text, buttons=buttons)
    
    async def run(self):
        """Основной метод запуска"""
        try:
            # Инициализируем бота
            await self.initialize()
            
            # Запускаем сессию пользователя
            await self.start_user_session()
            
            # Отправляем приветственное сообщение
            await self.send_welcome_message()
            
            logger.info("✅ Бот полностью запущен и готов к работе!")
            
            # Запускаем оба клиента
            await asyncio.gather(
                self.bot.run_until_disconnected(),
                self.user_client.run_until_disconnected()
            )
            
        except KeyboardInterrupt:
            logger.info("Бот остановлен")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise
    
    async def send_welcome_message(self):
        """Отправить приветственное сообщение"""
        welcome_text = (
            f"🤖 **Бот для автоматического удаления сообщений запущен!**\n\n"
            f"👤 **Владелец:** {OWNER_ID}\n"
            f"👥 **Пользователей в черном списке:** {len(self.config['blacklist'])}\n"
            f"💬 **Мониторинг чатов:** {'🌐 Все чаты' if self.config['enabled_for_all'] else f'💬 {len(self.config['enabled_chats'])} чатов'}\n"
            f"📝 **Сохранено записей:** {len(self.recordings)} ({self.count_messages_in_recordings()} сообщений)\n"
            f"📊 **Скорость печати:** {self.typing_speed.get('words_per_minute', 'Не тестировалась')} слов/минуту\n"
            f"⚡ **Режим:** {'Активный мониторинг' if self.active_monitoring else 'Приостановлен'}\n\n"
            f"⚠️ **Уведомления об удалении:** {'Включены' if self.config['delete_notifications'] else 'Отключены'}\n\n"
            f"🎬 **Новые функции:**\n"
            f"• 📨 Отправка записей с отслеживанием сообщений врага!\n"
            f"• 🔄 Автопоиск сообщений если враг удалил сообщение\n"
            f"• ⏱️ Точное сохранение скорости и пауз\n"
            f"• 📄 **НОВОЕ: Отправка сообщений из файла!**\n"
            f"• 📊 **НОВОЕ: Анализ скорости печати!**\n"
            f"• 🔧 Исправление старых записей\n\n"
            f"📋 **Используйте /menu для управления**"
        )
        
        try:
            await self.bot.send_message(OWNER_ID, welcome_text, parse_mode='md')
        except:
            pass
    
    def count_messages_in_recordings(self):
        """Подсчитать общее количество сообщений во всех записях"""
        total = 0
        for recording in self.recordings.values():
            total += len(recording.get('messages', []))
        return total


# Запуск бота
async def main():
    print("=" * 60)
    print("🤖 БОТ ДЛЯ АВТОМАТИЧЕСКОГО УДАЛЕНИЯ СООБЩЕНИЙ")
    print("=" * 60)
    print(f"👤 Владелец: {OWNER_ID}")
    print(f"🔑 Токен бота: {BOT_TOKEN[:15]}...")
    print(f"💾 Файл конфигурации: {CONFIG_FILE}")
    print(f"🎬 Файл записей: {RECORDINGS_FILE}")
    print(f"📊 Файл скорости печати: {TYPING_SPEED_FILE}")
    print("=" * 60)
    print("⚡ ОСНОВНЫЕ ФУНКЦИИ:")
    print("• 🗑️ Удаление ВСЕХ сообщений в цепочке")
    print("• 🎬 Запись сообщений с ТОЧНОЙ скоростью и паузами")
    print("• 📨 Воспроизведение записей в любом чате")
    print("• 👁️ Отслеживание сообщений врага")
    print("• 📨 Ответ на последнее сообщение пользователя")
    print("• 🔄 Автопоиск ПРЕДЫДУЩЕГО или СЛЕДУЮЩЕГО сообщения если удалено")
    print("• ⏱️ Точное сохранение оригинальной скорости (миллисекунды)")
    print("• 📊 **НОВОЕ: Анализ скорости печати пользователя!**")
    print("• 📄 **НОВОЕ: Отправка сообщений из файла с вашей скоростью!**")
    print("• 💾 Сохранение записей между перезагрузками")
    print("• 🔕 Уведомления об удалении отключены")
    print("=" * 60)
    print("🚀 Запуск...")
    
    bot = BotInterface(BOT_TOKEN)
    await bot.run()


if __name__ == "__main__":
    # Создаем event loop
    loop = asyncio.get_event_loop()
    
    try:
        # Запускаем бота
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    finally:
        loop.close()
