짤줍
====

트위터 관심글에 있는 그림 파일들을 내 컴퓨터에 다운로드합니다.
Azyu님의 [FavoImgs](https://github.com/azyu/FavoImgs/)를 보고 리눅스나 맥에서도 돌아가면
좋을 것 같아 만들었습니다.


설치
----

짤줍은 [Python](https://www.python.org/download/) 2.6, 2.7 버전에서 돌아갑니다.
짤줍의 설치는 다음과 같이 [pip](http://pip.readthedocs.org/en/latest/installing.html)를
사용하는 것을 권장합니다.

    $ pip install jjaljup

설치가 완료되면 `jjaljup` (Windows의 경우 `jjaljup.exe`)을 커맨드 라인에 입력하면 실행할 수
있습니다.

    $ jjaljup
    Usage: jjaljup [OPTIONS] COMMAND [ARGS]...
    ...

### Windows에서 설치

Windows에서 [lxml](http://lxml.de)의 설치가 실패하는 경우,
[Unofficial Windows Binaries for Python Extension Packages](http://www.lfd.uci.edu/~gohlke/pythonlibs/#lxml)에서
비공식 인스톨러를 다운로드한 뒤 설치하면 해결할 수 있습니다. 32/64비트와 Python 버전 (2.6 또는
2.7)을 잘 보고 받으세요.


사용방법
--------

짤줍을 사용하려면 트위터 어플리케이션 등록을 해야합니다.
[Twitter Application Management](https://apps.twitter.com/)에 가서
"Create New App" 버튼을 눌러 새로운 앱을 만드세요. 이름, 설명, 웹사이트 주소는 아무렇게나 해도
됩니다. 앱을 만든 뒤 "API Keys" 탭으로 가면 API key와 API secret이 있습니다. 커맨드가 실행될
때 이 두 값이 각각 `JJALJUP_API_KEY`와 `JJALJUP_API_SECRET` 환경 변수에 들어가
있어야 합니다. 다음은 현재 터미널에서 임시로 환경 변수를 설정한 뒤 짤줍을 실행하는 예시입니다. 여러분들이
가진 값과는 다를 수 있습니다.

    $ export JJALJUP_API_KEY=bOJZcMNBCdfIZfw70DAd4BCBP
    $ export JJALJUP_API_SECRET=YvMMkcKo9vFhlX02wd9TKuPAdiPNAs7eDlFZmkV2e2SeXSo7qc
    $ jjaljup sync

Windows에서는 `export` 대신 `set`을 사용하면 됩니다.

`JJALJUP_DATABASE_URI` 환경 변수를 설정하면 데이터베이스를 지정할 수 있습니다. 기본값은
`sqlite:///jjaljup.db`로, 현재 경로에 `jjaljup.db`라는 SQLite 파일을 만듭니다.
자세한 내용은 [SQLAlchemy 문서](http://docs.sqlalchemy.org/en/rel_0_9/core/engines.html#database-urls)를
참조하세요.

환경 변수를 영구적으로 저장하려면 Linux/Mac에서는 홈 디렉토리의 `.profile` 파일을 사용하거나
Windows에서는 시스템 속성 - 고급 - 환경 변수에서 설정하면 됩니다.

`jjaljup sync`를 실행하면 선택된 계정의 모든 관심글에 있는 그림 파일을 다운로드 합니다.
짤줍은 다음과 같은 종류의 파일들을 다운로드할 수 있습니다.

* 트위터에서 직접 올린 그림
* 트위터에서 직접 올린 움직이는 GIF (MP4 동영상 파일로 받아짐)
* 외부 링크 중 그림 파일 확장자로 끝나는 경우 (JPG, JPEG, GIF, PNG)
* Twitpic, yfrog에 올린 그림

`jjaljup watch`를 실행하면 커맨드가 실행되는 동안 선택된 계정의 활동을 실시간으로 감시하면서
관심글을 담을 때마다 그림 파일을 다운로드합니다.

보다 자세한 설명은 커맨드를 입력한 후 `--help`를 덧붙이면 볼 수 있습니다 (간단한 영어).

    $ jjaljup sync --help
    Usage: jjaljup sync [OPTIONS]
    ...


주의사항
--------

계정으로 앱 인증을 하면 접속 토큰이 데이터베이스에 평문으로 저장됩니다. 여러분이 만든 트위터 앱의 API
key와 API secret이 있어야 접속 토큰을 사용할 수 있기 때문에 아주 큰 문제는 아니지만, 그래도
데이터베이스 파일이 유출되지 않도록 주의해 주세요. 만약 유출될 경우 앱 관리 페이지에서 "Regenerate
API keys" 버튼을 눌러 키를 재생성하면 피해를 막을 수 있습니다.


나중에 추가될 수도 있는 기능
----------------------------

* 서드 파티 이미지/비디오 사이트 추가 지원: imgur, Vine 등.
* 리스트, 커스텀 타임라인 지원. 단, 커스텀 타임라인은 아직 공식 API가 없음 (베타 상태).
* 다른 사람의 관심글 저장하기.
