unittest:
	@cd tests; PYTHONPATH=.. py.test -m "not webtest"

webtest:
	@cd tests; PYTHONPATH=.. py.test -m webtest

test:
	@cd tests; PYTHONPATH=.. py.test

release:
	python setup.py sdist upload

.PHONY: unittest webtest test release
