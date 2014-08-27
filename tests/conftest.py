import sys

import pytest

def pytest_addoption(parser):
    parser.addoption('--script-python-runtime', action='store', default=sys.executable,
        help='Select Python runtime to run the tested script with.')

@pytest.fixture
def pyruntime(request):
    return request.config.getoption('--script-python-runtime')
