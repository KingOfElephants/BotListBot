import codecs

import datetime
from pprint import pprint

from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler
from telegram.ext.dispatcher import run_async

import captions
import const
import helpers
import util
from const import *
from const import BotStates
from custemoji import Emoji
from model import Bot
from model import Category
from model import Channel


def menu(bot, update):
    chat_id = util.chat_id_from_update(update)
    buttons = [[
        KeyboardButton(captions.EXIT),
    ], [
        KeyboardButton(captions.ADD_BOT),
        KeyboardButton(captions.EDIT_BOT),
    ], [
        KeyboardButton(captions.SEND_BOTLIST)
    ]]
    util.send_md_message(bot, chat_id, "Administration menu.",
                         reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
    return BotStates.ADMIN_MENU


def _input_failed(bot, update, chat_data, text):
    chat_id = util.chat_id_from_update(update)
    util.send_message_failure(bot, chat_id, text)
    chat_data['add_bot_message'] = None


def add_bot(bot, update, chat_data, category=None):
    chat_id = util.chat_id_from_update(update)
    text_input = None
    if update.message:
        text_input = update.message.text
    from bot import select_category
    if not category:
        msg = select_category(bot, update, CallbackActions.ADD_BOT_SELECT_CAT)
        chat_data['add_bot_message'] = msg.message_id
        return BotStates.ADDING_BOT
    text = ""
    reply_markup = None

    new_bot = chat_data.get('add_bot', None)
    if new_bot is None:
        new_bot = Bot(category=category)
        chat_data['add_bot'] = new_bot
        text += "*{}* category selected.\n\n".format(category)

    if new_bot.username is None:
        if text_input:
            username = helpers.validate_username(text_input)
            if username:
                new_bot.username = username
                text += "Username *{}* chosen.\n\n".format(username)
            else:
                return _input_failed(bot, update, chat_id, "Invalid username. Please try again.")
        else:
            text += util.action_hint("Please send me the *@username* of the bot to add")

    msg = util.send_or_edit_md_message(bot, chat_id, text, to_edit=chat_data['add_bot_message'],
                                       reply_markup=reply_markup)
    chat_data['add_bot'] = new_bot
    return BotStates.ADDING_BOT


def edit_bot(bot, update, chat_data, bot_to_edit=None):
    chat_id = util.chat_id_from_update(update)

    if not bot_to_edit:
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Select from category", callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT_SELECT_CAT
            ))
        ]])
        util.send_action_hint(bot, chat_id, "Search for a bot to edit or select it manually.",
                              reply_markup=reply_markup)
        return


def prepare_transmission(bot, update, chat_data):
    chat_id = util.chat_id_from_update(update)
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("☑ Done, please send the BotList", callback_data=util.callback_for_action(
            CallbackActions.SEND_BOTLIST
        ))
    ]])
    util.send_md_message(bot, chat_id, "Okay. Now please delete *all* old messages in @BotList.",
                         reply_markup=reply_markup)


@run_async
def send_botlist(bot, update, chat_data, resend_gif=False):
    chat_id = util.chat_id_from_update(update)
    message_id = util.message_id_from_update(update)
    channel = Channel.get(Channel.username == "botlist_testchannel")

    def notify_admin(txt):
        util.send_or_edit_md_message(bot, chat_id, Emoji.HOURGLASS_WITH_FLOWING_SAND + ' ' + txt, to_edit=message_id)

    if resend_gif:
        notify_admin("Sending intro GIF...")
        bot.sendDocument(channel.chat_id, open("assets/gif/animation.gif", 'rb'), timeout=120)
        channel.last_message_id += 1

    with codecs.open('files/intro.txt', 'r', 'utf-8') as f:
        intro = f.read()

    notify_admin("Sending channel intro text...")
    intro_msg = util.send_or_edit_md_message(bot, channel.chat_id, intro, to_edit="", timeout=120)
    channel.last_message_id = intro_msg.message_id

    counter = 0
    all_categories = Category.select()
    n = len(all_categories)
    for c in all_categories:
        counter += 1
        if counter % 5 == 1:
            notify_admin("Sending categories *{} to {}* ({} total)...".format(
                counter,
                n if counter + 4 > n else counter + 4,
                n
            ))

        # format category text
        cat_bots = Bot.select().where(Bot.category == c)
        text = '*' + str(c) + '*\n'
        text += '\n'.join([str(b) for b in cat_bots])

        # add "Details" deep-linking button
        buttons = list()
        if len([b for b in cat_bots if b.description is not None]):
            buttons.append(
                InlineKeyboardButton("Details", url="https://t.me/{}?start={}".format(
                    const.SELF_BOT_NAME, c.id)))
        buttons.append(InlineKeyboardButton("Copy Link", url="https://t.me/{}/{}".format(channel.username,
                                                                                         channel.last_message_id + 1)))
        reply_markup = InlineKeyboardMarkup([buttons])

        msg = util.send_or_edit_md_message(bot, channel.chat_id, text, reply_markup=reply_markup,
                                     to_edit=c.current_message_id, timeout=120)
        c.current_message_id = msg.message_id
        channel.last_message_id = msg.message_id
        c.save()

    with codecs.open('files/new_bots_list.txt', 'r', 'utf-8') as f:
        new_bots_list = f.read()

    # build list of newly added bots
    new_bots = Bot.select().where(
        Bot.date_added > datetime.date.today() - datetime.timedelta(days=const.BOT_CONSIDERED_NEW))
    # insert spaces and the name of the bot
    new_bots_list = new_bots_list.format('\n'.join(['     ' + str(b) for b in new_bots]))
    util.send_md_message(bot, channel.chat_id, new_bots_list, timeout=120)
    channel.last_message_id += 1
    new_bots_message_id = channel.last_message_id

    # generate category links to previous messages
    categories = '\n'.join(["[{}](https://t.me/{}/{})".format(
        str(c),
        channel.username,
        c.current_message_id
    ) for c in Category.select()])
    with codecs.open('files/category_list.txt', 'r', 'utf-8') as f:
        category_list = f.read()

    # insert placeholders in categories list
    category_list = category_list.format(
        "http://t.me/{}/{}".format(channel.username, intro_id), categories,
        "http://t.me/{}/{}".format(channel.username, new_bots_message_id),
        datetime.date.today().strftime("%d-%m-%Y")
    )
    util.send_md_message(bot, channel.chat_id, category_list, timeout=120)
    channel.last_message_id += 1

    channel.save()
    util.send_or_edit_md_message(bot, chat_id, util.success("Botlist updated successfully."),
                                 to_edit=message_id)


def exit_menu(bot, update):
    from bot import main_menu
    main_menu(bot, update)
    return ConversationHandler.END
