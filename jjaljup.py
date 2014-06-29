#! /usr/bin/env python
from __future__ import print_function

import logging
import os
import Queue
import sys
import time
import webbrowser
from datetime import datetime
from threading import Thread
from urlparse import urlparse

import click
import requests
import sqlalchemy
import twitter
from requests_oauthlib import OAuth1Session
from sqlalchemy import Column, event, ForeignKey, Integer, String
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from termcolor import colored
from twitter import Status as StatusBase

logging.basicConfig()

CLIENT_KEY = os.environ.get('JJALJUP_CLIENT_KEY')
CLIENT_SECRET = os.environ.get('JJALJUP_CLIENT_SECRET')
DATABASE_URI = os.environ.get('JJALJUP_DATABASE_URI', 'sqlite:///jjaljup.db')

IMAGE_EXTENSIONS = frozenset(['jpg', 'jpeg', 'gif', 'png'])

REQUEST_TOKEN_URL = 'https://api.twitter.com/oauth/request_token'
AUTHORIZATION_URL = 'https://api.twitter.com/oauth/authorize'
ACCESS_TOKEN_URL = 'https://api.twitter.com/oauth/access_token'
RATE_LIMIT_EXCEEDED = 88


@event.listens_for(Engine, 'connect')
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()


Base = declarative_base()


class User(Base):
    __tablename__ = 'user'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    screen_name = Column(String, nullable=False)
    oauth_token = Column(String, nullable=False)
    oauth_token_secret = Column(String, nullable=False)


class Tweet(Base):
    __tablename__ = 'tweet'

    id = Column(Integer, primary_key=True)
    images = relationship('Image', backref='tweet', lazy='joined',
                          cascade='all, delete-orphan', passive_deletes=True)


class Image(Base):
    __tablename__ = 'image'

    id = Column(Integer, primary_key=True)
    tweet_id = Column(Integer, ForeignKey('tweet.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    url = Column(String, nullable=False)
    local_path = Column(String, nullable=False)


# TODO store the database securely, preferably using native features of
# different operating systems.
# See win32crypt.CryptProtectData
engine = sqlalchemy.create_engine(DATABASE_URI)

Session = sessionmaker()
Session.configure(bind=engine)
Base.metadata.create_all(engine)

session = Session()  # Use this in main thread only


@click.group()
def cli():
    pass


@cli.command()
def add():
    """Add a new Twitter account."""
    add_user()


@cli.command()
def accounts():
    """Show a list of saved accounts."""
    users = list_users()
    if not users:
        print('No accounts.')
    else:
        print('Number of accounts: {0}'.format(len(users)))
        for i, user in enumerate(users, 1):
            print(u' {0}. {1} @{2}'.format(i, user.name, user.screen_name))


@cli.command()
@click.option('-a', '--account', metavar='SCREEN_NAME',
              help='Select a Twitter account to sync.')
@click.option('-d', '--directory', metavar='PATH', default='images',
              prompt=True, type=click.Path(file_okay=False, writable=True,
                                           resolve_path=True),
              help='Select a local directory to sync. If it does not exist, '
                   'new directories will be created as necessary.')
@click.option('--count', metavar='N', type=int,
              help='Number of favorite tweets to sync. If set, only the most '
                   'recent N tweets are examined.')
@click.option('--delete', is_flag=True, default=False,
              help='Delete unfavorated tweets and images from the directory. '
                   'Disabled by default.')
@click.option('--workers', metavar='N', type=int, default=8,
              help='Number of threads to run concurrently (defaults to 8).')
def sync(account, directory, count, delete, workers):
    """
    Synchronize images in the selected account's favorite tweets into the
    specified directory. Due to the limit on the Twitter API, at most 200
    tweets can be processed per API call and 15 calls made every 15 minutes,
    thus 12000 tweets per hour.

    """
    CALL_SIZE = 200
    if count is None:
        count = float('inf')
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(u'Created a directory at {0}'.format(directory))
    print(u'Images will be downloaded into {0}'.format(directory))
    api = create_api(select_user(account))
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
        if count < float('inf'):
            print(('Only the most recent {0} tweets will be '
                   'examined.').format(count))
        print('It may take {0}-{1} minutes to complete.'.format(eta_min,
                                                                eta_max))
    max_id = None
    tweet_ids = set()
    last = False
    num_saved_tweets = 0
    num_saved_images = 0
    try:
        while not last:
            status = get_rate_limit_status(api, 'favorites')
            data = status['favorites']['/favorites/list']
            limit = data['limit']
            remaining = data['remaining']
            print('Remaining API calls: {0}/{1}'.format(remaining, limit))
            reset = data['reset']
            try:
                while remaining > 0 and not last:
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
                            args=(directory, input_queue, output_queue)
                        ).start()
                    input_queue.join()
                    while not output_queue.empty():
                        num_saved_images += output_queue.get_nowait()
                    last = len(tweets) == 0 or num_saved_tweets >= count
                    max_id = tweets[-1].id - 1 if tweets else 0
                    print(('{0} tweets have been processed. '
                           'Remaining API calls: {1}/{2}').format(
                        num_saved_tweets, remaining, limit))
            except twitter.TwitterError as e:
                err = e.args[0][0]
                if err['code'] != RATE_LIMIT_EXCEEDED:
                    raise_unexpected_error(err)
            if not last:
                reset_dt = datetime.fromtimestamp(reset)
                print(('Rate limit exceeded. '
                       'Waiting for the next round at {0}.').format(reset_dt))
                time.sleep(max(1, reset - time.time() + 10))
        print('Synchronized {0} images in {1} tweets into {2}'.format(
            num_saved_images, num_saved_tweets, directory))
    finally:
        if tweet_ids and delete:
            min_id = min(tweet_ids)
            num_deleted_tweets = 0
            num_deleted_images = 0
            qr = session.query(Tweet).filter(~Tweet.id.in_(tweet_ids))
            if count < float('inf'):
                qr = qr.filter(Tweet.id >= min_id)
            for tweet in qr:
                num_deleted_tweets += 1
                num_deleted_images += len(tweet.images)
                delete_tweet(tweet, directory)
            if num_deleted_tweets > 0:
                print('Deleted {0} images in {1} unfavorated tweets.'.format(
                    num_deleted_images, num_deleted_tweets))


def list_users():
    return session.query(User).order_by(User.id).all()


def select_user(screen_name=None):
    user = session.query(User).filter_by(screen_name=screen_name).first()
    if user is not None:
        return user
    if screen_name is not None:
        print(colored('@{0} does not exist.'.format(screen_name), 'red'),
              file=sys.stderr)
    users = list_users()
    if users:
        n = len(users) + 1
        print(colored('Choose a Twitter account to work with:', 'blue'))
        for i, user in enumerate(users, 1):
            print(u' {0}. {1} (@{2})'.format(i, user.name, user.screen_name))
        print(' {0}. Add a new account'.format(n))
        while True:
            try:
                prompt = colored('Choice: ', 'blue')
                choice = int(raw_input(prompt))
                if 1 <= choice <= n:
                    break
            except ValueError:
                pass
            print('Please enter a number between 1 and {0}.'.format(n))
        user = add_user() if choice == n else users[choice - 1]
    else:
        user = add_user()
    return user


def add_user():
    oauth_token, oauth_token_secret = get_token_credentials()
    api = twitter.Api(consumer_key=CLIENT_KEY, consumer_secret=CLIENT_SECRET,
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


def create_api(user):
    oauth_token = user.oauth_token
    oauth_token_secret = user.oauth_token_secret
    return twitter.Api(consumer_key=CLIENT_KEY, consumer_secret=CLIENT_SECRET,
                       access_token_key=oauth_token,
                       access_token_secret=oauth_token_secret)


def get_token_credentials():
    oauth = OAuth1Session(CLIENT_KEY, client_secret=CLIENT_SECRET,
                          callback_uri='oob')
    temporary_credentials = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    oauth_token = temporary_credentials.get('oauth_token')
    oauth_token_secret = temporary_credentials.get('oauth_token_secret')

    authorization_url = oauth.authorization_url(AUTHORIZATION_URL)
    print(colored('Copy and paste the following URL into your web browser and '
                  'authorize the app:', 'blue'))
    print(authorization_url)
    webbrowser.open(authorization_url)
    verifier = raw_input(colored('Enter the PIN: ', 'blue'))

    oauth = OAuth1Session(CLIENT_KEY, client_secret=CLIENT_SECRET,
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
                print(colored('Rate limit exceeded. Waiting for 3 minutes '
                              'before trying again.', 'red'), file=sys.stderr)
            else:
                raise_unexpected_error(err)
        time.sleep(180)


def raise_unexpected_error(err):
    raise RuntimeError((u'Unexpected error occured: {message} '
                        u'(code: {code})').format(**err))


def save_tweet(directory, tweets, num_images):
    session = Session()
    while True:
        try:
            tweet_data = tweets.get_nowait()
        except Queue.Empty:
            break
        tweet = session.query(Tweet).get(tweet_data.id)
        if tweet is None:
            tweet = Tweet(id=tweet_data.id)
            session.add(tweet)
        old_image_urls = set([img.url for img in tweet.images])
        new_image_urls = extract_image_urls(tweet_data)
        tweet.images[:] = (img for img in tweet.images
                           if img.url not in old_image_urls - new_image_urls)
        for url in new_image_urls - old_image_urls:
            local_path = '{0}_{1}'.format(tweet.id, os.path.basename(url))
            o = urlparse(url)
            if o.netloc == 'pbs.twimg.com':
                url = url + ':orig'
            tweet.images.append(Image(url=url, local_path=local_path))
        for img in tweet.images:
            path = os.path.join(directory, img.local_path)
            if not os.path.exists(path):
                image_data = requests.get(img.url).content
                with open(path, 'wb') as f:
                    f.write(image_data)
        num_images.put(len(tweet.images))
        session.commit()
        tweets.task_done()


def delete_tweet(tweet, directory):
    for img in tweet.images:
        path = os.path.join(directory, img.local_path)
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError as e:
                print(colored(u'Failed to delete the image at {0}: {1}'.format(
                    path, e.strerror)))
    session.delete(tweet)
    session.commit()


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


if __name__ == '__main__':
    cli()
