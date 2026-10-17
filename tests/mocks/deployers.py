from pathlib import Path

import boa

MOCKS_DIR = Path(__file__).parent

MOCK_AGGREGATOR = boa.load_partial(str(MOCKS_DIR / "mock_aggregator.vy"))
MOCK_RECEIVER = boa.load_partial(str(MOCKS_DIR / "mock_receiver.vy"))
