from urlparse import urlparse

from jjaljup import get_twitter_agif

def test_get_twitter_agif():
    url = 'https://twitter.com/verge/status/479306079202209792/photo/1'
    video_url = 'https://pbs.twimg.com/tweet_video/BqbWVjQIAAEpReg.mp4'
    assert get_twitter_agif(url, urlparse(url)).url == video_url
