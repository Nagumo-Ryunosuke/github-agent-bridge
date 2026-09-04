.PHONY: test compile check install-local

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

compile:
	python3 -m compileall -q src

check: test compile

install-local:
	python3 -m pip install --user -e .
