from jjaljup import extract_twitter_agif

def test_extract_twitter_agif():
    url = 'https://twitter.com/verge/status/479306079202209792/photo/1'
    video_url = 'https://pbs.twimg.com/tweet_video/BqbWVjQIAAEpReg.mp4'
    assert extract_twitter_agif(url) == video_url
