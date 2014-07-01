from urlparse import urlparse

import pytest
from jjaljup import favorite_table, Image, plformat, Tweet, User


def test_models(session):
    john = User(id=1, name='john', screen_name='j',
                oauth_token='...', oauth_token_secret='...')
    tom = User(id=2, name='tom', screen_name='t',
               oauth_token='...', oauth_token_secret='...')
    tw_a = Tweet(id=10)
    tw_a.images.append(Image(url='a1', name='a1'))
    tw_b = Tweet(id=11)
    tw_b.images.append(Image(url='b1', name='b1'))
    tw_b.images.append(Image(url='b2', name='b2'))
    tw_b.images.append(Image(url='b3', name='b3'))
    tw_c = Tweet(id=12)
    tw_c.images.append(Image(url='c1', name='c1'))
    tw_c.images.append(Image(url='c2', name='c2'))
    john.favorites.append(tw_a)
    john.favorites.append(tw_c)
    tom.favorites.append(tw_b)
    tom.favorites.append(tw_c)

    with session.begin():
        session.add(john)
        session.add(tom)
        session.add(tw_a)
        session.add(tw_b)
        session.add(tw_c)
    assert repr(john) == '<User @j>'
    assert repr(tw_a) == '<Tweet(id=10)>'
    assert repr(tw_a.images[0]) == "<Image(url=u'a1')>"
    assert session.query(User).count() == 2
    assert session.query(Tweet).count() == 3
    assert session.query(Image).count() == 6
    assert session.execute(favorite_table.select().count()).scalar() == 4
    assert tw_a.favorited_users.all() == [john]
    assert tw_b.favorited_users.all() == [tom]
    assert tw_c.favorited_users.order_by(User.id).all() == [john, tom]

    with session.begin():
        session.execute(favorite_table.insert().values(user_id=1, tweet_id=11))
    assert john.favorites.order_by(Tweet.id).all() == [tw_a, tw_b, tw_c]
    assert tw_b.favorited_users.order_by(User.id).all() == [john, tom]

    with session.begin():
        john.favorites.remove(tw_c)
    assert session.execute(favorite_table.select().count()).scalar() == 4
    assert tw_c.favorited_users.all() == [tom]

    with session.begin():
        session.delete(tw_b)
    assert session.execute(favorite_table.select().count()).scalar() == 2
    assert john.favorites.all() == [tw_a]
    assert tom.favorites.all() == [tw_c]

    with session.begin():
        session.delete(john)
    assert session.execute(favorite_table.select().count()).scalar() == 1

    # FIXME if we can make the database delete tw_a automatically...
    assert tw_a.favorited_users.all() == []


@pytest.mark.parametrize('format_str, args, kwargs, formatted', [
    ('{0}', (1,), {}, '1'),
    ('{name}', (), {'name': 'john'}, 'john'),
    ('{0:.2f} {{}} {1!r} {a[0]}', (1.238, '\n'), {'a': [10, 11]},
     '1.24 {} \'\\n\' 10'),
    ('{0:.^11}', ('foo',), {}, '....foo....'),
    ('{0} {0|apple(s)}', (0,), {}, '0 apples'),
    ('{0} {0|apple(s)}', (1,), {}, '1 apple'),
    ('{0} {0|apple(s)}', (2,), {}, '2 apples'),
    ('{n} {n|apple(s)}', (), {'n': 3}, '3 apples'),
    ('{0} {0|apple(s)} of {1} {1|person/people}', (4, 0), {},
     '4 apples of 0 people'),
    ('{0} {0|apple(s)} of {1} {1|person/people}', (4, 1), {},
     '4 apples of 1 person'),
    ('{0} {0|apple(s)} of {1} {1|person/people}', (4, 2), {},
     '4 apples of 2 people'),
    ('There {|is/are} {num_apples} {|apple(s)}', (), {'num_apples': 3},
     'There are 3 apples'),
])
def test_plformat(format_str, args, kwargs, formatted):
    assert plformat(format_str, *args, **kwargs) == formatted


def test_plformat_ambiguous():
    with pytest.raises(RuntimeError):
        plformat('{0} {|apple(s)} in {1} {|basket(s)}', 1, 2)
