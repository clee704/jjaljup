#! /usr/bin/env python
from __future__ import print_function

import code
import itertools
import logging
import os
import pprint
import Queue
import re
import string
import sys
import threading
import time
import webbrowser
from datetime import datetime
from distutils.version import StrictVersion
from threading import Thread
from urlparse import urlparse

import click
import requests
import requests_oauthlib
import sqlalchemy
import twitter
from click import secho
from pyquery import PyQuery as pq
from requests_oauthlib import OAuth1Session
from sqlalchemy import Column, event, ForeignKey, Integer, String, Table
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from twitter import Api as ApiBase
from twitter import Status as StatusBase
from twitter import TwitterError
from unidecode import unidecode
from werkzeug.utils import secure_filename

__version__ = '0.0.7'

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = frozenset(['jpg', 'jpeg', 'gif', 'png'])

REQUEST_TOKEN_URL = 'https://api.twitter.com/oauth/request_token'
AUTHORIZATION_URL = 'https://api.twitter.com/oauth/authorize'
ACCESS_TOKEN_URL = 'https://api.twitter.com/oauth/access_token'
RATE_LIMIT_EXCEEDED = 88

Base = declarative_base()
Session = sessionmaker()


favorite_table = Table(
    'favorite', Base.metadata,
    Column('user_id', Integer, ForeignKey('user.id', ondelete='CASCADE'),
           primary_key=True),
    Column('tweet_id', Integer, ForeignKey('tweet.id', ondelete='CASCADE'),
           primary_key=True),
)


class User(Base):
    __tablename__ = 'user'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    screen_name = Column(String, nullable=False)
    oauth_token = Column(String, nullable=False)
    oauth_token_secret = Column(String, nullable=False)

    favorites = relationship('Tweet', secondary=favorite_table, lazy='dynamic')

    def __repr__(self):
        return '<User @{o.screen_name}>'.format(o=self)


class Tweet(Base):
    __tablename__ = 'tweet'

    id = Column(Integer, primary_key=True)

    images = relationship('Image', backref='tweet', lazy='joined',
                          cascade='all, delete-orphan', passive_deletes=True)
    favorited_users = relationship('User', secondary=favorite_table,
                                   lazy='dynamic')

    def __repr__(self):
        return '<Tweet(id={o.id})>'.format(o=self)


class Image(Base):
    __tablename__ = 'image'

    id = Column(Integer, primary_key=True)
    tweet_id = Column(Integer, ForeignKey('tweet.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    url = Column(String, nullable=False)
    name = Column(String, nullable=False)

    def __init__(self, url=None, name=None):
        self.url = url
        self.name = name
        self.cached_data = None

    def get_path(self, directory):
        bname = secure_filename(unidecode(u'{0}_{1}'.format(self.tweet_id,
                                                            self.name)))
        return os.path.join(directory, bname)

    def __repr__(self):
        return '<Image(url={o.url!r})>'.format(o=self)


@event.listens_for(Engine, 'connect')
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()


class State(object):

    def __init__(self):
        self.client_key = None
        self.client_secret = None
        self.session = None


pass_state = click.make_pass_decorator(State, ensure=True)


def client_credentials_option(f):

    def key_callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.client_key = value
        return state

    def secret_callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.client_secret = value
        return state

    key_option = click.option('--api-key', metavar='KEY',
                              envvar='JJALJUP_API_KEY', prompt='API key',
                              expose_value=False, callback=key_callback,
                              help='API key of your Twitter app.')
    secret_option = click.option('--api-secret', metavar='SECRET',
                                 envvar='JJALJUP_API_SECRET',
                                 prompt='API secret', expose_value=False,
                                 callback=secret_callback,
                                 help='API secret of your Twitter app.')
    return key_option(secret_option(f))


def session_option(f):
    def callback(ctx, param, value):
        engine = sqlalchemy.create_engine(value)
        Session.configure(bind=engine)
        Base.metadata.create_all(engine)
        state = ctx.ensure_object(State)
        state.session = Session(autocommit=True)
        return state
    return click.option('--database-uri', metavar='URI',
                        envvar='JJALJUP_DATABASE_URI',
                        default='sqlite:///jjaljup.db', expose_value=False,
                        callback=callback,
                        help='Specify a database that contains information '
                             'about authorized Twitter accounts and favorite '
                             'tweets (defaults to sqlite:///jjaljup.db).')(f)


@click.group()
@click.option('--debug', is_flag=True, default=False, help='Show debug logs.')
@click.version_option(__version__, prog_name='jjaljup')
def cli(debug):
    """
    jjaljup is a downloader for images in your favorite tweets. To use this
    script, you must create your own Twitter app at apps.twitter.com. Specify
    your app's API key and secret when using jjaljup commands, or have
    environment variables named JJALJUP_API_KEY and JJALJUP_API_SECRET to set
    them automatically.

    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.WARN)


@cli.command(short_help='Start a Python interpreter to debug.')
@session_option
@client_credentials_option
@pass_state
def debug(state):
    """
    Start a Python interpreter to debug. This command is intended for
    developers.

    """
    def create_api(user):
        return twitter.Api(consumer_key=state.client_key,
                           consumer_secret=state.client_secret,
                           access_token_key=user.oauth_token,
                           access_token_secret=user.oauth_token_secret)
    ctx = {'state': state, 'session': state.session, 'create_api': create_api}
    ctx.update(globals())
    try:
        from IPython import embed
        embed(user_ns=ctx)
    except ImportError:
        code.interact(local=ctx)


@cli.command()
@session_option
@client_credentials_option
@pass_state
def add(state):
    """Authorize a new Twitter account."""
    add_user(state.session, state.client_key, state.client_secret)


@cli.command()
@session_option
@pass_state
def accounts(state):
    """Show authorized accounts in the database."""
    users = list_users(state.session)
    if not users:
        print('No accounts.')
    else:
        print(plformat('There {|is/are} {0} {|account(s)}:', len(users)))
        for i, user in enumerate(users, 1):
            secho(u' {0}. {1} (@{2})'.format(i, user.name, user.screen_name))


@cli.command(short_help='Download images in favorite tweets.')
@click.option('-a', '--account', metavar='SCREEN_NAME',
              help='Select a Twitter account to sync.')
@click.option('-d', '--directory', metavar='PATH', default='images',
              prompt=True, type=click.Path(file_okay=False, writable=True,
                                           resolve_path=True),
              help='Select a local directory to sync. If the path does not '
                   'exist, new directories will be created as necessary.')
@click.option('--count', metavar='N', type=click.IntRange(1),
              help='Number of favorite tweets to sync. If set, only the most '
                   'recent N tweets are examined.')
@click.option('--delete', is_flag=True, default=False,
              help='Delete unfavorited tweets and images from the directory. '
                   'Disabled by default.')
@click.option('--workers', metavar='N', type=click.IntRange(1), default=8,
              help='Number of threads to run concurrently (defaults to 8).')
@session_option
@client_credentials_option
@pass_state
def sync(state, account, directory, count, delete, workers):
    """
    Synchronize images in the selected account's favorite tweets into the
    specified directory. Due to the limit on the Twitter API, at most 200
    tweets can be processed per API call and 15 calls made every 15 minutes,
    thus 12000 tweets per hour.

    """
    CALL_SIZE = 200
    INFINITY = float('inf')
    if count is None:
        count = INFINITY

    if not os.path.exists(directory):
        os.makedirs(directory)
        secho(b'Created a directory at {0}'.format(directory))
    secho(b'Images will be downloaded into {0}'.format(directory))

    user = select_user(state.session, state.client_key, state.client_secret,
                       account)
    api = twitter.Api(consumer_key=state.client_key,
                      consumer_secret=state.client_secret,
                      access_token_key=user.oauth_token,
                      access_token_secret=user.oauth_token_secret)

    num_favorites = None
    try:
        num_favorites = api.VerifyCredentials().favourites_count
    except TwitterError as e:
        if not is_rate_limited(e):
            raise
    if num_favorites is not None:
        eta_min = max(1, int(min(count, num_favorites) / CALL_SIZE))
        eta_max = max(10, int(min(count, num_favorites) / CALL_SIZE * 2))
        print(plformat('You have {0} favorite {|tweet(s)}.', num_favorites))
        if count != INFINITY:
            print(plformat('Only the most recent {0} {|tweet(s)} will be '
                           'examined.', count))
        print('It may take {0}-{1} minutes to complete.'.format(eta_min,
                                                                eta_max))

    max_id = None
    tweet_ids = set()
    num_saved_tweets = 0
    num_saved_images = 0
    input_queue = Queue.Queue()
    output_queue = Queue.Queue()
    for _ in range(workers):
        t = Thread(target=save_tweet_mt,
                   args=(directory, user.id, input_queue, output_queue))
        t.start()
    try:
        last = False
        while not last:
            status = get_rate_limit_status(api, 'favorites')
            data = status['favorites']['/favorites/list']
            limit = data['limit']
            remaining = data['remaining']
            print_api_status = lambda: print(
                'Remaining API calls: {0}/{1}'.format(remaining, limit))
            print_api_status()
            reset = data['reset']
            try:
                while remaining > 0:
                    tweets = api.GetFavorites(count=CALL_SIZE, max_id=max_id)
                    remaining -= 1
                    for tweet in tweets:
                        input_queue.put(tweet)
                        tweet_ids.add(tweet.id)
                        num_saved_tweets += 1
                        if num_saved_tweets >= count:
                            break
                    input_queue.join()
                    while True:
                        try:
                            num_saved_images += output_queue.get_nowait()
                        except Queue.Empty:
                            break
                    max_id = tweets[-1].id - 1 if tweets else 0
                    print('There are no more tweets. ' if len(tweets) == 0 else
                          plformat('{0} {|tweet(s)} {|has/have} been '
                                   'processed. ', num_saved_tweets), end='')
                    print_api_status()
                    last = len(tweets) == 0 or num_saved_tweets >= count
                    if last:
                        break
            except TwitterError as e:
                if not is_rate_limited(e):
                    raise
            if last:
                break
            reset_dt = datetime.fromtimestamp(reset)
            print(('Rate limit exceeded. '
                   'Waiting for the next round at {0}.').format(reset_dt))
            time.sleep(max(1, reset - time.time() + 10))

        secho(plformat(b'Synchronized {0} {0|image(s)} in {1} {1|tweet(s)} '
                       b'into {2}', num_saved_images, num_saved_tweets,
                       directory))
    finally:
        # Stop workers
        for _ in range(workers):
            input_queue.put(None)

        if tweet_ids and delete:
            min_id = min(tweet_ids)
            num_deleted_tweets = 0
            num_deleted_images = 0
            qr = user.favorites.filter(~Tweet.id.in_(tweet_ids))
            if count != INFINITY:
                qr = qr.filter(Tweet.id >= min_id)
            for tweet in qr:
                num_deleted_tweets += 1
                num_deleted_images += len(tweet.images)
                delete_tweet(state.session, directory, user, tweet)
            if num_deleted_tweets > 0:
                print(plformat('Deleted {0} {0|image(s)} in {1} unfavorited '
                               '{1|tweet(s)}.', num_deleted_images,
                               num_deleted_tweets))


@cli.command(short_help='Monitor account activity and download new images.')
@click.option('-a', '--account', metavar='SCREEN_NAME',
              help='Select a Twitter account to monitor.')
@click.option('-d', '--directory', metavar='PATH', default='images',
              prompt=True, type=click.Path(file_okay=False, writable=True,
                                           resolve_path=True),
              help='Select a local directory to sync. If the path does not '
                   'exist, new directories will be created as necessary.')
@click.option('--delete', is_flag=True, default=False,
              help='Delete unfavorited tweets and images from the directory. '
                   'Disabled by default.')
@session_option
@client_credentials_option
@pass_state
def watch(state, account, directory, delete):
    """
    Monitor the selected account's activity and save images in tweets that
    is favorited by the account.

    """
    if not os.path.exists(directory):
        os.makedirs(directory)
        secho(b'Created a directory at {0}'.format(directory))
    secho(b'Images will be downloaded into {0}'.format(directory))

    session = state.session
    user = select_user(session, state.client_key, state.client_secret, account)
    api = twitter.Api(consumer_key=state.client_key,
                      consumer_secret=state.client_secret,
                      access_token_key=user.oauth_token,
                      access_token_secret=user.oauth_token_secret)

    stream = api.GetUserStream()
    try:
        print('Receiving...')
        for msg in stream:
            if 'event' in msg and 'target_object' in msg:
                if msg['source']['id'] != user.id:
                    continue
                td = twitter.Status.NewFromJsonDict(msg['target_object'])
                if msg['event'] == 'favorite':
                    # FIXME extended_entities are missing in tweets from
                    # Streaming API. Is it a bug in the API?
                    # See https://dev.twitter.com/issues/1724
                    try:
                        td = api.GetStatus(td.id)
                    except TwitterError as e:
                        if is_rate_limited(e):
                            secho('Keep calm and take a rest.', fg='red',
                                  file=sys.stderr)
                    num_images = save_tweet(session, directory, user.id, td)
                    color = 'green' if num_images else 'yellow'
                    secho(plformat('{0} {|image(s)} are saved from a favorited '
                                   'tweet: ', num_images), fg=color, nl=False)
                    secho(td.text.replace(u'\n', u' '))
                elif msg['event'] == 'unfavorite' and delete:
                    tweet = user.favorites.filter(Tweet.id == td.id).scalar()
                    if tweet is None:
                        continue
                    num_images = len(tweet.images)
                    delete_tweet(session, directory, user, tweet)
                    color = 'red' if num_images else 'yellow'
                    secho(plformat('{0} {|image(s)} are deleted from an '
                                   'unfavorited tweet: ', num_images),
                          fg=color, nl=False)
                    secho(td.text.replace(u'\n', u' '))
    except TwitterError as e:
        if is_rate_limited(e):
            secho('Exceeded connection limit for user. '
                  'Please try again later.', fg='red', file=sys.stderr)
        else:
            raise
    finally:
        stream.close()


def list_users(session):
    return session.query(User).order_by(User.id).all()


def select_user(session, client_key, client_secret, screen_name=None):
    user = session.query(User).filter_by(screen_name=screen_name).first()
    if user is not None:
        return user
    if screen_name is not None:
        secho(u'@{0} does not exist.'.format(screen_name), fg='red',
              file=sys.stderr)
    users = list_users(session)
    user = None
    if users:
        n = len(users) + 1
        secho('Choose a Twitter account to work with:', fg='blue')
        for i, u in enumerate(users, 1):
            secho(u' {0}. {1} (@{2})'.format(i, u.name, u.screen_name))
        print(' {0}. Add a new account'.format(n))
        choice = click.prompt(click.style('Choice: ', fg='blue'),
                              type=click.IntRange(1, n), prompt_suffix='')
        if choice != n:
            user = users[choice - 1]
    if user is None:
        user = add_user(session, client_key, client_secret)
    return user


def add_user(session, client_key, client_secret):
    oauth_token, oauth_token_secret = get_token_credentials(client_key,
                                                            client_secret)
    api = twitter.Api(consumer_key=client_key, consumer_secret=client_secret,
                      access_token_key=oauth_token,
                      access_token_secret=oauth_token_secret)
    info = api.VerifyCredentials()
    debug_timer_start('add_user')
    with session.begin():
        user = session.query(User).get(info.id)
        if not user:
            user = User(id=info.id, name=info.name,
                        screen_name=info.screen_name,
                        oauth_token=oauth_token,
                        oauth_token_secret=oauth_token_secret)
            session.add(user)
        else:
            user.name = info.name
            user.screen_name = info.screen_name
            user.oauth_token = oauth_token
            user.oauth_token_secret = oauth_token_secret
    debug_timer_end('add_user')
    secho(u'Added {0} (@{1}).'.format(user.name, user.screen_name))
    return user


def get_token_credentials(client_key, client_secret):
    oauth = OAuth1Session(client_key, client_secret=client_secret,
                          callback_uri='oob')
    temporary_credentials = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    oauth_token = temporary_credentials.get('oauth_token')
    oauth_token_secret = temporary_credentials.get('oauth_token_secret')

    authorization_url = oauth.authorization_url(AUTHORIZATION_URL)
    secho('Copy and paste the following URL into your web browser and '
          'authorize the app:', fg='blue')
    print(authorization_url)
    webbrowser.open(authorization_url)
    verifier = click.prompt(click.style('Enter the PIN', fg='blue'))

    oauth = OAuth1Session(client_key, client_secret=client_secret,
                          resource_owner_key=oauth_token,
                          resource_owner_secret=oauth_token_secret,
                          verifier=verifier)
    token_credentials = oauth.fetch_access_token(ACCESS_TOKEN_URL)
    oauth_token = token_credentials.get('oauth_token')
    oauth_token_secret = token_credentials.get('oauth_token_secret')
    return oauth_token, oauth_token_secret


def get_rate_limit_status(api, resources):
    while True:
        try:
            return api.GetRateLimitStatus(resources)['resources']
        except TwitterError as e:
            if is_rate_limited(e):
                secho('Rate limit exceeded. Waiting for 3 minutes before '
                      'trying again.', fg='red', file=sys.stderr)
            else:
                raise
        time.sleep(180)


def is_rate_limited(twitter_error):
    data = twitter_error.args[0]
    if isinstance(data, list):
        return RATE_LIMIT_EXCEEDED in (e.get('code') for e in data)
    else:
        return data == 'Exceeded connection limit for user'


def save_tweet_mt(directory, user_id, tweets_queue, num_images_queue):
    session = Session(autocommit=True)
    while True:
        tweet_data = tweets_queue.get()
        if tweet_data is None:
            break
        try:
            num_images = save_tweet(session, directory, user_id, tweet_data)
            num_images_queue.put(num_images)
        except Exception:
            logger.exception('Unexpected error occurred while saving a tweet.')
            logger.debug('The tweet was: %s',
                         pprint.pformat(tweet_data.AsDict()))
        finally:
            tweets_queue.task_done()


def save_tweet(session, directory, user_id, tweet_data):
    debug_timer_start('save_tweet_1')
    with session.begin():
        tweet = session.query(Tweet).get(tweet_data.id)
        if tweet is None:
            tweet = Tweet(id=tweet_data.id)
            session.add(tweet)
        if tweet.favorited_users.filter_by(id=user_id).count() == 0:
            session.execute(favorite_table.insert().values(
                user_id=user_id, tweet_id=tweet.id))
    debug_timer_end('save_tweet_1')
    images = extract_images(tweet_data)
    debug_timer_start('save_tweet_2')
    with session.begin():
        tweet.images[:] = images
    debug_timer_end('save_tweet_2')
    num_images = 0
    for img in tweet.images:
        path = img.get_path(directory)
        if os.path.exists(path):
            num_images += 1
        else:
            image_data = img.cached_data
            del img.cached_data
            if not image_data:
                resp = requests.get(img.url)
                image_data = resp.content
                error = u''
                if resp.status_code != 200:
                    error = u'Got status code {0} from {1}'.format(
                        resp.status_code, img.url)
                elif not image_data:
                    error = u'Got empty response from {0}'.format(img.url)
                if error:
                    secho(error, fg='red', file=sys.stderr)
                    continue
            try:
                with open(path, 'wb') as f:
                    f.write(image_data)
                num_images += 1
            except IOError as e:
                secho(u'Failed to save the image to {0}: {1}'.format(
                    path, e.strerror), fg='red', file=sys.stderr)
    return num_images


def delete_tweet(session, directory, user, tweet):
    for img in tweet.images:
        path = img.get_path(directory)
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError as e:
                secho(u'Failed to delete the image at {0}: {1}'.format(
                    path, e.strerror), fg='red', file=sys.stderr)
    debug_timer_start('delete_tweet')
    with session.begin():
        user.favorites.remove(tweet)
        if tweet.favorited_users.count() == 0:
            session.delete(tweet)
    debug_timer_end('delete_tweet')


def extract_images(tweet_data):
    images = []
    image_urls = []
    for media in tweet_data.media:
        if media.get('type') == 'photo':
            url = media.get('media_url')
            if url:
                image_urls.append(url)
    for url_data in tweet_data.urls:
        url = url_data.expanded_url
        if not url:
            continue
        o = urlparse(url)
        if is_image_url(url, o):
            image_urls.append(url)
        elif o.netloc == 'twitter.com' and re.match(r'/.*/photo/\d+', o.path):
            img = get_twitter_agif(url, o)
            if img:
                images.append(img)
        elif o.netloc == 'twitpic.com':
            img = get_twitpic(url, o)
            if img:
                images.append(img)
        elif o.netloc == 'yfrog.com':
            img = get_yfrog(url, o)
            if img:
                images.append(img)
    for url in image_urls:
        o = urlparse(url)
        name = os.path.basename(o.path)
        if o.netloc == 'pbs.twimg.com' and 'tweet_video' not in url:
            url = url + ':orig'
        images.append(Image(url=url, name=name))
    for img in images:
        if not img.name:
            img.name = os.path.basename(urlparse(img.url).path)
    return images


def is_image_url(url, o):
    return o.path.lower().rsplit('.', 1)[-1] in IMAGE_EXTENSIONS


def is_image(resp):
    return resp.headers.get('content-type', '').startswith('image')


def get_twitter_agif(original_url, o):
    resp = requests.get(original_url)
    if resp.status_code != 200:
        return
    url = pq(resp.text).find('video.animated-gif source[type="video/mp4"]') \
                       .attr('video-src')
    if url:
        return Image(url=url)


def get_twitpic(original_url, o):
    url = 'http://twitpic.com/show/full' + o.path
    resp = requests.get(url)
    if resp.status_code != 200 or not is_image(resp):
        return
    img = Image(url=url, name=os.path.basename(urlparse(resp.url).path))
    img.cached_data = resp.content
    return img


def get_yfrog(original_url, o):
    page_url = 'http://twitter.yfrog.com/z' + o.path
    resp = requests.get(page_url)
    if resp.status_code != 200:
        return
    url = pq(resp.text).find('#the-image img').attr('src')
    if url:
        return Image(url=url)


# Hack until https://github.com/bear/python-twitter/issues/160 is resolved
class Status(StatusBase):

    @staticmethod
    def NewFromJsonDict(data):
        status = StatusBase.NewFromJsonDict(data)
        if 'extended_entities' in data:
            if 'media' in data['extended_entities']:
                status.media = data['extended_entities']['media']
        return status

twitter.Status = Status


# Hack until following issues are resolved:
#  1. Broken GetUserStream (https://github.com/bear/python-twitter/pull/162)
#  2. Bugs in Streaming API where responses are slopily parsed (newline should
#     be \r\n instead of \n and should return a message as soon as it is
#     received) and delimited=length is not handled at all are resolved.
# TODO create a pull request to bear/python-twitter
class Api(ApiBase):

    def GetUserStream(self, replies='all', withuser='user', track=None,
                      locations=None, delimited=None, stall_warning=None,
                      stringify_friend_ids=False):
        if not self.__auth:
            raise TwitterError("twitter.Api instance must be authenticated")
        data = {}
        if stringify_friend_ids:
            data['stringify_friend_ids'] = 'true'
        if replies is not None:
            data['replies'] = replies
        if withuser is not None:
            data['with'] = withuser
        if track is not None:
            data['track'] = ','.join(track)
        if locations is not None:
            data['locations'] = ','.join(locations)
        if delimited is not None:
            data['delimited'] = str(delimited)
        if delimited is not None:
            data['stall_warning'] = str(stall_warning)
        url = 'https://userstream.twitter.com/1.1/user.json'
        r = self._RequestStream(url, 'POST', data=data)

        # Streaming API returns 420 instead of 429, unlike other 1.1 APIs.
        if r.status_code == 420 or r.status_code == 429:
            raise TwitterError(r.read())

        return self._IterMessages(r, delimited)

    def _IterMessages(self, resp, delimited):
        buf = bytearray()
        delimiter = b'\r\n'
        delimiter_length = len(delimiter)
        while True:
            chunk = resp.raw.read(resp.raw._fp.chunk_left or 1,
                                  decode_content=True)
            if not chunk:
                continue
            suffix_length = len(chunk) + (delimiter_length - 1 if buf else 0)
            buf.extend(chunk)
            suffix = buf[-suffix_length:]
            i = -delimiter_length
            while True:
                i = suffix.find(delimiter, i + delimiter_length)
                if i == -1:
                    break
                j = len(buf) - suffix_length + i
                line = bytes(buf[:j])
                del buf[:j + delimiter_length]

                if not line:
                    continue

                # delimited=length is useless when chunked transfer encoding
                # is in use. If it's not, it still can't benefit from knowing
                # the length of the next message if the stream is compressed.
                # Here we just effectively ignore delimited=length.
                if delimited == 'length':
                    try:
                        message_length = int(line)
                        continue
                    except ValueError:
                        pass

                if line:
                    data = self._ParseAndCheckTwitter(line)
                    yield data

twitter.Api = Api


class PluralFormatter(string.Formatter):

    def get_value(self, key, args, kwargs):
        if isinstance(key, (int, long)):
            return args[key]
        if key in kwargs:
            return kwargs[key]
        if '|' in key:
            k, choices = self._decode_field(key)
            if k == '':
                value = self._get_one_number(args, kwargs)
            else:
                value = args[k] if isinstance(k, (int, long)) else kwargs[k]
            return choices[0] if value == 1 else choices[1]

    def _decode_field(self, key):
        k, choices_str = key.split('|')
        try:
            k = int(k)
        except ValueError:
            pass
        choices = self._decode_choices(choices_str)
        return k, choices

    def _decode_choices(self, choices_str):
        if '/' in choices_str:
            return choices_str.split('/')
        if '(' in choices_str and choices_str.endswith(')'):
            x = choices_str.split('(')
            return x[0], x[0] + x[1][:-1]
        raise RuntimeError('invalid spec: {0!r}'.format(choices_str))

    def _get_one_number(self, args, kwargs):
        value = None
        number_types = (int, long, float, complex)
        for v in itertools.chain(args, kwargs.itervalues()):
            if isinstance(v, number_types):
                if value is None:
                    value = v
                else:
                    raise RuntimeError('more than one number in arguments')
        return value


_plural_formatter = PluralFormatter()


def plformat(format_str, *args, **kwargs):
    return _plural_formatter.vformat(format_str, args, kwargs)


_debug_timers = {}


def debug_timer_start(name):
    key = '{0} {1}'.format(threading.current_thread().name, name)
    _debug_timers[key] = time.time()


def debug_timer_end(name):
    key = '{0} {1}'.format(threading.current_thread().name, name)
    t = time.time() - _debug_timers.pop(key)
    logger.debug('Transaction time for %s: %.06f', key, t)


def main():
    try:
        cli()
    except sqlalchemy.exc.OperationalError:
        logger.debug('sqlalchemy.exc.OperationalError', exc_info=True)
        if StrictVersion(__version__) < StrictVersion('0.1'):
            secho(('Your jjaljup database is outdated. '
                   'Unfortunately, migrating data to a new database '
                   'will not be supported until jjaljup reaches version 0.1. '
                   'You are using version {0}. '
                   'Please create a new database.').format(
                __version__), fg='red', file=sys.stderr)
        else:
            # TODO instruct how to migrate
            pass
    except requests_oauthlib.oauth1_session.TokenRequestDenied:
        secho('You entered a wrong PIN. Please try again.', fg='red',
              file=sys.stderr)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
