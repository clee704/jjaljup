# -*- coding: utf-8 -*-
import click
import pytest
from jjaljup import cli, User


def test_accounts_basic(session_and_runner):
    session, runner = session_and_runner
    with session.begin():
        session.add(User(name='john', screen_name='j', oauth_token='',
                         oauth_token_secret=''))
    result = runner.invoke(cli, ['accounts'])
    assert result.exit_code == 0
    assert result.output == 'There is 1 account:\n 1. john (@j)\n'


def test_accounts_unicode(session_and_runner):
    session, runner = session_and_runner
    with session.begin():
        session.add(User(name='john', screen_name='j', oauth_token='',
                         oauth_token_secret=''))
        session.add(User(name=u'철수 ☂', screen_name='cheolsu', oauth_token='',
                         oauth_token_secret=''))
    result = runner.invoke(cli, ['accounts'])
    assert result.exit_code == 0
    assert result.output == (u'There are 2 accounts:\n'
                             u' 1. john (@j)\n'
                             u' 2. 철수 ☂ (@cheolsu)\n')
