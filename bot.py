import os
import json
import asyncio
import pprint
from twitter import *
import requests
from telethon.sync import TelegramClient, events
from telethon.tl.custom import Button, file
from telethon.tl.types import PeerUser, PeerChat, PeerChannel, InputMediaUploadedDocument
from telethon import utils
import shutil
import uuid

### Globals
HERE = os.path.abspath(os.path.dirname(__file__))

### Configuration class
class Config(object):
    def __init__(self) -> None:        
        self._last_checked = None
        self.options = None
        
        self.setup_last_checked(filepath='last_checked.json')
        self.setup_options(filepath='config.json')

    def setup_last_checked(self, filepath):
        with open(os.path.join(HERE, filepath), 'r') as fh:
            self._last_checked = json.load(fh)
    
    def setup_options(self, filepath):
        with open(os.path.join(HERE, filepath), 'r') as fh:
            self.options = json.load(fh)

    @property
    def last_checked(self):
        return self._last_checked

    @last_checked.setter
    def last_checked(self, value):
        last_checked = self.last_checked
        last_checked[value[0]] = value[1]
        with open(os.path.join(HERE, 'last_checked.json'), 'w') as fh:
                json.dump(last_checked, fh, indent=4, sort_keys=True)

    @property
    def watched_users(self):
        return self.options['twitter']['watched_users']

    @property
    def main_channel(self):
        return self.options['telegram']['main_channel']

    @property
    def approving_channel(self):
        return self.options['telegram']['approving_channel']

### Twitter Authentication class
class TwitterAuth(object):
    def __init__(self) -> None:
        self.twitter = None
        
        self.setup_twitter_json('auth.json')

    def setup_twitter_json(self, filepath):
        with open(os.path.join(HERE, filepath), 'r') as fh:
            self.twitter = json.load(fh)['twitter']
    
    @property
    def consumer_key(self):
        return self.twitter['consumer_key']

    @property
    def consumer_secret(self):
        return self.twitter['consumer_secret']
    
    @property
    def access_token(self):
        return self.twitter['access_token']
    
    @property
    def access_secret(self):
        return self.twitter['access_secret']

### Telegram Authentication class
class TelegramAuth(object):
    def __init__(self) -> None:
        self.telegram = None

        self.setup_telegram_json('auth.json')
    
    def setup_telegram_json(self, filepath):
        with open(os.path.join(HERE, filepath), 'r') as fh:
            self.telegram = json.load(fh)['telegram']

    @property
    def api_id(self):
        return self.telegram['api_id']

    @property
    def api_hash(self):
        return self.telegram['api_hash']

    @property
    def bot_token(self):
        return self.telegram['bot_token']

### Post class
class Post(object):
    def __init__(self, id, file, url, tgid) -> None:
        self._id = id
        self._file = file
        self._url =  url
        self._tgid = tgid

    @property
    def id(self):
        return self._id
    
    @property
    def file(self):
        return self._file

    @property
    def url(self):
        return self._url
        
    @property
    def tgid(self):
        return self._tgid

### Queue class
class PostQueue(object):
    def __init__(self) -> None:
        self._queue = []
        self.load()

    @property
    def queue(self):
        return self._queue

    def add(self, post: Post):
        self._queue.append(post)
        self.save()

    def retrieve(self, post_id: int):
        post = list(filter(lambda x: x.id == post_id, self.queue))[0]
        self._queue.remove(post)
        self.save()
        return post

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__, indent=4)

    def save(self):
        with open(os.path.join(HERE, 'queue.json'), 'w') as fh:
            fh.write(self.to_json())

    def load(self):
        with open(os.path.join(HERE, 'queue.json'), 'r') as fh:
            queue = json.load(fh)
        if len(queue) > 0:
            for post in queue['_queue']:
                self.add(Post(post['_id'], post['_file'], post['_url'], post['_tgid']))

### Global objects definition
print('Loading configurations...')
try:
    twitterAuth = TwitterAuth()
    telegramAuth = TelegramAuth()
    config = Config()
    queue = PostQueue()
    print('Configurations loaded succesfully!')
except BaseException as e:
    print('Failed to load configurations!')
    raise e


### Twitter handle initialization
print('Authenticating into Twitter APIs...')
try:
    twh = Twitter(
        auth=OAuth(
            twitterAuth.access_token,
            twitterAuth.access_secret,
            twitterAuth.consumer_key,
            twitterAuth.consumer_secret
            )
    )
    print('Authentication successful!')
except BaseException as e:
    print('Failed to authenticate into Twitter APIs!')
    raise e

### Telegram handle initialization
print('Authenticating into Telegram Bot APIs...')
try:
    tgh = TelegramClient(
        'bot',
        telegramAuth.api_id,
        telegramAuth.api_hash
    ).start(
        bot_token=telegramAuth.bot_token
    )
    print('Authentication successful!')
except BaseException as e:
    print('Failed to authenticate into Telegram Bot APIs!')
    raise e

### Telegram callback handler
@tgh.on(events.CallbackQuery)
async def callback(event):
    original_message = await event.get_message()
    cbdatadec = event.data.decode('utf-8').split('-')
    cbaction = cbdatadec[0]
    cbdata = cbdatadec[1]

    if cbaction == 'pub':
        post = queue.retrieve(int(cbdata))
        await tgh.send_message(PeerChannel(config.main_channel), file=[f for f in post.file], message=f'[Original Tweet]({post.url})')
        to_delete = [original_message.id]
        to_delete.extend([x for x in post.tgid])
        await tgh.delete_messages(PeerChannel(config.approving_channel), message_ids=to_delete)
        for f in post.file:
            os.remove(f)
        await event.answer('Post published succesfully!')

    elif cbaction == 'del':
        post = queue.retrieve(int(cbdata))
        to_delete = [original_message.id]
        to_delete.extend([x for x in post.tgid])
        await tgh.delete_messages(PeerChannel(config.approving_channel), message_ids=to_delete)
        for f in post.file:
            os.remove(f)
        await event.answer('Post deleted succesfully!')


### Check if new retweets are made, then sends it to the approval channel
async def check_retweet():
    print('Fetching Twitter timeline...')
    try:
        f_statuses = list()
        for user in config.watched_users:
            statuses = twh.statuses.user_timeline(
                screen_name=user,
                count=None if config.last_checked[user] else 15,
                since_id=config.last_checked[user] if config.last_checked[user] else None,
                tweet_mode='extended'
            )
            f_statuses = f_statuses + list(filter(lambda x: x['retweeted_status'], statuses))
            print(f'Fetched {len(f_statuses)} total unprocessed posts! Current user: @{user}')
    except BaseException as e:
        print('Failed to fetch Twitter timeline!')
        raise e

    try:        
        f_statuses.reverse()
        for i, s in enumerate(f_statuses):
            tw_id = s['id']
            files = []
            for m in s['retweeted_status']['extended_entities']['media']:
                if m['type'] == 'photo':
                    url = m['media_url']
                    response = requests.get(url, stream=True)
                    ext = url.split('.')[-1]                    
                elif m['type'] == 'video':
                    url = m['video_info']['variants'][0]['url']
                    response = requests.get(url, stream=True)
                    ext = url.split('.')[-1].split('?')[0]

                file_id = str(uuid.uuid4())
                filename = 'img/{}.{}'.format(file_id, ext)                
                files.append(filename)
                with open(filename, 'wb') as out_file:
                    shutil.copyfileobj(response.raw, out_file)
                del response

            original = s['retweeted_status']['entities']['media'][0]['expanded_url']

            message = await tgh.send_file(PeerChannel(config.approving_channel), file=[f for f in files])
            
            buttons = [[Button.inline('Yes', f'pub-{tw_id}'.encode()), Button.inline('No', f'del-{tw_id}'.encode())]]   
            await tgh.send_message(PeerChannel(config.approving_channel), message='Publish this post?', buttons=buttons)
            queue.add(Post(tw_id, files, original, [m.id for m in message]))

            config.last_checked = [s['user']['screen_name'], tw_id]
            print(f'Processed {i+1}/{len(f_statuses)} posts...')
        print('All posts processed and waiting for approval!')
    except BaseException as e:
        print('Failed to process posts!')
        raise e

async def main():
    task = asyncio.create_task(check_retweet(), name='check_tweet')
    while True:
        if task.done():
            task = asyncio.create_task(check_retweet(), name='check_tweet')
        await asyncio.sleep(60)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    tgh.start()
    tgh.run_until_disconnected()