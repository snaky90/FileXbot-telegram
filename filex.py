# -*- coding: utf-8 -*-

from DbHandler import DbHandler
from Explorer import Explorer
from flask import Flask, request, make_response
import hashlib
import json
import logging
import os
from re import escape
import sys
import telebot


if (len(sys.argv) > 1):
    # Debug
    API_TOKEN = ''
    DB_URL = ''
    POLLING = True
else:
    # Production
    API_TOKEN = ''
    DB_URL = ''
    POLLING = False


WEBHOOK_URL = ""
MAX_FILES_PER_PAGE = 10


db = DbHandler(DB_URL)
server = Flask(__name__)
explorers = {}
bot = telebot.TeleBot(API_TOKEN)

if (len(sys.argv) > 1):
    if (sys.argv[1] == "log"):
        telebot.logger.setLevel(logging.DEBUG)

strings = json.load(open('strings.json'))


@bot.message_handler(commands=['help'])
def help(message):
    bot.send_message(message.from_user.id, strings['help_message'])


@bot.message_handler(commands=['donate'])
def help(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton(
        'PayPal', url='https://www.paypal.me/victor141516'))
    bot.send_message(message.from_user.id, "Thank you!", reply_markup=markup)


@bot.message_handler(commands=['start'])
def start(message):
    telegram_id = message.from_user.id

    already_user = (db.insert('users', {'name': message.from_user.username,
                                        'telegram_id': telegram_id}, {'telegram_id': telegram_id})) - 1
    if (not already_user):
        bot.send_message(telegram_id, strings['help_message'])
    user_id = db.select('users', "telegram_id = " + str(telegram_id))[0]['id']

    db.insert('directories', {
              'name': '/', 'parent_directory_id': "NULL", 'user_id': user_id})

    share_code = extract_unique_code(message.text)
    if share_code:
        handle_share(message)


@bot.message_handler(commands=['ls'])
def ls(message):
    telegram_id = message.from_user.id
    send_replacing_message(telegram_id, bot)


@bot.message_handler(commands=['rename'])
def rename(message):
    telegram_id = message.from_user.id
    explorer = get_or_create_explorer(telegram_id)

    if (len(explorer.path) == 1):
        bot.send_message(telegram_id, "Can't rename root directory")
    else:
        new_name = extract_unique_code(message.text)
        if (new_name != None and len(new_name) > 0):
            new_name = new_name.replace("'", "").replace('"', '')
            current_dir = explorer.get_current_dir()
            db.insert('directories', {'name': new_name}, {'id': str(current_dir['id'])})
    send_replacing_message(telegram_id, bot)


@bot.message_handler(commands=['note'])
def note(message):
    telegram_id = message.from_user.id
    explorer = get_or_create_explorer(telegram_id)

    new_message = bot.reply_to(message, message.text[6:])

    handle_docs(new_message, telegram_id=message.from_user.id)


@bot.message_handler(commands=['share'])
def share(message):
    telegram_id = message.from_user.id
    explorer = get_or_create_explorer(telegram_id)
    current_dir = explorer.get_current_dir()
    query = str(current_dir['id']) + "-" + str(current_dir['user_id'])
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            "This button", switch_inline_query=query)
    )
    bot.send_message(telegram_id, "Press this button and choose the person you want to share this directory to", reply_markup=markup)


@bot.message_handler(commands=['unshare'])
def unshare(message):
    telegram_id = message.from_user.id
    explorer = get_or_create_explorer(telegram_id)
    explorer.remove_shares()


@bot.inline_handler(lambda query: True)
def default_query(inline_query):
    message = '''I want to share a directory with you using FileX bot, please click <a href="http://telegram.me/filexbeta_bot?start=''' + inline_query.query + '''">here</a> to accept.'''
    try:
        r = telebot.types.InlineQueryResultArticle('1', 'Share directory', telebot.types.InputTextMessageContent(message, parse_mode="HTML"))
        bot.answer_inline_query(inline_query.id, [r])
    except Exception as e:
        print(e)


@bot.message_handler(content_types=['document', 'audio', 'document', 'photo', 'video', 'video_note', 'voice', 'contact'])
def handle_docs(message, telegram_id=False):
    if not telegram_id:
        telegram_id = message.from_user.id

    explorer = get_or_create_explorer(telegram_id)

    if (message.document != None):
        if (message.document.mime_type in strings['mime_conv']):
            mime = strings['mime_conv'][message.document.mime_type]
        else:
            print("Unkown mime: " + message.document.mime_type)
            mime = 'U'
        explorer.new_file(
            message.message_id, message.document.file_name.replace("'", "").replace('"', ''), mime, message.document.file_size)
    elif (message.audio != None):
        explorer.new_file(message.message_id, "audio" +
                          str(message.date), 'A', message.audio.file_size)
    elif (message.document != None):
        explorer.new_file(message.message_id, "document" +
                          str(message.date), 'D', message.document.file_size)
    elif (message.photo != None):
        explorer.new_file(message.message_id, "photo" +
                          str(message.date), 'P', message.photo[0].file_size)
    elif (message.video != None):
        explorer.new_file(message.message_id, "video" +
                          str(message.date), 'V', message.video.file_size)
    elif (message.video_note != None):
        explorer.new_file(message.message_id, "video_note" +
                          str(message.date), 'V', message.video_note.file_size)
    elif (message.voice != None):
        explorer.new_file(message.message_id, "voice" +
                          str(message.date), 'A', message.voice.file_size)
    elif (message.contact != None):
        explorer.new_file(message.message_id, "contact" +
                          str(message.date), 'D', message.contact.file_size)
    elif (message.text != None):
        explorer.new_file(message.message_id, message.text.split(
            '\n', 1)[0], 'D', len(message.text))

    send_replacing_message(telegram_id, bot)


@bot.message_handler(func=lambda m: True)
def text_message(message):
    if (message.forward_from):
        return handle_docs(message)

    new_directory_name = message.text
    telegram_id = message.from_user.id
    explorer = get_or_create_explorer(telegram_id)
    explorer.new_directory(new_directory_name)
    send_replacing_message(telegram_id, bot)


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    telegram_id = call.from_user.id
    explorer = get_or_create_explorer(telegram_id)
    action = call.data[:1]
    content_id = call.data[1:]

    if (call.data == ".."):
        explorer.go_to_parent_directory()

    if (call.data == "."):
        pass

    elif (action == "d"):
        explorer.go_to_directory(content_id)

    elif (action == "s"):
        explorer.go_to_directory(content_id)

    elif (action == "f"):
        file_message = db.select('files', "id = " + content_id)[0]
        user_message = db.select('users', "id = " + str(file_message['user_id']))[0]
        bot.forward_message(telegram_id, user_message['telegram_id'], file_message['telegram_id'])

    elif (action == "r"):
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton(
                '✅', callback_data='c' + call.data),
            telebot.types.InlineKeyboardButton('❌', callback_data='.')
        )
        message_sent = bot.send_message(
            telegram_id, "Are you sure?", reply_markup=markup)
        explorer.last_action_message_ids.append(message_sent.message_id)
        return

    elif (action == "c"):
        action = content_id[:1]
        content_id = content_id[1:]
        if (action == "r"):
            c_type = content_id[:1]
            content_id = content_id[1:]
            if (c_type == "d"):
                explorer.remove_directories([content_id])
            elif (c_type == "f"):
                explorer.remove_files([content_id])
            elif (c_type == "s"):
                directory_id = db.select('shares', "id = " + str(content_id))[0]['directory_id']
                explorer.remove_shares(explorer.user['id'], [directory_id])

    elif (action == "p"):
        explorer.explorer_list_position = explorer.explorer_list_position - 1
    elif (action == "n"):
        explorer.explorer_list_position = explorer.explorer_list_position+1

    send_replacing_message(telegram_id, bot)


def remove_messages(telegram_id, bot):
    explorer = get_or_create_explorer(telegram_id)
    result = []
    if (explorer.last_action_message_ids):
        for message_id in explorer.last_action_message_ids:
            try:
                result.append(bot.delete_message(telegram_id, message_id))
                explorer.last_action_message_ids.remove(message_id)
            except Exception as e:
                print("Line: " + str(sys.exc_info()[-1].tb_lineno))
                print(e)
    return result


def get_or_create_explorer(id):
    if (id not in explorers):
        explorers[id] = Explorer(id, db, MAX_FILES_PER_PAGE)
    return explorers[id]


def content_builder(content, up=True, previous_p=False, next_p=False):
    markup = telebot.types.InlineKeyboardMarkup()

    if (up):
        markup.add(telebot.types.InlineKeyboardButton(
            '⤴️ Go up', callback_data='..'))

    if (previous_p):
        markup.add(telebot.types.InlineKeyboardButton(
            '⏮ Previous', callback_data='p'))

    for each in content:
        if (each["type"] == "directories"):
            icon = "📁"
            letter = "d"
            key = "id"
        elif (each["type"] == "shares"):
            icon = "👥"
            letter = "s"
            key = "directory_id"
        elif (each['mime'] in strings['icon_mime']):
            icon = strings['icon_mime'][each['mime']]
            letter = "f"
            key = "id"
        else:
            icon = strings['icon_mime']['U']
            letter = "f"
            key = "id"

        markup.add(
            telebot.types.InlineKeyboardButton(
                icon + " " + each['name'], callback_data=letter + str(each[key])),
            telebot.types.InlineKeyboardButton(
                "❌", callback_data="r" + letter + str(each['id'])),
        )

    if (next_p):
        markup.add(telebot.types.InlineKeyboardButton(
            'Next ⏭', callback_data='n'))

    return markup


def handle_share(message):
    share_code = extract_unique_code(message.text).split("-")
    if (len(share_code) != 2):
        return False

    directory_id = str(int(share_code[0]))
    shared_from_user_id = str(int(share_code[1]))
    shared_to_user_id = str(int(message.from_user.id))

    shared_from_user = db.select('users', "id = " + shared_from_user_id)
    shared_to_user = db.select('users', "telegram_id = " + shared_to_user_id)
    directory = db.select('directories', "id = " + directory_id + " AND user_id = " + shared_from_user_id)

    if (len(shared_from_user + shared_to_user + directory) < 0):
        return False
    else:
        shared_to_user = shared_to_user[0]
        directory = directory[0]

    explorer = get_or_create_explorer(shared_to_user['telegram_id'])
    return explorer.receive_share(directory_id)


def send_replacing_message(telegram_id, bot):
    explorer = get_or_create_explorer(telegram_id)
    content = explorer.get_directory_content()
    previous_p = explorer.explorer_list_position > 0
    next_p = explorer.explorer_list_size - (explorer.explorer_list_position * MAX_FILES_PER_PAGE) > MAX_FILES_PER_PAGE
    keyboard = content_builder(content, len(
        explorer.path) > 1, previous_p, next_p)
    message_sent = bot.send_message(
        telegram_id, "**Path:** " + explorer.get_path_string(), reply_markup=keyboard, parse_mode="Markdown")
    remove_messages(telegram_id, bot)
    explorer.last_action_message_ids.append(message_sent.message_id)


def md5(in_str):
    m = hashlib.md5()
    m.update(in_str.encode('utf-8'))
    return m.hexdigest()


def extract_unique_code(text):
    # Extracts the unique_code from the sent /start command.
    return text.split()[1] if len(text.split()) > 1 else None


@server.route("/bot", methods=['POST'])
def getMessage():
    bot.process_new_updates(
        [telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200


@server.route("/")
def webhook():
    webhook = bot.get_webhook_info()
    print(webhook)
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + "/bot")
    return "!", 200


if (POLLING):
    bot.remove_webhook()
    bot.polling()
else:
    server.run(host="0.0.0.0", port=os.environ.get('PORT', 5000))
