짤줍
====

트위터 관심글에 있는 그림 파일들을 내 컴퓨터에 다운로드합니다.
Azyu님의 [FavoImgs](https://github.com/azyu/FavoImgs/)를 보고 리눅스나 맥에서도 돌아가면
좋을 것 같아 만들었습니다.


설치
----

설치는 [GitHub 저장소](https://github.com/clee704/jjaljup/)에서 `jjaljup.py` 파일을
다운받거나, pip를 이용하여 설치할 수 있습니다 (권장).

    $ pip install jjaljup

파일을 직접 다운 받은 경우 다음 명령으로 파일을 실행 가능하도록 만들어야 합니다.

    $ chmod +x jjaljup.py
    $ ./jjaljup.py --help

이 경우는 짤줍이 의존하는 패키지들도 직접 설치해야 합니다. 목록은 `requirements.txt` 파일을 보면
됩니다. 여러가지로 귀찮기 때문에 그냥 pip로 설치하는 것을 권장합니다. pip로 설치한 경우
`jjaljup`이라고 입력하면 커맨드를 실행할 수 있습니다.


사용방법
--------

짤줍을 사용하려면 트위터 어플리케이션 등록을 해야합니다.
[Twitter Application Management](https://apps.twitter.com/)에 가서
"Create New App" 버튼을 눌러 새로운 앱을 만드세요. 이름, 설명, 웹사이트 주소는 아무렇게나 해도
됩니다. 앱을 만든 뒤 "API Keys" 탭으로 가면 API key와 API secret이 있습니다. 커맨드가 실행될
때 이 두 값이 각각 `JJALJUP_API_KEY`와 `JJALJUP_API_SECRET` 환경 변수에 들어가
있어야 합니다. 아래는 예를 든 것으로 여러분들의 실제 값과는 다릅니다.

    $ export JJALJUP_API_KEY=bOJZcMNBCdfIZfw70DAd4BCBP
    $ export JJALJUP_API_SECRET=YvMMkcKo9vFhlX02wd9TKuPAdiPNAs7eDlFZmkV2e2SeXSo7qc
    $ jjaljup sync

`JJALJUP_DATABASE_URI` 환경 변수를 설정하면 데이터베이스를 지정할 수 있습니다. 기본값은
`sqlite:///jjaljup.db`로, 현재 경로에 `jjaljup.db`라는 SQLite 파일을 만듭니다.
자세한 내용은 [SQLAlchemy 문서](http://docs.sqlalchemy.org/en/rel_0_9/core/engines.html#database-urls)를
참조하세요.

옵션 등에 대해 알고 싶은 경우 커맨드를 입력한 후 `--help`를 덧붙이면 설명이 나옵니다.

    $ jjaljup --help
    Usage: jjaljup [OPTIONS] COMMAND [ARGS]...
    ...    
    $ jjaljup sync --help
    Usage: jjaljup sync [OPTIONS]
    ...

`jjaljup sync`를 실행하면 선택된 계정의 모든 관심글에 있는 그림 파일을 다운로드 합니다.
짤줍은 그림이 트위터에서 직접 올라간 경우, 외부 URL이 그림 파일 확장자로 끝나는 경우에만 파일을
다운로드 합니다.


주의사항
--------

계정으로 앱 인증을 하면 접속 토큰이 데이터베이스에 평문으로 저장됩니다. 여러분이 만든 트위터 앱의 API
key와 API secret이 있어야 접속 토큰을 사용할 수 있기 때문에 아주 큰 문제는 아니지만, 그래도
데이터베이스 파일이 유출되지 않도록 주의해 주세요. 만약 유출될 경우 앱 관리 페이지에서 "Regenerate
API keys" 버튼을 눌러 키를 재생성하면 피해를 막을 수 있습니다.


나중에 추가될 수도 있는 기능
----------------------------

* 트위터 움짤 (MP4)이나 Twitpic, imgur 등 지원
* Stream API를 이용한 실시간 다운로드
* 관심글이 아닌 트윗덱 컬렉션에서 다운로드
