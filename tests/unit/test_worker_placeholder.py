from slotline.worker.main import main


def test_worker_placeholder_exits_non_zero(capsys: object) -> None:
    assert main() == 1
