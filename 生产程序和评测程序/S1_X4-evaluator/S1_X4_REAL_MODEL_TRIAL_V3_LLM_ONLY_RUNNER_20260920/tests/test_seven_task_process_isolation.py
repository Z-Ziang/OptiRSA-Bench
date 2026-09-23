from pathlib import Path


def test_seven_task_orchestrator_declares_three_families():
    from src.seven_task_orchestrator import TASK_FAMILIES
    assert TASK_FAMILIES==('O_FAMILY','X2X3','S1X4')
