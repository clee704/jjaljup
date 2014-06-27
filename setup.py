import os

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

def readme():
    try:
        with open(os.path.join(os.path.dirname(__file__), 'README.md')) as f:
            return f.read()
    except Exception:
        return ''

setup(
    name='jjaljup',
    version='0.0.1',
    url='https://github.com/clee704/jjaljup',
    license='MIT',
    author='Choongmin Lee',
    author_email='choongmin@me.com',
    description='Downloads images in your favorite tweets.',
    long_description=readme(),
    py_modules=['jjaljup'],
    install_requires=[
        'python-twitter==1.3.1',
        'python-oauth2==0.7.0',
        'requests==2.3.0',
        'requests-oauthlib==0.4.1',
        'sqlalchemy==0.9.6',
        'termcolor==1.1.0',
        'click==2.2',
    ],
    entry_points={
        'console_scripts': [
            'jjaljup=jjaljup:cli',
        ],
    },
    keywords='crawler twitter downloader',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: Korean',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Utilities',
    ],
)
