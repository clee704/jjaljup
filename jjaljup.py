#! /usr/bin/env python
from __future__ import print_function

import code
import logging
import os
import pprint
import Queue
import sys
import time
import webbrowser
from datetime import datetime
from distutils.version import StrictVersion
from threading import Thread
from urlparse import urlparse

import click
import requests
import sqlalchemy
import twitter
from click import secho
from requests_oauthlib import OAuth1Session
from sqlalchemy import Column, event, ForeignKey, Integer, String, Table
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from twitter import Status as StatusBase

__version__ = '0.0.2'

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = frozenset(['jpg', 'jpeg', 'gif', 'png'])

REQUEST_TOKEN_URL = 'https://api.twitter.com/oauth/request_token'
AUTHORIZATION_URL = 'https://api.twitter.com/oauth/authorize'
ACCESS_TOKEN_URL = 'https://api.twitter.com/oauth/access_token'
RATE_LIMIT_EXCEEDED = 88

PATH_ENCODING = sys.getfilesystemencoding()

Base = declarative_base()
Session = sessionmaker()


favorite_table = Table('favorite', Base.metadata,
    Column('user_id', Integer, ForeignKey('user.id'), primary_key=True),
    Column('tweet_id', Integer, ForeignKey('tweet.id'), primary_key=True),
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
        return '<User @{0}>'.format(self.screen_name)


class Tweet(Base):
    __tablename__ = 'tweet'

    id = Column(Integer, primary_key=True)

    images = relationship('Image', backref='tweet', lazy='joined',
                          cascade='all, delete-orphan', passive_deletes=True)
    favorited_users = relationship('User', secondary=favorite_table,
                                   lazy='dynamic')

    def __repr__(self):
        return '<Tweet(id={0})>'.format(self.id)


class Image(Base):
    __tablename__ = 'image'

    id = Column(Integer, primary_key=True)
    tweet_id = Column(Integer, ForeignKey('tweet.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    url = Column(String, nullable=False)
    local_path = Column(String, nullable=False)

    def __repr__(self):
        return '<Image(url={0!r})>'.format(self.url)


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

    key_option = click.option('--client-key', metavar='KEY',
                              envvar='JJALJUP_CLIENT_KEY', prompt=True,
                              expose_value=False, callback=key_callback,
                              help='API key of your Twitter app.')
    secret_option = click.option('--client-secret', metavar='SECRET',
                                 envvar='JJALJUP_CLIENT_SECRET', prompt=True,
                                 expose_value=False, callback=secret_callback,
                                 help='API secret of your Twitter app.')
    return key_option(secret_option(f))


def session_option(f):
    def callback(ctx, param, value):
        engine = sqlalchemy.create_engine(value)
        Session.configure(bind=engine)
        Base.metadata.create_all(engine)
        state = ctx.ensure_object(State)
        state.session = Session()
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
def cli(debug):
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARN)


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
    """Add a new Twitter account."""
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
        print('Accounts: {0}'.format(len(users)))
        for i, user in enumerate(users, 1):
            print(u' {0}. {1} (@{2})'.format(i, user.name, user.screen_name))


@cli.command(short_help='Download images in favorite tweets.')
@click.option('-a', '--account', metavar='SCREEN_NAME',
              help='Select a Twitter account to sync.')
@click.option('-d', '--directory', metavar='PATH', default='images',
              prompt=True, type=click.Path(file_okay=False, writable=True,
                                           resolve_path=True),
              help='Select a local directory to sync. If the path does not '
                   'exist, new directories will be created as necessary.')
@click.option('--count', metavar='N', type=int,
              help='Number of favorite tweets to sync. If set, only the most '
                   'recent N tweets are examined.')
@click.option('--delete', is_flag=True, default=False,
              help='Delete unfavorated tweets and images from the directory. '
                   'Disabled by default.')
@click.option('--workers', metavar='N', type=int, default=8,
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
    except twitter.TwitterError as e:
        err = e.args[0][0]
        if err['code'] != RATE_LIMIT_EXCEEDED:
            raise_unexpected_error(err)
    if num_favorites is not None:
        eta_min = max(1, int(min(count, num_favorites) / CALL_SIZE))
        eta_max = max(10, int(min(count, num_favorites) / CALL_SIZE * 2))
        print('You have {0} favorite tweets.'.format(num_favorites))
        if count != INFINITY:
            print('Only the most recent {0} tweets will be examined.'.format(
                count))
        print('It may take {0}-{1} minutes to complete.'.format(eta_min,
                                                                eta_max))

    max_id = None
    tweet_ids = set()
    num_saved_tweets = 0
    num_saved_images = 0
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
                    tweets = api.GetFavorites(count=CALL_SIZE,
                                              max_id=max_id)
                    remaining -= 1
                    input_queue = Queue.Queue()
                    for tweet in tweets:
                        input_queue.put(tweet)
                        tweet_ids.add(tweet.id)
                        num_saved_tweets += 1
                        if num_saved_tweets >= count:
                            break
                    output_queue = Queue.Queue()
                    for _ in range(workers):
                        Thread(
                            target=save_tweet,
                            args=(directory, user.id, input_queue,
                                  output_queue)
                        ).start()
                    input_queue.join()
                    while not output_queue.empty():
                        num_saved_images += output_queue.get_nowait()
                    max_id = tweets[-1].id - 1 if tweets else 0
                    last = len(tweets) == 0 or num_saved_tweets >= count
                    if last:
                        if count == INFINITY:
                            print('There are no more tweets. ', end='')
                            print_api_status()
                        break
                    print('{0} tweets have been processed. '.format(
                        num_saved_tweets), end='')
                    print_api_status()
            except twitter.TwitterError as e:
                err = e.args[0][0]
                if err['code'] != RATE_LIMIT_EXCEEDED:
                    raise_unexpected_error(err)
            if last:
                break
            reset_dt = datetime.fromtimestamp(reset)
            print(('Rate limit exceeded. '
                   'Waiting for the next round at {0}.').format(reset_dt))
            time.sleep(max(1, reset - time.time() + 10))
        secho(b'Synchronized {0} images in {1} tweets into {2}'.format(
            num_saved_images, num_saved_tweets, directory))
    finally:
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
            state.session.commit()
            if num_deleted_tweets > 0:
                print('Deleted {0} images in {1} unfavorated tweets.'.format(
                    num_deleted_images, num_deleted_tweets))


def list_users(session):
    return session.query(User).order_by(User.id).all()


def select_user(session, client_key, client_secret, screen_name=None):
    user = session.query(User).filter_by(screen_name=screen_name).first()
    if user is not None:
        return user
    if screen_name is not None:
        secho('@{0} does not exist.'.format(screen_name), fg='red',
              file=sys.stderr)
    users = list_users(session)
    user = None
    if users:
        n = len(users) + 1
        secho('Choose a Twitter account to work with:', fg='blue')
        for i, u in enumerate(users, 1):
            print(u' {0}. {1} (@{2})'.format(i, u.name, u.screen_name))
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
    user = session.query(User).get(info.id)
    if not user:
        user = User(id=info.id, name=info.name, screen_name=info.screen_name,
                    oauth_token=oauth_token,
                    oauth_token_secret=oauth_token_secret)
        session.add(user)
    else:
        user.name = info.name
        user.screen_name = info.screen_name
        user.oauth_token = oauth_token
        user.oauth_token_secret = oauth_token_secret
    session.commit()
    print(u'Added {0} (@{1}).'.format(user.name, user.screen_name))
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
        except twitter.TwitterError as e:
            err = e.args[0][0]
            if err['code'] == RATE_LIMIT_EXCEEDED:
                secho('Rate limit exceeded. Waiting for 3 minutes before '
                      'trying again.', fg='red', file=sys.stderr)
            else:
                raise_unexpected_error(err)
        time.sleep(180)


def raise_unexpected_error(err):
    raise RuntimeError((u'Unexpected error occured: {message} '
                        u'(code: {code})').format(**err))


def save_tweet(directory, user_id, tweets, num_images):
    session = Session()
    while True:
        try:
            tweet_data = tweets.get_nowait()
        except Queue.Empty:
            break
        try:
            tweet = session.query(Tweet).get(tweet_data.id)
            if tweet is None:
                tweet = Tweet(id=tweet_data.id)
                session.add(tweet)
            if tweet.favorited_users.filter_by(id=user_id).count() == 0:
                session.execute(favorite_table.insert().values(
                    user_id=user_id, tweet_id=tweet.id))
            old_image_urls = set([img.url for img in tweet.images])
            new_image_urls = extract_image_urls(tweet_data)
            tweet.images[:] = (img for img in tweet.images
                               if img.url not in old_image_urls -
                                                 new_image_urls)
            for url in new_image_urls - old_image_urls:
                local_path = '{0}_{1}'.format(tweet.id, os.path.basename(url))
                o = urlparse(url)
                if o.netloc == 'pbs.twimg.com':
                    url = url + ':orig'
                tweet.images.append(Image(url=url, local_path=local_path))
            for img in tweet.images:
                path = os.path.join(directory,
                                    img.local_path.encode(PATH_ENCODING))
                if not os.path.exists(path):
                    image_data = requests.get(img.url).content
                    with open(path, 'wb') as f:
                        f.write(image_data)
            num_images.put(len(tweet.images))
            session.commit()
        except Exception:
            logger.exception('Unexpected error occurred while saving a tweet.')
            logger.debug('The tweet was: %s',
                         pprint.pformat(tweet_data.AsDict()))
            session.rollback()
        finally:
            tweets.task_done()


def delete_tweet(session, directory, user, tweet):
    for img in tweet.images:
        path = os.path.join(directory, img.local_path.encode(PATH_ENCODING))
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError as e:
                secho(u'Failed to delete the image at {0}: {1}'.format(
                    path, e.strerror), fg='red')
    user.favorites.remove(tweet)
    if tweet.favorited_users.count() == 0:
        session.delete(tweet)


def is_image_url(url):
    return url.lower().rsplit('.', 1)[-1] in IMAGE_EXTENSIONS


def is_image(resp):
    return resp.headers.get('content-type', '').startswith('image')


def extract_image_urls(tweet_data):
    image_urls = set()
    for media in tweet_data.media:
        if media['type'] == 'photo':
            image_urls.add(media['media_url'])
    for url_data in tweet_data.urls:
        if is_image_url(url_data.expanded_url):
            image_urls.add(url_data.expanded_url)
    return image_urls


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


if __name__ == '__main__':
    main()
