import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import requests


@pytest.fixture(autouse=True)
def mock_mock_apis(monkeypatch):
    original_get = requests.get

    def _mock_get(url, *args, **kwargs):
        if "api/v1/mock/weather" in url:

            class MockResponse:
                def json(self):
                    return {"weather": [{"main": "Clear", "description": "clear sky"}]}

            return MockResponse()
        elif "api/v1/mock/routes" in url:

            class MockResponse:
                def json(self):
                    return {"routes": [{"route_id": "R1", "status": "Normal"}]}

            return MockResponse()
        elif "api/v1/mock/suppliers" in url:

            class MockResponse:
                def json(self):
                    return {
                        "vendors": [{"vendor_id": "SUP_A", "overall_status": "Normal"}]
                    }

            return MockResponse()
        return original_get(url, *args, **kwargs)

    monkeypatch.setattr(requests, "get", _mock_get)
