from urlparse import urlparse

from jjaljup import get_twitpic, get_twitter_agif, get_yfrog


def test_get_twitter_agif():
    url = 'https://twitter.com/verge/status/479306079202209792/photo/1'
    video_url = 'https://pbs.twimg.com/tweet_video/BqbWVjQIAAEpReg.mp4'
    assert get_twitter_agif(url, urlparse(url)).url == video_url


def test_get_twitpic():
    url = 'http://twitpic.com/dhyrtq'
    image_url = 'http://twitpic.com/show/full/dhyrtq'
    name = '816236126.jpg'
    img = get_twitpic(url, urlparse(url))
    assert img.url == image_url
    assert img.name == name


def test_get_yfrog():
    url = 'http://yfrog.com/od4hocllj'
    image_url = 'http://a.yfrog.com/img877/9894/4hocll.jpg'
    assert get_yfrog(url, urlparse(url)).url == image_url
